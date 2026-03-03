"""
Trigger OpenHands Cloud to run the DailyMe pipeline.

This script starts an OpenHands Cloud conversation that executes the pipeline.
All heavy compute (Gmail fetching, LLM parsing, deduplication) happens in
OpenHands Cloud. This script just triggers it.

Usage:
    python scripts/openhands_trigger.py [--wait]

Environment variables:
    OPENHANDS_API_KEY: Your OpenHands Cloud API key
    GITHUB_REPO: Repository name (e.g., "rajshah4/dailyme")
    GITHUB_BRANCH: Branch name (default: "main")
"""

import os
import sys
import time
from typing import Any

import requests


class OpenHandsAPI:
    """Minimal OpenHands Cloud API client."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or os.getenv("OPENHANDS_API_KEY")
        if not self.api_key:
            raise ValueError("OPENHANDS_API_KEY not set")

        self.base_url = base_url or "https://app.all-hands.dev"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def create_conversation(
        self,
        initial_user_msg: str,
        repository: str,
        selected_branch: str = "main",
    ) -> dict[str, Any]:
        """Start a new OpenHands conversation."""
        payload = {
            "initial_user_msg": initial_user_msg,
            "repository": repository,
            "selected_branch": selected_branch,
        }

        response = requests.post(
            f"{self.base_url}/api/conversations",
            headers=self.headers,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def get_conversation_status(self, conversation_id: str) -> dict[str, Any]:
        """Get the status of a conversation."""
        response = requests.get(
            f"{self.base_url}/api/conversations/{conversation_id}",
            headers=self.headers,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def poll_until_terminal(
        self,
        conversation_id: str,
        timeout_s: int = 1800,
        poll_interval_s: int = 30,
    ) -> dict[str, Any]:
        """
        Poll conversation until it reaches a terminal state.

        Terminal states: completed, failed, cancelled, error
        """
        start_time = time.time()
        terminal_states = {"completed", "failed", "cancelled", "error"}

        while True:
            if time.time() - start_time > timeout_s:
                raise TimeoutError(f"Conversation did not complete within {timeout_s}s")

            status = self.get_conversation_status(conversation_id)
            state = status.get("status", "unknown").lower()

            if state in terminal_states:
                return status

            time.sleep(poll_interval_s)


def main():
    """Trigger the DailyMe pipeline on OpenHands Cloud."""
    # Configuration
    repo = os.getenv("GITHUB_REPO", "rajshah4/dailyme")
    branch = os.getenv("GITHUB_BRANCH", "main")
    wait = "--wait" in sys.argv or "--poll" in sys.argv

    # Pipeline task (with environment setup instructions for the agent)
    task = """Run the DailyMe newsletter pipeline:

**Setup:**
1. The repository contains a `.env` file with DATABASE_URL, GMAIL_TOKEN_JSON, and LLM credentials
2. If `.env` doesn't exist, you'll need these environment variables:
   - DATABASE_URL: Connection to Neon Postgres
   - GMAIL_TOKEN_JSON: Gmail API token for fetching emails
   - LLM_MODEL: openhands/claude-sonnet-4-5-20250929 (or your preferred model)
   - LLM_API_KEY: Your OpenHands/LLM API key

**Execute:**
```bash
# Install dependencies
uv sync

# Run the pipeline
uv run python scripts/run_pipeline.py
```

**What it does:**
- Fetches new emails from Gmail with the "DailyMe" label (last 7 days)
- Parses newsletters into individual stories using LLM extraction
- Deduplicates stories across newsletters
- Writes results to the Neon Postgres database

**Expected runtime:** 5-15 minutes depending on the number of new newsletters

**Note:** All credentials should already be configured in the environment. If you encounter missing environment variables, check the repository's `.env` file or ask the user to provide them."""

    print(f"🚀 Triggering OpenHands Cloud pipeline for {repo}@{branch}")

    # Create conversation
    api = OpenHandsAPI()
    conv = api.create_conversation(
        initial_user_msg=task,
        repository=repo,
        selected_branch=branch,
    )

    conversation_id = conv.get("conversation_id")
    conversation_url = conv.get("url", f"{api.base_url}/conversations/{conversation_id}")

    print(f"✅ Pipeline started: {conversation_url}")
    print(f"📝 Conversation ID: {conversation_id}")

    if wait:
        print("\n⏳ Waiting for pipeline to complete...")
        try:
            final = api.poll_until_terminal(
                conversation_id,
                timeout_s=1800,  # 30 minutes max
                poll_interval_s=30,  # Check every 30 seconds
            )
            status = final.get("status", "unknown")
            print(f"\n✅ Pipeline {status}: {conversation_url}")

            if status == "completed":
                sys.exit(0)
            else:
                print(f"⚠️  Pipeline ended with status: {status}")
                sys.exit(1)

        except TimeoutError as e:
            print(f"\n⏱️  {e}")
            print(f"Check status at: {conversation_url}")
            sys.exit(1)
        except KeyboardInterrupt:
            print(f"\n⏸️  Interrupted. Pipeline continues at: {conversation_url}")
            sys.exit(0)
    else:
        print("\n💡 Pipeline running in background. Check progress at the URL above.")
        sys.exit(0)


if __name__ == "__main__":
    main()
