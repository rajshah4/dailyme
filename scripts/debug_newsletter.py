"""Debug missing newsletter - check Gmail, database, and parsing status."""

import asyncio
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from app.config import settings
from app.db import async_session
from app.ingestion.gmail import fetch_labeled_emails, get_gmail_service
from app.models import Newsletter, RawEmail, Story, StoryGroup
from sqlalchemy import select


async def check_database(newsletter_name: str):
    """Check if newsletter exists in database."""
    print(f"\n🔍 Checking database for: {newsletter_name}")
    print("=" * 60)
    
    async with async_session() as session:
        # Check newsletters table
        result = await session.execute(
            select(Newsletter).where(Newsletter.name.ilike(f"%{newsletter_name}%"))
        )
        newsletters = result.scalars().all()
        
        if newsletters:
            print(f"✅ Found {len(newsletters)} matching newsletter(s):")
            for nl in newsletters:
                print(f"   - {nl.name} (id: {nl.id})")
                
                # Check for raw emails
                email_result = await session.execute(
                    select(RawEmail).where(RawEmail.newsletter_id == nl.id)
                )
                emails = email_result.scalars().all()
                print(f"     📧 {len(emails)} emails in raw_emails")
                
                if emails:
                    latest = max(emails, key=lambda e: e.received_at)
                    print(f"     📅 Latest: {latest.subject[:50]}... ({latest.received_at})")
                    print(f"     🔄 Parsed: {latest.parsed}")
                
                # Check for stories
                story_result = await session.execute(
                    select(Story).where(Story.newsletter_id == nl.id)
                )
                stories = story_result.scalars().all()
                print(f"     📰 {len(stories)} stories extracted")
                
                if stories:
                    recent_stories = sorted(stories, key=lambda s: s.created_at, reverse=True)[:3]
                    print(f"     📋 Recent stories:")
                    for s in recent_stories:
                        print(f"        - {s.title[:60]}...")
        else:
            print(f"❌ No newsletter found matching: {newsletter_name}")
            
        # Check all newsletters
        all_newsletters = await session.execute(select(Newsletter))
        print(f"\n📚 All newsletters in database:")
        for nl in all_newsletters.scalars().all():
            print(f"   - {nl.name}")


def check_gmail(newsletter_name: str):
    """Check Gmail for emails with DailyMe label."""
    print(f"\n📬 Checking Gmail for: {newsletter_name}")
    print("=" * 60)
    
    try:
        service = get_gmail_service()
        emails = fetch_labeled_emails(service, max_results=50, max_age_days=7)
        
        print(f"✅ Found {len(emails)} total emails with DailyMe label (last 7 days)")
        
        # Filter by newsletter name
        matching = [e for e in emails if newsletter_name.lower() in e.subject.lower() 
                    or newsletter_name.lower() in e.from_address.lower()]
        
        if matching:
            print(f"\n✅ Found {len(matching)} matching email(s):")
            for e in matching:
                print(f"   📧 Subject: {e.subject}")
                print(f"   📧 From: {e.from_address}")
                print(f"   📅 Received: {e.received_at}")
                print(f"   🆔 Gmail ID: {e.gmail_id}")
                print()
        else:
            print(f"❌ No emails found matching: {newsletter_name}")
            print(f"\n💡 Recent emails in DailyMe label:")
            for e in emails[:5]:
                print(f"   - {e.subject[:60]}... from {e.from_address}")
                
    except Exception as e:
        print(f"❌ Error checking Gmail: {e}")
        print("\n💡 Make sure:")
        print("   1. The email has the 'DailyMe' label in Gmail")
        print("   2. GMAIL_TOKEN_JSON is set correctly")
        print("   3. The email arrived within the last 7 days")


async def check_story_groups(newsletter_name: str):
    """Check story groups for matching stories."""
    print(f"\n📊 Checking story groups")
    print("=" * 60)
    
    async with async_session() as session:
        # Get recent story groups
        result = await session.execute(
            select(StoryGroup)
            .order_by(StoryGroup.first_seen_at.desc())
            .limit(20)
        )
        groups = result.scalars().all()
        
        print(f"✅ Found {len(groups)} recent story groups")
        
        if groups:
            print(f"\n📋 Most recent stories:")
            for g in groups[:10]:
                canonical = await session.get(Story, g.canonical_story_id)
                if canonical:
                    newsletter = await session.get(Newsletter, canonical.newsletter_id)
                    print(f"   - {canonical.title[:60]}...")
                    print(f"     from {newsletter.name if newsletter else 'Unknown'} ({g.first_seen_at})")


async def main():
    """Run all checks."""
    if len(sys.argv) < 2:
        print("Usage: python scripts/debug_newsletter.py 'Newsletter Name'")
        print("\nExample: python scripts/debug_newsletter.py 'AI News'")
        sys.exit(1)
    
    newsletter_name = sys.argv[1]
    
    print(f"\n{'='*60}")
    print(f"  DailyMe Newsletter Debugger")
    print(f"{'='*60}")
    print(f"Searching for: {newsletter_name}")
    print(f"Current time: {datetime.now(timezone.utc)}")
    
    # Check Gmail first
    check_gmail(newsletter_name)
    
    # Check database
    await check_database(newsletter_name)
    
    # Check story groups
    await check_story_groups(newsletter_name)
    
    print(f"\n{'='*60}")
    print("✅ Diagnostic complete!")
    print(f"{'='*60}\n")
    
    print("💡 Troubleshooting tips:")
    print("   1. If email is in Gmail but not database:")
    print("      → Run the pipeline: uv run python scripts/run_pipeline.py")
    print("   2. If email is in database but not parsed:")
    print("      → Check the pipeline logs for parsing errors")
    print("   3. If stories are extracted but not showing on website:")
    print("      → Check the story's first_seen_at timestamp")
    print("      → Stories older than 3 days won't show (unless starred)")
    print("   4. If email doesn't have DailyMe label:")
    print("      → Add the label in Gmail and wait for next pipeline run")


if __name__ == "__main__":
    asyncio.run(main())
