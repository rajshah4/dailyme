"""DailyMe Social Top Stories Pipeline (Hacker News + Reddit).

Runs independently from newsletter ingestion and stores a compact set of curated
social stories for RSS publication.

Design goals:
- Keep storage lightweight for Neon free tier (<150MB by wide margin)
- Deterministic top-story selection with controllable volume
- Safe to run every 2 hours
"""

import asyncio
import html
import logging
import math
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

import httpx
from sqlalchemy import delete, select

sys.path.insert(0, ".")

from app.db import async_session, engine
from app.models import Base, SocialStory

logger = logging.getLogger("dailyme.social")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

HN_SOURCE = "hacker_news"
REDDIT_SOURCE = "reddit"

REDDIT_COMMUNITIES = [
    "MachineLearning",
    "artificial",
    "LocalLLaMA",
    "OpenAI",
]

RUN_INTERVAL_HOURS = 2
RETENTION_DAYS = 10
MAX_STORED_ROWS = 3000  # Hard cap to keep well below Neon free tier limits

# Target volume tuning (roughly 2-hour cadence => 12 runs/day)
# Looser defaults to keep social feed active (goal: ~5-10 fresh entries/day).
TARGET_HN_POSTS_PER_DAY = 8
TARGET_REDDIT_POSTS_PER_DAY = 20

# Backfill floors if dynamic thresholds are too strict for a given run.
MIN_HN_CANDIDATES_PER_RUN = 3
MIN_REDDIT_CANDIDATES_PER_COMMUNITY = 2
MIN_REDDIT_COMMENTS = 1

MAX_ITEMS_PER_SOURCE = 20
MAX_ITEMS_PER_COMMUNITY = 6
MAX_ITEMS_PER_DOMAIN = 3

HN_TOP_LOOKBACK_DAYS = 30
HN_HOT_LOOKBACK_DAYS = 7
REDDIT_TOP_LIMIT = 100
REDDIT_HOT_LIMIT = 100

# Use browser-like UA to avoid Reddit blocking
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"


@dataclass(slots=True)
class Candidate:
    source: str
    community: str
    external_id: str
    title: str
    url: str | None
    permalink: str
    score: int
    comment_count: int
    upvote_ratio: float | None
    source_created_at: datetime
    tags: list[str]
    summary: str | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_dt(timestamp: float | int | None) -> datetime:
    if not timestamp:
        return _utc_now()
    return datetime.fromtimestamp(float(timestamp), tz=timezone.utc)


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        from urllib.parse import urlparse

        return (urlparse(url).netloc or "").lower()
    except Exception:
        return None


def _clean_html_text(html_text: str, max_length: int = 1000) -> str:
    """Remove HTML tags, decode entities, and clean up text content."""
    if not html_text:
        return ""
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', html_text)
    
    # Decode HTML entities
    text = html.unescape(text)
    
    # Filter out navigation links like "[link]", "[comments]"
    text = re.sub(r'\[(?:link|comments)\]', '', text)
    
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Limit length
    if len(text) > max_length:
        text = text[:max_length].rsplit(' ', 1)[0] + '...'
    
    return text


async def _fetch_hn_post_text(client: httpx.AsyncClient, item_id: str) -> str | None:
    """Fetch HN post text content via Firebase API for self posts (Ask HN, Show HN, etc.)."""
    try:
        url = f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
        resp = await client.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        # Get the 'text' field (post body for Ask HN, Show HN, etc.)
        text_content = data.get("text", "")
        if not text_content:
            return None
        
        # Clean and limit
        return _clean_html_text(text_content, max_length=1000)
    except Exception as e:
        logger.debug("Failed to fetch HN post text for %s: %s", item_id, e)
        return None


def _score_sort_key(c: Candidate) -> tuple[float, int]:
    recency_hours = max((_utc_now() - c.source_created_at).total_seconds() / 3600, 0.0)
    recency_boost = max(0.0, 1.0 - recency_hours / 72.0)
    quality = math.log1p(max(c.score, 0)) + 0.4 * math.log1p(max(c.comment_count, 0))
    if c.upvote_ratio is not None:
        quality += 0.5 * c.upvote_ratio
    return quality + recency_boost, c.score


