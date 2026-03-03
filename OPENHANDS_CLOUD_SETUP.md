# ☁️ OpenHands Cloud Compute Setup

This guide shows you how to use **OpenHands Cloud for all heavy compute** while hosting the web app on your own domain.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Cron Trigger (GitHub Actions)                              │
│  • Runs every 30 minutes                                    │
│  • Just makes one API call (~5 seconds)                     │
│  • Zero heavy compute                                       │
└────────────────────┬────────────────────────────────────────┘
                     │ triggers
                     ↓
┌─────────────────────────────────────────────────────────────┐
│  OpenHands Cloud (Heavy Compute)                            │
│  • Fetches Gmail newsletters                                │
│  • Parses with LLM (Claude Sonnet 4)                        │
│  • Deduplicates stories                                     │
│  • Writes results to database                               │
│  • Takes 5-15 minutes per run                               │
└────────────────────┬────────────────────────────────────────┘
                     │ writes to
                     ↓
┌─────────────────────────────────────────────────────────────┐
│  Neon Postgres (Storage)                                    │
│  • Stores newsletters, stories, feedback                    │
└────────────────────┬────────────────────────────────────────┘
                     │ reads from
                     ↓
┌─────────────────────────────────────────────────────────────┐
│  Vercel at rajivshah.com (Presentation)                     │
│  • Serves your personalized news feed                       │
│  • Zero compute load (just reads DB and renders HTML)       │
└─────────────────────────────────────────────────────────────┘
```

## Why This Architecture?

✅ **OpenHands Cloud handles all heavy lifting:**
- Gmail API calls
- LLM inference (expensive!)
- HTML parsing
- Deduplication logic

✅ **Your infrastructure stays lightweight:**
- GitHub Actions: Just triggers API (~5 sec, uses free tier minutes)
- Vercel: Just serves HTML (well within free tier)
- Neon: Just stores data (free tier)

✅ **Benefits:**
- 🎯 No dependency on Railway or other compute platforms
- 🌐 Web app hosted at your own domain (rajivshah.com)
- 💰 Pay-as-you-go for compute (OpenHands Cloud)
- 🔧 Easy to debug (full logs in OpenHands Cloud UI)
- ⚡ Can scale if needed (OpenHands handles it)

## Setup Instructions

### 1. Get OpenHands Cloud API Key

1. Go to https://app.all-hands.dev
2. Sign in or create an account
3. Navigate to Settings → API Keys
4. Generate a new API key
5. Copy the key (starts with `sk-...`)

### 2. Add GitHub Secret

Add your OpenHands API key to GitHub:

1. Go to your repository: https://github.com/rajshah4/dailyme
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Name: `OPENHANDS_API_KEY`
5. Value: Your API key from step 1
6. Click **Add secret**

**Important:** You can now REMOVE these old secrets (no longer needed):
- ❌ `LLM_MODEL` (OpenHands Cloud will handle this)
- ❌ `LLM_API_KEY` (OpenHands Cloud uses its own)
- ❌ `GMAIL_TOKEN_JSON` (will be in OpenHands Cloud environment)

Keep only:
- ✅ `OPENHANDS_API_KEY` (new)
- ✅ `DATABASE_URL` (still needed - OpenHands writes to your DB)

### 3. Set Up OpenHands Cloud Environment

OpenHands Cloud needs access to your Gmail and database when running the pipeline.

**Option A: Add to GitHub repo (Recommended)**

Create a `.env.cloud` file in your repo with:

```bash
DATABASE_URL=postgresql+asyncpg://[user]:[password]@[host]/[database]
LLM_MODEL=openhands/claude-sonnet-4-5-20250929
GMAIL_TOKEN_JSON='{"token": "...", "refresh_token": "...", ...}'
```

Then update `scripts/run_pipeline.py` to load this file.

**Option B: Set in OpenHands Cloud UI**

When the conversation starts, OpenHands can ask for these values or you can pre-configure them in your OpenHands Cloud project settings.

### 4. Test the Trigger

**Manually trigger the pipeline:**

```bash
# Install dependencies
pip install requests

# Set your API key
export OPENHANDS_API_KEY="sk-..."
export GITHUB_REPO="rajshah4/dailyme"
export GITHUB_BRANCH="main"

