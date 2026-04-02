# DailyMe — Agent Memory

## Agent Operating Rules
- **Always push after committing** — This project's pipelines are triggered by OpenHands Automations (cron). A local commit is invisible until pushed. Every fix must end with `git push origin main` or it has not actually been deployed.
- **Confirm changes are live** — After pushing, tell the user: what was changed, what commit was made, and confirm it was pushed to remote. Don't assume they can see what happened.

## Project Overview
- **What:** Personalized AI news aggregator from forwarded email newsletters + Social Top Stories (HN/Reddit)
- **Goal:** Demo app showing OpenHands coding agents running continuously as operators
- **Status:** Working MVP — pipeline extracts stories from Gmail, social pipeline fetches HN/Reddit, web UI live

## Key Architecture
- **Pipeline:** `scripts/run_pipeline.py` — fetches Gmail → LLM extracts stories → dedup → store
- **Social Pipeline:** `scripts/run_social_pipeline.py` — fetches HN/Reddit → dynamic thresholding → store
- **Pipeline scheduling:** OpenHands Automations cron (every 2h) — ID `5fbefeb3-9f35-459e-8b5c-54959be03cb0`
- **Social scheduling:** OpenHands Automations cron (every 2h) — ID `2129c579-8fb7-4562-9024-6b16af843b6c`
- **Status check:** `uv run python scripts/check_automations.py`
- **GitHub Actions** (`.github/workflows/`) — cron disabled, `workflow_dispatch` kept for manual one-off triggers
- **Web app:** FastAPI + Jinja2 on Railway — reads from Postgres, renders feed
- **Database:** Neon Postgres with pgvector

## Key Decisions
- **Stack:** Python 3.12 + FastAPI + Jinja2 + PostgreSQL (Neon) + pgvector
- **Ingestion:** Gmail API polling with "DailyMe" label, 7-day lookback window
- **LLM Extraction:** OpenHands Cloud LLM (`openhands/claude-sonnet-4-5-20250929`) via SDK
- **HTML→Text:** `_html_to_readable()` extracts leaf block elements only (skips containers to avoid 62K collapsed lines)
- **URL Resolution:** Substack redirect URLs followed via HTTP HEAD to get real destinations (tweet URLs, etc.)
- **Content limit:** 20K chars to LLM — `MAX_CONTENT_LENGTH=20000` in `llm_extract.py` (AINews has ~87K readable; at 40K the V1 conversation hits 20+ min and 500 errors; at 20K it completes in ~5 min)
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
- **Pipeline:** OpenHands Automations cron every 2h (ID `5fbefeb3-9f35-459e-8b5c-54959be03cb0`)
  - Check status: `uv run python scripts/check_automations.py`
  - Manual trigger: `gh workflow run pipeline.yml` (GitHub Actions workflow_dispatch still works)
  - See `OPENHANDS_CLOUD_SETUP.md` for full details
- **DB:** Neon Postgres — ep-delicate-moon-aiqylnhh.c-4.us-east-1.aws.neon.tech
- **GitHub secrets:** OPENHANDS_API_KEY, OH_API_KEY, DATABASE_URL, GMAIL_TOKEN_JSON
- **Vercel env vars (website):** DAILYME_DATABASE_URL (for news page)

## Current State
- **6 newsletters in Gmail DailyMe label**
- **71 stories in feed** from AINews, Import AI, The Rundown AI, Cobus Greyling, and others
- **Social feed live** at `/news/social-rss.xml` (Next.js) and `/social/rss.xml` (FastAPI)
- **Pipeline stable** — OpenHands Automations running every 2h
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
- `.github/workflows/pipeline.yml` — manual trigger only (cron moved to OpenHands Automations)

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
- **AINews newsletters take ~5 min** for LLM extraction via V1 API with `MAX_CONTENT_LENGTH=20000` — set `OPENHANDS_RUN_TIMEOUT=600` when running locally/manually. Default 180s is too short. GHA workflow already inherits env from secrets. At the old 40K limit it took 20+ min and hit server 500 errors.
- **Pipeline idempotency check** is on `gmail_id` existence in `raw_emails`, NOT on `parsed` flag — resetting `parsed=False` does NOT cause the main pipeline to re-process an email. Use a direct reparse script to retry failed extractions.
- **V1 poll 5xx retry** — `_wait_for_conversation` retries up to 5× on 5xx errors (with 10s back-off) before failing. This handles transient server errors during long-running conversations.
- **RSS endpoint:** `GET /rss.xml` now emits RSS 2.0 from the same ranked story selection as `/`; supports optional `tag` and `starred` query params
- **Social top-stories pipeline:** `scripts/run_social_pipeline.py` ingests HN + curated Reddit, applies dynamic thresholds + diversity caps, upserts into `social_stories`, and prunes by age/count guardrails (`RETENTION_DAYS`, `MAX_STORED_ROWS`) to stay Neon free-tier friendly
- **Social RSS endpoint:** `GET /social/rss.xml` publishes the curated social feed from `social_stories`
- **Social scheduler:** OpenHands Automations cron every 2h (ID `2129c579-8fb7-4562-9024-6b16af843b6c`); `.github/workflows/social_pipeline.yml` kept for manual dispatch only
- **Reddit 403 in cloud/dev environments** — `www.reddit.com/r/*/top.json` returns 403 from data-center IPs; `www.reddit.com/r/*/top.rss` returns 200 from the same IPs. **Primary fix:** `_fetch_reddit_community_rss()` fetches the Atom RSS feed — no credentials needed, bypasses IP blocks, extracts title/permalink/external-URL/date. Score is synthetic (rank-based: position 1 → 100, position 2 → 99, …) since RSS omits upvote counts. **Optional enhancement:** set `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` (Reddit "script" app at https://www.reddit.com/prefs/apps); `_get_reddit_oauth_token()` then fetches a client_credentials Bearer token and routes requests to `oauth.reddit.com` for real score data. Routing logic: token present → JSON path; no token → RSS path; JSON failure → auto-fallback to RSS.
