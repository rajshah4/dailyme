---
name: pipeline-runner
description: Run the DailyMe newsletter processing pipeline. Handles email ingestion, parsing, dedup, ranking, and optional digest delivery.
triggers:
- pipeline
- run pipeline
- process newsletters
- fetch emails
- daily run
---

# DailyMe Pipeline Runner

You are the operator of the DailyMe newsletter processing system. Your job is to run the pipeline that turns forwarded email newsletters into a personalized, deduped news feed.

## How to Run the Pipeline

```bash
cd /Users/rajiv.shah/Code/dailyme
uv run python scripts/run_pipeline.py
```

## What the Pipeline Does

1. **Fetch** — Polls Gmail for unread emails in the dedicated inbox
2. **Parse** — Cleans HTML, extracts story segments from each newsletter
3. **Dedup** — Canonicalizes URLs, checks title similarity, groups duplicates
4. **Store** — Writes stories and story groups to Postgres
5. **Mark read** — Marks processed emails as read in Gmail

## When Parsing Fails

If the pipeline reports "LLM fallback needed" for a newsletter:

1. Look at the raw email HTML stored in the `raw_emails` table
2. Use your language understanding to extract stories (see the `newsletter-parser` skill)
3. Insert the extracted stories into the `stories` table
4. Create `story_groups` and `story_group_members` entries

## Sending the Daily Digest

To trigger the daily digest email:

```python
from app.delivery.digest import send_digest
from app.processing.ranker import rank_story_groups
# ... fetch story groups, rank them, then call send_digest(ranked_stories)
```

## Checking Results

After running the pipeline:

1. Check the front page: `uv run uvicorn app.main:app --host 0.0.0.0 --port 8000`
2. Check stats: `curl http://localhost:8000/stats`
3. Check the database directly for story counts

## Troubleshooting

- **Gmail auth error**: The token may have expired. Delete `token.json` and re-authenticate.
- **Database connection error**: Check `DATABASE_URL` in `.env`.
- **No stories extracted**: The newsletter format may not be supported yet. Check `app/processing/segmenter.py` and consider adding patterns.

## Improving the Pipeline

If a newsletter consistently fails to parse:

1. Forward a sample to the inbox
2. Run the pipeline, note the `raw_email.id` of the failed email
3. Look at the HTML structure in the database
4. Add newsletter-specific patterns to `app/processing/segmenter.py`
5. Re-run parsing for that email

This is a key OpenHands demo: the agent improves its own pipeline over time.
