"""DailyMe Social Top Stories Pipeline (Hacker News + Reddit).

Runs independently from newsletter ingestion and stores a compact set of curated
social stories for RSS publication.

Reddit fetching strategy (two paths, auto-selected):
  - No credentials: fetches www.reddit.com/r/*/top.rss (Atom feed, no auth,
    works from cloud IPs). Score is synthetic/rank-based.
  - REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET set: fetches oauth.reddit.com JSON
    API for real upvote scores. Falls back to RSS on failure.

Design goals:
- Keep storage lightweight for Neon free tier (<150MB by wide margin)
- Deterministic top-story selection with controllable volume
- Safe to run every 2 hours
"""

import asyncio
import html as html_lib
import logging
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

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
TARGET_HN_POSTS_PER_DAY = 8
TARGET_REDDIT_POSTS_PER_DAY = 12

MAX_ITEMS_PER_SOURCE = 20
MAX_ITEMS_PER_COMMUNITY = 6
MAX_ITEMS_PER_DOMAIN = 3

HN_TOP_LOOKBACK_DAYS = 30
HN_HOT_LOOKBACK_DAYS = 7
REDDIT_TOP_LIMIT = 100
REDDIT_HOT_LIMIT = 100

USER_AGENT = "dailyme-social/1.0"


