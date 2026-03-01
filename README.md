# 📰 DailyMe

**Personalized AI news from your newsletters — powered by OpenHands coding agents.**

DailyMe turns forwarded email newsletters into a personalized, deduplicated "front page" and a daily email digest. The unique part: an [OpenHands](https://github.com/All-Hands-AI/OpenHands) AI agent doesn't just build the code — it **runs the system continuously** as an operator.

## How It Works

```
You forward newsletters → OpenHands agent processes them → Personalized front page + daily digest
```

1. **Forward** your favorite AI newsletters to a dedicated Gmail inbox
2. **OpenHands agent** wakes up every 2 hours, fetches new emails, parses them into stories
3. Stories are **deduplicated** (same news from 5 newsletters = 1 story)
4. Stories are **ranked** by recency, coverage, and your interests
5. **Front page** shows your personalized feed; **daily digest** hits your inbox at 8 AM

## OpenHands Features Showcased

| Feature | How It's Used |
|---------|--------------|
| **Skills** | Newsletter-specific parsing knowledge in `.agents/skills/` |
| **Sub-Agent Delegation** | Parallel processing of multiple newsletters |
| **Cloud API** | Scheduled pipeline runs via cron → REST API |
| **Custom Tools** | Typed Gmail, DB, SendGrid, Embedding tools |
| **Iterative Refinement** | Self-improving parser accuracy |

See [OPENHANDS_SHOWCASE.md](OPENHANDS_SHOWCASE.md) for the full strategy.

## Quick Start

```bash
# Install dependencies
uv sync

# Set up environment
cp .env.example .env
# Edit .env with your database URL, Gmail credentials, etc.

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

## License

MIT