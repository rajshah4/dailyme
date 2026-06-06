# Hudson Bay Demo — Trade Confirmation Monitoring
## Setup & Status Document

> **Purpose:** Live demo for Jinyoung Kim (Hudson Bay Capital) showing OpenHands as an
> agent control plane for business workflows, not just coding tasks.
>
> **Demo narrative:** Send a trade confirmation email → agent fires in seconds →
> extracts fields → Claude validates → row appears in Google Sheet → Laminar shows the trace.

---

## What's Already Built & Live

### OpenHands Infrastructure (already deployed, nothing to recreate)

| Component | ID / Value |
|---|---|
| **Webhook ID** | `6a1e457b-6920-4c00-b641-e6dbef0acfd0` |
| **Webhook URL** | `https://app.all-hands.dev/api/automation/v1/events/4aa504f5-4108-48a0-9edf-408f7f98f9ec/gmail-pubsub` |
| **Automation ID** | `aabf8563-f55a-41ab-ad5f-09f0a28718b9` |
| **Automation name** | Trade Confirmation Monitor — Hudson Bay Demo |
| **Trigger** | Event / `gmail-pubsub` source |
| **Fires on** | `projects/dailyme-488917/subscriptions/trade-confirmations-push` |

### Code in This Repo

| File | Purpose |
|---|---|
| `scripts/trade_confirmation_pipeline.py` | Main pipeline: Gmail → extract → Claude validate → Sheets write |
| `scripts/send_test_trade_email.py` | Sends synthetic clean + exception trade emails for demo day |

### External Resources

| Resource | Value |
|---|---|
| **Gmail account** | `raj@rajivshah.com` |
| **GCP Project ID** | `dailyme-488917` |
| **GCP Project Number** | `433110665490` |
| **Pub/Sub topic** | `projects/dailyme-488917/topics/trade-confirmations` *(to be created)* |
| **Pub/Sub subscription** | `projects/dailyme-488917/subscriptions/trade-confirmations-push` *(to be created)* |
| **Google Sheet** | `1syj7m-Enbt1qpuxlAS5BkmEKQGsoVkLCc8Wek1FvFP8` |
| **Sheet URL** | https://docs.google.com/spreadsheets/d/1syj7m-Enbt1qpuxlAS5BkmEKQGsoVkLCc8Wek1FvFP8/edit |

### OpenHands Secrets Required

