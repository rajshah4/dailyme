"""Newsletter segmentation — extract individual stories from newsletter HTML.

Uses the OpenHands LLM as the extraction engine. The LLM understands
newsletter structure, identifies real stories vs section headers, extracts
clean titles/summaries/tags, and handles any format without hardcoded rules.

Post-processing resolves Substack tracking URLs to direct links.
For beehiiv newsletters (e.g. The Rundown AI), tries to fetch the cleaner
web version via the "Read Online" link before falling back to email HTML.
"""

import logging

from app.processing.llm_extract import extract_stories as llm_extract, is_configured as llm_is_configured
from app.processing.substack import clean_story_urls, is_substack_email
from app.processing.web_version import fetch_web_version
from app.schemas import ParsedStory

logger = logging.getLogger(__name__)


async def segment_newsletter(
    html: str,
    subject: str | None = None,
    from_address: str | None = None,
    raw_html: str | None = None,
) -> list[ParsedStory]:
    """Extract stories from a newsletter using the OpenHands LLM.

    Args:
        html: Cleaned HTML for the LLM to read
        subject: Email subject line
        from_address: Sender email (for Substack URL resolution)
        raw_html: Original raw HTML (Substack URLs may be stripped by clean_html)

    Raises:
        RuntimeError: If LLM is not configured (LLM_API_KEY not set)
    """
    if not llm_is_configured():
        raise RuntimeError(
            "LLM not configured. Set LLM_API_KEY and LLM_MODEL environment variables. "
            "When running as an OpenHands agent, these are set automatically."
        )

    url_html = raw_html or html

    # Try to use the web version if available (cleaner, smaller, real URLs)
    llm_html = html
    web_html = fetch_web_version(url_html, from_address=from_address, subject=subject)
    if web_html:
        llm_html = web_html

    stories = await llm_extract(llm_html, subject, from_address)
    if not stories:
        logger.warning("LLM returned no stories for: %s", subject)
        return []

    logger.info("LLM extracted %d stories", len(stories))

    # Post-process: resolve Substack tracking URLs to clean direct links
    if from_address and is_substack_email(from_address):
        stories = clean_story_urls(stories, url_html)
        logger.info("  Resolved Substack URLs")

    return stories
