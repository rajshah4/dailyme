# OpenHands Showcase Strategy

How DailyMe demonstrates OpenHands capabilities — not just as a tool that wrote the code, but as the **runtime operator** of a continuously-running system.

---

## OpenHands Features → Where They Show Up in DailyMe

### 1. 🧠 Skills System (repo + keyword-triggered)

**What it is:** Skills are specialized prompts (SKILL.md files) that inject domain knowledge into agents. They activate based on keywords or are always-on.

**How DailyMe uses it:**
- **`AGENTS.md`** — Repository-level skill that tells any OpenHands agent how this project works, what the schema is, how to run the pipeline. Already created.
- **`.agents/skills/newsletter-parser/SKILL.md`** — A keyword skill triggered when the agent encounters parsing failures. Contains newsletter-specific parsing rules, known newsletter formats (TLDR, The Batch, etc.), and fallback strategies.
- **`.agents/skills/pipeline-runner/SKILL.md`** — A skill that describes how to run the full ingest→parse→dedup→rank→digest pipeline. Activated when the agent is asked to "run the pipeline" or "process newsletters."
- **`.agents/skills/dedup-strategy/SKILL.md`** — Documents the dedup algorithm so any agent session can consistently apply it.

**Demo moment:** "The agent knows how to parse 10 different newsletter formats because we gave it a skill — no retraining needed, just a markdown file."

### 2. 🤝 Sub-Agent Delegation (DelegateTool — parallel)

**What it is:** A parent agent spawns sub-agents that run in parallel, each with their own skills and context. Results are collected when all finish.

**How DailyMe uses it:**
- **Parallel newsletter processing:** When 5 newsletters arrive, spawn 5 sub-agents — one per newsletter — each with the `newsletter-parser` skill. They parse simultaneously, then the parent agent collects all stories and runs dedup.
- **Parallel story enrichment:** One sub-agent resolves shortened URLs, another computes embeddings, another assigns topics. All in parallel.

**Demo moment:** "Five newsletters arrived. The agent delegated parsing to 5 sub-agents in parallel — all processed in the time it takes to do one."

### 3. 📋 TaskToolSet (sequential sub-agents)

**What it is:** Parent launches a sub-agent, blocks until it finishes, then uses its result. Good for sequential pipelines.

**How DailyMe uses it:**
- **Pipeline stages:** Parse → Dedup → Cluster → Rank → Deliver as a chain of sequential sub-agent tasks.
- Each stage gets the output of the previous one.
- If a stage fails, the parent can retry or adapt.

**Demo moment:** "The pipeline ran 5 stages — each handled by a specialist sub-agent. When the dedup stage found a tricky edge case, it adapted on the fly."

### 4. 🔧 Custom Tools

**What it is:** Define typed tools (action + observation + executor) that the agent can call, beyond bash/file editing.

**How DailyMe uses it:**
- **GmailTool** — Fetches unread emails from the dedicated inbox, returns structured email data.
- **DatabaseTool** — Runs SQL queries against our Postgres DB (insert stories, query for dedup, etc.).
- **SendGridTool** — Sends the daily digest email.
- **EmbeddingTool** — Computes sentence-transformer embeddings for story text.

**Demo moment:** "The agent doesn't shell out to curl — it has typed tools for Gmail, the database, and email sending. Each tool validates inputs and returns structured data."

### 5. 🔌 MCP Integration (Model Context Protocol)

**What it is:** Connect agents to external tool servers via the MCP standard. Agents can discover and use tools from any MCP server.

**How DailyMe uses it:**
- **Postgres MCP server** — The agent reads/writes to the database via an MCP-connected Postgres server instead of raw SQL.
- **GitHub MCP** — For repo operations (already available in OpenHands Cloud).

**Demo moment:** "The agent connects to our Postgres database through MCP — the same protocol that works across any AI tool."

### 6. 📡 Event Architecture (typed events + hooks)

**What it is:** Everything in OpenHands is a typed event (Actions, Observations, User Messages, State Updates). Hooks can intercept events at tool lifecycle points.

**How DailyMe uses it:**
- **Pipeline progress hooks** — Log each step (emails fetched, stories parsed, duplicates found, etc.) as structured events.
- **Error hooks** — When a parsing action fails, a hook catches it and logs the raw email for manual review.
- **Metrics hooks** — Track pipeline latency, parse success rate, dedup counts as events.

**Demo moment:** "Every action the agent takes is a typed event. We built hooks that track pipeline metrics — parse success rate, dedup coverage — all observable."

### 7. ☁️ Cloud API (scheduled agent runs)

