# 📰 DailyMe

**Personalized AI news from your newsletters — powered by OpenHands coding agents.**

DailyMe turns forwarded email newsletters into a personalized, deduplicated news feed. The unique part: an [OpenHands Cloud](https://www.all-hands.dev) agent runs the system continuously as an operator, handling all the heavy compute.

**Live demo:** [rajivshah.com/news](https://rajivshah.com/news)

## How It Works

```
You forward newsletters → OpenHands Cloud processes them → Personalized feed on your website
```

1. **Forward** your favorite AI newsletters to a dedicated Gmail inbox
2. **OpenHands Cloud agent** wakes up every 30 minutes, fetches new emails, parses them into stories
3. Stories are **deduplicated** (same news from 5 newsletters = 1 story)
4. Stories are **ranked** by recency, coverage, and topic tags
5. **News page** on your website shows your personalized feed (updated in real-time)

## OpenHands Features Showcased

| Feature | How It's Used |
|---------|--------------|
| **Skills** | Newsletter-specific parsing knowledge in `.agents/skills/` |
| **Sub-Agent Delegation** | Parallel processing of multiple newsletters |
| **Cloud API** | Scheduled pipeline runs via cron → REST API |
| **Custom Tools** | Typed Gmail, DB, Embedding tools |
| **Iterative Refinement** | Self-improving parser accuracy |

See [OPENHANDS_SHOWCASE.md](OPENHANDS_SHOWCASE.md) for the full strategy.

## Quick Start

```bash
# Install dependencies
uv sync

# Set up environment
cp .env.example .env
# Edit .env with your database URL, Gmail credentials, etc.
# For OpenHands V1 conversations, set OH_API_KEY.

# Run database migrations
uv run alembic upgrade head

# Start the web app
uv run uvicorn app.main:app --reload --port 8000

# Run the pipeline (usually done by OpenHands agent)
uv run python scripts/run_pipeline.py
```

## Tech Stack

- **Python 3.12** + FastAPI + Jinja2 (server-rendered HTML)
- **PostgreSQL** with pgvector (Neon free tier)
- **Gmail API** for email ingestion
- **sentence-transformers** for local embeddings (no API key needed)
- **OpenHands** provides the LLM for hard parsing cases
- **Pico CSS** for clean, minimal styling

## Environment Notes

- Prefer `OH_API_KEY` for OpenHands V1 conversation-based extraction.
- `LLM_API_KEY` remains supported as a fallback for older paths and compatibility.
- `LLM_MODEL=openhands/...` is still the expected model format.

## Project Structure

```
app/
├── main.py              # FastAPI routes
├── config.py            # Settings (env vars)
├── db.py                # Async database connection
├── models.py            # SQLAlchemy models
├── schemas.py           # Pydantic schemas
├── ingestion/           # Gmail polling + HTML parsing
├── processing/          # Segmentation, dedup, clustering, ranking
├── delivery/            # Daily digest email
├── templates/           # Jinja2 HTML templates
└── static/              # CSS
scripts/
├── run_pipeline.py      # Main pipeline (run by OpenHands agent)
.agents/skills/          # OpenHands agent skills
├── newsletter-parser/   # LLM extraction skill
├── pipeline-runner/     # Pipeline operation skill
└── dedup-strategy/      # Dedup knowledge skill
```

## Deployment Architecture

### Production Setup

```
┌─────────────────────────────────────────────┐
│  GitHub Actions (every 30 min)             │
│  • Triggers OpenHands Cloud API (~5 sec)   │
└──────────────────┬──────────────────────────┘
                   │ starts conversation
                   ↓
┌─────────────────────────────────────────────┐
│  OpenHands Cloud (Heavy Compute)            │
│  • Fetches Gmail newsletters                │
│  • Parses with Claude Sonnet 4              │
│  • Deduplicates stories                     │
│  • 5-15 minutes per run                     │
└──────────────────┬──────────────────────────┘
                   │ writes to
                   ↓
┌─────────────────────────────────────────────┐
│  Neon Postgres (Storage)                    │
│  • Stores newsletters, stories, feedback    │
└──────────────────┬──────────────────────────┘
                   │ reads from
                   ↓
┌─────────────────────────────────────────────┐
│  rajivshah.com/news (Next.js on Vercel)     │
│  • Serves personalized feed                 │
│  • Zero compute load (just DB reads)        │
└─────────────────────────────────────────────┘
```

**Key Benefits:**
- ✅ OpenHands Cloud handles all heavy lifting (Gmail, LLM, parsing)
- ✅ News page integrated into existing website (no separate deployment)
- ✅ Minimal infrastructure costs (free tiers everywhere)
- ✅ Clean separation: compute (OpenHands) + storage (Neon) + presentation (Vercel)

**Setup Guides:**
- **OpenHands Cloud Pipeline:** See `OPENHANDS_CLOUD_SETUP.md`
- **Web Integration:** News page is in the `rajiv-shah-website-private` repo
- **Alternative Standalone Deployment:** See `VERCEL_DEPLOYMENT.md` (if you want a separate site)

## License

MIT
