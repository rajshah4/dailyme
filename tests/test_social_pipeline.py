from datetime import datetime, timezone

import pytest

from scripts import run_social_pipeline as sp


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, responses: dict[str, dict]):
        self._responses = responses

    async def get(self, url: str, timeout: int = 30):
        for key, payload in self._responses.items():
            if key in url:
                return _FakeResponse(payload)
        raise AssertionError(f"Unexpected URL: {url}")


@pytest.mark.asyncio
async def test_fetch_hn_candidates_applies_dynamic_threshold(monkeypatch):
    now = datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(sp, "_utc_now", lambda: now)

    top_hits = [
        {"objectID": str(i), "points": 300 - i}
        for i in range(300)
    ]

    hot_hits = [
        {
            "objectID": "keep-1",
            "points": 95,
            "title": "Story above threshold",
            "url": "https://example.com/a",
            "created_at_i": int(now.timestamp()),
            "num_comments": 12,
        },
        {
            "objectID": "drop-1",
            "points": 50,
            "title": "Story below threshold",
            "url": "https://example.com/b",
            "created_at_i": int(now.timestamp()),
            "num_comments": 9,
        },
    ]

    client = _FakeClient(
        {
            "api/v1/search?": {"hits": top_hits},
            "api/v1/search_by_date": {"hits": hot_hits},
        }
    )

    candidates = await sp._fetch_hn_candidates(client)
    titles = {c.title for c in candidates}

    assert "Story above threshold" in titles
    assert "Story below threshold" not in titles
    assert all(c.source == sp.HN_SOURCE for c in candidates)


def _candidate(
    *,
    external_id: str,
    source: str,
    community: str,
    title: str,
    url: str,
    score: int,
):
    return sp.Candidate(
        source=source,
        community=community,
        external_id=external_id,
        title=title,
        url=url,
        permalink=f"https://example.com/p/{external_id}",
        score=score,
        comment_count=20,
        upvote_ratio=0.9,
        source_created_at=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
        tags=[f"source:{source}"],
    )


def test_pick_top_enforces_diversity_caps(monkeypatch):
    monkeypatch.setattr(sp, "MAX_ITEMS_PER_SOURCE", 10)
    monkeypatch.setattr(sp, "MAX_ITEMS_PER_COMMUNITY", 2)
    monkeypatch.setattr(sp, "MAX_ITEMS_PER_DOMAIN", 1)

    candidates = []

    # HN candidates, all same domain; only one should survive domain cap.
    for i, score in enumerate([300, 290, 280], start=1):
        candidates.append(
            _candidate(
                external_id=f"hn-{i}",
                source=sp.HN_SOURCE,
                community="frontpage",
                title=f"HN {i}",
                url=f"https://dupdomain.com/article-{i}",
                score=score,
            )
        )

    # Reddit community A; at most 2 from this community.
    for i, score in enumerate([270, 260, 250], start=1):
        candidates.append(
            _candidate(
                external_id=f"ra-{i}",
                source=sp.REDDIT_SOURCE,
                community="MachineLearning",
                title=f"RA {i}",
                url=f"https://a{i}.example.org/post",
                score=score,
            )
        )

    # Reddit community B; at most 2 from this community.
    for i, score in enumerate([240, 230, 220], start=1):
        candidates.append(
            _candidate(
                external_id=f"rb-{i}",
                source=sp.REDDIT_SOURCE,
                community="LocalLLaMA",
                title=f"RB {i}",
                url=f"https://b{i}.example.net/post",
                score=score,
            )
        )

    selected = sp._pick_top(candidates)

    # Domain cap on dupdomain.com
    hn_selected = [c for c in selected if c.source == sp.HN_SOURCE]
    assert len(hn_selected) == 1

    # Community caps on Reddit selections
    ml_selected = [c for c in selected if c.community == "MachineLearning"]
    llm_selected = [c for c in selected if c.community == "LocalLLaMA"]
    assert len(ml_selected) <= 2
    assert len(llm_selected) <= 2

    # Domain cap globally: no domain should appear more than once.
    domains = [sp._domain(c.url) for c in selected if c.url]
    assert len(domains) == len(set(domains))
