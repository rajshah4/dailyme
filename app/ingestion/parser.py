"""Newsletter HTML parsing and cleanup pipeline.

Converts raw newsletter HTML into clean text with links preserved.
"""

import logging
import re

from bs4 import BeautifulSoup, Tag
from markdownify import markdownify

logger = logging.getLogger(__name__)

# Patterns for content we want to strip
TRACKING_PIXEL_PATTERN = re.compile(
    r'<img[^>]*(width\s*=\s*["\']?1|height\s*=\s*["\']?1|1x1)[^>]*>', re.IGNORECASE
)

FOOTER_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"unsubscribe",
        r"manage\s+preferences",
        r"view\s+in\s+browser",
        r"view\s+online",
        r"email\s+preferences",
        r"update\s+your\s+preferences",
        r"opt[\s-]out",
        r"you\s+are\s+receiving\s+this",
        r"you\s+received\s+this",
        r"was\s+sent\s+to",
        r"forward\s+to\s+a\s+friend",
        r"©\s*20\d{2}",
    ]
]

SOCIAL_PATTERNS = re.compile(
    r"(share\s+on|follow\s+us|twitter|facebook|linkedin|instagram)\s",
    re.IGNORECASE,
)


def clean_html(raw_html: str) -> str:
    """Clean newsletter HTML: remove tracking, footers, ads.

    Returns cleaned HTML suitable for story segmentation.
    """
    if not raw_html:
        return ""

    # Remove tracking pixels
    html = TRACKING_PIXEL_PATTERN.sub("", raw_html)

    soup = BeautifulSoup(html, "lxml")

    # Remove script and style tags
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()

    # Remove hidden elements
    for tag in soup.find_all(style=re.compile(r"display\s*:\s*none", re.IGNORECASE)):
        tag.decompose()

    # Remove tracking images (1x1 pixels or known trackers)
    for img in soup.find_all("img"):
        width = img.get("width", "")
        height = img.get("height", "")
        src = img.get("src", "")
        if (
            (str(width) == "1" or str(height) == "1")
            or "track" in src.lower()
            or "pixel" in src.lower()
            or "open" in src.lower()
        ):
            img.decompose()

    # Remove footer-like sections
    _remove_footer_sections(soup)

    return str(soup)


def _remove_footer_sections(soup: BeautifulSoup):
    """Remove footer sections based on content patterns."""
    # Walk backwards from the bottom, removing blocks that match footer patterns
    all_blocks = soup.find_all(["div", "table", "tr", "td", "p", "section", "footer"])
    for block in reversed(all_blocks):
        text = block.get_text(strip=True)
        if len(text) < 10:
            continue
        # Check if block matches footer patterns
        matches = sum(1 for p in FOOTER_PATTERNS if p.search(text))
        if matches >= 2:
            block.decompose()
        elif block.name == "footer":
            block.decompose()


def html_to_markdown(cleaned_html: str) -> str:
    """Convert cleaned HTML to markdown, preserving links."""
    return markdownify(cleaned_html, strip=["img"], convert=["a", "p", "h1", "h2", "h3", "h4", "li", "ul", "ol", "br", "hr", "strong", "em", "b", "i"])


def extract_links(soup: BeautifulSoup) -> list[dict]:
    """Extract all links from a BeautifulSoup object."""
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        if href and not href.startswith("mailto:") and not href.startswith("#"):
            links.append({"url": href, "text": text})
    return links


def extract_newsletter_name(from_address: str, subject: str) -> str:
    """Best-effort extraction of newsletter name from sender or subject."""
    # Try to extract name from "Name <email>" format
    if "<" in from_address:
        name = from_address.split("<")[0].strip().strip('"')
        if name:
            return name

    # Fall back to the part before @ in email
    email = from_address.strip("<>")
    if "@" in email:
        return email.split("@")[0].replace(".", " ").title()

    return from_address


def extract_sender_domain(from_address: str) -> str:
    """Extract domain from email address."""
    match = re.search(r"@([\w.-]+)", from_address)
    return match.group(1) if match else "unknown"
