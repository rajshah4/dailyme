"""Story segmentation: split one newsletter into multiple story items.

Three-layer approach:
  Layer 1 — Structural HTML signals (heading/block detection)
  Layer 2 — Heuristic text signals (pattern matching)
  Layer 3 — LLM fallback (OpenHands agent handles this externally)
"""

import logging
import re

from bs4 import BeautifulSoup, Tag

from app.schemas import ParsedStory

logger = logging.getLogger(__name__)

MIN_STORIES_THRESHOLD = 2
MIN_TITLE_LENGTH = 10
MAX_TITLE_LENGTH = 200


def segment_newsletter(html: str) -> list[ParsedStory]:
    """Segment a newsletter into individual stories.

    Tries structural parsing first, falls back to heuristic, then returns
    partial results for LLM fallback if needed.
    """
    # Layer 1: Structural HTML
    stories = _segment_structural(html)
    if len(stories) >= MIN_STORIES_THRESHOLD:
        logger.info("Layer 1 (structural): found %d stories", len(stories))
        return stories

    # Layer 2: Heuristic text
    stories = _segment_heuristic(html)
    if len(stories) >= MIN_STORIES_THRESHOLD:
        logger.info("Layer 2 (heuristic): found %d stories", len(stories))
        return stories

    # Layer 3: Return what we have — LLM fallback handled by OpenHands agent
    logger.warning(
        "Layers 1-2 found %d stories (below threshold). "
        "Flagging for LLM fallback.",
        len(stories),
    )
    return stories


def _segment_structural(html: str) -> list[ParsedStory]:
    """Layer 1: Extract stories using HTML heading/block structure."""
    soup = BeautifulSoup(html, "lxml")
    stories = []

    # Look for heading tags that likely introduce stories
    headings = soup.find_all(["h1", "h2", "h3", "h4"])

    for i, heading in enumerate(headings):
        title = heading.get_text(strip=True)
        if not title or len(title) < MIN_TITLE_LENGTH or len(title) > MAX_TITLE_LENGTH:
            continue

        # Collect body text and links between this heading and the next
        body_parts = []
        urls = []
        sibling = heading.next_sibling

        while sibling:
            if isinstance(sibling, Tag):
                if sibling.name in ["h1", "h2", "h3", "h4"]:
                    break
                if sibling.name == "hr":
                    break

                text = sibling.get_text(strip=True)
                if text:
                    body_parts.append(text)

                # Extract links
                for a in (
                    sibling.find_all("a", href=True) if hasattr(sibling, "find_all") else []
                ):
                    href = a["href"]
                    if _is_story_link(href):
                        urls.append(href)

            sibling = sibling.next_sibling

        summary = " ".join(body_parts)[:500] if body_parts else None
        url = urls[0] if urls else None

        # Also check if the heading itself is a link
        heading_link = heading.find("a", href=True)
        if heading_link and _is_story_link(heading_link["href"]):
            url = heading_link["href"]

        stories.append(ParsedStory(
            title=title,
            summary=summary,
            url=url,
            position=len(stories),
        ))

    return stories


def _segment_heuristic(html: str) -> list[ParsedStory]:
    """Layer 2: Extract stories using text pattern heuristics."""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text("\n", strip=True)
    stories = []

    # Split on horizontal rules or double newlines with short lines (potential headings)
    blocks = re.split(r"\n{3,}|_{3,}|-{3,}|={3,}", text)

    for block in blocks:
        block = block.strip()
        if not block or len(block) < 30:
            continue

        lines = block.split("\n")
        # First short line might be a title
        potential_title = lines[0].strip()

        if (
            MIN_TITLE_LENGTH <= len(potential_title) <= MAX_TITLE_LENGTH
            and len(lines) > 1
        ):
            body = "\n".join(lines[1:]).strip()

            # Try to find a URL in the block
            url = None
            url_matches = re.findall(r"https?://[^\s<>\"']+", block)
            for u in url_matches:
                if _is_story_link(u):
                    url = u.rstrip(".,;:)")
                    break

            stories.append(ParsedStory(
                title=potential_title,
                summary=body[:500] if body else None,
                url=url,
                position=len(stories),
            ))

    return stories


def _is_story_link(url: str) -> bool:
    """Check if a URL is likely a story link (not tracking/social/unsub)."""
    skip_patterns = [
        "unsubscribe", "manage-preferences", "mailto:",
        "twitter.com/intent", "facebook.com/sharer",
        "linkedin.com/share", "t.co/", "bit.ly/",
        "list-manage.com", "mailchimp.com",
        "#", "javascript:",
    ]
    url_lower = url.lower()
    return not any(p in url_lower for p in skip_patterns)


def needs_llm_fallback(stories: list[ParsedStory]) -> bool:
    """Check if the segmentation result needs LLM fallback."""
    return len(stories) < MIN_STORIES_THRESHOLD
