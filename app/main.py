from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
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

app = FastAPI(title="DailyMe", description="Personalized AI news from newsletters")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def feed(request: Request, session: AsyncSession = Depends(get_session)):
    """Front page: ranked, deduped story feed."""
    # Get story groups with their canonical stories
    result = await session.execute(
        select(StoryGroup)
        .options(
            selectinload(StoryGroup.canonical_story).selectinload(Story.newsletter),
            selectinload(StoryGroup.canonical_story).selectinload(Story.cluster),
            selectinload(StoryGroup.members),
        )
        .order_by(StoryGroup.first_seen_at.desc())
        .limit(50)
    )
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

    return templates.TemplateResponse(
        "feed.html",
        {
            "request": request,
            "stories": ranked,
            "feedback_map": feedback_map,
            "last_updated": datetime.now(timezone.utc),
        },
    )


@app.post("/feedback")
async def submit_feedback(
    story_group_id: UUID = Form(...),
    action: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    """Submit thumbs up/down or hide topic feedback."""
    fb = Feedback(story_group_id=story_group_id, action=action)
    session.add(fb)
    await session.commit()
    return RedirectResponse(url="/", status_code=303)


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/stats")
async def stats(session: AsyncSession = Depends(get_session)):
    """Pipeline stats for observability."""
    story_count = await session.scalar(select(func.count(Story.id)))
    group_count = await session.scalar(select(func.count(StoryGroup.id)))
    feedback_count = await session.scalar(select(func.count(Feedback.id)))
    return {
        "total_stories": story_count,
        "story_groups": group_count,
        "feedback_actions": feedback_count,
    }
