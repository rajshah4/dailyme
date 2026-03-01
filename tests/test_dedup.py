"""Tests for URL canonicalization and deduplication."""

from app.processing.dedup import canonicalize_url, find_duplicate, title_jaccard_similarity


class TestCanonicalizeUrl:
    def test_strips_utm_params(self):
        url = "https://techcrunch.com/article/?utm_source=tldr&utm_medium=email"
        assert canonicalize_url(url) == "https://techcrunch.com/article"

    def test_removes_www(self):
        url = "https://www.example.com/page"
        assert canonicalize_url(url) == "https://example.com/page"

    def test_removes_trailing_slash(self):
        url = "https://example.com/page/"
        assert canonicalize_url(url) == "https://example.com/page"

    def test_lowercases_host(self):
        url = "https://TechCrunch.COM/Article"
        assert canonicalize_url(url) == "https://techcrunch.com/Article"

    def test_preserves_non_tracking_params(self):
        url = "https://example.com/search?q=openai&page=2"
        result = canonicalize_url(url)
        assert "q=openai" in result
        assert "page=2" in result

    def test_none_input(self):
        assert canonicalize_url(None) is None

    def test_empty_string(self):
        assert canonicalize_url("") is None

    def test_strips_fbclid(self):
        url = "https://example.com/post?fbclid=abc123"
        assert canonicalize_url(url) == "https://example.com/post"


class TestTitleJaccardSimilarity:
    def test_identical_titles(self):
        sim = title_jaccard_similarity("OpenAI releases GPT-5", "OpenAI releases GPT-5")
        assert sim == 1.0

    def test_similar_titles(self):
        sim = title_jaccard_similarity(
            "OpenAI Releases GPT-5",
            "GPT-5 Released by OpenAI",
        )
        # After stop word removal: {"openai", "releases", "gpt5"} vs {"gpt5", "released", "openai"}
        # Jaccard = 2/4 = 0.5 (releases ≠ released)
        assert sim >= 0.4

    def test_different_titles(self):
        sim = title_jaccard_similarity(
            "OpenAI Releases GPT-5",
            "Google launches new quantum computer",
        )
        assert sim < 0.3

    def test_empty_title(self):
        sim = title_jaccard_similarity("", "Some title")
        assert sim == 0.0


class TestFindDuplicate:
    def test_exact_url_match(self):
        existing = [
            {"story_group_id": "abc", "url_canonical": "https://example.com/story", "title": "Story A"},
        ]
        result = find_duplicate("https://example.com/story", "Different Title", existing)
        assert result == "abc"

    def test_title_similarity_match(self):
        # Use titles with higher word overlap (Jaccard > 0.6 threshold)
        existing = [
            {"story_group_id": "abc", "url_canonical": "https://other.com/x", "title": "OpenAI Releases GPT-5 Model"},
        ]
        result = find_duplicate("https://example.com/y", "OpenAI Releases GPT-5 Model Today", existing)
        assert result == "abc"

    def test_no_match(self):
        existing = [
            {"story_group_id": "abc", "url_canonical": "https://other.com/x", "title": "Totally different story"},
        ]
        result = find_duplicate("https://example.com/y", "Google launches quantum", existing)
        assert result is None

    def test_empty_existing(self):
        result = find_duplicate("https://example.com/y", "Some title", [])
        assert result is None
