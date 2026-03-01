"""Story segmentation: split one newsletter into multiple story items.

Three-layer approach:
  Layer 1 — Structural HTML signals (heading/block detection)
  Layer 2 — Heuristic text signals (pattern matching)
  Layer 3 — LLM fallback (OpenHands agent handles this externally)

Post-processing:
  - Filter junk sections (subscribe CTAs, paywall prompts, share buttons)
  - Detect content tags (long_form, vendor, podcast, research, etc.)
  - Detect single-article newsletters and tag as long_form
"""

import logging
import re

from bs4 import BeautifulSoup, Tag

from app.processing.substack import clean_story_urls, is_substack_email
from app.processing.tagger import detect_tags, is_junk_section
from app.schemas import ParsedStory

logger = logging.getLogger(__name__)

MIN_STORIES_THRESHOLD = 2
MIN_TITLE_LENGTH = 10
MAX_TITLE_LENGTH = 200


def segment_newsletter(
    html: str,
    subject: str | None = None,
    from_address: str | None = None,
    raw_html: str | None = None,
) -> list[ParsedStory]:
    """Segment a newsletter into individual stories.

    Args:
        html: Cleaned HTML for segmentation
        subject: Email subject line
        from_address: Sender email (for platform-specific handling)
        raw_html: Original raw HTML (for URL extraction — clean_html may strip some)
    """
    # Use raw HTML for URL extraction, cleaned HTML for segmentation
    url_html = raw_html or html

    # Layer 1: Structural HTML
    stories = _segment_structural(html)
    if len(stories) >= MIN_STORIES_THRESHOLD:
        logger.info("Layer 1 (structural): found %d raw stories", len(stories))
        stories = _post_process(stories, html, url_html, subject, from_address)
        return stories

    # Layer 2: Heuristic text
    stories = _segment_heuristic(html)
    if len(stories) >= MIN_STORIES_THRESHOLD:
        logger.info("Layer 2 (heuristic): found %d raw stories", len(stories))
        stories = _post_process(stories, html, url_html, subject, from_address)
        return stories

    # Layer 3: Return what we have — LLM fallback handled by OpenHands agent
    logger.warning(
        "Layers 1-2 found %d stories (below threshold). "
        "Flagging for LLM fallback.",
        len(stories),
    )
    # For single-article newsletters, return the whole thing as one long_form story
    if subject and len(stories) <= 1:
        stories = _fallback_single_article(html, subject, url_html)
    # Resolve Substack URLs if applicable
    if from_address and is_substack_email(from_address):
        stories = clean_story_urls(stories, url_html, fill_missing=True)
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


# Generic section headings that suggest article structure, not separate stories
_SECTION_TITLE_PATTERNS = [
    r"^introduction$", r"^conclusion$", r"^summary$", r"^overview$",
    r"^background$", r"^methods?$", r"^results?$", r"^discussion$",
    r"^(?:the )?algorithm\b", r"^(?:the )?implementation\b",
    r"^(?:the )?approach\b", r"^(?:the )?framework\b",
    r"^(?:the )?architecture\b", r"^(?:the )?model\b",
    r"^theoretical\b", r"^empirical\b", r"^experimental\b",
    r"^key (?:findings?|takeaways?|insights?|points?)\b",
    r"^what (?:is|are|we|this)\b",
    r"^why (?:this|it|does)\b",
    r"^how (?:it|this|to)\b",
    r"^behind the scenes\b",
    r"^find the podcast\b",
    r"^office hours\b",
]


def _looks_like_single_article(stories: list[ParsedStory], subject: str) -> bool:
    """Heuristic: detect if segmented 'stories' are actually sections of one article.

    Signals:
    1. First story title closely matches the email subject
    2. Most stories have no URL (they're just section headers)
    3. Section titles look like article structure (Introduction, Methods, etc.)
    4. Only substack/self-referential links present
    """
    # Signal 1: first story title ~ subject
    first_title = stories[0].title.lower().strip()
    subject_lower = subject.lower().strip()
    title_matches_subject = (
        first_title in subject_lower
        or subject_lower in first_title
        or _jaccard_words(first_title, subject_lower) > 0.5
    )

    # Signal 2: fraction of stories without URLs
    no_url_count = sum(1 for s in stories if not s.url)
    no_url_fraction = no_url_count / len(stories)

    # Signal 3: section-like titles
    section_count = 0
    for s in stories[1:]:  # skip first (main title)
        title_lower = s.title.lower().strip()
        for pat in _SECTION_TITLE_PATTERNS:
            if re.search(pat, title_lower):
                section_count += 1
                break
    section_fraction = section_count / max(len(stories) - 1, 1)

    # Decision: combine signals
    # Strong: title matches + most have no URL
    if title_matches_subject and no_url_fraction >= 0.5:
        return True
    # Strong: title matches + many section headers
    if title_matches_subject and section_fraction >= 0.5:
        return True
    # Moderate: lots of section headers + few URLs
    if section_fraction >= 0.6 and no_url_fraction >= 0.4:
        return True

    return False


def _jaccard_words(a: str, b: str) -> float:
    """Word-level Jaccard similarity."""
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def _post_process(
    stories: list[ParsedStory],
    html: str,
    url_html: str,
    subject: str | None,
    from_address: str | None = None,
) -> list[ParsedStory]:
    """Post-process extracted stories: filter junk, detect tags, handle single-article."""
    # Step 1: Filter junk sections
    clean = []
    filtered_count = 0
    for story in stories:
        if is_junk_section(story.title, story.summary):
            filtered_count += 1
            logger.debug("  Filtered junk: '%s'", story.title[:60])
            continue
        clean.append(story)

    if filtered_count:
        logger.info("  Filtered %d junk sections", filtered_count)

    # Step 2: Detect if this is a single-article newsletter
    if subject and len(clean) >= 2 and _looks_like_single_article(clean, subject):
        logger.info("  Detected single-article newsletter — collapsing to 1 long_form story")
        result = _fallback_single_article(html, subject, url_html)
        if from_address and is_substack_email(from_address):
            result = clean_story_urls(result, url_html, fill_missing=True)
        return result

    # Step 3: Resolve Substack tracking URLs to direct links
    if from_address and is_substack_email(from_address):
        clean = clean_story_urls(clean, url_html)
        logger.info("  Resolved Substack tracking URLs")

    # Step 4: Tag each story
    for story in clean:
        story.tags = detect_tags(story.title, story.summary)

    # Step 5: Renumber positions
    for i, story in enumerate(clean):
        story.position = i

    return clean


def _fallback_single_article(
    html: str, subject: str, url_html: str | None = None,
) -> list[ParsedStory]:
    """For single-article newsletters, return the whole thing as one long_form story."""
    from app.processing.substack import extract_article_url

    soup = BeautifulSoup(html, "lxml")

    # Get all text as summary
    text = soup.get_text(" ", strip=True)
    # Trim to reasonable summary length
    summary = text[:600].strip()
    if len(text) > 600:
        summary += "..."

    # Try Substack-specific extraction first (from raw HTML for best results)
    url = extract_article_url(url_html or html)

    # Fallback: find the first meaningful external link
    if not url:
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if _is_story_link(href) and not href.startswith("https://substack.com/@"):
                url = href
                break

    tags = ["long_form"]
    tags.extend(detect_tags(subject, summary))
    # Deduplicate tags
    tags = list(dict.fromkeys(tags))

    return [ParsedStory(
        title=subject,
        summary=summary,
        url=url,
        position=0,
        tags=tags,
    )]


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
