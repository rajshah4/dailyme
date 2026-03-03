# 🔧 DailyMe Troubleshooting Guide

## Missing Newsletter / Stories Not Showing Up

If you forwarded a newsletter but it's not appearing on your news page, follow these steps:

### Step 1: Check if Email Has the DailyMe Label

1. Open Gmail and search for the newsletter
2. Check if it has the **"DailyMe"** label
3. If not, add the label manually:
   - Open the email
   - Click the label icon (or press `L`)
   - Select or create "DailyMe" label
   - Save

### Step 2: Check When the Email Arrived

- The pipeline only fetches emails from the **last 7 days**
- If the email is older than 7 days, it won't be picked up
- Solution: Forward it again to get a fresh copy

### Step 3: Run the Diagnostic Script

From the `dailyme` repo:

```bash
cd /path/to/dailyme
uv run python scripts/debug_newsletter.py "AI News Truth"
```

Replace "AI News Truth" with part of your newsletter name (case-insensitive).

**What it checks:**
- ✅ Gmail: Is the email in your inbox with DailyMe label?
- ✅ Database: Is the newsletter registered and emails stored?
- ✅ Parsing: Were stories extracted from the email?
- ✅ Story Groups: Are stories visible in recent feed?

### Step 4: Check the Pipeline

**Has the pipeline run recently?**

Check: https://github.com/rajshah4/dailyme/actions

- The pipeline should run every 30 minutes
- Click on the latest run to see logs
- Look for errors or warnings

**Manually trigger the pipeline:**

1. Go to: https://github.com/rajshah4/dailyme/actions
2. Click **Trigger Pipeline (OpenHands Cloud)**
3. Click **Run workflow** → **Run workflow**
4. Wait ~5 seconds (it just triggers OpenHands Cloud)
5. Check OpenHands Cloud at: https://app.all-hands.dev/conversations

**Or run locally:**

```bash
cd /path/to/dailyme
uv run python scripts/run_pipeline.py
```

### Step 5: Common Issues & Solutions

#### Issue: Email in Gmail but not in database

**Symptom:** Debug script shows email in Gmail but not in `raw_emails` table

**Cause:** Pipeline hasn't run since email arrived, or there was an error fetching

**Solution:**
1. Manually trigger the pipeline (see Step 4)
2. Check GitHub Actions logs for errors
3. Verify `GMAIL_TOKEN_JSON` is set correctly in GitHub secrets

#### Issue: Email in database but not parsed

**Symptom:** Email is in `raw_emails` but `parsed = False`

**Cause:** Parsing failed (LLM error, malformed HTML, timeout)

**Solution:**
1. Check pipeline logs for LLM errors
2. The email might have unusual formatting
3. Try forwarding a fresh copy
4. Check if the newsletter is mostly images (can't parse images well)

#### Issue: Stories extracted but not showing on website

**Symptom:** Stories are in `stories` table but not on rajivshah.com/news

**Causes & Solutions:**

**A) Stories are older than 3 days:**
- Check `first_seen_at` timestamp in `story_groups` table
- Stories older than 3 days are hidden (unless starred)
- Solution: Star them in the database or adjust the time window

**B) Stories not in story groups:**
- Check if stories are linked to `story_groups`
- Check `story_group_members` table
- Solution: Re-run deduplication or manually create groups

**C) Website not reading from database:**
- Check Vercel environment variables
- Verify `DAILYME_DATABASE_URL` is set
- Check Vercel deployment logs for errors

#### Issue: Newsletter name not recognized

**Symptom:** Debug script can't find newsletter in database

**Cause:** This is the first email from this newsletter, so it hasn't been registered yet

**Solution:**
- Run the pipeline - it will auto-register new newsletters
- The pipeline extracts sender domain and creates a newsletter entry
- Subsequent emails from the same sender will be grouped together

#### Issue: Stories showing but wrong publication time

**Symptom:** Story shows "3 days ago" but you just got it

**Cause:** The `first_seen_at` timestamp is based on when the email was **received** in your inbox, not when the pipeline ran

