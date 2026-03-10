"""Tests for OpenHands V1 extraction helpers."""

from app.processing.llm_extract import _extract_agent_text_from_events, _strip_markdown_fences


def test_extract_agent_text_from_latest_agent_message():
    events = [
        {
            "kind": "MessageEvent",
            "source": "user",
            "llm_message": {"role": "user", "content": [{"type": "text", "text": "prompt"}]},
        },
        {
            "kind": "MessageEvent",
            "source": "agent",
            "llm_message": {
                "role": "assistant",
                "content": [{"type": "text", "text": '[{"title":"Older"}]'}],
            },
        },
        {
            "kind": "MessageEvent",
            "source": "agent",
            "llm_message": {
                "role": "assistant",
                "content": [{"type": "text", "text": '[{"title":"Newest"}]'}],
            },
        },
    ]

    assert _extract_agent_text_from_events(events) == '[{"title":"Newest"}]'


def test_extract_agent_text_joins_text_parts_only():
    events = [
        {
            "kind": "MessageEvent",
            "source": "agent",
            "llm_message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "["},
                    {"type": "image", "image_url": "ignored"},
                    {"type": "text", "text": '{"title":"Story"}]'},
                ],
            },
        }
    ]

    assert _extract_agent_text_from_events(events) == '[\n{"title":"Story"}]'


def test_strip_markdown_fences_handles_json_block():
    raw = """```json
    [{"title":"Story"}]
    ```"""

    assert _strip_markdown_fences(raw) == '[{"title":"Story"}]'
