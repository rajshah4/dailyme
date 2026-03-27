# DailyMe — Agent Memory

## Agent Operating Rules
- **Always push after committing** — This project runs on GitHub Actions cron jobs. A local commit is invisible to the automated pipelines. Every fix must end with `git push origin main` or it has not actually been deployed.
- **Confirm changes are live** — After pushing, tell the user: what was changed, what commit was made, and confirm it was pushed to remote. Don't assume they can see what happened.

## Project Overview
- **What:** Personalized AI news aggregator from forwarded email newsletters + Social Top Stories (HN/Reddit)
- **Goal:** Demo app showing OpenHands coding agents running continuously as operators
- **Status:** Working MVP — pipeline extracts stories from Gmail, social pipeline fetches HN/Reddit, web UI live

## Key Architecture
- **Pipeline:** `scripts/run_pipeline.py` — fetches Gmail → LLM extracts stories → dedup → store
- **Social Pipeline:** `scripts/run_social_pipeline.py` — fetches HN/Reddit → dynamic thresholding → store
- **Pipeline scheduling:** GitHub Actions cron (every 30 min) — see `.github/workflows/pipeline.yml`
- **Social scheduling:** GitHub Actions cron (every 2 hours) — see `.github/workflows/social_pipeline.yml`
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

## Deployment (Production)
- **Web UI:** Integrated into rajivshah.com/news (Next.js page)
  - No separate deployment needed; fetches from Neon DB on each page load
  - **Repo:** `rajiv-shah-website-private` (separate Next.js repo)
  - **Social RSS:** Endpoint `/news/social-rss.xml` is served by Next.js app, reading `social_stories` table
  - **FastAPI UI:** (This repo) serves as a fallback/dev UI and API backend at `https://dailyme-production.up.railway.app` (or similar)
- **Pipeline:** OpenHands Cloud triggered by GitHub Actions every 30 min
  - Trigger: `.github/workflows/pipeline.yml` (just API call, ~5 sec)
  - Compute: OpenHands Cloud (fetches Gmail, parses with LLM, dedup, store)
  - See `OPENHANDS_CLOUD_SETUP.md` for full details
- **DB:** Neon Postgres — ep-delicate-moon-aiqylnhh.c-4.us-east-1.aws.neon.tech
- **GitHub secrets:** OPENHANDS_API_KEY, OH_API_KEY, DATABASE_URL, GMAIL_TOKEN_JSON
- **Vercel env vars (website):** DAILYME_DATABASE_URL (for news page)

## Current State
- **6 newsletters in Gmail DailyMe label**
- **71 stories in feed** from AINews, Import AI, The Rundown AI, Cobus Greyling, and others
- **Social feed live** at `/news/social-rss.xml` (Next.js) and `/social/rss.xml` (FastAPI)
- **Pipeline stable** — GitHub Actions cron running green every 30 min
- **The Rundown AI:** Now uses web version (14K chars vs 35K email) via constructed URL fallback; extracts 12 stories in ~3.5 min

## .env Configuration
```
DATABASE_URL=postgresql+asyncpg://...@neon.tech/dailyme
LLM_MODEL=openhands/claude-sonnet-4-5-20250929
OH_API_KEY=sk-oh-...
LLM_API_KEY=sk-...
```
No LLM_BASE_URL needed — SDK auto-routes `openhands/` prefix. For V1 conversations, prefer `OH_API_KEY`; `LLM_API_KEY` remains as a fallback.
- **DATABASE_URL normalization** — `app/db.py` auto-normalizes the URL: converts `postgresql://` → `postgresql+asyncpg://`, strips `sslmode=require` and `channel_binding=require` (asyncpg incompatible), passes SSL via `connect_args={"ssl": True}`. Raw `postgresql://` URLs from Neon (which include `?sslmode=require&channel_binding=require`) work fine as-is.

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
- **Neon DB connection drops** after ~5 min idle — if LLM takes >5 min, the DB session dies. `pool_pre_ping` only helps at checkout, not during a long-running transaction. **Fix:** close DB session before calling LLM, open a fresh session after LLM returns. Pattern: `fetch data → dispose engine → run LLM → create new engine → save results`.
- **AINews newsletters take 10+ min** for LLM extraction via V1 API — set `OPENHANDS_RUN_TIMEOUT=600` when running locally/manually. Default 180s is too short. GHA workflow already inherits env from secrets.
- **Pipeline idempotency check** is on `gmail_id` existence in `raw_emails`, NOT on `parsed` flag — resetting `parsed=False` does NOT cause the main pipeline to re-process an email. Use a direct reparse script to retry failed extractions.
- **RSS endpoint:** `GET /rss.xml` now emits RSS 2.0 from the same ranked story selection as `/`; supports optional `tag` and `starred` query params
- **Social top-stories pipeline:** `scripts/run_social_pipeline.py` ingests HN + curated Reddit, applies dynamic thresholds + diversity caps, upserts into `social_stories`, and prunes by age/count guardrails (`RETENTION_DAYS`, `MAX_STORED_ROWS`) to stay Neon free-tier friendly
- **Social RSS endpoint:** `GET /social/rss.xml` publishes the curated social feed from `social_stories`
- **Social scheduler:** `.github/workflows/social_pipeline.yml` triggers OpenHands Cloud every 2 hours via `scripts/openhands_trigger_social.py`
- **Reddit 403 in cloud/dev environments** — Reddit blocks JSON API requests from data-center IPs with 403. `_fetch_reddit_community_candidates` handles this gracefully (try/except → returns `[]` + warning log). Top-level gather uses `return_exceptions=True` so HN still runs. Fix is in place as of commit `778815b`.