**Solution:**
- This is by design - we want to show when the news actually arrived
- If the sender sent the email 3 days ago, it will show as 3 days old
- Not an issue, just how it works

### Step 6: Check Story Display Settings

**Are you filtering by tags?**
- On rajivshah.com/news, check if you have a tag filter active
- Click "All" to see all stories

**Is the newsletter very recent?**
- The website caches data for a few minutes
- Wait 5 minutes or hard refresh (Ctrl+Shift+R / Cmd+Shift+R)
- Or redeploy on Vercel to clear cache

### Step 7: Manual Database Check

If you have access to the database:

```sql
-- Check if newsletter exists
SELECT * FROM newsletters WHERE name ILIKE '%AI News%';

-- Check raw emails for this newsletter
SELECT id, subject, received_at, parsed 
FROM raw_emails 
WHERE newsletter_id = [newsletter_id]
ORDER BY received_at DESC 
LIMIT 10;

-- Check extracted stories
SELECT id, title, created_at 
FROM stories 
WHERE newsletter_id = [newsletter_id]
ORDER BY created_at DESC 
LIMIT 10;

-- Check story groups (what shows on the website)
SELECT sg.id, sg.first_seen_at, s.title
FROM story_groups sg
JOIN stories s ON s.id = sg.canonical_story_id
WHERE s.newsletter_id = [newsletter_id]
ORDER BY sg.first_seen_at DESC
LIMIT 10;
```

## Pipeline Not Running

### Check GitHub Actions

1. Go to: https://github.com/rajshah4/dailyme/settings/secrets/actions
2. Verify these secrets are set:
   - `OPENHANDS_API_KEY` ✅
   - `DATABASE_URL` ✅
   - `GMAIL_TOKEN_JSON` ✅

3. Check workflow file: `.github/workflows/pipeline.yml`
   - Should have cron schedule: `*/30 * * * *` (every 30 min)
   - Should trigger OpenHands Cloud API

### Check OpenHands Cloud

1. Go to: https://app.all-hands.dev/conversations
2. Look for recent conversations about "DailyMe pipeline"
3. Check for errors in the conversation logs
4. Verify your API key is valid

## Website Not Showing Stories

### Check Vercel Environment Variables

1. Go to: https://vercel.com/dashboard
2. Select your website project
3. Go to **Settings** → **Environment Variables**
4. Verify `DAILYME_DATABASE_URL` is set correctly
5. Format should be: `postgresql://user:password@host/database`
   - NOT `postgresql+asyncpg://...` (that's Python-specific)

### Check Vercel Deployment

1. Go to: https://vercel.com/dashboard
2. Select your website project
3. Go to **Deployments**
4. Check latest deployment for errors
5. Look at **Function Logs** for the news page

### Test Database Connection

From your local machine:

```bash
cd /path/to/rajiv-shah-website-private

# Set environment variable
export DAILYME_DATABASE_URL="postgresql://..."

# Test Next.js dev server
npm run dev

# Visit http://localhost:3000/news
```

If it works locally but not on Vercel, it's an environment variable issue.

## Getting Help

**Check logs:**
- GitHub Actions: https://github.com/rajshah4/dailyme/actions
- OpenHands Cloud: https://app.all-hands.dev/conversations
- Vercel: https://vercel.com/dashboard → Your Project → Deployments → Logs

**Run diagnostics:**
```bash
cd /path/to/dailyme
uv run python scripts/debug_newsletter.py "Newsletter Name"
```

**Common patterns:**
- Email arrived but not in database → Pipeline hasn't run
- Email in database but not parsed → LLM/parsing error
- Stories extracted but not showing → Check timestamps and story_groups
- Website shows old stories → Check 3-day TTL setting

**Need more help?**
- Check `dailyme` repo issues: https://github.com/rajshah4/dailyme/issues
- Review `OPENHANDS_CLOUD_SETUP.md` for pipeline setup
- Review `NEWS_SETUP.md` in website repo for web integration