async def _fetch_hn_candidates(client: httpx.AsyncClient) -> list[Candidate]:
    now = _utc_now()
    top_cutoff = int((now - timedelta(days=HN_TOP_LOOKBACK_DAYS)).timestamp())
    hot_cutoff = int((now - timedelta(days=HN_HOT_LOOKBACK_DAYS)).timestamp())

    top_url = (
        "https://hn.algolia.com/api/v1/search"
        f"?tags=story&hitsPerPage=1000&numericFilters=created_at_i>{top_cutoff}"
    )
    hot_url = (
        "https://hn.algolia.com/api/v1/search_by_date"
        f"?tags=front_page&hitsPerPage=300&numericFilters=created_at_i>{hot_cutoff}"
    )

    top_resp, hot_resp = await asyncio.gather(
        client.get(top_url, timeout=30),
        client.get(hot_url, timeout=30),
    )
    top_resp.raise_for_status()
    hot_resp.raise_for_status()

    top_hits = top_resp.json().get("hits", [])
    hot_hits = hot_resp.json().get("hits", [])

    # Derive dynamic threshold from monthly top score distribution.
    top_scores = sorted((int(h.get("points") or 0) for h in top_hits if h.get("objectID")), reverse=True)
    rank_idx = min(max(TARGET_HN_POSTS_PER_DAY * HN_TOP_LOOKBACK_DAYS - 1, 0), max(len(top_scores) - 1, 0))
    threshold = top_scores[rank_idx] if top_scores else 0
    effective_threshold = int(threshold * 0.85)

    def _candidate_from_hn_hit(hit: dict) -> Candidate | None:
        object_id = str(hit.get("objectID") or "").strip()
        if not object_id:
            return None

        title = (hit.get("title") or hit.get("story_title") or "").strip()
        if not title:
            return None

        points = int(hit.get("points") or 0)
        story_url = hit.get("url") or hit.get("story_url")
        permalink = f"https://news.ycombinator.com/item?id={object_id}"
        created_at = _safe_dt(hit.get("created_at_i"))

        return Candidate(
            source=HN_SOURCE,
            community="frontpage",
            external_id=object_id,
            title=title,
            url=story_url,
            permalink=permalink,
            score=points,
            comment_count=int(hit.get("num_comments") or 0),
            upvote_ratio=None,
            source_created_at=created_at,
            tags=["source:hn"],
        )

    candidates: list[Candidate] = []
    for hit in hot_hits:
        points = int(hit.get("points") or 0)
        if points < effective_threshold:
            continue

        candidate = _candidate_from_hn_hit(hit)
        if candidate:
            candidates.append(candidate)

    if not candidates:
        selected_ids = set()
        fallback_hits = sorted(hot_hits, key=lambda h: int(h.get("points") or 0), reverse=True)
        for hit in fallback_hits:
            if len(candidates) >= MIN_HN_CANDIDATES_PER_RUN:
                break
            object_id = str(hit.get("objectID") or "").strip()
            if not object_id or object_id in selected_ids:
                continue
            candidate = _candidate_from_hn_hit(hit)
            if not candidate:
                continue
            candidates.append(candidate)
            selected_ids.add(candidate.external_id)

    logger.info(
        "HN candidates threshold=%s effective=%s selected=%s",
        threshold,
        effective_threshold,
        len(candidates),
    )
    
    # Fetch text content for self posts (Ask HN, Show HN, posts without external URL)
    self_posts = [c for c in candidates if not c.url]
    if self_posts:
        logger.info("Fetching text content for %s HN self posts", len(self_posts))
        text_tasks = [_fetch_hn_post_text(client, c.external_id) for c in self_posts]
        text_results = await asyncio.gather(*text_tasks, return_exceptions=True)
        
        for candidate, text_content in zip(self_posts, text_results):
            if isinstance(text_content, str) and text_content:
                # Update candidate summary (need to create new Candidate since it's frozen)
                idx = candidates.index(candidate)
                candidates[idx] = Candidate(
                    source=candidate.source,
                    community=candidate.community,
                    external_id=candidate.external_id,
                    title=candidate.title,
                    url=candidate.url,
                    permalink=candidate.permalink,
                    score=candidate.score,
                    comment_count=candidate.comment_count,
                    upvote_ratio=candidate.upvote_ratio,
                    source_created_at=candidate.source_created_at,
                    tags=candidate.tags,
                    summary=text_content,
                )
    
    return candidates


