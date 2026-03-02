from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from fastapi import Depends, FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_session
from app.models import (
    Feedback,
    InterestWeight,
    Story,
    StoryGroup,
    StoryGroupMember,
)
from app.processing.ranker import rank_story_groups

STORY_TTL_DAYS = 7

app = FastAPI(title="DailyMe", description="Personalized AI news from newsletters")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def feed(
    request: Request,
    tag: str | None = Query(None),
    starred: bool = Query(False),
    session: AsyncSession = Depends(get_session),
):
    """Front page: ranked, deduped story feed with optional tag filter."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=STORY_TTL_DAYS)

    # Base query: non-expired OR starred
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

    # Starred filter
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

    result = await session.execute(query)
    story_groups = result.scalars().all()

    # Get interest weights for ranking
    weights_result = await session.execute(select(InterestWeight))
    weights = {w.topic_keyword: w.weight for w in weights_result.scalars().all()}

    # Get recent feedback
    feedback_result = await session.execute(
        select(Feedback).order_by(Feedback.created_at.desc()).limit(200)
    )
    feedback_map = {}
    for fb in feedback_result.scalars().all():
        if fb.story_group_id:
            feedback_map[fb.story_group_id] = fb.action

    # Rank the stories
    ranked = rank_story_groups(story_groups, weights, feedback_map)

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
