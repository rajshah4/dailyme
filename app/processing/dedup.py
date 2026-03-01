"""Deduplication: URL canonicalization + title similarity + embedding similarity.

Steps:
  1. URL canonicalization (strip tracking params, normalize)
  2. Exact URL match
  3. Title Jaccard similarity
  4. Embedding cosine similarity (when embeddings available)
"""

import logging
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

logger = logging.getLogger(__name__)

# URL params to strip (tracking/campaign)
STRIP_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "ref", "source", "campaign", "mc_cid", "mc_eid",
    "fbclid", "gclid", "msclkid", "twclid",
    "oly_enc_id", "oly_anon_id", "vero_id",
    "_hsenc", "_hsmi", "hsa_cam", "hsa_grp",
}

STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "is", "are", "was", "were", "be", "been",
    "this", "that", "it", "its", "from", "as", "has", "have", "had",
    "not", "no", "will", "can", "do", "does", "did",
    "new", "how", "why", "what", "when", "where", "who",
}


def canonicalize_url(url: str | None) -> str | None:
    """Normalize a URL for dedup comparison.

    - Strip tracking query params
    - Remove www. prefix
    - Remove trailing slashes
    - Lowercase scheme and host
    """
    if not url:
        return None

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return url

    parsed = urlparse(url)

    # Lowercase scheme and host
    scheme = parsed.scheme.lower()
    host = parsed.hostname or ""
    host = host.lower()

    # Remove www. prefix
    if host.startswith("www."):
        host = host[4:]

    # Strip tracking params
    query_params = parse_qs(parsed.query, keep_blank_values=False)
    clean_params = {
        k: v for k, v in query_params.items() if k.lower() not in STRIP_PARAMS
    }
    clean_query = urlencode(clean_params, doseq=True) if clean_params else ""

    # Remove trailing slash from path
    path = parsed.path.rstrip("/") or "/"

    # Reconstruct
    canonical = urlunparse((scheme, host, path, "", clean_query, ""))
    return canonical


def title_jaccard_similarity(title_a: str, title_b: str) -> float:
    """Compute Jaccard similarity of title word-sets (after normalization)."""
    words_a = _normalize_title_words(title_a)
    words_b = _normalize_title_words(title_b)

    if not words_a or not words_b:
        return 0.0

    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def _normalize_title_words(title: str) -> set[str]:
    """Normalize a title: lowercase, strip punctuation, remove stop words."""
    title = title.lower()
    title = re.sub(r"[^\w\s]", "", title)
    words = set(title.split())
    return words - STOP_WORDS


def find_duplicate(
    new_url_canonical: str | None,
    new_title: str,
    existing_stories: list[dict],
    url_threshold: bool = True,
    title_threshold: float = 0.6,
) -> str | None:
    """Find a duplicate story in the existing set.

    Returns the story_group_id if a duplicate is found, None otherwise.

    existing_stories should be a list of dicts with:
        {"story_group_id": str, "url_canonical": str, "title": str}
    """
    for existing in existing_stories:
        # Step 2: Exact URL match
        if (
            url_threshold
            and new_url_canonical
            and existing.get("url_canonical")
            and new_url_canonical == existing["url_canonical"]
        ):
            logger.debug(
                "Dedup: exact URL match: %s", new_url_canonical
            )
            return existing["story_group_id"]

        # Step 3: Title similarity
        sim = title_jaccard_similarity(new_title, existing.get("title", ""))
        if sim > title_threshold:
            logger.debug(
                "Dedup: title similarity %.2f: '%s' ~ '%s'",
                sim, new_title[:50], existing.get("title", "")[:50],
            )
            return existing["story_group_id"]

    return None
