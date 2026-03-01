# DailyMe — Personalized AI News from Newsletters

## Project Plan v1.0

---

## 1. Scope, Non-Goals & Success Metrics

### What We're Building

A demo system that:

1. **Ingests** forwarded email newsletters via a dedicated inbox.
2. **Parses** each newsletter into individual stories (headline, summary, source attribution, link).
3. **Deduplicates** stories that appear in multiple newsletters.
4. **Clusters** stories into topics.
5. **Ranks** stories based on user-defined interests and explicit feedback.
6. **Serves** two outputs:
   - A **web front page** — a simple, clean, ranked feed of today's stories.
   - A **daily email digest** — a formatted summary sent once per day.

The system runs as a **long-lived cloud agent job** with periodic scheduling, demonstrating how OpenHands coding agents can build and operate a continuously-running system.

### Non-Goals (MVP)

- No mobile app or native clients.
- No multi-user auth system (single-user demo; one inbox, one feed).
- No real-time push/websocket updates (polling/cron is fine).
- No full-text search (stretch goal).
- No payment or subscription management.
- No scraping of newsletter source websites (we only use what's in the email body).
- No fine-tuned ML models — heuristics and embeddings only.

### Success Metrics

| Metric | Target (MVP) |
|--------|-------------|
| Newsletters parsed without errors | ≥ 90% of forwarded emails |
| Stories correctly segmented per newsletter | ≥ 80% precision (spot-checked) |
| Duplicate stories identified | ≥ 70% recall on known duplicates |
| Front page loads | < 2s TTFB |
| Daily digest delivered | Every day by 8 AM user-local time |
| End-to-end latency (email received → story visible) | < 5 minutes |
| Demo-ready | Can forward 5 newsletters, open front page, see deduplicated ranked feed |

---

## 2. Phased Roadmap

### Week 1 — MVP (Core Loop)

| Day | Milestone |
|-----|-----------|
| 1 | Repo setup, schema design, email ingestion (Gmail API + polling) |
| 2 | Newsletter HTML parsing → clean text + story segmentation |
| 3 | URL canonicalization + basic dedup (exact URL + title similarity) |
| 4 | Simple ranking (static interest weights) + front page (server-rendered HTML) |
| 5 | Daily digest email (SendGrid) + cron scheduling + deploy to Railway/Fly.io |

**MVP deliverable:** Forward 5 newsletters → see ranked, deduped front page + receive digest email.

### Week 2 — Improvements

| Day | Milestone |
|-----|-----------|
| 6 | Thumbs up/down feedback UI + re-ranking based on feedback |
| 7 | Topic clustering (embedding-based) + topic labels on front page |
| 8 | "Hide topic" action + improved dedup with cosine similarity |
| 9 | Newsletter attribution UI (see which newsletters covered each story) |
| 10 | Error monitoring, retry logic, parsing edge-case fixes |

### Stretch Goals (Week 3+)

- Full-text search over story archive.
- AI-generated one-paragraph summary per topic cluster.
- Multi-user support with auth (Clerk or simple magic link).
- GitHub repo showcase page / README with architecture diagram.
- Webhook-based ingestion (Postmark inbound) as alternative to Gmail polling.
- Browser extension to save articles to the feed.
- RSS output feed.

---

## 3. Technical Architecture

### High-Level Data Flow

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Newsletters │────▶│   Ingestion  │────▶│  Processing  │────▶│   Storage    │
│  (Email)     │     │  (Gmail API) │     │  Pipeline    │     │  (Postgres)  │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
                                                                       │
                                          ┌──────────────┐             │
                                          │  Front Page  │◀────────────┤
                                          │  (FastAPI +  │             │
                                          │   Jinja2)    │             │
                                          └──────────────┘             │
                                                                       │
                                          ┌──────────────┐             │
                                          │ Daily Digest │◀────────────┘
                                          │ (SendGrid)   │
                                          └──────────────┘
```

### Components

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| **Language** | Python 3.12 | Fast iteration, rich email/HTML libraries |
| **Web framework** | FastAPI + Jinja2 templates | Lightweight, async, server-rendered HTML (no JS framework needed for MVP) |
| **Database** | PostgreSQL (Neon free tier or Supabase) | Relational, free hosted options, pgvector for embeddings later |
| **Email ingestion** | Gmail API (OAuth2 + polling every 2 min) | Free, no domain setup, you just forward to a Gmail address |
| **Email sending** | SendGrid (free tier: 100 emails/day) | Reliable, simple API |
| **HTML parsing** | BeautifulSoup4 + readability-lxml | Robust newsletter HTML cleanup |
| **Story segmentation** | Heuristic parser + LLM fallback (OpenAI gpt-4o-mini) | Rule-based first, LLM for hard cases |
| **Embeddings** | OpenAI text-embedding-3-small | Cheap ($0.02/1M tokens), good quality |
| **Vector similarity** | pgvector extension on Postgres | No separate vector DB needed |
| **Scheduling** | APScheduler (in-process) | Simple, no external scheduler needed |
| **Deployment** | Railway or Fly.io (free/hobby tier) | Easy deploy, persistent process |
| **CSS** | Pico CSS or MVP.css | Classless CSS for instant good-looking HTML |

### Decision: Gmail API Polling vs. Inbound Webhook

| Approach | Pros | Cons |
|----------|------|------|
| **Gmail API polling** ✅ chosen | No domain needed, works today, free | 2-min latency, OAuth setup |
| Inbound webhook (Postmark) | Real-time, clean | Needs custom domain, costs money |

**Choice:** Gmail API polling for MVP. Create a dedicated Gmail address (e.g., `dailyme.inbox@gmail.com`). Forward newsletters there. Poll every 2 minutes via cron.

### Directory Structure

```
dailyme/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app + routes
│   ├── config.py             # Settings (env vars)
│   ├── db.py                 # Database connection + models
│   ├── models.py             # SQLAlchemy models
│   ├── schemas.py            # Pydantic schemas
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── gmail.py          # Gmail API client
│   │   └── parser.py         # Email HTML → clean stories
│   ├── processing/
│   │   ├── __init__.py
│   │   ├── segmenter.py      # Split newsletter into stories
│   │   ├── dedup.py           # URL canon + similarity dedup
│   │   ├── clustering.py      # Topic clustering
│   │   └── ranker.py          # Ranking / personalization
│   ├── delivery/
│   │   ├── __init__.py
│   │   ├── digest.py          # Daily digest email builder
│   │   └── sendgrid.py        # SendGrid client
│   ├── templates/
│   │   ├── base.html
│   │   ├── feed.html          # Front page
│   │   └── digest.html        # Email digest template
│   └── static/
│       └── style.css
├── migrations/                # Alembic migrations
├── scripts/
│   ├── seed.py                # Seed test data
│   └── run_pipeline.py        # Manual pipeline trigger
├── tests/
├── .env.example
├── pyproject.toml
├── Dockerfile
├── PROJECT_PLAN.md
├── AGENTS.md
└── README.md
```

---

## 4. Data Model / Schema

### Core Tables

```sql
-- Newsletters we've seen
CREATE TABLE newsletters (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL,              -- e.g. "The Batch", "TLDR AI"
    sender_email  TEXT NOT NULL,
    sender_domain TEXT NOT NULL,
    first_seen_at TIMESTAMPTZ DEFAULT now(),
    email_count   INT DEFAULT 0,
    UNIQUE(sender_email)
);

-- Raw emails as received
CREATE TABLE raw_emails (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    gmail_id      TEXT UNIQUE NOT NULL,       -- Gmail message ID (idempotency key)
    newsletter_id UUID REFERENCES newsletters(id),
    subject       TEXT,
    from_address  TEXT NOT NULL,
    received_at   TIMESTAMPTZ NOT NULL,
    raw_html      TEXT,                       -- original HTML body
    raw_text      TEXT,                       -- plaintext fallback
    parsed        BOOLEAN DEFAULT FALSE,
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- Individual stories extracted from newsletters
CREATE TABLE stories (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    raw_email_id    UUID REFERENCES raw_emails(id),
    newsletter_id   UUID REFERENCES newsletters(id),
    title           TEXT NOT NULL,
    summary         TEXT,                     -- 1-3 sentence summary
    url             TEXT,                     -- canonical URL to source
    url_canonical   TEXT,                     -- cleaned/normalized URL
    image_url       TEXT,
    author          TEXT,
    published_at    TIMESTAMPTZ,
    extracted_at    TIMESTAMPTZ DEFAULT now(),
    embedding       vector(1536),             -- for dedup + clustering
    cluster_id      UUID REFERENCES topic_clusters(id),
    is_duplicate    BOOLEAN DEFAULT FALSE,
    duplicate_of    UUID REFERENCES stories(id),
    position_in_email INT,                    -- order in newsletter (1st story, 2nd, etc.)
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Deduplicated story groups (canonical story)
CREATE TABLE story_groups (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_story_id UUID REFERENCES stories(id),  -- "best" version
    title           TEXT NOT NULL,
    url_canonical   TEXT,
    story_count     INT DEFAULT 1,            -- how many newsletters covered this
    first_seen_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Which stories belong to which group
CREATE TABLE story_group_members (
    story_group_id  UUID REFERENCES story_groups(id),
    story_id        UUID REFERENCES stories(id),
    PRIMARY KEY (story_group_id, story_id)
);

-- Topic clusters
CREATE TABLE topic_clusters (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    label       TEXT,                         -- e.g. "LLM Agents", "GPU Infrastructure"
    centroid    vector(1536),
    story_count INT DEFAULT 0,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- User feedback (single user for MVP)
CREATE TABLE feedback (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    story_group_id UUID REFERENCES story_groups(id),
    action      TEXT NOT NULL CHECK (action IN ('thumbs_up', 'thumbs_down', 'hide_topic')),
    cluster_id  UUID REFERENCES topic_clusters(id),  -- for hide_topic
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- User interest profile (single user, stored as weighted topics)
CREATE TABLE interest_weights (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_keyword TEXT NOT NULL UNIQUE,       -- e.g. "ai_agents", "infrastructure"
    weight      FLOAT DEFAULT 1.0,           -- higher = more interested
    source      TEXT DEFAULT 'default',       -- 'default' | 'feedback' | 'manual'
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- Digest history
CREATE TABLE digests (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sent_at     TIMESTAMPTZ,
    story_count INT,
    status      TEXT DEFAULT 'pending',       -- 'pending' | 'sent' | 'failed'
    created_at  TIMESTAMPTZ DEFAULT now()
);
```

### Indexes

```sql
CREATE INDEX idx_stories_url_canonical ON stories(url_canonical);
CREATE INDEX idx_stories_embedding ON stories USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX idx_raw_emails_gmail_id ON raw_emails(gmail_id);
CREATE INDEX idx_stories_extracted_at ON stories(extracted_at DESC);
CREATE INDEX idx_story_groups_first_seen ON story_groups(first_seen_at DESC);
```

---

## 5. Core Algorithms & Heuristics

### 5.1 Email Parsing and Cleanup

```
Input:  Raw HTML email body
Output: Clean structured text with links preserved

Pipeline:
1. Extract HTML body from MIME multipart (prefer text/html over text/plain)
2. Remove tracking pixels (<img> with width/height = 1)
3. Remove unsubscribe footers (regex: /unsubscribe|manage preferences|view in browser/i)
4. Remove social media share buttons section
5. Use readability-lxml to extract main content (removes nav, sidebars)
6. Preserve <a href> links — these are critical for attribution
7. Convert to markdown via markdownify for cleaner text
8. Strip excessive whitespace/newlines
```

**Key heuristic:** Newsletter emails have a predictable structure — header/branding → stories → footer/ads. We strip the top and bottom 10-15% of content as likely branding/footer.

### 5.2 Story Segmentation

Turn one newsletter email into N individual story items.

```
Strategy (layered, try in order):

Layer 1 — Structural HTML signals (fast, no API calls)
  - Look for repeated patterns: <h2>/<h3> followed by <p> and <a>
  - Look for <hr> or <table> boundaries between stories
  - Newsletter-specific templates often use consistent heading tags
  - Each "block" = { heading, body_text, links[] }

Layer 2 — Heuristic text signals
  - A new story starts when:
    • A line is < 80 chars, followed by a longer paragraph (headline + body)
    • A "Read more →" or "[link]" pattern appears (end of previous story)
    • A markdown "##" or "**bold line**" appears after a paragraph break
  - Extract the first URL in each block as the story link

Layer 3 — LLM fallback (for newsletters that resist structural parsing)
  - Send cleaned text to gpt-4o-mini with prompt:
    "Extract individual news stories from this newsletter. For each story return:
     title, summary (1-2 sentences), source_url, author (if mentioned)."
  - Parse structured JSON response
  - Cache results keyed by newsletter sender + subject hash

Selection logic:
  - If Layer 1 finds ≥ 2 stories with URLs → use Layer 1
  - Else if Layer 2 finds ≥ 2 stories → use Layer 2
  - Else → use Layer 3 (LLM)
```

**Cost control:** Layer 3 (LLM) costs ~$0.005 per newsletter. At 10 newsletters/day = $0.05/day = $1.50/month. Acceptable.

### 5.3 Deduplication

Two stories about the same news event from different newsletters should be grouped.

```
Step 1 — URL Canonicalization
  - Strip query params: utm_*, ref, source, campaign, mc_*, etc.
  - Strip trailing slashes
  - Normalize to lowercase
  - Resolve common shorteners (bit.ly, t.co) via HEAD request + follow redirects
  - Remove www. prefix
  - Example: https://www.techcrunch.com/2024/article/?utm_source=tldr
           → techcrunch.com/2024/article

Step 2 — Exact URL match
  - If url_canonical matches an existing story → mark as duplicate

Step 3 — Title similarity (for cases where different URLs cover same story)
  - Compute normalized title: lowercase, strip punctuation, remove stop words
  - If Jaccard similarity of title word-sets > 0.6 → candidate duplicate

Step 4 — Embedding similarity (Week 2)
  - Compute cosine similarity of story embeddings
  - If cosine_sim > 0.88 → mark as duplicate
  - This catches "OpenAI releases GPT-5" vs "GPT-5 announced by OpenAI"

Grouping:
  - Duplicates are linked to a story_group
  - The "canonical" story is the one with: (a) the longest summary, or
    (b) the earliest extraction time
  - story_group.story_count tracks coverage breadth
```

### 5.4 Topic Clustering

Group stories into topics for the front page.

```
MVP (Week 1) — Keyword-based topics:
  - Predefined topic keywords with regex patterns:
    {
      "ai_agents":     ["agent", "agentic", "tool use", "function calling"],
      "llm_models":    ["gpt", "claude", "llama", "gemini", "model release"],
      "infrastructure": ["gpu", "cuda", "inference", "serving", "performance"],
      "enterprise_ai": ["enterprise", "deployment", "production", "compliance"],
      "research":      ["paper", "arxiv", "benchmark", "dataset", "training"],
      "funding":       ["raised", "funding", "valuation", "series"],
      "open_source":   ["open source", "github", "release", "library"],
    }
  - Assign story to topic with highest keyword match count
  - Stories with 0 matches → "Other" topic

Week 2 — Embedding-based clustering:
  - Compute embeddings for all stories in the last 24h
  - Run DBSCAN or agglomerative clustering (eps=0.3, min_samples=2)
  - Label clusters using the most frequent named entities or LLM summary
  - Store cluster centroids for incremental assignment of new stories
```

### 5.5 Ranking & Personalization

Score each story group for display order on the front page.

```
score = (w_recency * recency_score)
      + (w_coverage * coverage_score)
      + (w_interest * interest_score)
      + (w_feedback * feedback_score)
      + (w_position * position_score)

Where:
  recency_score   = max(0, 1 - hours_since_first_seen / 48)
  coverage_score  = min(story_group.story_count / 5, 1.0)    # more newsletters = more important
  interest_score  = interest_weights[topic] or 0.5 (default)
  feedback_score  = +0.3 if thumbs_up on similar topics, -0.5 if thumbs_down
  position_score  = max(0, 1 - avg_position_in_emails / 10)  # stories listed first = more important

Default weights (MVP):
  w_recency  = 0.30
  w_coverage = 0.25
  w_interest = 0.25
  w_feedback = 0.15
  w_position = 0.05

Personalization via feedback:
  - thumbs_up on a story → boost interest_weight for that story's topic by +0.1
  - thumbs_down → decrease by -0.1
  - hide_topic → set topic weight to 0 (filtered from feed)
  - Weights are clamped to [0.0, 2.0]
```

---

## 6. Evaluation Plan & Failure Modes

### How We Know It's Getting Better

| What to Measure | How | Target |
|----------------|-----|--------|
| **Parse success rate** | Count emails where parsing produces ≥1 story / total emails | ≥ 90% |
| **Segmentation accuracy** | Manual review of 20 newsletters, count correctly split stories | ≥ 80% |
| **Dedup precision** | Of stories marked duplicate, what % are truly the same story? | ≥ 90% |
| **Dedup recall** | Of known duplicate pairs, what % did we catch? | ≥ 70% |
| **Ranking quality** | Does top-5 feel relevant? (subjective, thumbs up rate) | ≥ 60% thumbs-up in top 5 |
| **Digest delivery** | Did the email arrive on time? | 100% |
| **E2E latency** | Time from email arrival to story on front page | < 5 min |

### Evaluation Process

1. **Daily manual spot-check** (5 min): Open front page, scan top 10 stories, give thumbs up/down. Note any obvious parsing failures.
2. **Weekly metrics review**: Query DB for parse rates, dedup counts, feedback ratios.
3. **A/B ranking** (stretch): Show two orderings, pick preferred one.

### Failure Modes & Mitigations

| Failure Mode | Likelihood | Impact | Mitigation |
|-------------|-----------|--------|------------|
| Newsletter HTML too complex to parse | High | Stories missed | LLM fallback (Layer 3); per-newsletter parser templates |
| Gmail API rate limit (250 quota units/sec) | Low | Delayed ingestion | Exponential backoff; poll every 2 min not every 30s |
| Dedup false positives (different stories merged) | Medium | Information loss | Conservative threshold (0.88 cosine); show "also covered by" |
| Dedup false negatives (same story not caught) | Medium | Cluttered feed | Acceptable for MVP; embedding similarity in Week 2 |
| LLM API down | Low | Segmentation fails for complex newsletters | Queue and retry; structural parser handles most cases |
| Email forwarding breaks formatting | Medium | Garbled content | Extract from original MIME part; test with multiple email clients |
| SendGrid free tier limit (100/day) | Low | Digest not sent | One email/day is well within limit |
| Story with no URL | Medium | Can't link out | Display story with newsletter attribution as source |
| Embedding costs spike | Low | Budget impact | text-embedding-3-small is very cheap; batch embed |

---

## 7. Task Breakdown — Ticket List

Story points: 1 = few hours, 2 = half day, 3 = full day, 5 = 1.5 days, 8 = 2-3 days.

### Epic 1: Project Setup (5 pts)

| # | Task | Points | Dependencies |
|---|------|--------|-------------|
| 1.1 | Initialize repo: pyproject.toml, uv, project structure, .env.example | 1 | — |
| 1.2 | Set up PostgreSQL (Neon free tier) + pgvector extension | 2 | — |
| 1.3 | Create SQLAlchemy models + Alembic migrations for all tables | 2 | 1.2 |

### Epic 2: Email Ingestion (5 pts)

| # | Task | Points | Dependencies |
|---|------|--------|-------------|
| 2.1 | Gmail API OAuth2 setup + credential storage | 2 | 1.1 |
| 2.2 | Gmail polling service: fetch unread, extract HTML/text, store in raw_emails | 2 | 2.1, 1.3 |
| 2.3 | Newsletter auto-detection: identify sender, create/update newsletters table | 1 | 2.2 |

### Epic 3: Parsing & Segmentation (8 pts)

| # | Task | Points | Dependencies |
|---|------|--------|-------------|
| 3.1 | HTML cleanup pipeline (tracking pixels, footers, readability extraction) | 2 | 2.2 |
| 3.2 | Structural story segmenter (Layer 1: HTML heading/block detection) | 3 | 3.1 |
| 3.3 | Heuristic text segmenter (Layer 2: text pattern matching) | 2 | 3.1 |
| 3.4 | LLM fallback segmenter (Layer 3: gpt-4o-mini extraction) | 1 | 3.1 |

### Epic 4: Deduplication (5 pts)

| # | Task | Points | Dependencies |
|---|------|--------|-------------|
| 4.1 | URL canonicalization (strip params, resolve redirects, normalize) | 2 | 3.2 |
| 4.2 | Exact URL + title similarity dedup → story_groups creation | 2 | 4.1 |
| 4.3 | Embedding-based dedup (cosine similarity via pgvector) | 1 | 4.2, 5.3 |

### Epic 5: Clustering & Ranking (5 pts)

| # | Task | Points | Dependencies |
|---|------|--------|-------------|
| 5.1 | Keyword-based topic assignment | 1 | 3.2 |
| 5.2 | Ranking function (recency + coverage + interest + position) | 2 | 5.1, 4.2 |
| 5.3 | Compute + store embeddings for stories (OpenAI API) | 1 | 3.2 |
| 5.4 | Embedding-based clustering (DBSCAN) — Week 2 | 1 | 5.3 |

### Epic 6: Front Page (5 pts)

| # | Task | Points | Dependencies |
|---|------|--------|-------------|
| 6.1 | FastAPI routes: GET / (feed), GET /story/{id} | 1 | 5.2 |
| 6.2 | Jinja2 templates: feed page with story cards (title, summary, source, link) | 2 | 6.1 |
| 6.3 | Thumbs up/down + hide topic UI (HTMX or plain form POSTs) | 2 | 6.2 |

### Epic 7: Daily Digest (3 pts)

| # | Task | Points | Dependencies |
|---|------|--------|-------------|
| 7.1 | Digest builder: select top 10 stories, render HTML email template | 2 | 5.2 |
| 7.2 | SendGrid integration + scheduled send (APScheduler) | 1 | 7.1 |

### Epic 8: Scheduling & Deployment (3 pts)

| # | Task | Points | Dependencies |
|---|------|--------|-------------|
| 8.1 | APScheduler: poll Gmail every 2 min, run pipeline, daily digest at 8 AM | 1 | 2.2, 7.2 |
| 8.2 | Dockerfile + Railway/Fly.io deployment | 2 | all |

### Epic 9: Improvements — Week 2 (8 pts)

| # | Task | Points | Dependencies |
|---|------|--------|-------------|
| 9.1 | Feedback-driven re-ranking (update interest_weights from thumbs) | 2 | 6.3 |
| 9.2 | Topic labels on front page + "hide topic" filtering | 1 | 5.4, 6.3 |
| 9.3 | Newsletter attribution badges ("covered by 3 newsletters") | 1 | 4.2, 6.2 |
| 9.4 | Retry/error handling for all external API calls | 2 | all |
| 9.5 | Parsing edge-case hardening (test with 20+ real newsletters) | 2 | 3.2 |

### Total: ~47 story points

| Phase | Points |
|-------|--------|
| Week 1 MVP (Epics 1-8) | 39 pts |
| Week 2 Improvements (Epic 9) | 8 pts |

---

## 8. Risks & Mitigations

### Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| **Newsletter HTML diversity** — each newsletter uses different templates, making universal parsing hard | High | High | Layered approach (structural → heuristic → LLM). Add per-newsletter parser profiles over time. Start with 5 known newsletters. |
| **Gmail API OAuth complexity** — OAuth2 refresh flow can be fiddly | Medium | Medium | Use google-auth library with stored refresh token. Test token refresh on day 1. Alternative: use an App Password with IMAP if OAuth is too painful. |
| **Email forwarding alters content** — forwarding from your primary inbox to the dedicated inbox may wrap original HTML in forwarding markup | Medium | Medium | Parse the MIME structure to find the original message part. Test with Gmail and Apple Mail forwarding. |
| **Rate limits (Gmail, OpenAI, SendGrid)** — hitting free tier limits | Low | Medium | Gmail: 250 quota units/sec (plenty for polling). OpenAI: batch calls, <$2/month. SendGrid: 100 emails/day (we send 1). |
| **pgvector query performance** — slow at scale | Low | Low | We'll have <10K stories. IVFFlat index is fine. Upgrade to HNSW if needed. |

### Product Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| **Low story quality** — parsed stories are garbled or miss key info | Medium | High | Manual spot-checks daily. LLM fallback catches most cases. Store raw HTML for reprocessing. |
| **Dedup too aggressive** — merges distinct stories | Low | High | Conservative similarity thresholds. "Also covered by" UI shows all sources. |
| **Not enough signal for personalization** — too few newsletters for meaningful ranking | Medium | Medium | Seed with 5-8 good AI newsletters. Coverage score helps even without feedback. |
| **Demo doesn't feel impressive** — too basic or too buggy | Medium | High | Focus on clean UI + reliable pipeline. One polished flow > many half-done features. |

### Legal / Copyright

| Concern | Assessment | Approach |
|---------|-----------|----------|
| Displaying newsletter content | Low risk for personal/demo use | We show titles + short summaries + link to original. Not republishing full content. |
| Email forwarding ToS | Negligible for personal use | You're forwarding your own subscriptions to yourself. |
| OpenAI usage for extraction | Fine | Extraction/summarization is standard use. |

---

## 9. Next Actions — Execute Today Checklist

- [ ] **Create Gmail account** — Set up `dailyme.inbox@gmail.com` (or similar available address)
- [ ] **Enable Gmail API** — Go to Google Cloud Console → create project → enable Gmail API → create OAuth2 credentials (desktop app type) → download `credentials.json`
- [ ] **Get API keys:**
  - [ ] OpenAI API key (for gpt-4o-mini + embeddings) — set spending limit to $5/month
  - [ ] SendGrid API key (free tier) — verify sender email
- [ ] **Set up database** — Create free Neon Postgres database at neon.tech → enable pgvector extension (`CREATE EXTENSION vector;`)
- [ ] **Initialize repo:**
  ```bash
  cd /Users/rajiv.shah/Code/dailyme
  git init
  # We'll scaffold the project structure in the next coding session
  ```
- [ ] **Forward 5 test newsletters** to the dedicated inbox:
  - TLDR AI
  - The Batch (Andrew Ng)
  - Ben's Bites
  - Import AI
  - The Neuron (or similar)
- [ ] **Kick off Epic 1 + Epic 2** — Project setup + email ingestion

---

## Assumptions Made

1. **Single user** — No auth needed. One inbox, one feed, one person.
2. **Gmail polling** over webhook — Simpler setup, 2-min latency is acceptable.
3. **Server-rendered HTML** over SPA — Faster to build, easier to demo, no JS framework needed. HTMX for interactivity (thumbs up/down).
4. **PostgreSQL + pgvector** — One database for everything (relational + vectors). No separate vector DB.
5. **OpenAI for LLM + embeddings** — Cheapest quality/cost ratio for the task. gpt-4o-mini for extraction, text-embedding-3-small for vectors.
6. **Python monolith** — One service handles ingestion, processing, serving, and scheduling. Split later if needed.
7. **5-10 newsletters** — The system is designed for a personal scale of 5-10 daily newsletters, not thousands.
8. **Digest at 8 AM ET** — Configurable, but this is the default.

---

*Plan authored: 2026-03-01. Ready to build.*
