"""Tests for newsletter story segmentation."""

from app.processing.segmenter import segment_newsletter, _is_story_link


class TestSegmentNewsletter:
    def test_extracts_stories_from_heading_blocks(self):
        html = """
        <html><body>
        <h2>OpenAI Releases GPT-5</h2>
        <p>OpenAI announced GPT-5 today with major improvements.
        <a href="https://openai.com/gpt5">Read more</a></p>

        <h2>Google Launches New Quantum Chip</h2>
        <p>Google's new quantum processor achieves breakthrough.
        <a href="https://google.com/quantum">Details here</a></p>

        <h2>Meta Open Sources New LLM</h2>
        <p>Meta released Llama 4 under MIT license.
        <a href="https://meta.com/llama4">GitHub repo</a></p>
        </body></html>
        """
        stories = segment_newsletter(html)
        assert len(stories) >= 2
        titles = [s.title for s in stories]
        assert any("GPT-5" in t for t in titles)

    def test_extracts_links(self):
        html = """
        <html><body>
        <h2><a href="https://openai.com/gpt5">OpenAI Releases GPT-5</a></h2>
        <p>Major announcement from OpenAI about their latest model.</p>

        <h2>Another Story About AI</h2>
        <p>More details here. <a href="https://example.com/ai">Link</a></p>
        </body></html>
        """
        stories = segment_newsletter(html)
        urls = [s.url for s in stories if s.url]
        assert len(urls) >= 1

    def test_empty_html(self):
        stories = segment_newsletter("")
        assert stories == []

    def test_minimal_content(self):
        html = "<html><body><p>Just a short paragraph.</p></body></html>"
        stories = segment_newsletter(html)
        # Should return few/no stories — below threshold
        assert len(stories) < 2


class TestIsStoryLink:
    def test_valid_story_link(self):
        assert _is_story_link("https://techcrunch.com/article/123")

    def test_rejects_unsubscribe(self):
        assert not _is_story_link("https://example.com/unsubscribe")

    def test_rejects_twitter_share(self):
        assert not _is_story_link("https://twitter.com/intent/tweet?text=hi")

    def test_rejects_mailto(self):
        assert not _is_story_link("mailto:test@example.com")

    def test_rejects_mailchimp(self):
        assert not _is_story_link("https://list-manage.com/track/click")