async def _fetch_reddit_community_rss(
    client: httpx.AsyncClient,
    community: str,
) -> list[Candidate]:
    """Fetch Reddit community via RSS (Atom) feed to bypass JSON API 403 errors."""
    # RSS endpoints work from data center IPs where JSON endpoints return 403
    top_url = f"https://www.reddit.com/r/{community}/top.rss?t=month&limit={REDDIT_TOP_LIMIT}"
    hot_url = f"https://www.reddit.com/r/{community}/hot.rss?limit={REDDIT_HOT_LIMIT}"

    try:
        top_resp, hot_resp = await asyncio.gather(
            client.get(top_url, timeout=30),
            client.get(hot_url, timeout=30),
        )
        top_resp.raise_for_status()
        hot_resp.raise_for_status()
    except Exception as exc:
        logger.warning("Reddit r/%s RSS unavailable (%s) — skipping", community, exc)
        return []

    def _parse_rss_feed(xml_content: str) -> list[dict]:
        """Parse Atom feed and return list of entry dicts."""
        try:
            root = ET.fromstring(xml_content)
            # Atom namespace
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            entries = []
            
            for entry in root.findall("atom:entry", ns):
                # Extract ID (e.g., "t3_1sj6sas")
                entry_id_elem = entry.find("atom:id", ns)
                if entry_id_elem is None or not entry_id_elem.text:
                    continue
                external_id = entry_id_elem.text.strip()
                
                # Extract title
                title_elem = entry.find("atom:title", ns)
                if title_elem is None or not title_elem.text:
                    continue
                title = title_elem.text.strip()
                
                # Extract permalink
                link_elem = entry.find("atom:link[@href]", ns)
                permalink = link_elem.get("href") if link_elem is not None else ""
                
                # Extract published/updated time
                published_elem = entry.find("atom:published", ns)
                updated_elem = entry.find("atom:updated", ns)
                timestamp_str = (published_elem.text if published_elem is not None and published_elem.text 
                               else updated_elem.text if updated_elem is not None and updated_elem.text 
                               else "")
                
                # Extract external URL and post body from content HTML
                content_elem = entry.find("atom:content", ns)
                external_url = None
                post_body = None
                
                if content_elem is not None and content_elem.text:
                    content_html = content_elem.text
                    
                    # Look for href in [link] anchor (the actual linked article)
                    match = re.search(r'<span><a href="([^"]+)">\[link\]</a></span>', content_html)
                    if match:
                        external_url = match.group(1)
                    
                    # Extract post body/selftext (the actual post content)
                    # Reddit RSS includes the post body in the content element as HTML
                    post_body = _clean_html_text(content_html, max_length=1000)
                
                entries.append({
                    "external_id": external_id,
                    "title": title,
                    "permalink": permalink if permalink.startswith("http") else f"https://www.reddit.com{permalink}",
                    "external_url": external_url,
                    "timestamp": timestamp_str,
                    "summary": post_body,
                })
            
            return entries
        except Exception as e:
            logger.warning("Failed to parse RSS feed: %s", e)
            return []

    top_entries = _parse_rss_feed(top_resp.text)
    hot_entries = _parse_rss_feed(hot_resp.text)

    # Use rank-based synthetic scores since RSS doesn't include upvotes
    # Position 1 → score 100, position 2 → score 99, etc.
    def _assign_synthetic_score(entries: list[dict], base_score: int) -> None:
        for idx, entry in enumerate(entries):
            entry["synthetic_score"] = max(base_score - idx, 1)

    _assign_synthetic_score(top_entries, 100)
    _assign_synthetic_score(hot_entries, 100)

    # Determine threshold based on top entries
    top_scores = [e["synthetic_score"] for e in top_entries]
    rank_idx = min(max(TARGET_REDDIT_POSTS_PER_DAY * 30 // max(len(REDDIT_COMMUNITIES), 1) - 1, 0), max(len(top_scores) - 1, 0))
    threshold = top_scores[rank_idx] if top_scores else 0
    effective_threshold = int(threshold * 0.8)

    def _candidate_from_rss_entry(entry: dict, score: int) -> Candidate | None:
        external_id = entry.get("external_id", "").strip()
        if not external_id:
            return None

        title = entry.get("title", "").strip()
        if not title:
            return None

        permalink = entry.get("permalink", "")
        external_url = entry.get("external_url")
        timestamp_str = entry.get("timestamp", "")
        summary = entry.get("summary")  # Extract post body content
        
        # Parse ISO timestamp
        try:
            from dateutil import parser as date_parser
            created_at = date_parser.isoparse(timestamp_str)
        except Exception:
            created_at = _utc_now()

        return Candidate(
            source=REDDIT_SOURCE,
            community=community,
            external_id=external_id,
            title=title,
            url=external_url,
            permalink=permalink,
            score=score,
            comment_count=0,  # RSS doesn't include comment count
            upvote_ratio=None,  # RSS doesn't include upvote ratio
            source_created_at=created_at,
            tags=["source:reddit", f"community:{community}"],
            summary=summary,
        )

    candidates: list[Candidate] = []
    seen_ids: set[str] = set()
    
    # Process hot entries with threshold
    for entry in hot_entries:
        score = entry.get("synthetic_score", 0)
        if score < effective_threshold:
            continue
        
        external_id = entry.get("external_id", "")
        if external_id in seen_ids:
            continue
        
        candidate = _candidate_from_rss_entry(entry, score)
        if candidate:
            candidates.append(candidate)
            seen_ids.add(external_id)

    # Backfill if needed
    if len(candidates) < MIN_REDDIT_CANDIDATES_PER_COMMUNITY:
        fallback_entries = sorted(hot_entries, key=lambda e: e.get("synthetic_score", 0), reverse=True)
        for entry in fallback_entries:
            if len(candidates) >= MIN_REDDIT_CANDIDATES_PER_COMMUNITY:
                break
            external_id = entry.get("external_id", "")
            if not external_id or external_id in seen_ids:
                continue
            candidate = _candidate_from_rss_entry(entry, entry.get("synthetic_score", 0))
            if not candidate:
                continue
            candidates.append(candidate)
            seen_ids.add(external_id)

    logger.info(
        "Reddit r/%s RSS threshold=%s effective=%s selected=%s",
        community,
        threshold,
        effective_threshold,
        len(candidates),
    )
    return candidates


async def _fetch_reddit_community_candidates(
    client: httpx.AsyncClient,
    community: str,
) -> list[Candidate]:
    """Main entry point - uses RSS feed parsing."""
    return await _fetch_reddit_community_rss(client, community)


async def _fetch_reddit_candidates(client: httpx.AsyncClient) -> list[Candidate]:
    batches = await asyncio.gather(*[
        _fetch_reddit_community_candidates(client, community)
        for community in REDDIT_COMMUNITIES
    ])
    return [item for batch in batches for item in batch]


def _dedupe_candidates(candidates: list[Candidate]) -> list[Candidate]:
    # Canonical by URL first, then fallback to source+external id
    by_key: dict[str, Candidate] = {}
    for c in candidates:
        key = (c.url or "").strip().lower()
        if not key:
            key = f"{c.source}:{c.external_id}"

        if key not in by_key:
            by_key[key] = c
            continue

        current = by_key[key]
        if _score_sort_key(c) > _score_sort_key(current):
            by_key[key] = c

    return list(by_key.values())


def _pick_top(candidates: list[Candidate]) -> list[Candidate]:
    ranked = sorted(candidates, key=_score_sort_key, reverse=True)

    selected: list[Candidate] = []
    source_counts: dict[str, int] = {HN_SOURCE: 0, REDDIT_SOURCE: 0}
    community_counts: dict[str, int] = {}
    domain_counts: dict[str, int] = {}

    for c in ranked:
        if len(selected) >= MAX_ITEMS_PER_SOURCE * 2:
            break
        if source_counts.get(c.source, 0) >= MAX_ITEMS_PER_SOURCE:
            continue
        if community_counts.get(c.community, 0) >= MAX_ITEMS_PER_COMMUNITY:
            continue

        domain = _domain(c.url)
        if domain and domain_counts.get(domain, 0) >= MAX_ITEMS_PER_DOMAIN:
            continue

        selected.append(c)
        source_counts[c.source] = source_counts.get(c.source, 0) + 1
        community_counts[c.community] = community_counts.get(c.community, 0) + 1
        if domain:
            domain_counts[domain] = domain_counts.get(domain, 0) + 1

    return selected


async def _upsert_selected(selected: list[Candidate]) -> None:
    fetched_at = _utc_now()

    async with async_session() as session:
        # Upsert-ish: update by (source, external_id), insert otherwise
        for idx, c in enumerate(selected):
            existing = await session.execute(
                select(SocialStory).where(
                    SocialStory.source == c.source,
                    SocialStory.external_id == c.external_id,
                )
            )
            story = existing.scalar_one_or_none()
            rank_score = float(MAX_ITEMS_PER_SOURCE * 2 - idx)

            if story:
                story.community = c.community
                story.title = c.title
                story.url = c.url
                story.permalink = c.permalink
                story.score = c.score
                story.comment_count = c.comment_count
                story.upvote_ratio = c.upvote_ratio
                story.tags = c.tags
                story.rank_score = rank_score
                story.source_created_at = c.source_created_at
                story.fetched_at = fetched_at
                story.summary = c.summary
            else:
                session.add(SocialStory(
                    source=c.source,
                    community=c.community,
                    external_id=c.external_id,
                    title=c.title,
                    url=c.url,
                    permalink=c.permalink,
                    score=c.score,
                    comment_count=c.comment_count,
                    upvote_ratio=c.upvote_ratio,
                    tags=c.tags,
                    rank_score=rank_score,
                    source_created_at=c.source_created_at,
                    fetched_at=fetched_at,
                    summary=c.summary,
                ))

        # Retention guardrails: age-based + count-based
        cutoff = fetched_at - timedelta(days=RETENTION_DAYS)
        await session.execute(delete(SocialStory).where(SocialStory.fetched_at < cutoff))
        await session.flush()

        rows_result = await session.execute(
            select(SocialStory.id).order_by(SocialStory.fetched_at.desc())
        )
        all_ids = [row[0] for row in rows_result.all()]
        if len(all_ids) > MAX_STORED_ROWS:
            to_delete = all_ids[MAX_STORED_ROWS:]
            await session.execute(delete(SocialStory).where(SocialStory.id.in_(to_delete)))

        await session.commit()


async def run_social_pipeline() -> dict[str, int]:
    logger.info("=" * 60)
    logger.info("DailyMe Social Pipeline — Starting run at %s", _utc_now().isoformat())
    logger.info("=" * 60)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    headers = {"User-Agent": os.getenv("SOCIAL_USER_AGENT", USER_AGENT)}
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        results = await asyncio.gather(
            _fetch_hn_candidates(client),
            _fetch_reddit_candidates(client),
            return_exceptions=True,
        )
        hn = results[0] if not isinstance(results[0], BaseException) else []
        reddit = results[1] if not isinstance(results[1], BaseException) else []
        if isinstance(results[0], BaseException):
            logger.warning("HN fetch failed: %s", results[0])
        if isinstance(results[1], BaseException):
            logger.warning("Reddit fetch failed entirely: %s", results[1])

    combined = _dedupe_candidates(hn + reddit)
    selected = _pick_top(combined)
    await _upsert_selected(selected)

    stats = {
        "hn_candidates": len(hn),
        "reddit_candidates": len(reddit),
        "combined": len(combined),
        "selected": len(selected),
    }
    logger.info("Social pipeline stats: %s", stats)
    return stats


if __name__ == "__main__":
    asyncio.run(run_social_pipeline())
