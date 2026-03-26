"""Reprocess a specific email that failed during initial parsing."""

import asyncio
import sys
from sqlalchemy import select

from app.db import async_session
from app.models import RawEmail, Newsletter, Story, StoryGroup, StoryGroupMember
from app.processing.clustering import assign_topic
from app.processing.dedup import canonicalize_url, find_duplicate
from app.processing.segmenter import segment_newsletter
from app.ingestion.parser import clean_html

async def reprocess_email(gmail_id: str):
    """Reprocess a specific email by gmail_id.

    Uses separate DB sessions for fetch, LLM, and commit to avoid the 5-min
    Neon idle-connection timeout during long LLM calls.
    """
    import time
    from uuid import UUID

    # Phase 1: Fetch email data (short-lived session)
    async with async_session() as session:
        result = await session.execute(
            select(RawEmail, Newsletter)
            .join(Newsletter, RawEmail.newsletter_id == Newsletter.id)
            .where(RawEmail.gmail_id == gmail_id)
        )
        row = result.one_or_none()
        if not row:
            print(f"❌ Email with gmail_id {gmail_id} not found")
            return

        raw_email, newsletter = row
        email_id = raw_email.id
        email_subject = raw_email.subject
        email_from = raw_email.from_address
        email_received_at = raw_email.received_at
        newsletter_id = newsletter.id
        newsletter_name = newsletter.name
        raw_html = raw_email.raw_html or raw_email.raw_text or ""

        # Delete existing stories in this same session
        existing_result = await session.execute(
            select(Story).where(Story.raw_email_id == raw_email.id)
        )
        existing_stories = existing_result.scalars().all()
        if existing_stories:
            print(f"🗑️  Deleting {len(existing_stories)} existing stories...")
            for story in existing_stories:
                await session.delete(story)
            await session.commit()

    print(f"📧 Reprocessing email:")
    print(f"   Subject: {email_subject}")
    print(f"   Newsletter: {newsletter_name}")
    print(f"   Received: {email_received_at}")
    print()

    # Phase 2: LLM extraction (no DB session held)
    print("🤖 Extracting stories with LLM...")
    print(f"   Content length: {len(raw_html)} bytes")
    cleaned = clean_html(raw_html) if raw_html else ""
    print(f"   Cleaned length: {len(cleaned)} bytes")
    print(f"   Calling segment_newsletter with 1200s timeout...")

    start = time.time()
    try:
        stories = await asyncio.wait_for(
            segment_newsletter(
                cleaned,
                subject=email_subject,
                from_address=email_from,
                raw_html=raw_html,
            ),
            timeout=1200,
        )
        elapsed = time.time() - start
        print(f"   ✓ Segmentation completed in {elapsed:.1f}s")
    except Exception as e:
        print(f"❌ LLM extraction failed: {e}")
        async with async_session() as session:
            raw_email = await session.get(RawEmail, email_id)
            if raw_email:
                raw_email.parsed = True
                await session.commit()
        return

    print(f"✓ Extracted {len(stories)} stories")

    if not stories:
        print("⚠️  No stories extracted")
        async with async_session() as session:
            raw_email = await session.get(RawEmail, email_id)
            if raw_email:
                raw_email.parsed = True
                await session.commit()
        return

    # Phase 3: Dedup and store (fresh session)
    async with async_session() as session:
        raw_email = await session.get(RawEmail, email_id)

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

        print("💾 Storing stories...")
        new_groups = 0
        deduped = 0

        for parsed_story in stories:
            url_canonical = canonicalize_url(parsed_story.url)
            dup_group_id = find_duplicate(
                url_canonical, parsed_story.title, existing_for_dedup
            )

            story = Story(
                raw_email_id=email_id,
                newsletter_id=newsletter_id,
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

            if dup_group_id:
                deduped += 1
                group_uuid = UUID(dup_group_id)
                member = StoryGroupMember(story_group_id=group_uuid, story_id=story.id)
                session.add(member)
                group = await session.get(StoryGroup, group_uuid)
                if group:
                    group.story_count += 1
            else:
                new_groups += 1
                group = StoryGroup(
                    canonical_story_id=story.id,
                    title=parsed_story.title,
                    url_canonical=url_canonical,
                    story_count=1,
                    first_seen_at=email_received_at,
                )
                session.add(group)
                await session.flush()
                member = StoryGroupMember(story_group_id=group.id, story_id=story.id)
                session.add(member)
                existing_for_dedup.append({
                    "story_group_id": str(group.id),
                    "url_canonical": url_canonical,
                    "title": parsed_story.title,
                })

            print(f"   ✓ {parsed_story.title[:70]}")

        if raw_email:
            raw_email.parsed = True
        await session.commit()

    print()
    print(f"✅ Success!")
    print(f"   Stories extracted: {len(stories)}")
    print(f"   New story groups: {new_groups}")
    print(f"   Deduplicated: {deduped}")


if __name__ == "__main__":
    gmail_id = sys.argv[1] if len(sys.argv) > 1 else "19cbbc5f1c405eb4"
    asyncio.run(reprocess_email(gmail_id))
