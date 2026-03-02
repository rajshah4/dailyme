# DailyMe — Agent Memory

## Project Overview
- **What:** Personalized AI news aggregator from forwarded email newsletters
- **Goal:** Demo app showing OpenHands coding agents running continuously as operators
- **Status:** Working MVP — pipeline extracts stories from Gmail, web UI live

## Key Architecture
- **Pipeline:** `scripts/run_pipeline.py` — fetches Gmail → LLM extracts stories → dedup → store
- **Pipeline scheduling:** GitHub Actions cron (every 30 min) — see `.github/workflows/pipeline.yml`
- **Web app:** FastAPI + Jinja2 on Railway — reads from Postgres, renders feed
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

## Deployment
- **Web app:** Railway — https://web-production-c609c.up.railway.app/
- **Pipeline:** GitHub Actions cron — https://github.com/rajshah4/dailyme/actions
- **DB:** Neon Postgres — ep-delicate-moon-aiqylnhh.c-4.us-east-1.aws.neon.tech
- **GitHub secrets:** DATABASE_URL, LLM_MODEL, LLM_API_KEY, GMAIL_TOKEN_JSON
- **Railway env vars:** DATABASE_URL, LLM_MODEL, LLM_API_KEY, GMAIL_TOKEN_JSON (web only)

## Current State
- **6 newsletters in Gmail DailyMe label**
- **71 stories in feed** from AINews, Import AI, The Rundown AI, Cobus Greyling, and others
- **Pipeline stable** — GitHub Actions cron running green every 30 min
- **The Rundown AI:** Now uses web version (14K chars vs 35K email) via constructed URL fallback; extracts 12 stories in ~3.5 min

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
- `app/processing/segmenter.py` — Orchestrates LLM extraction + URL resolution + web version
- `app/processing/web_version.py` — Fetches cleaner web version of beehiiv newsletters (constructed URL fallback)
- `app/processing/dedup.py` — URL canonicalization + title similarity
- `app/processing/ranker.py` — Scoring: recency + coverage + interest + position
- `app/templates/feed.html` — Feed UI with tag filter bar, star, thumbs up/down
- `scripts/run_pipeline.py` — Full pipeline: Gmail → parse → dedup → store
- `.github/workflows/pipeline.yml` — GitHub Actions cron (every 30 min)

## Build & Run Commands
- `uv sync` — install all dependencies
- `uv run uvicorn app.main:app --reload --port 8000` — start web app locally
- `uv run python scripts/run_pipeline.py` — run pipeline once locally
- `gh workflow run pipeline.yml` — trigger pipeline via GitHub Actions
- `railway up` — deploy web to Railway (link to web service first)

## Important Patterns
- Idempotency via `gmail_id` on `raw_emails` table — safe to re-fetch same emails
- Gmail only fetches emails from last 7 days (`after:` query filter)
- `_html_to_readable()` must skip container elements (`_BLOCK_TAGS` set) — extracting from `<td>` wrappers produces 62K lines that blow through content limit
- Substack redirect URLs are opaque UUIDs — must follow HTTP HEAD to resolve
- Pipeline catches LLM errors per-email and continues (marks email as parsed to avoid retries)
- `StoryGroup.first_seen_at` = email `received_at`, NOT `datetime.now()`
- **Commit per email** — each email gets its own DB session + commit, so one failure doesn't roll back everything
- **LLM timeout via env vars** — `LLM_TIMEOUT=120` and `LLM_NUM_RETRIES=2` in GHA workflow (load_from_env reads LLM_ prefix). Post-init `_llm.timeout = N` doesn't work reliably
- **asyncio.wait_for(300s)** wraps `segment_newsletter()` as backup timeout, but won't cancel sync LLM calls mid-flight
- **Don't pass `timeout` as kwarg to `llm.completion()`** — causes "multiple values for keyword argument" error
- **Web version for beehiiv newsletters** — `web_version.py` fetches cleaner web page via constructed URL (beehiiv redirects blocked by Cloudflare in GHA). Maps sender domain → base URL in `_SENDER_WEB_PATTERNS`
- **Neon DB connection drops** after ~5 min idle — if LLM takes >5 min, the DB session dies. `pool_pre_ping` only helps at checkout, not during a long-running transaction. Keep LLM processing under 5 min total