These must be set in [OpenHands Settings → Secrets](https://app.all-hands.dev):

| Secret name | What it is |
|---|---|
| `GMAIL_TOKEN_JSON` | Base64-encoded OAuth token — **needs expanded scopes** (see Step 2 below) |
| `ANTHROPIC_API_KEY` | Claude API key for trade validation LLM call |
| `LMNR_PROJECT_API_KEY` | Laminar project key for observability traces |

---

## Remaining Setup Steps (run on your machine)

### Step 1 — Pub/Sub Setup (4 gcloud commands)

Run from any machine authenticated to GCP with `dailyme-488917`:

```bash
PROJECT_ID=dailyme-488917
WEBHOOK_URL="https://app.all-hands.dev/api/automation/v1/events/4aa504f5-4108-48a0-9edf-408f7f98f9ec/gmail-pubsub"

# Enable Pub/Sub API
gcloud services enable pubsub.googleapis.com --project=$PROJECT_ID

# Create the topic Gmail will push to
gcloud pubsub topics create trade-confirmations --project=$PROJECT_ID

# Grant Gmail's service account permission to publish
gcloud pubsub topics add-iam-policy-binding trade-confirmations \
  --project=$PROJECT_ID \
  --member="serviceAccount:gmail-api-push@system.gserviceaccount.com" \
  --role="roles/pubsub.publisher"

# Create push subscription → OpenHands webhook URL
gcloud pubsub subscriptions create trade-confirmations-push \
  --topic=trade-confirmations \
  --push-endpoint="$WEBHOOK_URL" \
  --ack-deadline=60 \
  --project=$PROJECT_ID
```

**Verify it worked:**
```bash
gcloud pubsub subscriptions describe trade-confirmations-push --project=$PROJECT_ID
```
You should see `pushConfig.pushEndpoint` pointing to the OpenHands webhook URL.

---

### Step 2 — Expand OAuth Scopes (for Google Sheets write)

The current `GMAIL_TOKEN_JSON` secret only has `gmail.readonly`. The pipeline also needs
`spreadsheets` scope to write to the Google Sheet.

**You need:** `credentials.json` from the GCP Console for project `dailyme-488917`.
Get it from: GCP Console → APIs & Services → Credentials → OAuth 2.0 Client → Download JSON

Save this as `expand_oauth.py` and run it locally:

```python
from google_auth_oauthlib.flow import InstalledAppFlow
import base64

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",       # for send_test_trade_email.py
    "https://www.googleapis.com/auth/spreadsheets",     # write rows to Google Sheet
    "https://www.googleapis.com/auth/drive.file",       # access the sheet in Drive
]

flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
creds = flow.run_local_server(port=0)

print("\n=== COPY THIS INTO OPENHANDS → Settings → Secrets → GMAIL_TOKEN_JSON ===\n")
print(base64.b64encode(creds.to_json().encode()).decode())
```

Paste the output into OpenHands Settings → Secrets → `GMAIL_TOKEN_JSON`.

---

### Step 3 — Activate Gmail Push Notifications (watch)

**Do this after Step 1 is complete.** Run from any Python environment with the repo installed:

```bash
cd dailyme
uv sync
uv run python scripts/activate_gmail_watch.py
```

Or run this snippet directly (after `uv sync`):

```python
import os, json, base64
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

token_env = os.environ.get("GMAIL_TOKEN_JSON", "")
data = json.loads(base64.b64decode(token_env).decode())
creds = Credentials.from_authorized_user_info(data, data.get("scopes", []))
if creds.expired: creds.refresh(Request())

service = build("gmail", "v1", credentials=creds)
result = service.users().watch(
    userId="me",
    body={
        "topicName": "projects/dailyme-488917/topics/trade-confirmations",
        "labelIds": ["INBOX"],
        "labelFilterBehavior": "INCLUDE",
    }
).execute()

print("✅ Gmail watch active")
print("   historyId :", result["historyId"])
print("   expires   :", result["expiration"], "(renew within 7 days)")
```

> ⚠️ **Watch expires after 7 days.** Re-run this before the Hudson Bay meeting if
> more than a week has passed since you last ran it.

---

### Step 4 — Prep the Google Sheet

Open the sheet and make sure Row 1 has these exact headers (the pipeline appends
after row 1, so they won't be overwritten):

| A | B | C | D | E | F | G | H | I | J | K | L | M | N |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Status | Trade ID | Security | CUSIP | Type | Quantity | Price | Trade Date | Settlement Date | Counterparty | Portfolio | Notes | Email Subject | Processed At |

Sheet URL: https://docs.google.com/spreadsheets/d/1syj7m-Enbt1qpuxlAS5BkmEKQGsoVkLCc8Wek1FvFP8/edit

---

## End-to-End Test (run after all steps complete)

```bash
cd dailyme
uv sync

# Test 1: clean trade (should write ✅ CONFIRMED row)
uv run python scripts/send_test_trade_email.py

# Wait ~5–10 seconds, then check:
# 1. OpenHands conversation fired: https://app.all-hands.dev
# 2. Row appeared in Sheet: https://docs.google.com/spreadsheets/d/1syj7m-Enbt1qpuxlAS5BkmEKQGsoVkLCc8Wek1FvFP8
# 3. Laminar trace visible: https://app.lmnr.ai

# Test 2: exception trade (should write ⚠️ EXCEPTION row — quantity missing)
uv run python scripts/send_test_trade_email.py --bad
```

**Expected Sheet result after both tests:**

| Status | Trade ID | Security | ... |
|---|---|---|---|
| ✅ CONFIRMED | TRD-2024-089234 | Apple Inc. (AAPL) | ... |
| ⚠️ EXCEPTION | TRD-2024-089235 | Microsoft Corp. (MSFT) | ... |

---

## Demo Day Script (45-min Hudson Bay meeting)

### Pre-meeting checklist (do 30 min before)
- [ ] Gmail watch is active (re-run Step 3 if meeting is 7+ days after initial setup)
- [ ] Sheet is open in a browser tab, row 2+ is empty (clear old test rows)
- [ ] OpenHands Automations tab open: https://app.all-hands.dev
- [ ] Laminar dashboard open: https://app.lmnr.ai
- [ ] Both synthetic emails ready to send (keep `send_test_trade_email.py` in terminal)
- [ ] Slides ready for context-setting

### Meeting flow

**0–5 min — Context**
- Recap Jinyoung's 3 use cases (research summarizer, LP questionnaire, trade confirmations)
- Frame today: "We're going to run the trade confirmation one live, right now"

**5–20 min — Live demo**

1. Show the Gmail inbox (`raj@rajivshah.com`) on screen — it's empty of trade emails
2. Run: `uv run python scripts/send_test_trade_email.py`
3. Show the email arriving in Gmail (subject: `TRADE CONFIRMATION - TRD-2024-089234`)
4. Say: *"The agent is watching this inbox. Watch what happens..."*
5. Switch to OpenHands — show the conversation starting automatically (~5 sec)
6. Let it run live — audience watches the agent reason through the extraction
7. Switch to Google Sheet — show the ✅ CONFIRMED row appear
8. Now run: `uv run python scripts/send_test_trade_email.py --bad`
9. Repeat — show the ⚠️ EXCEPTION row with "quantity missing" note
10. Say: *"A rigid pipeline would crash or fail silently. This agent reasoned about the
    missing field and flagged it for human review — no code change needed."*

**20–30 min — Laminar (observability)**
- Flip to Laminar dashboard
- Show the two traces side by side — the Claude validation call for each email
- Show: tokens used, latency, the prompt + response
- Say: *"This is the same observability story as LangSmith — but native to the execution environment"*

**30–40 min — Architecture & positioning**
- Show the architecture slide
- OpenHands vs LangGraph/LangSmith positioning (complement, not replace)
- Self-hosting on Azure path

**40–45 min — Next steps**
- Agree on 1 pilot workflow
- Technical follow-up: Azure self-hosted setup

### Key talking points
- *"Non-developer users can trigger and review agent runs without writing code"*
- *"The agent handles the exception case — that's the value over a deterministic pipeline"*
- *"Laminar gives you full observability: every LLM call, every token, full audit trail"*
- *"This can run on-prem in your Azure environment — open source, self-hostable"*

---

## Architecture Diagram

```
raj@rajivshah.com (Gmail inbox)
          │
          │  Gmail push notifications (watch API)
          ▼
Google Cloud Pub/Sub
  topic: trade-confirmations
  subscription: trade-confirmations-push
          │
          │  HTTPS POST (push subscription)
          ▼
OpenHands Webhook
  https://app.all-hands.dev/api/automation/v1/events/.../gmail-pubsub
          │
          │  Event matches → fires automation aabf8563
          ▼
OpenHands Conversation (visible in UI)
  - Clones rajshah4/dailyme
  - uv sync
  - Runs trade_confirmation_pipeline.py
          │
    ┌─────┴──────┐
    ▼            ▼
Gmail API    Anthropic Claude (via ANTHROPIC_API_KEY)
(fetch email)  (validate fields — traced in Laminar)
                     │
                     ▼
             Google Sheets API
             (append row to Sheet)
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Automation doesn't fire after email | Check watch() is still active (7-day expiry). Re-run Step 3. |
| Automation fires but Sheets write fails | OAuth token missing `spreadsheets` scope. Re-run Step 2. |
| `watch()` returns 404 on topic | Pub/Sub topic not created yet. Run Step 1. |
| Automation fires but can't find email | `TRADE_LOOKBACK_MINUTES` too short. Default is 15 — increase if needed. |
| Duplicate rows in Sheet | Dedup is by Trade ID. Check if you sent the same test email twice. |
| Laminar traces not showing | Verify `LMNR_PROJECT_API_KEY` is set in OpenHands secrets. |
| `send_test_trade_email.py` fails with 403 | Token missing `gmail.send` scope. Re-run Step 2. |
