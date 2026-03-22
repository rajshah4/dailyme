from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from uuid import UUID
from xml.etree import ElementTree as ET

from fastapi import Depends, FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_session
from app.models import (
    Feedback,
    InterestWeight,
    SocialStory,
    Story,
    StoryGroup,
    StoryGroupMember,
)
from app.processing.ranker import rank_story_groups

STORY_TTL_DAYS = 3

app = FastAPI(title="DailyMe", description="Personalized AI news from newsletters")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _story_group_query(starred: bool = False):
    cutoff = datetime.now(timezone.utc) - timedelta(days=STORY_TTL_DAYS)

    query = (
        select(StoryGroup)
        .options(
            selectinload(StoryGroup.canonical_story).selectinload(Story.newsletter),
            selectinload(StoryGroup.canonical_story).selectinload(Story.cluster),
            selectinload(StoryGroup.members),
        )
        .where((StoryGroup.first_seen_at >= cutoff) | (StoryGroup.starred == True))
        .order_by(StoryGroup.first_seen_at.desc())
        .limit(100)
    )

    if starred:
        query = (
            select(StoryGroup)
            .options(
                selectinload(StoryGroup.canonical_story).selectinload(Story.newsletter),
                selectinload(StoryGroup.canonical_story).selectinload(Story.cluster),
                selectinload(StoryGroup.members),
            )
            .where(StoryGroup.starred == True)
            .order_by(StoryGroup.first_seen_at.desc())
            .limit(100)
        )

    return query


async def _load_ranked_stories(session: AsyncSession, starred: bool = False):
    result = await session.execute(_story_group_query(starred=starred))
    story_groups = result.scalars().all()

    weights_result = await session.execute(select(InterestWeight))
    weights = {w.topic_keyword: w.weight for w in weights_result.scalars().all()}

    feedback_result = await session.execute(
        select(Feedback).order_by(Feedback.created_at.desc()).limit(200)
    )
    feedback_map = {}
    for fb in feedback_result.scalars().all():
        if fb.story_group_id:
            feedback_map[fb.story_group_id] = fb.action

    ranked = rank_story_groups(story_groups, weights, feedback_map)
    return story_groups, ranked, feedback_map, weights


def _build_rss_xml(
    stories,
    base_url: str,
    *,
    tag: str | None = None,
    starred: bool = False,
    now: datetime | None = None,
) -> bytes:
    channel_title = "DailyMe News Feed"
    if starred:
        channel_title += " (Starred)"
    if tag:
        channel_title += f" — {tag}"

    built_at = now or datetime.now(timezone.utc)
    if built_at.tzinfo is None:
        built_at = built_at.replace(tzinfo=timezone.utc)

    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = channel_title
    ET.SubElement(channel, "link").text = base_url
    ET.SubElement(channel, "description").text = "Personalized AI news stories from DailyMe"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(
        built_at.astimezone(timezone.utc),
        usegmt=True,
    )

    for story in stories:
        item = ET.SubElement(channel, "item")
        story_url = story.url or base_url

        ET.SubElement(item, "title").text = story.title
        ET.SubElement(item, "link").text = story_url

        guid = ET.SubElement(item, "guid", isPermaLink="false")
        guid.text = str(story.story_group_id)

        pub_at = story.first_seen_at or built_at
        if pub_at.tzinfo is None:
            pub_at = pub_at.replace(tzinfo=timezone.utc)
        ET.SubElement(item, "pubDate").text = format_datetime(
            pub_at.astimezone(timezone.utc),
            usegmt=True,
        )

        ET.SubElement(item, "description").text = story.summary or ""
        for story_tag in story.tags:
            ET.SubElement(item, "category").text = story_tag

    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


async def _load_social_stories(session: AsyncSession, limit: int = 40):
    result = await session.execute(
        select(SocialStory)
        .order_by(SocialStory.fetched_at.desc(), SocialStory.rank_score.desc(), SocialStory.score.desc())
        .limit(limit)
    )
    return result.scalars().all()


