# DailyMe — Agent Memory

## Project Overview
- **What:** Personalized AI news aggregator from forwarded email newsletters
- **Goal:** Demo app showing OpenHands coding agents running continuously
- **Status:** Planning phase — PROJECT_PLAN.md created 2026-03-01

## Key Decisions
- **Stack:** Python 3.12 + FastAPI + Jinja2 + PostgreSQL (Neon) + pgvector
- **Ingestion:** Gmail API polling (every 2 min), dedicated inbox
- **Segmentation:** 3-layer approach: structural HTML → heuristic text → LLM fallback (gpt-4o-mini)
- **Dedup:** URL canonicalization → title Jaccard similarity → embedding cosine similarity
- **Embeddings:** OpenAI text-embedding-3-small, stored in pgvector
- **Frontend:** Server-rendered HTML with Pico CSS + HTMX for interactivity
- **Deployment target:** Railway or Fly.io
- **Single user, no auth for MVP**

## User Interests (for personalization defaults)
- AI research, agent tooling, infra/performance, enterprise use cases

## File Structure
- `PROJECT_PLAN.md` — Full project plan with architecture, schema, algorithms, tickets
- `app/` — Main application code (FastAPI)
- `app/ingestion/` — Gmail polling + email parsing
- `app/processing/` — Segmentation, dedup, clustering, ranking
- `app/delivery/` — Daily digest email
- `app/templates/` — Jinja2 HTML templates

## Build & Run Commands
- TBD — will use `uv` for dependency management
- `uv run python -m app.main` (planned)

## Important Patterns
- All external API calls should have retry logic with exponential backoff
- Store raw HTML for reprocessing when parser improves
- Idempotency via gmail_id on raw_emails table
- Conservative dedup thresholds to avoid merging different stories
