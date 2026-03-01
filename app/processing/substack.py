"""Substack-specific parsing utilities.

Substack is the most common newsletter platform. Their emails have predictable
URL patterns that we can exploit to get clean, direct article links instead of
tracking redirects.

URL patterns found in Substack emails:
  1. Direct:   https://{author}.substack.com/p/{slug}
  2. Open:     https://open.substack.com/pub/{author}/p/{slug}
  3. App-link: https://substack.com/app-link/post?publication_id=X&post_id=Y&...
  4. Redirect: https://substack.com/redirect/... (base64 encoded, contains real URL)

We prefer (1) > (2) > (3). Redirect links are opaque without HTTP requests.
"""

import re
from urllib.parse import parse_qs, unquote, urlparse

# Regex patterns for extracting clean Substack URLs from email HTML
_DIRECT_URL_RE = re.compile(
    r"https?://([a-z0-9-]+)\.substack\.com/p/([a-z0-9][\w-]*)", re.IGNORECASE
)
_OPEN_URL_RE = re.compile(
    r"https?://open\.substack\.com/pub/([a-z0-9-]+)/p/([a-z0-9][\w-]*)", re.IGNORECASE
)
_APP_LINK_RE = re.compile(
    r"https?://substack\.com/app-link/post\?[^\"'\s>]+", re.IGNORECASE
)
_EMBEDDED_URL_RE = re.compile(
    r"https%3A%2F%2F([a-z0-9-]+)\.substack\.com%2Fp%2F([a-z0-9][\w-]*)", re.IGNORECASE
)


def is_substack_email(from_address: str) -> bool:
    """Check if an email is from Substack."""
    return "substack.com" in from_address.lower()


def extract_article_url(html: str) -> str | None:
    """Extract the canonical article URL from a Substack email.

    Returns the cleanest direct URL available, or None if not found.
    """
    # Priority 1: direct {author}.substack.com/p/{slug}
    # (but not open.substack.com which is a different pattern)
    for m in _DIRECT_URL_RE.finditer(html):
        author, slug = m.group(1), m.group(2)
        if author != "open":
            return f"https://{author}.substack.com/p/{slug}"

    # Priority 2: open.substack.com/pub/{author}/p/{slug}
    m = _OPEN_URL_RE.search(html)
    if m:
        author, slug = m.group(1), m.group(2)
        return f"https://{author}.substack.com/p/{slug}"

    # Priority 3: extract from URL-encoded redirect links
    for m in _EMBEDDED_URL_RE.finditer(html):
        author, slug = m.group(1), m.group(2)
        if author != "open":
            return f"https://{author}.substack.com/p/{slug}"

    return None


def extract_author_slug(from_address: str) -> str | None:
    """Extract the Substack author slug from the sender email.

    e.g. 'alexchao+humans-of-ai@substack.com' → 'alexchao'
    """
    m = re.match(r"([a-z0-9._-]+?)(?:\+[^@]*)?\s*@substack\.com", from_address.lower())
    if m:
        return m.group(1)
    # Also check display name format: "Name <email@substack.com>"
    email_match = re.search(r"<([^>]+@substack\.com)>", from_address.lower())
    if email_match:
        m = re.match(r"([a-z0-9._-]+?)(?:\+[^@]*)?\s*@substack\.com", email_match.group(1))
        if m:
            return m.group(1)
    return None


def resolve_substack_url(url: str, html: str | None = None) -> str:
    """Resolve a Substack tracking URL to its clean direct form.

    Handles:
    - app-link URLs → extract publication info and construct direct URL
    - redirect URLs → attempt to decode
    - Already-clean URLs → return as-is
    """
    if not url:
        return url

    parsed = urlparse(url)

    # Already a direct URL
    if parsed.hostname and parsed.hostname.endswith(".substack.com") and "/p/" in parsed.path:
        if parsed.hostname != "open.substack.com":
            # Strip tracking params, keep clean
            return f"https://{parsed.hostname}{parsed.path.split('?')[0]}"

    # open.substack.com → convert to direct
    if parsed.hostname == "open.substack.com":
        m = re.match(r"/pub/([^/]+)/p/([^/?]+)", parsed.path)
        if m:
            return f"https://{m.group(1)}.substack.com/p/{m.group(2)}"

    # app-link → try to get direct URL from the HTML if available
    if "substack.com/app-link/" in url and html:
        direct = extract_article_url(html)
        if direct:
            return direct

    # If we have a redirect URL with an embedded real URL
    if "substack.com/redirect/" in url:
        decoded = unquote(unquote(url))
        m = re.search(r"https://([a-z0-9-]+)\.substack\.com/p/([a-z0-9][\w-]*)", decoded)
        if m:
            return f"https://{m.group(1)}.substack.com/p/{m.group(2)}"
        # Opaque UUID redirect — follow HTTP to get real destination
        resolved = _follow_redirect(url)
        if resolved:
            return resolved

    return url


def _follow_redirect(url: str) -> str | None:
    """Follow a redirect URL and return the final destination."""
    import httpx

    try:
        with httpx.Client(follow_redirects=True, timeout=5.0) as client:
            resp = client.head(url)
            final = str(resp.url)
            if final != url:
                return final
    except Exception:
        pass
    return None


def clean_story_urls(stories: list, html: str, fill_missing: bool = False) -> list:
    """Resolve all Substack tracking URLs in a list of ParsedStory objects.

    Args:
        stories: list of ParsedStory objects
        html: raw HTML of the email (for extracting article URL)
        fill_missing: if True, assign the article URL to stories without URLs
                      (only useful for single-article newsletters)
    """
    article_url = extract_article_url(html)

    for story in stories:
        if story.url:
            story.url = resolve_substack_url(story.url, html)
        elif fill_missing and article_url:
            story.url = article_url

    return stories