async def _get_reddit_oauth_token(client: httpx.AsyncClient) -> str | None:
    """Obtain a Reddit OAuth2 Bearer token via client_credentials flow.

    Requires REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET env vars (from a Reddit
    "script" or "web" app created at https://www.reddit.com/prefs/apps).
    Returns None if credentials are not configured or the request fails.
    """
    client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
    client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        logger.debug("REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET not set — will use RSS feed")
        return None
    try:
        resp = await client.post(
            "https://www.reddit.com/api/v1/access_token",
            data={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
            timeout=15,
        )
        resp.raise_for_status()
        token = resp.json().get("access_token")
        logger.info("Reddit OAuth2 token obtained (expires_in=%s s)", resp.json().get("expires_in"))
        return token
    except Exception as exc:
        logger.warning("Failed to obtain Reddit OAuth2 token (%s) — falling back to RSS feed", exc)
        return None


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

    # Derive dynamic threshold from monthly top score distribution
    top_scores = sorted((int(h.get("points") or 0) for h in top_hits if h.get("objectID")), reverse=True)
    rank_idx = min(max(TARGET_HN_POSTS_PER_DAY * HN_TOP_LOOKBACK_DAYS - 1, 0), max(len(top_scores) - 1, 0))
    threshold = top_scores[rank_idx] if top_scores else 0

    candidates: list[Candidate] = []
    for hit in hot_hits:
        object_id = str(hit.get("objectID") or "").strip()
        if not object_id:
            continue
        points = int(hit.get("points") or 0)
        if points < threshold:
            continue

        title = (hit.get("title") or hit.get("story_title") or "").strip()
        if not title:
            continue

        story_url = hit.get("url") or hit.get("story_url")
        permalink = f"https://news.ycombinator.com/item?id={object_id}"
        created_at = _safe_dt(hit.get("created_at_i"))

        candidates.append(Candidate(
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
        ))

    logger.info("HN candidates above threshold (%s): %s", threshold, len(candidates))
    return candidates


def _parse_reddit_rss_entries(rss_text: str, community: str) -> list[Candidate]:
    """Parse Reddit Atom RSS feed into Candidate objects with synthetic rank-based scores."""
    NS_A = "http://www.w3.org/2005/Atom"
    try:
        root = ET.fromstring(rss_text)
    except ET.ParseError as exc:
        logger.warning("Reddit r/%s RSS parse error: %s", community, exc)
        return []

    candidates: list[Candidate] = []
    for rank, entry in enumerate(root.findall(f"{{{NS_A}}}entry")):
        id_el      = entry.find(f"{{{NS_A}}}id")
        title_el   = entry.find(f"{{{NS_A}}}title")
        link_el    = entry.find(f"{{{NS_A}}}link")
        pub_el     = entry.find(f"{{{NS_A}}}published")
        content_el = entry.find(f"{{{NS_A}}}content")

        raw_id = (id_el.text or "").strip() if id_el is not None else ""
        external_id = raw_id.replace("t3_", "") if raw_id.startswith("t3_") else raw_id
        if not external_id:
            continue

        title = (title_el.text or "").strip() if title_el is not None else ""
        if not title:
            continue

        permalink = link_el.get("href", "") if link_el is not None else ""
        created_at = _safe_dt(None)
        if pub_el is not None and pub_el.text:
            try:
                created_at = datetime.fromisoformat(pub_el.text)
            except ValueError:
                pass

        # Extract external article URL from content HTML (first non-reddit href)
        post_url: str | None = None
        if content_el is not None and content_el.text:
            content_html = html_lib.unescape(content_el.text)
            hrefs = re.findall(r'href="([^"]+)"', content_html)
            post_url = next(
                (u for u in hrefs if "reddit.com" not in u and "redd.it" not in u and u.startswith("http")),
                None,
            )

        # Synthetic score: first RSS entry (highest upvoted) = 100, decreasing by rank
        synthetic_score = max(0, 100 - rank)

        candidates.append(Candidate(
            source=REDDIT_SOURCE,
            community=community,
            external_id=external_id,
            title=title,
            url=post_url or permalink,
            permalink=permalink,
            score=synthetic_score,
            comment_count=0,  # not available in RSS
            upvote_ratio=None,
            source_created_at=created_at,
            tags=["source:reddit", f"community:{community}"],
        ))

    return candidates


async def _fetch_reddit_community_candidates(
    client: httpx.AsyncClient,
    community: str,
    token: str | None = None,
) -> list[Candidate]:
    """Fetch Reddit community candidates.

    With an OAuth token → uses oauth.reddit.com JSON API (full score data).
    Without a token    → uses public RSS feed (no credentials, no IP blocks).
    """
    if token:
        return await _fetch_reddit_community_json(client, community, token)
    return await _fetch_reddit_community_rss(client, community)


async def _fetch_reddit_community_json(
    client: httpx.AsyncClient,
    community: str,
    token: str,
) -> list[Candidate]:
    """Fetch via authenticated JSON API (oauth.reddit.com) — full score data."""
    top_url = f"https://oauth.reddit.com/r/{community}/top.json?t=month&limit={REDDIT_TOP_LIMIT}"
    hot_url = f"https://oauth.reddit.com/r/{community}/hot.json?limit={REDDIT_HOT_LIMIT}"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        top_resp, hot_resp = await asyncio.gather(
            client.get(top_url, headers=headers, timeout=30),
            client.get(hot_url, headers=headers, timeout=30),
        )
        top_resp.raise_for_status()
        hot_resp.raise_for_status()
    except Exception as exc:
        logger.warning("Reddit r/%s JSON (OAuth) unavailable (%s) — falling back to RSS", community, exc)
        return await _fetch_reddit_community_rss(client, community)

    top_children = (((top_resp.json() or {}).get("data") or {}).get("children") or [])
    hot_children = (((hot_resp.json() or {}).get("data") or {}).get("children") or [])

    top_scores = sorted((int((c.get("data") or {}).get("score") or 0) for c in top_children), reverse=True)
    rank_idx = min(max(TARGET_REDDIT_POSTS_PER_DAY * 30 // max(len(REDDIT_COMMUNITIES), 1) - 1, 0), max(len(top_scores) - 1, 0))
    threshold = top_scores[rank_idx] if top_scores else 0

    candidates: list[Candidate] = []
    for child in hot_children:
        data = child.get("data") or {}
        external_id = str(data.get("id") or "").strip()
        if not external_id:
            continue
        score = int(data.get("score") or 0)
        if score < threshold:
            continue
        title = (data.get("title") or "").strip()
        if not title or int(data.get("num_comments") or 0) < 3:
            continue
        candidates.append(Candidate(
            source=REDDIT_SOURCE,
            community=community,
            external_id=external_id,
            title=title,
            url=data.get("url"),
            permalink=f"https://www.reddit.com{data.get('permalink', '')}",
            score=score,
            comment_count=int(data.get("num_comments") or 0),
            upvote_ratio=float(data.get("upvote_ratio")) if data.get("upvote_ratio") is not None else None,
            source_created_at=_safe_dt(data.get("created_utc")),
            tags=["source:reddit", f"community:{community}"],
            summary=data.get("selftext")[:1000] if data.get("selftext") else None,
        ))

    logger.info("Reddit r/%s JSON candidates above threshold (%s): %s", community, threshold, len(candidates))
    return candidates


async def _fetch_reddit_community_rss(
    client: httpx.AsyncClient,
    community: str,
) -> list[Candidate]:
    """Fetch via public RSS feed — no credentials required, bypasses IP blocks."""
    # top.rss already sorted by score; use it as both threshold-sampler and candidates
    top_url = f"https://www.reddit.com/r/{community}/top.rss?t=month&limit={REDDIT_TOP_LIMIT}"
    try:
        resp = await client.get(top_url, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Reddit r/%s RSS unavailable (%s) — skipping", community, exc)
        return []

    candidates = _parse_reddit_rss_entries(resp.text, community)
    logger.info("Reddit r/%s RSS candidates: %s", community, len(candidates))
    return candidates


async def _fetch_reddit_candidates(client: httpx.AsyncClient, token: str | None = None) -> list[Candidate]:
    batches = await asyncio.gather(*[
        _fetch_reddit_community_candidates(client, community, token=token)
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
        reddit_token = await _get_reddit_oauth_token(client)
        if reddit_token:
            logger.info("Reddit: OAuth2 token present — using oauth.reddit.com JSON API")
        else:
            logger.info("Reddit: no OAuth2 credentials — using RSS feed (www.reddit.com/r/*/top.rss)")

        results = await asyncio.gather(
            _fetch_hn_candidates(client),
            _fetch_reddit_candidates(client, token=reddit_token),
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
