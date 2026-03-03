# 🚀 Deploying DailyMe to Vercel

This guide shows you how to deploy the DailyMe web app to Vercel alongside your existing www.rajivshah.com site.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  GitHub Actions (Compute Layer)                         │
│  • Runs every 30 minutes                                │
│  • Fetches Gmail newsletters                            │
│  • Processes with OpenHands Cloud LLM                   │
│  • Writes results to Neon Postgres                      │
└────────────────────┬────────────────────────────────────┘
                     │
                     ↓ (writes to)
┌─────────────────────────────────────────────────────────┐
│  Neon Postgres (Storage Layer)                          │
│  • Stores newsletters, stories, feedback                │
│  • pgvector for embeddings                              │
└────────────────────┬────────────────────────────────────┘
                     │
                     ↓ (reads from)
┌─────────────────────────────────────────────────────────┐
│  Vercel (Presentation Layer)                            │
│  • Serves your personalized news feed                   │
│  • Hosted at news.rajivshah.com (or subdomain of       │
│    your choice)                                         │
│  • Zero compute load (just reads DB and renders HTML)   │
└─────────────────────────────────────────────────────────┘
```

## Why Vercel?

✅ **Perfect fit for this use case:**
- Zero heavy compute (that's done in GitHub Actions)
- Just database reads + HTML rendering
- Serverless = auto-scaling (though you won't need it for personal use)
- Free tier is more than enough
- Integrates with your existing rajivshah.com setup

✅ **Cost:** Should stay within free tier
- Very low traffic (personal news feed)
- No expensive compute operations
- Just serving lightweight HTML pages

## Prerequisites

1. ✅ Vercel account (you already have one for www.rajivshah.com)
2. ✅ GitHub repository for DailyMe
3. ✅ Neon Postgres database (already set up)
4. ✅ GitHub Actions already running (no changes needed!)

## Step-by-Step Deployment

### 1. Connect Repository to Vercel

**Option A: Via Vercel Dashboard (Easiest)**

1. Go to https://vercel.com/new
2. Click "Import Git Repository"
3. Select your `dailyme` repository
4. Vercel will auto-detect the configuration from `vercel.json`

**Option B: Via Vercel CLI**

```bash
# Install Vercel CLI (if not already installed)
npm install -g vercel

# Login to your account
vercel login

# Deploy from the dailyme directory
cd /path/to/dailyme
vercel
```

### 2. Set Environment Variables

In Vercel Dashboard → Your Project → Settings → Environment Variables, add:

| Variable | Value | Where to use |
|----------|-------|--------------|
| `DATABASE_URL` | Your Neon Postgres connection string | Production, Preview, Development |
| `LLM_MODEL` | `openhands/claude-sonnet-4-5-20250929` | Not needed for web app (only pipeline) |
| `LLM_API_KEY` | Your OpenHands API key | Not needed for web app (only pipeline) |

**Important:** You only need `DATABASE_URL` for the web app. The LLM variables are only used in the pipeline (GitHub Actions).

**Your DATABASE_URL format:**
```
postgresql+asyncpg://[user]:[password]@[host]/[database]
```

### 3. Set Up Custom Domain

To use `news.rajivshah.com` (or any subdomain):

1. In Vercel Dashboard → Your Project → Settings → Domains
2. Click "Add Domain"
3. Enter `news.rajivshah.com`
4. Vercel will show you DNS records to add

**Add to your DNS (wherever rajivshah.com is registered):**
```
Type:  CNAME
Name:  news
Value: cname.vercel-dns.com
```

5. Wait for DNS propagation (usually < 5 minutes)
6. Vercel automatically provisions SSL certificate

### 4. Deploy!

If using dashboard: Click "Deploy" after setting environment variables.

If using CLI:
```bash
vercel --prod
```

### 5. Verify Deployment

Visit your new URL: `https://news.rajivshah.com`

You should see your personalized news feed! ✨

**Check these endpoints:**
- `https://news.rajivshah.com/` - Main feed
- `https://news.rajivshah.com/health` - Health check
- `https://news.rajivshah.com/stats` - Stats about your stories

## What About the Pipeline?

**No changes needed!** Your GitHub Actions workflow continues to run every 30 minutes, doing all the heavy compute:

- ✅ Fetching Gmail
- ✅ Parsing with LLM
- ✅ Deduplication
- ✅ Writing to Postgres

The Vercel app just **reads** from the database and serves HTML. Clean separation! 🎯

## Removing Railway

Once Vercel is working:

1. Verify everything works on Vercel
2. Go to Railway dashboard
3. Delete the `dailyme` service
4. 💰 Save money!

## Troubleshooting

### Issue: "Module not found" errors

**Fix:** Make sure `requirements.txt` is in the root directory and contains all dependencies.

### Issue: Database connection fails

**Fix:** 
1. Check that `DATABASE_URL` is set in Vercel environment variables
2. Make sure the connection string uses `postgresql+asyncpg://` (not just `postgresql://`)
3. Verify Neon database is accessible from Vercel's IP ranges (it should be by default)

### Issue: Static files not loading

**Fix:** Vercel should serve them from `app/static/`. If not, check the `vercel.json` routes configuration.

### Issue: First request is slow

**Explanation:** This is normal for serverless! The first request after idle time has a "cold start" (~2-3 seconds). Subsequent requests are fast. For a personal news feed, this is totally fine.

## Monitoring

Check Vercel's built-in monitoring:
- Dashboard → Your Project → Analytics
- See request counts, response times, errors

For the pipeline (GitHub Actions):
- Check runs at: https://github.com/[your-username]/dailyme/actions

## Cost Estimate

**Vercel Free Tier includes:**
- 100 GB bandwidth/month
- 100 GB-hours compute/month
- Unlimited requests

**Your usage (personal news feed):**
- ~10-50 requests/day → ~1,500/month
- Each request: < 100 KB
- Total bandwidth: < 150 MB/month

**Verdict:** Should stay well within free tier forever! 🎉

## Next Steps

1. ✅ Deploy to Vercel
2. ✅ Set up custom domain (news.rajivshah.com)
3. ✅ Verify everything works
4. ✅ Remove Railway
5. 🎉 Enjoy your self-hosted, dependency-free news feed!

---

## Questions?

- Vercel docs: https://vercel.com/docs
- DailyMe issues: https://github.com/[your-username]/dailyme/issues
