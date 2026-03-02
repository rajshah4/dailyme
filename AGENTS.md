# DailyMe — Agent Memory

## Project Overview
- **What:** Personalized AI news aggregator from forwarded email newsletters
- **Goal:** Demo app showing OpenHands coding agents running continuously as operators
- **Status:** Working MVP — pipeline extracts stories from Gmail, web UI live

## Key Architecture
- **Pipeline:** `scripts/run_pipeline.py` — fetches Gmail → LLM extracts stories → dedup → store
- **Web app:** FastAPI + Jinja2 — reads from Postgres, renders feed
- **Scheduler:** `scripts/scheduler.py` — runs pipeline on a loop (default: every 2 min)
- **Database:** Neon Postgres with pgvector

## Key Decisions
- **Stack:** Python 3.12 + FastAPI + Jinja2 + PostgreSQL (Neon) + pgvector
- **Ingestion:** Gmail API polling with "DailyMe" label, 7-day lookback window
- **LLM Extraction:** OpenHands Cloud LLM (`openhands/claude-sonnet-4-5-20250929`) via SDK
- **HTML→Text:** `_html_to_readable()` extracts leaf block elements only (skips containers to avoid 62K collapsed lines)
- **URL Resolution:** Substack redirect URLs followed via HTTP HEAD to get real destinations (tweet URLs, etc.)
- **Content limit:** 80K chars to LLM (AINews is ~82K readable)
- **Dedup:** URL canonicalization + title Jaccard similarity
- **Content Tags:** Rule-based: long_form, research, launch, funding, vendor, podcast, tutorial, benchmark
- **Frontend:** Server-rendered HTML with Pico CSS
- **7-day expiry:** Stories expire after 7 days unless starred
- **Thumbs up/down:** Recommendation signal only — does NOT affect ranking
- **Star/save:** Starred stories survive expiry indefinitely
- **Timestamps:** `first_seen_at` = email `received_at` (when it hit mailbox, not pipeline run time)
- **Single user, no auth for MVP**

## Current State
- **3 newsletters processed:** AINews, Alex Chao, Machine Learning at Scale
- **52 stories extracted, 49 with real URLs**
- **Known issue:** OpenHands Cloud LLM proxy can timeout on large newsletters (The Rundown AI at 35K chars). Pipeline now catches errors and continues.
- **2 new emails** (The Rundown AI, OpenClaw) labeled but not yet processed (LLM timeout)

## .env Configuration
```
DATABASE_URL=postgresql+asyncpg://...@neon.tech/dailyme
LLM_MODEL=openhands/claude-sonnet-4-5-20250929
LLM_API_KEY=sk-...
```
No LLM_BASE_URL needed — SDK auto-routes `openhands/` prefix.

## File Structure
- `app/main.py` — FastAPI routes: feed (`/`), feedback (`/feedback`), star (`/star`), cleanup (`/cleanup`)
- `app/models.py` — SQLAlchemy models (Newsletter, RawEmail, Story, StoryGroup, Feedback)
- `app/ingestion/gmail.py` — Gmail API client, `fetch_labeled_emails()` with 7-day `after:` filter
- `app/processing/llm_extract.py` — LLM-based story extraction, `_html_to_readable()` converter
- `app/processing/substack.py` — Substack URL resolution (regex + HTTP redirect follow)
- `app/processing/segmenter.py` — Orchestrates LLM extraction + URL resolution
- `app/processing/dedup.py` — URL canonicalization + title similarity
- `app/processing/ranker.py` — Scoring: recency + coverage + interest + position
- `app/templates/feed.html` — Feed UI with tag filter bar, star, thumbs up/down
- `scripts/run_pipeline.py` — Full pipeline: Gmail → parse → dedup → store
- `scripts/scheduler.py` — Long-running scheduler loop

## Build & Run Commands
- `uv sync` — install all dependencies
- `uv run uvicorn app.main:app --reload --port 8000` — start web app
- `uv run python scripts/run_pipeline.py` — run pipeline once
- `uv run python scripts/scheduler.py` — run pipeline on loop (every 2 min)
- `uv run python scripts/scheduler.py --interval 300` — every 5 minutes

## Important Patterns
- Idempotency via `gmail_id` on `raw_emails` table — safe to re-fetch same emails
- Gmail only fetches emails from last 7 days (`after:` query filter)
- `_html_to_readable()` must skip container elements (`_BLOCK_TAGS` set) — extracting from `<td>` wrappers produces 62K lines that blow through content limit
- Substack redirect URLs are opaque UUIDs — must follow HTTP HEAD to resolve
- Pipeline catches LLM errors per-email and continues (marks email as parsed to avoid retries)
- `StoryGroup.first_seen_at` = email `received_at`, NOT `datetime.now()`
