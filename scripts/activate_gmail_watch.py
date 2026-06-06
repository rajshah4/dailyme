"""
Activate Gmail push notifications → Pub/Sub → OpenHands webhook.

Run this:
  - Once after completing Pub/Sub setup (gcloud commands in HUDSON_BAY_DEMO.md)
  - Again before the Hudson Bay demo if more than 7 days have passed (watch expires)

Usage:
    uv run python scripts/activate_gmail_watch.py
"""

import base64
import json
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

PUBSUB_TOPIC = "projects/dailyme-488917/topics/trade-confirmations"


def main():
    token_env = os.environ.get("GMAIL_TOKEN_JSON", "")
    if not token_env:
        raise RuntimeError("GMAIL_TOKEN_JSON environment variable not set")

    data = json.loads(base64.b64decode(token_env).decode())
    scopes = data.get("scopes", [data.get("scope", "")])
    creds = Credentials.from_authorized_user_info(data, scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    service = build("gmail", "v1", credentials=creds)

    print(f"Activating Gmail watch on inbox → {PUBSUB_TOPIC}")

    result = service.users().watch(
        userId="me",
        body={
            "topicName": PUBSUB_TOPIC,
            "labelIds": ["INBOX"],
            "labelFilterBehavior": "INCLUDE",
        },
    ).execute()

    import datetime
    expiry_ms = int(result["expiration"])
    expiry_dt = datetime.datetime.fromtimestamp(expiry_ms / 1000, tz=datetime.timezone.utc)

    print()
    print("✅ Gmail watch active")
    print(f"   historyId : {result['historyId']}")
    print(f"   expires   : {expiry_dt.strftime('%Y-%m-%d %H:%M UTC')}  ← renew before this")
    print()
    print("The full pipeline is now live:")
    print("  Send email with 'TRADE CONFIRMATION' in subject to raj@rajivshah.com")
    print("  → Pub/Sub fires → OpenHands automation triggers → Sheet gets a row")
    print()
    print("To test end to end:")
    print("  uv run python scripts/send_test_trade_email.py        # clean trade")
    print("  uv run python scripts/send_test_trade_email.py --bad  # exception trade")


if __name__ == "__main__":
    main()
