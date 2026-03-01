---
name: newsletter-parser
description: Parse email newsletters into individual stories. Use when structural/heuristic parsing fails and LLM extraction is needed.
triggers:
- parse
- newsletter
- segment
- extract stories
---

# Newsletter Parser Skill

You are parsing an email newsletter into individual news stories. The heuristic parser has already been tried and produced insufficient results (<2 stories). You need to use your language understanding to extract stories.

## Input Format

You will receive the cleaned HTML or text content of a newsletter email.

## Output Format

Return a JSON array of stories. Each story must have:

```json
[
  {
    "title": "Story headline",
    "summary": "1-2 sentence summary of the story",
    "url": "https://link-to-source-article.com",
    "author": "Author name if mentioned (optional)"
  }
]
```

## Parsing Guidelines

1. **Each distinct news item is a separate story.** A newsletter about "5 AI announcements" should produce 5 stories, not 1.
2. **Titles should be concise** (under 100 characters). Use the newsletter's own headline if available.
3. **Summaries should capture the key point** in 1-2 sentences. Don't just repeat the title.
4. **URLs must be the link to the original source**, not the newsletter's tracking link. If only a tracking link is available, use it — the pipeline will try to resolve it.
5. **Skip** ads, sponsor sections, job listings, event promotions, and "share this newsletter" content.
6. **Skip** the newsletter header/branding and footer/unsubscribe sections.

## Platform-Specific: Substack

Most newsletters come via Substack. Key patterns:

### URL Resolution
Substack emails contain tracking URLs that should be resolved to clean direct links:
- **Direct URL**: `https://{author}.substack.com/p/{slug}` — best, use this
- **Open URL**: `https://open.substack.com/pub/{author}/p/{slug}` — convert to direct
- **App-link**: `https://substack.com/app-link/post?publication_id=X&post_id=Y` — deep link, avoid
- **Redirect**: `https://substack.com/redirect/...` — opaque without HTTP, keep as fallback

The module `app/processing/substack.py` handles all URL resolution automatically.

### Single-Article vs Multi-Story
- **Single-article** (e.g., Alex Chao, ML at Scale): One long post with section headings (Introduction, Methods, etc.). Should be collapsed to 1 `long_form` story.
- **Multi-story digest** (e.g., AINews, TLDR): Multiple items under headings. Should produce 10-15 stories.
- Detection heuristic: if first story title matches email subject and most sections have no URLs or generic section headings, it's single-article.

### Junk Sections to Filter
- "Subscribe to X to unlock the rest" (paywall)
- "Become a paying subscriber" (paywall CTA)
- "Invite your friends and earn rewards" (referral)
- "A subscription gets you:" (promo)

## Known Newsletter Formats

### AINews (swyx)
- Lead story is the email subject, followed by commentary
- "AI Twitter Recap", "AI Reddit Recap", "AI Discord Recap" sections
- Sub-stories numbered: "1. Topic", "2. Topic", "3. Topic"
- Redirect URLs point to external sources (Twitter, Reddit, etc.)
- Typically 12-15 stories

### TLDR AI / TLDR Tech
- Stories are grouped under headings like "Headlines & Launches", "Research & Innovation", "Engineering & Resources"
- Each story has a bold title, 2-3 sentence summary, and a link
- Typically 10-15 stories per email

### The Batch (Andrew Ng / DeepLearning.AI)
- Lead story with longer analysis
- "News" section with shorter items
- "Research" section with paper highlights
- Typically 5-8 stories

### Ben's Bites
- Conversational style, stories woven into narrative
- Look for bold text and inline links as story boundaries
- Typically 5-10 stories

### Import AI
- Longer analysis pieces mixed with shorter items
- Often has "Things that caught my eye" section
- Links embedded in prose

### The Neuron
- Clear section headers with story blocks
- Each story has headline + 1-2 paragraph summary
- Typically 5-8 stories

## Error Handling

- If the newsletter is just a single long article (not a multi-story digest), return it as 1 story with the subject line as the title.
- If the content is garbled or mostly images, return an empty array `[]` and note the issue.

## After Extraction

After extracting stories, write the JSON result to stdout so the pipeline can capture it. The calling code in `scripts/run_pipeline.py` will handle storing the results in the database.
