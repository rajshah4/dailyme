"""LLM-powered newsletter story extraction.

Uses litellm (same backend as OpenHands) to extract stories from newsletters.
Configure via .env or environment variables:
  LLM_MODEL    — e.g. "anthropic/claude-sonnet-4-5-20250929"
  LLM_API_KEY  — your API key
  LLM_BASE_URL — optional custom endpoint
"""

import json
import logging

from bs4 import BeautifulSoup

from app.config import settings
from app.schemas import ParsedStory

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """\
You are extracting individual news stories from an email newsletter.

Given the newsletter content below, extract each distinct news item as a separate story.

Rules:
1. Each distinct news item is a separate story — if there are 5 announcements, return 5 stories.
2. Use the actual story headline, NOT the section header. "AI Twitter Recap" is a section, not a story.
3. Titles should be concise (under 100 chars). Use the newsletter's own headline when available.
4. Summaries: 1-2 sentences capturing the key point. Don't repeat the title.
5. URL: the link to the original source. Prefer direct URLs over tracking/redirect URLs.
6. Tags: assign from this list where applicable: long_form, research, launch, funding, vendor, podcast, tutorial, benchmark, opinion
7. SKIP: ads, sponsor sections, job listings, "share this newsletter", subscribe CTAs, referral promos, unsubscribe footers.
8. For single-article newsletters (one long post, not a digest), return 1 story with tag "long_form".

Return a JSON array only, no markdown fences:
[
  {
    "title": "Story headline",
    "summary": "1-2 sentence summary",
    "url": "https://...",
    "tags": ["research", "launch"]
  }
]

Newsletter subject: {subject}
Newsletter from: {from_address}

Newsletter content:
{content}
"""

# Max chars of newsletter content to send to the LLM
MAX_CONTENT_LENGTH = 15000


def is_configured() -> bool:
    """Check if LLM extraction is configured."""
    return bool(settings.llm_api_key or settings.llm_base_url)


async def extract_stories(
    html: str,
    subject: str | None = None,
    from_address: str | None = None,
) -> list[ParsedStory] | None:
    """Extract stories from newsletter HTML using an LLM.

    Returns list of ParsedStory on success, None if LLM is not configured
    or extraction fails (caller should fall back to heuristics).
    """
    if not is_configured():
        return None

    import litellm

    model = settings.llm_model
    api_key = settings.llm_api_key or None
    base_url = settings.llm_base_url or None

    # Convert HTML to readable text to save tokens
    content = _html_to_readable(html)
    if len(content) > MAX_CONTENT_LENGTH:
        content = content[:MAX_CONTENT_LENGTH] + "\n\n[... content truncated ...]"

    prompt = EXTRACTION_PROMPT.format(
        subject=subject or "Unknown",
        from_address=from_address or "Unknown",
        content=content,
    )

    try:
        logger.info("  Calling LLM (%s) for story extraction...", model)
        response = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            api_key=api_key,
            base_url=base_url,
            temperature=0.1,
            max_tokens=4000,
        )

        raw = response.choices[0].message.content.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        stories_data = json.loads(raw)
        if not isinstance(stories_data, list):
            logger.warning("  LLM returned non-list: %s", type(stories_data))
            return None

        stories = []
        for i, item in enumerate(stories_data):
            if not isinstance(item, dict) or not item.get("title"):
                continue
            stories.append(ParsedStory(
                title=item["title"][:200],
                summary=item.get("summary"),
                url=item.get("url"),
                tags=item.get("tags", []),
                position=i,
            ))

        logger.info("  LLM extracted %d stories", len(stories))
        return stories

    except json.JSONDecodeError as e:
        logger.warning("  LLM returned invalid JSON: %s", e)
        return None
    except Exception as e:
        logger.warning("  LLM extraction failed: %s", e)
        return None


def _html_to_readable(html: str) -> str:
    """Convert HTML to a readable text format preserving structure.

    More readable than raw HTML (saves tokens) but preserves headings,
    bold text, and links that the LLM needs to identify stories.
    """
    soup = BeautifulSoup(html, "lxml")

    # Remove scripts, styles, tracking
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()

    lines = []
    for element in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote", "td"]):
        text = element.get_text(" ", strip=True)
        if not text or len(text) < 3:
            continue

        prefix = ""
        if element.name in ["h1", "h2"]:
            prefix = "## "
        elif element.name in ["h3", "h4"]:
            prefix = "### "
        elif element.name == "li":
            prefix = "- "
        elif element.name == "blockquote":
            prefix = "> "

        # Preserve bold markers
        bolds = element.find_all(["strong", "b"])
        for b in bolds:
            b_text = b.get_text(strip=True)
            if b_text and len(b_text) > 5:
                text = text.replace(b_text, f"**{b_text}**", 1)

        # Append links inline
        links = element.find_all("a", href=True)
        link_strs = []
        for a in links:
            href = a["href"]
            if (
                href.startswith("http")
                and "unsubscribe" not in href.lower()
                and "tracking" not in href.lower()
                and len(href) < 200
            ):
                link_strs.append(href)
        link_suffix = f" [{', '.join(link_strs[:2])}]" if link_strs else ""

        lines.append(f"{prefix}{text}{link_suffix}")

    return "\n".join(lines)
