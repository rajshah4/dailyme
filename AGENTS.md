# DailyMe — Agent Memory

## Project Overview
- **What:** Personalized AI news aggregator from forwarded email newsletters
- **Goal:** Demo app showing OpenHands coding agents running continuously as operators
- **Status:** Planning phase — PROJECT_PLAN.md created 2026-03-01

## Key Architecture: OpenHands-as-Operator
- **Two-process model:**
  1. **OpenHands agent** (runs on OpenHands Cloud) = the brain. Runs pipeline periodically: ingest emails, parse, segment stories, dedup, cluster, rank, trigger digest. Uses its own built-in LLM for hard parsing cases — no separate OpenAI API key.
  2. **FastAPI web app** (runs on Railway/Fly.io) = the read layer. Queries Postgres, renders the front page + handles feedback.
- The agent writes to Postgres; the web app reads from it.

## Key Decisions
- **Stack:** Python 3.12 + FastAPI + Jinja2 + PostgreSQL (Neon) + pgvector
- **Ingestion:** Gmail API polling (every 2 min), dedicated inbox
- **Segmentation:** 3-layer approach: structural HTML → heuristic text → OpenHands agent LLM fallback
- **Dedup:** URL canonicalization → title Jaccard similarity → embedding cosine similarity
- **Embeddings:** sentence-transformers `all-MiniLM-L6-v2` (384-dim, local, free — no API key)
- **LLM:** Provided by OpenHands agent — no separate OpenAI/Anthropic key needed
- **Frontend:** Server-rendered HTML with Pico CSS + HTMX for interactivity
- **Deployment:** Web app on Railway/Fly.io; pipeline via OpenHands Cloud
- **Single user, no auth for MVP**

## User Interests (for personalization defaults)
- AI research, agent tooling, infra/performance, enterprise use cases

## File Structure
- `PROJECT_PLAN.md` — Full project plan with architecture, schema, algorithms, tickets
- `app/` — Main application code (FastAPI web app)
- `app/ingestion/` — Gmail polling + email parsing
- `app/processing/` — Segmentation, dedup, clustering, ranking
- `app/delivery/` — Daily digest email
- `app/templates/` — Jinja2 HTML templates
- `scripts/run_pipeline.py` — Pipeline script that OpenHands agent executes

## Build & Run Commands
- TBD — will use `uv` for dependency management
- `uv run python -m app.main` (web app)
- `uv run python scripts/run_pipeline.py` (pipeline, run by OpenHands agent)

## Important Patterns
- All external API calls should have retry logic with exponential backoff
- Store raw HTML for reprocessing when parser improves
- Idempotency via gmail_id on raw_emails table
- Conservative dedup thresholds to avoid merging different stories
- Pipeline must be idempotent and resumable (tracks last-processed email ID)
- OpenHands agent can self-improve: fix parsers, add newsletter-specific handlers
