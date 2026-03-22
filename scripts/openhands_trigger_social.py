"""Trigger OpenHands Cloud to run the DailyMe social top-stories pipeline."""

from scripts.openhands_trigger import OpenHandsAPI, _start_pipeline_conversation


def main() -> None:
    repo = "rajshah4/dailyme"
    branch = "main"

    task = """Run the DailyMe social top-stories pipeline:

**Setup:**
1. Use repository .env for DATABASE_URL if present
2. No Gmail or LLM required for this job

**Execute:**
```bash
uv sync
uv run python scripts/run_social_pipeline.py
```

**What it does:**
- Fetches top candidates from Hacker News and curated Reddit communities
- Applies dynamic threshold filtering (target posts/day)
- Deduplicates and enforces diversity caps
- Stores compact results in `social_stories` table with strict retention

**Storage constraints:**
- Keep total rows capped to avoid Neon free-tier overage
- Delete old rows automatically each run

**Expected runtime:** ~1-2 minutes
"""

    print(f"🚀 Triggering OpenHands Cloud social pipeline for {repo}@{branch}")
    api = OpenHandsAPI()
    _, ready_task = _start_pipeline_conversation(
        api,
        initial_user_msg=task,
        repository=repo,
        selected_branch=branch,
    )

    conversation_id = ready_task.get("app_conversation_id")
    conversation = api.get_conversation_status(conversation_id) or {}
    conversation_url = conversation.get("conversation_url", f"{api.base_url}/conversations/{conversation_id}")

    print(f"✅ Social pipeline started: {conversation_url}")
    print(f"📝 Conversation ID: {conversation_id}")


if __name__ == "__main__":
    main()
