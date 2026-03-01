import uuid
from datetime import datetime

from pydantic import BaseModel


class StoryCard(BaseModel):
    """A story as displayed on the front page."""

    id: uuid.UUID
    title: str
    summary: str | None
    url: str | None
    image_url: str | None
    newsletter_name: str | None
    newsletter_count: int  # how many newsletters covered this
    topic_label: str | None
    score: float
    first_seen_at: datetime | None
    is_thumbs_up: bool = False
    is_thumbs_down: bool = False


class FeedResponse(BaseModel):
    """The front page feed."""

    stories: list[StoryCard]
    total_count: int
    last_updated: datetime | None


class FeedbackRequest(BaseModel):
    """User feedback on a story."""

    story_group_id: uuid.UUID
    action: str  # thumbs_up, thumbs_down, hide_topic


class ParsedStory(BaseModel):
    """A story extracted from a newsletter during parsing."""

    title: str
    summary: str | None = None
    url: str | None = None
    image_url: str | None = None
    author: str | None = None
    position: int = 0
