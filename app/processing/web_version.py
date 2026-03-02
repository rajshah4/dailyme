"""Fetch web version of newsletters that have a 'Read Online' link.

Some newsletters (e.g. beehiiv-hosted like The Rundown AI) include a
"Read Online" link that points to a cleaner web version of the content.
The web version is typically much smaller than the email HTML and has
real URLs instead of tracking links.

Strategy:
1. Find the "Read Online" tracking URL in the email
2. Try following the redirect (works locally, blocked by Cloudflare in GHA)
3. If blocked, try known newsletter URL patterns (therundown.ai/p/{slug})
4. Fetch the web page directly
"""

import logging
import re
import unicodedata

import httpx

logger = logging.getLogger(__name__)

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Patterns for "Read Online" links in email HTML
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

# Known newsletter sender → web archive base URL patterns
_SENDER_WEB_PATTERNS = {
    "therundown.ai": "https://www.therundown.ai/p/",
}


def _slugify(text: str) -> str:
    """Convert text to URL slug matching beehiiv's algorithm."""
    # Remove emoji and non-ASCII symbols
    text = "".join(
        c for c in text
        if unicodedata.category(c) not in ("So", "Sk", "Sm", "Sc")
    )
    # Strip possessives before slugifying (e.g. "Anthropic's" → "Anthropic")
    text = re.sub(r"['\u2019]s\b", "", text)
    text = text.lower().strip()
    # Replace non-alphanumeric chars with hyphens
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _resolve_tracking_url(tracking_url: str) -> str | None:
    """Follow a tracking redirect to get the real URL."""
    try:
        r = httpx.get(
            tracking_url,
            follow_redirects=True,
            headers=_BROWSER_HEADERS,
            timeout=10,
        )
        final_url = str(r.url)

        if r.status_code != 200:
            logger.info("  Web version: redirect returned HTTP %d", r.status_code)
            return None

        if "beehiiv.com" in final_url and "/p/" not in final_url:
            logger.info("  Web version: redirect stuck on beehiiv")
            return None

        return final_url

    except Exception as e:
        logger.info("  Web version: redirect failed (%s)", e)
        return None


def _construct_web_url(from_address: str | None, subject: str | None) -> str | None:
    """Construct web version URL from sender domain + subject slug."""
    if not from_address or not subject:
        return None

    for domain, base_url in _SENDER_WEB_PATTERNS.items():
        if domain in from_address:
            slug = _slugify(subject)
            return base_url + slug

    return None


def _fetch_page(url: str) -> str | None:
    """Fetch a web page, return HTML if successful."""
    try:
        r = httpx.get(url, headers=_BROWSER_HEADERS, timeout=15)
        if r.status_code == 200:
            return r.text
    except Exception as e:
        logger.info("  Web version: fetch failed for %s (%s)", url.split("?")[0], e)
    return None


def fetch_web_version(
    raw_html: str,
    from_address: str | None = None,
    subject: str | None = None,
) -> str | None:
    """Try to fetch a cleaner web version of the newsletter.

    Returns the web page HTML if successful, None otherwise.
    Falls back gracefully — caller should use email HTML if this returns None.
    """
    tracking_url = extract_read_online_url(raw_html)
    if not tracking_url:
        return None

    logger.info("  Found 'Read Online' link, fetching web version...")

    # Strategy 1: Follow the tracking redirect
    final_url = _resolve_tracking_url(tracking_url)
    if final_url:
        web_html = _fetch_page(final_url)
        if web_html:
            logger.info("  Fetched web version via redirect (%d chars)", len(web_html))
            return web_html

    # Strategy 2: Construct URL from sender domain + subject slug
    constructed_url = _construct_web_url(from_address, subject)
    if constructed_url:
        logger.info("  Trying constructed URL: %s", constructed_url)
        web_html = _fetch_page(constructed_url)
        if web_html:
            logger.info("  Fetched web version via constructed URL (%d chars)", len(web_html))
            return web_html

    logger.info("  Web version: all strategies failed, falling back to email")
    return None


def extract_read_online_url(html: str) -> str | None:
    """Find the 'Read Online' / 'View Online' URL in email HTML."""
    for pattern in _READ_ONLINE_PATTERNS:
        match = pattern.search(html[:25000])
        if match:
            return match.group(1)
    return None