def _build_social_rss_xml(stories, base_url: str, now: datetime | None = None) -> bytes:
    built_at = now or datetime.now(timezone.utc)
    if built_at.tzinfo is None:
        built_at = built_at.replace(tzinfo=timezone.utc)

    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "DailyMe Social Top Stories"
    ET.SubElement(channel, "link").text = base_url
    ET.SubElement(channel, "description").text = (
        "Top-curated stories from Hacker News and Reddit, refreshed every 2 hours"
    )
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(
        built_at.astimezone(timezone.utc),
        usegmt=True,
    )

    for story in stories:
        item = ET.SubElement(channel, "item")
        link = story.url or story.permalink or base_url

        ET.SubElement(item, "title").text = story.title
        ET.SubElement(item, "link").text = link

        guid = ET.SubElement(item, "guid", isPermaLink="false")
        guid.text = f"{story.source}:{story.external_id}"

        pub_at = story.source_created_at or story.fetched_at or built_at
        if pub_at.tzinfo is None:
            pub_at = pub_at.replace(tzinfo=timezone.utc)
        ET.SubElement(item, "pubDate").text = format_datetime(
            pub_at.astimezone(timezone.utc),
            usegmt=True,
        )

        description_parts = [
            f"Source: {story.source}",
            f"Community: {story.community}",
            f"Score: {story.score}",
        ]
        if story.comment_count:
            description_parts.append(f"Comments: {story.comment_count}")
        if story.summary:
            description_parts.append(story.summary)
        ET.SubElement(item, "description").text = " | ".join(description_parts)

        ET.SubElement(item, "category").text = f"source:{story.source}"
        ET.SubElement(item, "category").text = f"community:{story.community}"
        for story_tag in story.tags or []:
            ET.SubElement(item, "category").text = story_tag

    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def feed(
    request: Request,
    tag: str | None = Query(None),
    starred: bool = Query(False),
    session: AsyncSession = Depends(get_session),
):
    """Front page: ranked, deduped story feed with optional tag filter."""
    story_groups, ranked, feedback_map, weights = await _load_ranked_stories(
        session,
        starred=starred,
    )

    # Tag filter (post-ranking, since tags come from the canonical story)
    if tag:
        ranked = [r for r in ranked if tag in r.tags]

    # Collect all unique tags for the filter UI
    all_tags = sorted({t for r in ranked for t in r.tags}) if not tag else []
    if tag:
        # Recompute from unfiltered set for the filter bar
        all_ranked = rank_story_groups(story_groups, weights, feedback_map)
        all_tags = sorted({t for r in all_ranked for t in r.tags})

    # Build starred set for template
    starred_ids = {sg.id for sg in story_groups if sg.starred}

    return templates.TemplateResponse(
        "feed.html",
        {
            "request": request,
            "stories": ranked,
            "feedback_map": feedback_map,
            "starred_ids": starred_ids,
            "all_tags": all_tags,
            "active_tag": tag,
            "show_starred": starred,
            "last_updated": datetime.now(timezone.utc),
        },
    )



@app.get("/rss.xml")
async def rss_feed(
    request: Request,
    tag: str | None = Query(None),
    starred: bool = Query(False),
    session: AsyncSession = Depends(get_session),
):
    """RSS feed of ranked stories with optional tag/starred filtering."""
    _, ranked, _, _ = await _load_ranked_stories(session, starred=starred)

    if tag:
        ranked = [r for r in ranked if tag in r.tags]

    xml = _build_rss_xml(
        ranked,
        str(request.base_url).rstrip("/"),
        tag=tag,
        starred=starred,
    )
    return Response(content=xml, media_type="application/rss+xml")



@app.get("/social/rss.xml")
async def social_rss_feed(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """RSS feed for curated top social stories (HN + Reddit)."""
    stories = await _load_social_stories(session, limit=40)
    xml = _build_social_rss_xml(
        stories,
        str(request.base_url).rstrip("/") + "/social",
    )
    return Response(content=xml, media_type="application/rss+xml")


@app.post("/feedback")
async def submit_feedback(
    story_group_id: UUID = Form(...),
    action: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    """Submit thumbs up/down feedback as recommendation signal."""
    fb = Feedback(story_group_id=story_group_id, action=action)
    session.add(fb)
    await session.commit()
    return RedirectResponse(url="/", status_code=303)


@app.post("/star")
async def toggle_star(
    story_group_id: UUID = Form(...),
    session: AsyncSession = Depends(get_session),
):
    """Toggle star/save on a story group."""
    group = await session.get(StoryGroup, story_group_id)
    if group:
        group.starred = not group.starred
        await session.commit()
    return RedirectResponse(url="/", status_code=303)


@app.post("/cleanup")
async def cleanup_expired(session: AsyncSession = Depends(get_session)):
    """Delete stories older than TTL that aren't starred. Called by cron."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=STORY_TTL_DAYS)

    # Find expired, non-starred groups
    expired = await session.execute(
        select(StoryGroup.id).where(
            StoryGroup.first_seen_at < cutoff,
            StoryGroup.starred == False,
        )
    )
    expired_ids = [r[0] for r in expired.all()]

    if not expired_ids:
        return {"deleted": 0}

    # Delete members, then groups
    await session.execute(
        delete(StoryGroupMember).where(StoryGroupMember.story_group_id.in_(expired_ids))
    )
    await session.execute(
        delete(Feedback).where(Feedback.story_group_id.in_(expired_ids))
    )
    await session.execute(
        delete(StoryGroup).where(StoryGroup.id.in_(expired_ids))
    )
    await session.commit()

    return {"deleted": len(expired_ids)}


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/stats")
async def stats(session: AsyncSession = Depends(get_session)):
    """Pipeline stats for observability."""
    story_count = await session.scalar(select(func.count(Story.id)))
    group_count = await session.scalar(select(func.count(StoryGroup.id)))
    feedback_count = await session.scalar(select(func.count(Feedback.id)))
    starred_count = await session.scalar(
        select(func.count(StoryGroup.id)).where(StoryGroup.starred == True)
    )
    return {
        "total_stories": story_count,
        "story_groups": group_count,
        "starred": starred_count,
        "feedback_actions": feedback_count,
    }
