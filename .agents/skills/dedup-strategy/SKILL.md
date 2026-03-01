---
name: dedup-strategy
description: Deduplication strategy for identifying when multiple newsletters cover the same story. Use when reviewing or improving dedup logic.
triggers:
- dedup
- duplicate
- merge
- same story
---

# DailyMe Dedup Strategy

## The Problem

Multiple AI newsletters often cover the same story. "TLDR AI", "The Batch", and "Ben's Bites" might all report on the same GPT-5 announcement. We want to group these into one story with attribution to all sources.

## How Dedup Works (4 layers)

### Layer 1 — URL Canonicalization
Strip tracking parameters and normalize:
- Remove: `utm_*`, `ref`, `source`, `campaign`, `mc_*`, `fbclid`, `gclid`
- Remove `www.` prefix
- Remove trailing slashes
- Lowercase scheme and host

Example: `https://www.techcrunch.com/article/?utm_source=tldr` → `techcrunch.com/article`

Code: `app/processing/dedup.py::canonicalize_url()`

### Layer 2 — Exact URL Match
If two stories have the same canonical URL → they're duplicates.

### Layer 3 — Title Jaccard Similarity
- Normalize: lowercase, strip punctuation, remove stop words
- Compute Jaccard similarity of word sets
- Threshold: > 0.6 = duplicate

Example: "OpenAI Releases GPT-5" vs "GPT-5 Released by OpenAI" → Jaccard ≈ 0.75 → duplicate

### Layer 4 — Embedding Cosine Similarity (Week 2)
- Uses `sentence-transformers/all-MiniLM-L6-v2` (384-dim, local)
- Threshold: > 0.85 = duplicate
- Catches semantic duplicates that differ in wording

## Key Principles

1. **Be conservative** — It's better to show a duplicate than to merge two different stories.
2. **Group, don't delete** — Duplicates are grouped in `story_groups`, not removed. The user can see "covered by 3 newsletters."
3. **Pick the best canonical** — The story with the longest summary (or earliest time) becomes the group's canonical story.
4. **Preserve attribution** — Every story keeps its `newsletter_id` so we can show "via TLDR AI, The Batch, Ben's Bites."

## When to Adjust Thresholds

- Too many false positives (different stories merged): **Raise** Jaccard threshold to 0.7+ or cosine to 0.90+
- Too many false negatives (same story not caught): **Lower** Jaccard to 0.5 or cosine to 0.80
- Check by querying: `SELECT sg.title, sg.story_count FROM story_groups sg WHERE sg.story_count > 1 ORDER BY sg.story_count DESC`