**What it is:** OpenHands Cloud exposes a REST API to programmatically create conversations, send messages, and get results.

**How DailyMe uses it:**
- **Scheduled pipeline runs** — A simple cron job (or GitHub Action) calls the Cloud API every 2 hours: "Run the DailyMe pipeline: fetch new newsletters, parse, dedup, rank, and update the database."
- **Daily digest trigger** — At 8 AM, an API call tells the agent: "Send today's digest email."
- **Ad-hoc commands** — "Add a new parser for this newsletter format" via API.

**Demo moment:** "A cron job hits the OpenHands Cloud API every 2 hours. The agent wakes up, processes new newsletters, and goes back to sleep. No server to maintain."

### 8. 🔄 Iterative Refinement (self-improvement)

**What it is:** The agent can critique its own output and iterate to improve quality.

**How DailyMe uses it:**
- **Parser accuracy improvement** — After segmenting a newsletter, the agent checks: "Did I extract a reasonable number of stories? Do they all have URLs? Are any suspiciously short?" If quality is low, it retries with a different strategy.
- **Ranking calibration** — The agent reviews user feedback (thumbs up/down) and adjusts interest weights.

**Demo moment:** "The agent noticed its parser only found 1 story in a newsletter that usually has 10. It automatically switched to LLM extraction and got 8 stories."

### 9. 🔐 Security & Action Confirmation

**What it is:** Actions are assessed for security risk. High-risk actions require user confirmation.

**How DailyMe uses it:**
- **Email sending confirmation** — Before sending the daily digest to a real email address, the agent confirms with the user (or operates within pre-approved parameters).
- **Database writes** — Classified as medium risk, auto-approved within the pipeline context.

### 10. 📊 Metrics & Observability

**What it is:** Built-in metrics tracking and OpenTelemetry tracing.

**How DailyMe uses it:**
- Track LLM token usage per pipeline run.
- Trace the full pipeline execution for debugging.
- Dashboard showing: newsletters processed, stories extracted, dedup rate, digest delivery status.

---

## The Narrative Arc for the Demo

### Setup (30 seconds)
"I subscribe to 10 AI newsletters. They overlap heavily — the same stories appear in 5 different emails. I wanted a single, personalized front page."

### The Build (2 minutes)
"I gave OpenHands a project plan and it built the system:
- Custom skills for newsletter parsing
- Sub-agents that process newsletters in parallel
- A pipeline that deduplicates and ranks stories
- A front page and daily digest"

### The Operation (2 minutes — the real wow)
"But here's the interesting part — OpenHands doesn't just build the code. It **runs the system continuously:**
- Every 2 hours, a Cloud API call triggers the agent
- It fetches new newsletters, parses them, deduplicates, ranks
- If a parser fails, it adapts — sometimes fixing its own code
- It sends me a personalized digest every morning
- I never touch a cron job or a server — the agent IS the backend"

### The Learning (1 minute)
"When I thumbs-down a story, the agent adjusts my interest weights. When a new newsletter format arrives, I tell the agent to add a parser — it writes the skill and it's active next run."

---

## File Layout for OpenHands Integration

```
dailyme/
├── AGENTS.md                              # Repo-level skill (always loaded)
├── .agents/
│   └── skills/
│       ├── newsletter-parser/
│       │   └── SKILL.md                   # Keyword: "parse", "newsletter", "segment"
│       ├── pipeline-runner/
│       │   └── SKILL.md                   # Keyword: "pipeline", "run", "process"
│       └── dedup-strategy/
│           └── SKILL.md                   # Keyword: "dedup", "duplicate", "merge"
├── app/
│   ├── tools/                             # Custom OpenHands tools (SDK)
│   │   ├── gmail_tool.py
│   │   ├── database_tool.py
│   │   ├── sendgrid_tool.py
│   │   └── embedding_tool.py
│   └── ...
├── scripts/
│   ├── run_pipeline.py                    # Full pipeline (for Cloud API trigger)
│   ├── schedule_agent.py                  # Cron → Cloud API caller
│   └── run_pipeline_sdk.py               # SDK version using sub-agents
└── ...
```

---

## What We're NOT Doing (Keep It Real)

- We're not faking the demo. The agent actually runs the pipeline.
- We're not over-engineering. If a feature doesn't naturally fit, we skip it.
- We're using the platform features where they genuinely add value:
  - Skills for domain knowledge → YES, parsing newsletters is a perfect use case
  - Sub-agents for parallelism → YES, multiple newsletters at once
  - Cloud API for scheduling → YES, this is how you'd actually run periodic tasks
  - Custom tools for type safety → YES, better than raw bash for API calls
