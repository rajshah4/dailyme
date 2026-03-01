"""DailyMe Pipeline — Run by OpenHands agent on a schedule.

This is the main entry point that the OpenHands agent executes.
It performs the full ingest → parse → dedup → rank → store cycle.

Usage (by OpenHands agent):
    python scripts/run_pipeline.py

The pipeline is idempotent — safe to run multiple times.
Uses gmail_id as the idempotency key to avoid reprocessing.
"""

import asyncio
import logging
import sys
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

# Ensure app is importable
sys.path.insert(0, ".")

from app.config import settings
from app.db import async_session, engine
from app.ingestion.gmail import EmailMessage, fetch_unread_emails, get_gmail_service, mark_as_read
from app.ingestion.parser import (
    clean_html,
    extract_newsletter_name,
    extract_sender_domain,
)
from app.models import Base, Newsletter, RawEmail, Story, StoryGroup, StoryGroupMember
from app.processing.clustering import assign_topic
from app.processing.dedup import canonicalize_url, find_duplicate
from app.processing.segmenter import needs_llm_fallback, segment_newsletter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("dailyme.pipeline")


async def run_pipeline():
    """Execute the full newsletter processing pipeline."""
    logger.info("=" * 60)
    logger.info("DailyMe Pipeline — Starting run at %s", datetime.now(timezone.utc).isoformat())
    logger.info("=" * 60)

    # Stats for this run
    stats = {
        "emails_fetched": 0,
        "emails_new": 0,
        "stories_extracted": 0,
        "stories_deduped": 0,
        "groups_created": 0,
        "llm_fallback_needed": 0,
    }

    # Step 1: Fetch unread emails from Gmail
    logger.info("[1/5] Fetching unread emails from Gmail...")
    try:
        service = get_gmail_service()
        emails = fetch_unread_emails(service)
        stats["emails_fetched"] = len(emails)
        logger.info("  → Fetched %d unread emails", len(emails))
    except Exception:
        logger.exception("Failed to fetch emails from Gmail")
        return stats

    if not emails:
        logger.info("No new emails. Pipeline complete.")
        return stats

    # Step 2: Store raw emails and identify newsletters
    logger.info("[2/5] Storing raw emails and identifying newsletters...")
    async with async_session() as session:
        for email in emails:
            # Check if already processed (idempotency)
            existing = await session.execute(
                select(RawEmail).where(RawEmail.gmail_id == email.gmail_id)
            )
            if existing.scalar_one_or_none():
                logger.debug("  → Skipping already-processed email: %s", email.gmail_id)
                continue

            stats["emails_new"] += 1

            # Find or create newsletter
            newsletter = await _get_or_create_newsletter(session, email)

            # Store raw email
            raw_email = RawEmail(
                gmail_id=email.gmail_id,
                newsletter_id=newsletter.id,
                subject=email.subject,
                from_address=email.from_address,
                received_at=email.received_at,
                raw_html=email.html_body,
                raw_text=email.text_body,
            )
            session.add(raw_email)
            await session.flush()

            # Step 3: Parse and segment
            logger.info("[3/5] Parsing: '%s' from %s", email.subject, newsletter.name)
            html = email.html_body or email.text_body or ""
            cleaned = clean_html(html) if email.html_body else html
            stories = segment_newsletter(cleaned, subject=email.subject)
            logger.info("  → Extracted %d stories", len(stories))

            if needs_llm_fallback(stories):
                stats["llm_fallback_needed"] += 1
                logger.warning(
                    "  ⚠ Only %d stories found — flagged for LLM fallback. "
                    "Raw email stored for reprocessing.",
                    len(stories),
                )

            # Step 4: Dedup and create story groups
            logger.info("[4/5] Deduplicating stories...")

            # Get existing story groups for dedup comparison
            existing_groups_result = await session.execute(
                select(StoryGroup).order_by(StoryGroup.first_seen_at.desc()).limit(200)
            )
            existing_groups = existing_groups_result.scalars().all()
            existing_for_dedup = [
                {
                    "story_group_id": str(sg.id),
                    "url_canonical": sg.url_canonical,
                    "title": sg.title,
                }
                for sg in existing_groups
            ]

            for parsed_story in stories:
                url_canonical = canonicalize_url(parsed_story.url)

                # Check for duplicates
                dup_group_id = find_duplicate(
                    url_canonical, parsed_story.title, existing_for_dedup
                )

                # Create the story record
                story = Story(
                    raw_email_id=raw_email.id,
                    newsletter_id=newsletter.id,
                    title=parsed_story.title,
                    summary=parsed_story.summary,
                    url=parsed_story.url,
                    url_canonical=url_canonical,
                    image_url=parsed_story.image_url,
                    author=parsed_story.author,
                    position_in_email=parsed_story.position,
                    is_duplicate=dup_group_id is not None,
                    tags=parsed_story.tags or [],
                )
                session.add(story)
                await session.flush()

                stats["stories_extracted"] += 1

                if dup_group_id:
                    # Add to existing group
                    stats["stories_deduped"] += 1
                    from uuid import UUID

                    group_uuid = UUID(dup_group_id)
                    member = StoryGroupMember(
                        story_group_id=group_uuid, story_id=story.id
                    )
                    session.add(member)

                    # Update group count
                    group = await session.get(StoryGroup, group_uuid)
                    if group:
                        group.story_count += 1

                    logger.debug("  → Duplicate: '%s' → existing group", parsed_story.title[:50])
                else:
                    # Create new group
                    group = StoryGroup(
                        canonical_story_id=story.id,
                        title=parsed_story.title,
                        url_canonical=url_canonical,
                        story_count=1,
                        first_seen_at=datetime.now(timezone.utc),
                    )
                    session.add(group)
                    await session.flush()

                    member = StoryGroupMember(
                        story_group_id=group.id, story_id=story.id
                    )
                    session.add(member)

                    stats["groups_created"] += 1

                    # Add to dedup comparison set for remaining stories
                    existing_for_dedup.append({
                        "story_group_id": str(group.id),
                        "url_canonical": url_canonical,
                        "title": parsed_story.title,
                    })

                    logger.debug("  → New story group: '%s'", parsed_story.title[:50])

            # Mark email as parsed
            raw_email.parsed = True

            # Mark as read in Gmail
            try:
                mark_as_read(service, email.gmail_id)
            except Exception:
                logger.warning("Could not mark email %s as read", email.gmail_id)

        await session.commit()

    # Step 5: Summary
    logger.info("[5/5] Pipeline complete!")
    logger.info("=" * 60)
    logger.info("  Emails fetched:      %d", stats["emails_fetched"])
    logger.info("  New emails:          %d", stats["emails_new"])
    logger.info("  Stories extracted:    %d", stats["stories_extracted"])
    logger.info("  Duplicates found:    %d", stats["stories_deduped"])
    logger.info("  New story groups:    %d", stats["groups_created"])
    logger.info("  LLM fallback needed: %d", stats["llm_fallback_needed"])
    logger.info("=" * 60)

    return stats


async def _get_or_create_newsletter(session, email: EmailMessage) -> Newsletter:
    """Find or create a newsletter entry for this sender."""
    # Extract a clean email address from "Name <email>" format
    from_addr = email.from_address
    if "<" in from_addr:
        from_addr = from_addr.split("<")[1].rstrip(">")

    result = await session.execute(
        select(Newsletter).where(Newsletter.sender_email == from_addr)
    )
    newsletter = result.scalar_one_or_none()

    if newsletter:
        newsletter.email_count += 1
        return newsletter

    newsletter = Newsletter(
        name=extract_newsletter_name(email.from_address, email.subject),
        sender_email=from_addr,
        sender_domain=extract_sender_domain(from_addr),
    )
    session.add(newsletter)
    await session.flush()
    return newsletter


if __name__ == "__main__":
    asyncio.run(run_pipeline())
