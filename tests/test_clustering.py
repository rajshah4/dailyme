"""Tests for topic clustering."""

from app.processing.clustering import assign_topic, get_topic_display_name


class TestAssignTopic:
    def test_ai_agents(self):
        assert assign_topic("New agentic framework for tool use") == "ai_agents"

    def test_llm_models(self):
        assert assign_topic("Claude 4 released by Anthropic") == "llm_models"

    def test_infrastructure(self):
        assert assign_topic("GPU inference optimization with TensorRT") == "infrastructure"

    def test_research(self):
        assert assign_topic("New arxiv paper on training techniques") == "research"

    def test_funding(self):
        assert assign_topic("AI startup raised $100M Series B") == "funding"

    def test_open_source(self):
        assert assign_topic("New open source library released on GitHub") == "open_source"

    def test_other(self):
        assert assign_topic("Random unrelated news about cooking") == "other"

    def test_uses_summary_too(self):
        topic = assign_topic("Big announcement", "OpenAI released a new GPT model today")
        assert topic == "llm_models"


class TestGetTopicDisplayName:
    def test_known_topics(self):
        assert "Agent" in get_topic_display_name("ai_agents")
        assert "LLM" in get_topic_display_name("llm_models")

    def test_unknown_topic(self):
        result = get_topic_display_name("something_new")
        assert result == "Something New"
