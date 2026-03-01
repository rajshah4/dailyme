"""Ranking and personalization: score story groups for the front page.

score = (w_recency * recency) + (w_coverage * coverage) + (w_interest * interest)
      + (w_feedback * feedback) + (w_position * position)
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from app.processing.clustering import assign_topic, get_topic_display_name

logger = logging.getLogger(__name__)

# Default ranking weights
W_RECENCY = 0.30
W_COVERAGE = 0.25
W_INTEREST = 0.25
W_FEEDBACK = 0.15
W_POSITION = 0.05


@dataclass
class RankedStory:
    """A story group with its computed score, ready for display."""

    story_group_id: UUID
    title: str
    summary: str | None
    url: str | None
    image_url: str | None
    newsletter_name: str | None
    newsletter_count: int
    topic_key: str
    topic_label: str
    score: float
    first_seen_at: datetime | None
    recency_score: float
    coverage_score: float
    interest_score: float
    feedback_score: float
    position_score: float


def rank_story_groups(
    story_groups,
    interest_weights: dict[str, float],
    feedback_map: dict[UUID, str],
) -> list[RankedStory]:
    """Rank story groups and return sorted list for display."""
    ranked = []

    for sg in story_groups:
        story = sg.canonical_story
        if not story:
            continue

        # Compute topic
        topic_key = assign_topic(story.title, story.summary)
        topic_label = get_topic_display_name(topic_key)

        # Check if topic is hidden
        interest_weight = interest_weights.get(topic_key, 1.0)
        if interest_weight <= 0:
            continue  # hidden topic

        # Recency: 1.0 for brand new, 0.0 after 48 hours
        recency = _recency_score(sg.first_seen_at)

        # Coverage: more newsletters = more important (capped at 5)
        coverage = min(sg.story_count / 5.0, 1.0)

        # Interest: from user-defined topic weights
        interest = min(interest_weight, 2.0) / 2.0  # normalize to [0, 1]

        # Feedback: boost/penalize based on recent actions
        feedback = _feedback_score(sg.id, topic_key, feedback_map)

        # Position: stories at the top of newsletters are more important
        position = _position_score(story.position_in_email)

        # Composite score
        score = (
            W_RECENCY * recency
            + W_COVERAGE * coverage
            + W_INTEREST * interest
            + W_FEEDBACK * feedback
            + W_POSITION * position
        )

        newsletter_name = story.newsletter.name if story.newsletter else None

        ranked.append(RankedStory(
            story_group_id=sg.id,
            title=story.title,
            summary=story.summary,
            url=story.url,
            image_url=story.image_url,
            newsletter_name=newsletter_name,
            newsletter_count=sg.story_count,
            topic_key=topic_key,
            topic_label=topic_label,
            score=score,
            first_seen_at=sg.first_seen_at,
            recency_score=recency,
            coverage_score=coverage,
            interest_score=interest,
            feedback_score=feedback,
            position_score=position,
        ))

    # Sort by score descending
    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked


def _recency_score(first_seen_at: datetime | None) -> float:
    if not first_seen_at:
        return 0.5
    now = datetime.now(timezone.utc)
    hours = (now - first_seen_at).total_seconds() / 3600
    return max(0.0, 1.0 - hours / 48.0)


def _feedback_score(
    story_group_id: UUID,
    topic_key: str,
    feedback_map: dict[UUID, str],
) -> float:
    action = feedback_map.get(story_group_id)
    if action == "thumbs_up":
        return 0.3
    elif action == "thumbs_down":
        return -0.5
    return 0.0


def _position_score(position: int | None) -> float:
    if position is None:
        return 0.5
    return max(0.0, 1.0 - position / 10.0)