# Trigger the pipeline
python scripts/openhands_trigger.py
```

You'll see output like:
```
🚀 Triggering OpenHands Cloud pipeline for rajshah4/dailyme@main
✅ Pipeline started: https://app.all-hands.dev/conversations/abc123
📝 Conversation ID: abc123
💡 Pipeline running in background. Check progress at the URL above.
```

Click the URL to watch OpenHands work in real-time! 🎬

**To wait for completion:**

```bash
python scripts/openhands_trigger.py --wait
```

This will poll every 30 seconds and exit when the pipeline finishes.

### 5. Enable GitHub Actions Cron

The workflow is already configured in `.github/workflows/pipeline.yml`:

```yaml
on:
  schedule:
    - cron: '*/30 * * * *'  # Every 30 minutes
  workflow_dispatch:         # Manual trigger button
```

GitHub Actions will now:
1. Wake up every 30 minutes
2. Run for ~5 seconds (just triggers the API)
3. Exit immediately
4. OpenHands Cloud does the rest

**Test it:**

1. Go to: https://github.com/rajshah4/dailyme/actions
2. Click **Trigger Pipeline (OpenHands Cloud)**
3. Click **Run workflow** → **Run workflow**
4. Watch it complete in ~5 seconds ✨

### 6. Web Interface

The news feed is integrated into rajivshah.com/news (in the `rajiv-shah-website-private` repo).

**No separate deployment needed!** The website fetches stories directly from your Neon Postgres database.

If you want a standalone deployment instead, see `VERCEL_DEPLOYMENT.md`.

## Cost Estimate

**OpenHands Cloud:**
- ~48 runs per day (every 30 min)
- ~5-15 minutes per run (depends on # of newsletters)
- LLM calls for parsing newsletters
- **Estimated:** $X-Y/month (contact OpenHands for pricing)

**GitHub Actions:**
- ~5 seconds per run = ~4 minutes/day
- Free tier: 2,000 minutes/month
- **Cost:** $0 (well within free tier)

**Vercel:**
- Serving HTML only, no compute
- ~1,500 page views/month (personal use)
- **Cost:** $0 (free tier)

**Neon Postgres:**
- Storage + queries
- **Cost:** $0 (free tier, unless you exceed limits)

**Total:** Just OpenHands Cloud compute costs. Everything else is free! 🎉

## Monitoring & Debugging

### View Pipeline Runs

**OpenHands Cloud:**
- Dashboard: https://app.all-hands.dev/conversations
- See full logs, LLM calls, errors
- Can interact with agent if something fails

**GitHub Actions:**
- Dashboard: https://github.com/rajshah4/dailyme/actions
- Just shows the trigger (should always succeed in ~5 sec)

### Common Issues

**Issue: "OPENHANDS_API_KEY not set"**

Fix: Add the secret to GitHub (see step 2)

**Issue: OpenHands can't access Gmail/Database**

Fix: Make sure `DATABASE_URL` and `GMAIL_TOKEN_JSON` are available to OpenHands Cloud (see step 3)

**Issue: Pipeline times out**

This is fine! OpenHands conversations can run for 30+ minutes if needed. The GitHub Actions job exits immediately after triggering.

**Issue: Want to see live progress**

Visit the conversation URL from the GitHub Actions log output, or check your OpenHands Cloud dashboard.

## Alternative Trigger Methods

Don't want to use GitHub Actions at all? You can trigger from:

### 1. Vercel Cron

Create `api/cron.py`:

```python
from scripts.openhands_trigger import OpenHandsAPI
import os

def handler(request):
    api = OpenHandsAPI()
    conv = api.create_conversation(
        initial_user_msg="Run DailyMe pipeline...",
        repository=os.getenv("GITHUB_REPO"),
        selected_branch="main",
    )
    return {"status": "triggered", "url": conv["url"]}
```

Then configure in `vercel.json`:

```json
{
  "crons": [{
    "path": "/api/cron",
    "schedule": "*/30 * * * *"
  }]
}
```

### 2. External Cron Service

Use a service like:
- https://cron-job.org (free)
- https://www.easycron.com
- Any server with crontab

Just schedule:
```bash
*/30 * * * * curl -X POST https://your-trigger-endpoint.com/trigger
```

### 3. Your Own Server

If you run a server at rajivshah.com:

```bash
# crontab -e
*/30 * * * * cd /path/to/dailyme && python scripts/openhands_trigger.py
```

## Next Steps

1. ✅ Get OpenHands Cloud API key
2. ✅ Add `OPENHANDS_API_KEY` to GitHub secrets
3. ✅ Test trigger manually
4. ✅ Enable GitHub Actions cron
5. ✅ Deploy web app to Vercel (see `VERCEL_DEPLOYMENT.md`)
6. ✅ Point `news.rajivshah.com` to Vercel
7. 🎉 Enjoy your fully self-hosted news feed!

---

Questions? Check:
- OpenHands Cloud docs: https://docs.all-hands.dev
- OpenHands Discord: https://discord.gg/openhands
