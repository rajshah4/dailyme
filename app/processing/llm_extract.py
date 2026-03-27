"""LLM-powered newsletter story extraction via OpenHands V1 conversations.

This uses the OpenHands V1 app-conversation API rather than the deprecated
V0 conversation/LLM completion flow. Each extraction creates a short-lived
conversation, waits for the agent to finish, reads the final assistant
message from conversation events, and then deletes the sandbox.

Configuration (via environment or .env):
  LLM_MODEL                     — e.g. "openhands/claude-sonnet-4-5-20250929"
  LLM_API_KEY                   — OpenHands Cloud API key
  OPENHANDS_BASE_URL            — optional app server base URL
  OPENHANDS_SELECTED_REPOSITORY — optional repo context for the conversation
  OPENHANDS_SELECTED_BRANCH     — optional branch when repo context is used
"""

import asyncio
import json
import logging
import os
import time
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from app.schemas import ParsedStory

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """\
You are extracting every individual news story from an email newsletter.

Extract ALL distinct stories — every item the newsletter covers, no matter how brief.

Rules:
1. Each distinct news item is a separate story. If the newsletter mentions 30 things,
   return 30 stories.
2. Use the actual story headline, NOT the section header.
   "AI Twitter Recap" is a section heading, not a story; extract the individual stories within it.
3. Titles should be concise (under 100 chars). Use the newsletter's own headline when available.
4. Summaries: 1-2 sentences capturing the key point. Don't repeat the title.
5. URL: use the EXACT URL from the newsletter text. Do NOT reconstruct or guess URLs.
   Copy the URL verbatim, even if it's a redirect/tracking URL. We resolve redirects later.
   Only omit if there is truly no URL at all.
6. Tags: assign 1-2 from this list:
   long_form, research, launch, funding, vendor, podcast, tutorial, benchmark, opinion
7. SKIP only these: ads, sponsors, job listings, "share this newsletter", subscribe CTAs,
   referral promos, social media follow links, unsubscribe footers, author bios.
8. For single-article newsletters (one long post, not a multi-story digest),
   return exactly 1 story with tag "long_form".

Return a JSON array only, no markdown fences:
[
  {{
    "title": "Story headline",
    "summary": "1-2 sentence summary",
    "url": "https://...",
    "tags": ["research"]
  }}
]

Newsletter subject: {subject}
Newsletter from: {from_address}

Newsletter content:
{content}
"""

MAX_CONTENT_LENGTH = 40000  # Reduced to handle large newsletters without timing out

DEFAULT_OPENHANDS_BASE_URL = "https://app.all-hands.dev"
DEFAULT_START_TIMEOUT_SECONDS = 120
DEFAULT_RUN_TIMEOUT_SECONDS = 180
DEFAULT_POLL_INTERVAL_SECONDS = 2.0

_client = None


