from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
from xml.etree import ElementTree as ET

from app.main import _build_rss_xml


def test_build_rss_xml_generates_channel_and_items():
    story_id = uuid4()
    stories = [
        SimpleNamespace(
            story_group_id=story_id,
            title="OpenAI ships new model",
            summary="A concise summary",
            url="https://example.com/story",
            first_seen_at=datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
            tags=["launch", "research"],
        )
    ]

    xml = _build_rss_xml(
        stories,
        "https://dailyme.example",
        tag="research",
        starred=True,
        now=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
    )

    root = ET.fromstring(xml)
    assert root.tag == "rss"

    channel = root.find("channel")
    assert channel is not None
    assert channel.findtext("title") == "DailyMe News Feed (Starred) — research"

    items = channel.findall("item")
    assert len(items) == 1
    assert items[0].findtext("title") == "OpenAI ships new model"
    assert items[0].findtext("link") == "https://example.com/story"
    assert items[0].findtext("guid") == str(story_id)

    categories = [c.text for c in items[0].findall("category")]
    assert categories == ["launch", "research"]


def test_build_rss_xml_falls_back_to_base_url_and_empty_description():
    stories = [
        SimpleNamespace(
            story_group_id=uuid4(),
            title="No URL story",
            summary=None,
            url=None,
            first_seen_at=None,
            tags=[],
        )
    ]

    xml = _build_rss_xml(
        stories,
        "https://dailyme.example",
        now=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
    )

    channel = ET.fromstring(xml).find("channel")
    assert channel is not None

    item = channel.find("item")
    assert item is not None
    assert item.findtext("link") == "https://dailyme.example"
    assert item.findtext("description") == ""
