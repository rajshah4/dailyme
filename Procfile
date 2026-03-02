web: uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
worker: uv run python scripts/scheduler.py --interval 120
