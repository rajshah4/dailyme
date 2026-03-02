"""Fetch web version of newsletters that have a 'Read Online' link.

Some newsletters (e.g. beehiiv-hosted like The Rundown AI) include a
"Read Online" link that points to a cleaner web version of the content.
The web version is typically much smaller than the email HTML and has
real URLs instead of tracking links.

This module extracts the "Read Online" URL from email HTML, follows
the redirect, and fetches the web page content.
"""

import logging
import re

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Patterns for "Read Online" links in email HTML
# beehiiv: <a href="https://link.mail.beehiiv.com/..."><span>Read Online</span></a>
_READ_ONLINE_PATTERNS = [
    re.compile(
        r'href="(https?://[^"]+)"[^>]*>(?:<[^>]*>)*\s*Read\s*Online',
        re.IGNORECASE,
    ),
    re.compile(
        r'href="(https?://[^"]+)"[^>]*>(?:<[^>]*>)*\s*View\s*(?:Online|in\s*Browser)',
        re.IGNORECASE,
    ),
]


def extract_read_online_url(html: str) -> str | None:
    """Find the 'Read Online' / 'View Online' URL in email HTML."""
    for pattern in _READ_ONLINE_PATTERNS:
        match = pattern.search(html[:25000])  # Only check header area
        if match:
            return match.group(1)
    return None


def fetch_web_version(raw_html: str) -> str | None:
    """Try to fetch a cleaner web version of the newsletter.

    Returns the web page HTML if successful, None otherwise.
    Falls back gracefully — caller should use email HTML if this returns None.
    """
    tracking_url = extract_read_online_url(raw_html)
    if not tracking_url:
        return None

    logger.info("  Found 'Read Online' link, fetching web version...")

    try:
        # Follow the tracking redirect to get the real URL
        r = httpx.get(
            tracking_url,
            follow_redirects=True,
            headers=_BROWSER_HEADERS,
            timeout=10,
        )
        final_url = str(r.url)

        # Check that we actually resolved to a real page (not stuck on beehiiv)
        if r.status_code != 200:
            logger.debug("  Web version fetch failed: HTTP %d", r.status_code)
            return None

        # If still on beehiiv domain, the redirect didn't work
        if "beehiiv.com" in final_url and "/p/" not in final_url:
            logger.debug("  Redirect stuck on beehiiv, skipping web version")
            return None

        web_html = r.text
        logger.info("  Fetched web version from %s (%d chars)", final_url.split("?")[0], len(web_html))
        return web_html

    except httpx.TimeoutException:
        logger.debug("  Web version fetch timed out")
        return None
    except Exception as e:
        logger.debug("  Web version fetch failed: %s", e)
        return None
