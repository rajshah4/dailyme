"""
Trigger OpenHands Cloud to run the DailyMe pipeline.

This script starts an OpenHands Cloud V1 app conversation that executes the
pipeline.
All heavy compute (Gmail fetching, LLM parsing, deduplication) happens in
OpenHands Cloud. This script just triggers it.

Usage:
    python scripts/openhands_trigger.py [--wait]

Environment variables:
    OPENHANDS_API_KEY: Your OpenHands Cloud API key
    OH_API_KEY: Alternate name for the same key
    GITHUB_REPO: Repository name (e.g., "rajshah4/dailyme")
    GITHUB_BRANCH: Branch name (default: "main")
"""

import os
import sys
import time
from typing import Any

import requests

DEFAULT_START_ATTEMPTS = 3
DEFAULT_START_BACKOFF_SECONDS = 5


class OpenHandsAPI:
    """Minimal OpenHands Cloud V1 app-conversation client."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or os.getenv("OPENHANDS_API_KEY") or os.getenv("OH_API_KEY")
        if not self.api_key:
            raise ValueError("OPENHANDS_API_KEY or OH_API_KEY not set")

        self.base_url = base_url or "https://app.all-hands.dev"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-Access-Token": self.api_key,
            "Content-Type": "application/json",
        }

    def create_conversation_start_task(
        self,
        initial_user_msg: str,
        repository: str,
        selected_branch: str = "main",
    ) -> dict[str, Any]:
        """Start a new OpenHands V1 app conversation."""
        payload = {
            "initial_message": {
                "role": "user",
                "content": [{"type": "text", "text": initial_user_msg}],
                "run": True,
            },
            "selected_repository": repository,
            "selected_branch": selected_branch,
        }

        response = requests.post(
            f"{self.base_url}/api/v1/app-conversations",
            headers=self.headers,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def get_start_task(self, task_id: str) -> dict[str, Any] | None:
        """Get the status of a V1 app conversation start task."""
        response = requests.get(
            f"{self.base_url}/api/v1/app-conversations/start-tasks",
            headers=self.headers,
            params={"ids": task_id},
            timeout=30,
        )
        response.raise_for_status()
        tasks = response.json()
        return tasks[0] if tasks else None

    def wait_for_start_task(
        self,
        task_id: str,
        timeout_s: int = 120,
        poll_interval_s: int = 2,
    ) -> dict[str, Any]:
        """Wait until the V1 start task yields an app conversation id."""
        start_time = time.time()

        while True:
            if time.time() - start_time > timeout_s:
                raise TimeoutError(f"Conversation did not start within {timeout_s}s")

            task = self.get_start_task(task_id)
            if not task:
                raise RuntimeError(f"Start task disappeared: {task_id}")

            state = str(task.get("status", "unknown")).upper()
            if state == "READY":
                return task
            if state == "ERROR":
                raise RuntimeError(task.get("detail") or "OpenHands conversation failed to start")

            time.sleep(poll_interval_s)

    def get_conversation_status(self, conversation_id: str) -> dict[str, Any] | None:
        """Get the status of a V1 app conversation."""
        response = requests.get(
            f"{self.base_url}/api/v1/app-conversations",
            headers=self.headers,
            params={"ids": conversation_id},
            timeout=30,
        )
        response.raise_for_status()
        conversations = response.json()
        return conversations[0] if conversations else None

    def poll_until_terminal(
        self,
        conversation_id: str,
        timeout_s: int = 1800,
        poll_interval_s: int = 30,
    ) -> dict[str, Any]:
        """
        Poll conversation until it reaches a terminal state.

        Terminal states are mapped from V1 execution_status.
        """
        start_time = time.time()

        while True:
            if time.time() - start_time > timeout_s:
                raise TimeoutError(f"Conversation did not complete within {timeout_s}s")

            status = self.get_conversation_status(conversation_id)
            if not status:
                raise RuntimeError(f"Conversation disappeared: {conversation_id}")

            state = str(status.get("execution_status", "unknown")).lower()
            sandbox_state = str(status.get("sandbox_status", "unknown")).lower()

            if sandbox_state == "error":
                raise RuntimeError(f"Conversation sandbox entered ERROR: {conversation_id}")

            if state in {"finished", "error", "stuck"}:
                return status

            time.sleep(poll_interval_s)


def _is_retryable_start_error(error: Exception) -> bool:
    """Retry transient OpenHands startup failures."""
    if isinstance(error, requests.HTTPError):
        response = error.response
        if response is not None and response.status_code >= 500:
            return True
    if isinstance(error, requests.RequestException):
        return True
    if isinstance(error, TimeoutError):
        return True
    if isinstance(error, RuntimeError):
        message = str(error).lower()
        return "500" in message or "timed out" in message or "start task disappeared" in message
    return False


def _start_pipeline_conversation(
    api: OpenHandsAPI,
    *,
    initial_user_msg: str,
    repository: str,
    selected_branch: str,
    max_attempts: int = DEFAULT_START_ATTEMPTS,
    backoff_seconds: int = DEFAULT_START_BACKOFF_SECONDS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create an OpenHands conversation with retries for transient startup failures."""
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            start_task = api.create_conversation_start_task(
                initial_user_msg=initial_user_msg,
                repository=repository,
                selected_branch=selected_branch,
            )
            task_id = start_task.get("id")
            if not task_id:
                raise RuntimeError("OpenHands V1 start task returned no id")

            ready_task = api.wait_for_start_task(task_id)
            conversation_id = ready_task.get("app_conversation_id")
            if not conversation_id:
                raise RuntimeError("OpenHands V1 start task returned no app_conversation_id")
            return start_task, ready_task
        except Exception as exc:
            last_error = exc
            if attempt >= max_attempts or not _is_retryable_start_error(exc):
                raise

            print(
                f"⚠️  OpenHands startup attempt {attempt}/{max_attempts} failed: {exc}",
                file=sys.stderr,
            )
            print(
                f"🔁 Retrying in {backoff_seconds * attempt}s...",
                file=sys.stderr,
            )
            time.sleep(backoff_seconds * attempt)

    raise RuntimeError(f"OpenHands conversation failed to start: {last_error}")


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
   - OH_API_KEY: Your OpenHands Cloud API key
   - OPENHANDS_API_KEY: Alternate name for the same key

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
    _start_task, ready_task = _start_pipeline_conversation(
        api,
        initial_user_msg=task,
        repository=repo,
        selected_branch=branch,
    )
    conversation_id = ready_task.get("app_conversation_id")

    conversation = api.get_conversation_status(conversation_id) or {}
    conversation_url = conversation.get("conversation_url", f"{api.base_url}/conversations/{conversation_id}")

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
            status = final.get("execution_status", "unknown")
            print(f"\n✅ Pipeline {status}: {conversation_url}")

            if status == "finished":
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
