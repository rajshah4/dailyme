"""Topic clustering: assign stories to topics.

MVP: keyword-based matching.
Week 2: embedding-based clustering (DBSCAN).
"""

import logging
import re

logger = logging.getLogger(__name__)

# Predefined topic keywords — ordered by specificity
TOPIC_KEYWORDS: dict[str, list[str]] = {
    "ai_agents": [
        "agent", "agentic", "tool use", "function calling",
        "mcp", "model context protocol", "autonomous",
        "openhands", "devin", "cursor", "copilot agent",
    ],
    "llm_models": [
        "gpt", "claude", "llama", "gemini", "mistral", "phi",
        "model release", "foundation model", "language model",
        "chatgpt", "openai", "anthropic", "meta ai",
    ],
    "infrastructure": [
        "gpu", "cuda", "inference", "serving", "performance",
        "latency", "throughput", "optimization", "quantization",
        "tpu", "triton", "vllm", "tensorrt",
    ],
    "enterprise_ai": [
        "enterprise", "deployment", "production", "compliance",
        "governance", "responsible ai", "safety", "alignment",
        "regulation", "policy",
    ],
    "research": [
        "paper", "arxiv", "benchmark", "dataset", "training",
        "preprint", "study", "researcher", "findings",
        "breakthrough", "state of the art", "sota",
    ],
    "funding": [
        "raised", "funding", "valuation", "series a", "series b",
        "series c", "ipo", "acquisition", "acquired", "investment",
        "venture", "unicorn",
    ],
    "open_source": [
        "open source", "github", "release", "library",
        "framework", "repository", "community", "contributor",
        "mit license", "apache",
    ],
    "coding": [
        "coding", "programming", "developer", "software",
        "ide", "code generation", "refactor",
    ],
}


def assign_topic(title: str, summary: str | None = None) -> str:
    """Assign a topic label based on keyword matching.

    Returns the topic with the highest match count, or 'other'.
    """
    text = (title + " " + (summary or "")).lower()

    scores: dict[str, int] = {}
    for topic, keywords in TOPIC_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw in text:
                score += 1
        if score > 0:
            scores[topic] = score

    if not scores:
        return "other"

    return max(scores, key=scores.get)


def get_topic_display_name(topic_key: str) -> str:
    """Convert topic key to a display-friendly name."""
    display_names = {
        "ai_agents": "🤖 AI Agents",
        "llm_models": "🧠 LLM Models",
        "infrastructure": "⚡ Infrastructure",
        "enterprise_ai": "🏢 Enterprise AI",
        "research": "📄 Research",
        "funding": "💰 Funding",
        "open_source": "📦 Open Source",
        "coding": "💻 Coding",
        "other": "📰 Other",
    }
    return display_names.get(topic_key, topic_key.replace("_", " ").title())
