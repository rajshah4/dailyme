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
    """Reprocess a specific email by gmail_id."""
    async with async_session() as session:
        # Find the email
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
        
        print(f"📧 Reprocessing email:")
        print(f"   Subject: {raw_email.subject}")
        print(f"   Newsletter: {newsletter.name}")
        print(f"   Received: {raw_email.received_at}")
        print()
        
        # Delete existing stories for this email
        result = await session.execute(
            select(Story).where(Story.raw_email_id == raw_email.id)
        )
        existing_stories = result.scalars().all()
        if existing_stories:
            print(f"🗑️  Deleting {len(existing_stories)} existing stories...")
            for story in existing_stories:
                await session.delete(story)
            await session.flush()
        
        # Parse and segment
        print("🤖 Extracting stories with LLM...")
        print(f"   Content length: {len(raw_email.raw_html or raw_email.raw_text or '')} bytes")
        raw_html = raw_email.raw_html or raw_email.raw_text or ""
        cleaned = clean_html(raw_html) if raw_email.raw_html else raw_html
        print(f"   Cleaned length: {len(cleaned)} bytes")
        print(f"   Calling segment_newsletter with 300s timeout...")
        
        import time
        start = time.time()
        try:
            stories = await asyncio.wait_for(
                segment_newsletter(
                    cleaned,
                    subject=raw_email.subject,
                    from_address=raw_email.from_address,
                    raw_html=raw_html,
                ),
                timeout=300,
            )
            elapsed = time.time() - start
            print(f"   ✓ Segmentation completed in {elapsed:.1f}s")
        except Exception as e:
            print(f"❌ LLM extraction failed: {e}")
            raw_email.parsed = True
            await session.commit()
            return
        
        print(f"✓ Extracted {len(stories)} stories")
        
        if not stories:
            print("⚠️  No stories extracted")
            raw_email.parsed = True
            await session.commit()
            return
        
        # Get existing story groups for dedup
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
        
        # Create stories and groups
        print("💾 Storing stories...")
        new_groups = 0
        deduped = 0
        
        for parsed_story in stories:
            url_canonical = canonicalize_url(parsed_story.url)
            
            # Check for duplicates
            dup_group_id = find_duplicate(
                url_canonical, parsed_story.title, existing_for_dedup
            )
            
            # Create story
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
            
            if dup_group_id:
                # Add to existing group
                deduped += 1
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
            else:
                # Create new group
                new_groups += 1
                group = StoryGroup(
                    canonical_story_id=story.id,
                    title=parsed_story.title,
                    url_canonical=url_canonical,
                    story_count=1,
                    first_seen_at=raw_email.received_at,
                )
                session.add(group)
                await session.flush()
                
                member = StoryGroupMember(
                    story_group_id=group.id, story_id=story.id
                )
                session.add(member)
                
                # Add to dedup list
                existing_for_dedup.append({
                    "story_group_id": str(group.id),
                    "url_canonical": url_canonical,
                    "title": parsed_story.title,
                })
            
            print(f"   ✓ {parsed_story.title[:70]}")
        
        # Mark as parsed
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