class OpenHandsV1Client:
    """Minimal client for one-shot V1 app conversations."""
    def __init__(self) -> None:
        load_dotenv(".env")
        self.api_key = (
            os.getenv("OPENHANDS_API_KEY")
            or os.getenv("OH_API_KEY")
            or os.getenv("LLM_API_KEY")
        )
        self.base_url = (
            os.getenv("OPENHANDS_BASE_URL")
            or os.getenv("LLM_BASE_URL")
            or DEFAULT_OPENHANDS_BASE_URL
        ).rstrip("/")
        self.model = os.getenv("LLM_MODEL")
        self.selected_repository = os.getenv("OPENHANDS_SELECTED_REPOSITORY")
        self.selected_branch = os.getenv("OPENHANDS_SELECTED_BRANCH")
        self.start_timeout_seconds = int(
            os.getenv("OPENHANDS_START_TIMEOUT", DEFAULT_START_TIMEOUT_SECONDS)
        )
        self.run_timeout_seconds = int(
            os.getenv("OPENHANDS_RUN_TIMEOUT", DEFAULT_RUN_TIMEOUT_SECONDS)
        )
        self.poll_interval_seconds = float(
            os.getenv("OPENHANDS_POLL_INTERVAL", DEFAULT_POLL_INTERVAL_SECONDS)
        )
        self.request_timeout_seconds = max(
            self.start_timeout_seconds,
            self.run_timeout_seconds,
            30,
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self, *, session_api_key: str | None = None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            headers["X-Access-Token"] = self.api_key
        if session_api_key:
            headers["X-Session-API-Key"] = session_api_key
        return headers

    async def extract_json(self, prompt: str) -> str:
        sandbox_id = None
        conversation_id = None
        conversation_url = None
        session_api_key = None
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._headers(),
            timeout=self.request_timeout_seconds,
            follow_redirects=True,
        ) as client:
            try:
                start_task = await self._start_conversation(client, prompt)
                sandbox_id = start_task.get("sandbox_id")
                conversation_id = start_task.get("app_conversation_id")
                if not conversation_id:
                    raise RuntimeError("OpenHands start task completed without a conversation id")

                conversation = await self._wait_for_conversation(client, conversation_id)
                conversation_url = conversation.get("conversation_url")
                session_api_key = conversation.get("session_api_key")
                events = await self._fetch_message_events(
                    client,
                    conversation_id,
                    conversation_url=conversation_url,
                    session_api_key=session_api_key,
                )
                response = _extract_agent_text_from_events(events)
                if not response:
                    raise RuntimeError("OpenHands returned no assistant response")
                return response
            finally:
                if sandbox_id:
                    await self._delete_sandbox(client, sandbox_id)

    async def _start_conversation(
        self,
        client: httpx.AsyncClient,
        prompt: str,
    ) -> dict:
        payload: dict[str, object] = {
            "initial_message": {
                "role": "user",
                "content": [{"type": "text", "text": prompt}],
                "run": True,
            },
        }
        if self.selected_repository:
            payload["selected_repository"] = self.selected_repository
        if self.selected_branch:
            payload["selected_branch"] = self.selected_branch

        response = await client.post("/api/v1/app-conversations", json=payload)
        response.raise_for_status()
        start_task = response.json()
        task_id = start_task["id"]

        deadline = time.monotonic() + self.start_timeout_seconds
        while time.monotonic() < deadline:
            task_response = await client.get(
                "/api/v1/app-conversations/start-tasks",
                params={"ids": task_id},
            )
            task_response.raise_for_status()
            tasks = task_response.json()
            task = tasks[0] if tasks else None
            if not task:
                raise RuntimeError(f"OpenHands start task disappeared: {task_id}")

            status = task.get("status")
            if status == "READY":
                return task
            if status == "ERROR":
                raise RuntimeError(
                    task.get("detail") or "OpenHands conversation failed to start"
                )

            await asyncio.sleep(self.poll_interval_seconds)

        raise TimeoutError("Timed out waiting for OpenHands conversation start after "
                           f"{self.start_timeout_seconds}s")

    async def _wait_for_conversation(
        self,
        client: httpx.AsyncClient,
        conversation_id: str,
    ) -> dict:
        deadline = time.monotonic() + self.run_timeout_seconds
        while time.monotonic() < deadline:
            response = await client.get(
                "/api/v1/app-conversations",
                params={"ids": conversation_id},
            )
            response.raise_for_status()
            conversations = response.json()
            conversation = conversations[0] if conversations else None
            if not conversation:
                raise RuntimeError(f"OpenHands conversation disappeared: {conversation_id}")

            sandbox_status = conversation.get("sandbox_status")
            execution_status = conversation.get("execution_status")
            if sandbox_status == "ERROR":
                raise RuntimeError("OpenHands sandbox entered ERROR state")
            if execution_status == "finished":
                return conversation
            if execution_status in {"error", "stuck"}:
                raise RuntimeError(f"OpenHands conversation ended with status={execution_status}")

            await asyncio.sleep(self.poll_interval_seconds)

        raise TimeoutError(
            f"Timed out waiting for OpenHands conversation run after {self.run_timeout_seconds}s"
        )

    async def _fetch_message_events(
        self,
        client: httpx.AsyncClient,
        conversation_id: str,
        *,
        conversation_url: str | None,
        session_api_key: str | None,
    ) -> list[dict]:
        if conversation_url and session_api_key:
            return await self._fetch_agent_server_events(
                client,
                conversation_url,
                conversation_id,
                session_api_key,
            )

        response = await client.get(
            f"/api/v1/conversation/{conversation_id}/events/search",
            params={"kind__eq": "MessageEvent", "limit": 100, "sort_order": "TIMESTAMP"},
        )
        response.raise_for_status()
        return response.json().get("items", [])

    async def _fetch_agent_server_events(
        self,
        client: httpx.AsyncClient,
        conversation_url: str,
        conversation_id: str,
        session_api_key: str,
    ) -> list[dict]:
        agent_base_url = conversation_url.split("/api/conversations/")[0].rstrip("/")
        url = (
            f"{agent_base_url}/api/conversations/{conversation_id}/events/search?"
            + urlencode({"limit": 100})
        )
        response = await client.get(
            url,
            headers=self._headers(session_api_key=session_api_key),
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("items", payload.get("events", []))

    async def _delete_sandbox(self, client: httpx.AsyncClient, sandbox_id: str) -> None:
        try:
            response = await client.delete(f"/api/v1/sandboxes/{sandbox_id}")
            if response.status_code not in {200, 204, 404, 422}:
                response.raise_for_status()
        except Exception as exc:
            logger.warning("Failed to delete OpenHands sandbox %s: %s", sandbox_id, exc)


def _get_client() -> OpenHandsV1Client | None:
    global _client
    if _client is None:
        candidate = OpenHandsV1Client()
        if not candidate.is_configured:
            return None
        _client = candidate
        logger.info(
            "Initialized OpenHands V1 client: base_url=%s model=%s repo=%s",
            candidate.base_url,
            candidate.model,
            candidate.selected_repository,
        )
    return _client


def _extract_agent_text_from_events(events: list[dict]) -> str | None:
    latest_text = None
    for event in events:
        if event.get("kind") != "MessageEvent":
            continue
        if event.get("source") != "agent":
            continue

        llm_message = event.get("llm_message") or {}
        if llm_message.get("role") != "assistant":
            continue

        parts = []
        for content in llm_message.get("content") or []:
            if content.get("type") == "text" and content.get("text"):
                parts.append(content["text"])
        if parts:
            latest_text = "\n".join(parts).strip()
    return latest_text


def is_configured() -> bool:
    """Check if LLM extraction is available."""
    return _get_client() is not None


async def extract_stories(
    html: str,
    subject: str | None = None,
    from_address: str | None = None,
) -> list[ParsedStory] | None:
    """Extract stories from newsletter HTML using the OpenHands LLM.

    Returns list of ParsedStory on success, None if LLM is not available
    or extraction fails (caller falls back to heuristics).
    """
    client = _get_client()
    if client is None:
        return None

    content = _html_to_readable(html)
    if len(content) > MAX_CONTENT_LENGTH:
        content = content[:MAX_CONTENT_LENGTH] + "\n\n[... content truncated ...]"

    prompt = EXTRACTION_PROMPT.format(
        subject=subject or "Unknown",
        from_address=from_address or "Unknown",
        content=content,
    )

    try:
        logger.info(
            "  Calling OpenHands V1 conversation API (%s) for story extraction...",
            client.model or "default",
        )
        raw = _extract_json_array(await client.extract_json(prompt))

        stories_data = json.loads(raw)
        if not isinstance(stories_data, list):
            logger.warning("  LLM returned non-list: %s", type(stories_data))
            return None

        stories = []
        for i, item in enumerate(stories_data):
            if not isinstance(item, dict) or not item.get("title"):
                continue
            stories.append(ParsedStory(
                title=item["title"][:200],
                summary=item.get("summary"),
                url=item.get("url"),
                tags=item.get("tags", []),
                position=i,
            ))

        logger.info("  LLM extracted %d stories", len(stories))
        return stories

    except json.JSONDecodeError as e:
        logger.warning("  LLM returned invalid JSON: %s", e)
        return None
    except Exception as e:
        logger.warning("  LLM extraction failed: %s", e)
        return None


def _strip_markdown_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
    return raw


def _extract_json_array(raw: str) -> str:
    """Extract the JSON array from a potentially noisy LLM response.

    Handles: markdown fences, trailing explanation text, leading preamble.
    Falls back to the original string if no array bracket is found.
    """
    raw = _strip_markdown_fences(raw)
    start = raw.find("[")
    if start == -1:
        return raw
    # Walk from the end to find the matching closing bracket
    depth = 0
    end = -1
    in_str = False
    escape_next = False
    for i, ch in enumerate(raw[start:], start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_str:
            escape_next = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        return raw
    return raw[start : end + 1]


_BLOCK_TAGS = {
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "li",
    "blockquote",
    "div",
    "td",
    "tr",
    "section",
    "article",
}


def _html_to_readable(html: str) -> str:
    """Convert HTML to readable text preserving structure for the LLM.

    Only extracts "leaf" block elements (those without nested block children)
    to avoid duplicating content from container elements. Preserves headings,
    bold text, and links.
    """
    soup = BeautifulSoup(html, "lxml")

    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()

    lines = []
    for element in soup.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "td"]
    ):
        # Skip container elements that have block-level children —
        # we'll extract the children individually
        if element.find(_BLOCK_TAGS):
            continue

        text = element.get_text(" ", strip=True)
        if not text or len(text) < 3:
            continue

        prefix = ""
        if element.name in ["h1", "h2"]:
            prefix = "## "
        elif element.name in ["h3", "h4", "h5", "h6"]:
            prefix = "### "
        elif element.name == "li":
            prefix = "- "
        elif element.name == "blockquote":
            prefix = "> "

        # Preserve bold markers
        for b in element.find_all(["strong", "b"]):
            b_text = b.get_text(strip=True)
            if b_text and len(b_text) > 5:
                text = text.replace(b_text, f"**{b_text}**", 1)

        # Append links inline — include redirect URLs, we resolve them later
        link_strs = []
        for a in element.find_all("a", href=True):
            href = a["href"]
            if (
                href.startswith("http")
                and "unsubscribe" not in href.lower()
            ):
                link_strs.append(href)
        link_suffix = f" [{', '.join(link_strs[:3])}]" if link_strs else ""

        lines.append(f"{prefix}{text}{link_suffix}")

    return "\n".join(lines)
