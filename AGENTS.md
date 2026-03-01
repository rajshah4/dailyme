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
- **Segmentation:** 4-layer approach: LLM (primary) → structural HTML → heuristic text → single-article fallback
- **LLM Extraction:** litellm (same backend as OpenHands) — any model, configured via LLM_API_KEY
- **Substack URL Resolver:** `app/processing/substack.py` — extracts clean direct URLs from Substack tracking links
- **Dedup:** URL canonicalization → title Jaccard similarity → embedding cosine similarity
- **Embeddings:** sentence-transformers `all-MiniLM-L6-v2` (384-dim, local, free — no API key)
- **Content Tags:** Rule-based: long_form, research, launch, funding, vendor, podcast, tutorial, benchmark
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
- `uv sync` — install all dependencies
- `uv sync --dev` — install with dev dependencies (pytest, ruff)
- `uv run uvicorn app.main:app --reload --port 8000` — start web app
- `uv run python scripts/run_pipeline.py` — run pipeline (OpenHands agent)
- `uv run python -m pytest tests/ -v` — run tests
- `uv run alembic upgrade head` — run database migrations
- `uv run alembic revision --autogenerate -m "description"` — create migration

## Important Patterns
- All external API calls should have retry logic with exponential backoff
- Store raw HTML for reprocessing when parser improves
- Idempotency via gmail_id on raw_emails table
- Conservative dedup thresholds to avoid merging different stories
- Pipeline must be idempotent and resumable (tracks last-processed email ID)
- OpenHands agent can self-improve: fix parsers, add newsletter-specific handlers

## OpenHands Features Showcased
See `OPENHANDS_SHOWCASE.md` for the full strategy. Key features demonstrated:
1. **Skills** — `.agents/skills/` with newsletter-parser, pipeline-runner, dedup-strategy
2. **Sub-Agent Delegation** — Parallel newsletter processing via DelegateTool
3. **TaskToolSet** — Sequential pipeline stages (parse → dedup → rank → deliver)
4. **Custom Tools** — GmailTool, DatabaseTool, SendGridTool, EmbeddingTool
5. **MCP Integration** — Postgres via MCP server
6. **Cloud API** — Scheduled pipeline runs via cron → REST API
7. **Event Hooks** — Pipeline progress tracking, error logging, metrics
8. **Iterative Refinement** — Self-correcting parser, feedback-driven ranking
