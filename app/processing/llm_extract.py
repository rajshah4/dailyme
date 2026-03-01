"""LLM-powered newsletter story extraction via OpenHands SDK.

Uses the OpenHands SDK LLM class — same models that power OpenHands agents.
When the pipeline runs as an OpenHands agent job, it uses the agent's own
LLM access. No separate API key needed.

Configuration (via environment or .env):
  LLM_MODEL    — e.g. "anthropic/claude-sonnet-4-5-20250929" (default)
  LLM_API_KEY  — API key (OpenHands Cloud key, or direct provider key)
  LLM_BASE_URL — optional custom endpoint
"""

import json
import logging

from bs4 import BeautifulSoup

from app.schemas import ParsedStory

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """\
You are extracting the notable news stories from an email newsletter digest.

Extract the **top stories** — the ones a busy AI practitioner would want to see.
For large digests (like AINews), focus on the 8-15 most significant items, not every link.

Rules:
1. Extract distinct NEWS STORIES, not every link or mention in the newsletter.
2. Use the actual story headline, NOT the section header. "AI Twitter Recap" is a section heading, not a story — extract the individual stories within it.
3. Titles should be concise (under 100 chars). Use the newsletter's own headline when available.
4. Summaries: 1-2 sentences capturing the key point. Don't repeat the title.
5. URL: the link to the original article/source. Prefer direct URLs over tracking/redirect URLs. Omit if no clear source link.
6. Tags: assign 1-2 from this list: long_form, research, launch, funding, vendor, podcast, tutorial, benchmark, opinion
7. SKIP all of these: ads, sponsors, job listings, "share this newsletter", subscribe CTAs, referral promos, social media follow links, unsubscribe footers, author bios.
8. For single-article newsletters (one long post, not a multi-story digest), return exactly 1 story with tag "long_form".

Return a JSON array only, no markdown fences:
[
  {{"title": "Story headline", "summary": "1-2 sentence summary", "url": "https://...", "tags": ["research"]}}
]

Newsletter subject: {subject}
Newsletter from: {from_address}

Newsletter content:
{content}
"""

MAX_CONTENT_LENGTH = 15000

# Singleton LLM instance — created once, reused across calls
_llm = None


def _get_llm():
    """Get or create the OpenHands LLM instance.

    Uses LLM.load_from_env() which reads LLM_MODEL, LLM_API_KEY, LLM_BASE_URL
    from the environment — same config pattern as the OpenHands agent itself.
    Loads .env file first so local dev works without manual exports.
    """
    global _llm
    if _llm is None:
        import os
        from dotenv import load_dotenv
        from openhands.sdk import LLM

        load_dotenv()  # ensure .env vars are in os.environ for LLM.load_from_env()

        if not os.getenv("LLM_API_KEY"):
            return None

        try:
            _llm = LLM.load_from_env()
            logger.info("Initialized OpenHands LLM: %s", _llm.model)
        except Exception as e:
            logger.debug("Could not initialize OpenHands LLM: %s", e)
            return None
    return _llm


def is_configured() -> bool:
    """Check if LLM extraction is available."""
    return _get_llm() is not None


async def extract_stories(
    html: str,
    subject: str | None = None,
    from_address: str | None = None,
) -> list[ParsedStory] | None:
    """Extract stories from newsletter HTML using the OpenHands LLM.

    Returns list of ParsedStory on success, None if LLM is not available
    or extraction fails (caller falls back to heuristics).
    """
    llm = _get_llm()
    if llm is None:
        return None

    content = _html_to_readable(html)
    if len(content) > MAX_CONTENT_LENGTH:
        content = content[:MAX_CONTENT_LENGTH] + "\n\n[... content truncated ...]"

    prompt = EXTRACTION_PROMPT.format(
        subject=subject or "Unknown",
        from_address=from_address or "Unknown",
        content=content,
    )

    try:
        from openhands.sdk.llm import Message, TextContent

        logger.info("  Calling OpenHands LLM (%s) for story extraction...", llm.model)
        response = llm.completion(
            messages=[Message(role="user", content=[TextContent(text=prompt)])],
        )

        raw = response.message.content[0].text.strip()
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
    """Convert HTML to readable text preserving structure for the LLM.

    Keeps headings, bold text, and links — strips tracking/layout noise.
    """
    soup = BeautifulSoup(html, "lxml")

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
        for b in element.find_all(["strong", "b"]):
            b_text = b.get_text(strip=True)
            if b_text and len(b_text) > 5:
                text = text.replace(b_text, f"**{b_text}**", 1)

        # Append links inline
        link_strs = []
        for a in element.find_all("a", href=True):
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
