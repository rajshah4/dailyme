"""
Demo: Send Synthetic Trade Confirmation Emails
===============================================
Sends realistic trade confirmation emails to raj@rajivshah.com
to trigger the OpenHands trade monitoring automation live on stage.

Usage:
    uv run python scripts/send_test_trade_email.py           # sends clean trade
    uv run python scripts/send_test_trade_email.py --bad     # sends exception trade (missing qty)
    uv run python scripts/send_test_trade_email.py --both    # sends both (clean then bad)
"""

import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


def get_gmail_service():
    token_env = os.environ.get("GMAIL_TOKEN_JSON", "")
    if not token_env:
        raise RuntimeError("GMAIL_TOKEN_JSON not set")
    data = json.loads(base64.b64decode(token_env).decode())
    scopes = data.get("scopes", [data.get("scope", "")])
    creds = Credentials.from_authorized_user_info(data, scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


CLEAN_TRADE = """\
From: operations@goldmansachs-confirm.com
To: raj@rajivshah.com
Subject: TRADE CONFIRMATION - TRD-2024-089234

════════════════════════════════════════════════════
           GOLDMAN SACHS — TRADE CONFIRMATION
════════════════════════════════════════════════════

Trade Reference:    TRD-2024-089234
Status:             CONFIRMED

SECURITY DETAILS
────────────────────────────────────────────────────
Security:           Apple Inc. (AAPL)
CUSIP:              037833100
ISIN:               US0378331005

TRADE DETAILS
────────────────────────────────────────────────────
Trade Type:         BUY
Quantity:           50,000 shares
Price:              $184.25 per share
Gross Value:        $9,212,500.00
Fees & Commission:  $4,606.25
Net Settlement:     $9,217,106.25

DATES
────────────────────────────────────────────────────
Trade Date:         2024-06-05
Settlement Date:    2024-06-07 (T+2)

PARTIES
────────────────────────────────────────────────────
Counterparty:       Goldman Sachs & Co. LLC
Broker:             Morgan Stanley Execution
Portfolio:          HBCM-EQUITY-01
Account:            HBC-7741-EQ
Trader:             J. Smith

════════════════════════════════════════════════════
This confirmation is subject to the terms of your
ISDA Master Agreement. Please confirm receipt.
Questions: tradeops@goldmansachs-confirm.com
════════════════════════════════════════════════════
"""

BAD_TRADE = """\
From: operations@morganstanley-confirm.com
To: raj@rajivshah.com
Subject: TRADE CONFIRMATION - TRD-2024-089235

════════════════════════════════════════════════════
         MORGAN STANLEY — TRADE CONFIRMATION
════════════════════════════════════════════════════

Trade Reference:    TRD-2024-089235
Status:             PENDING REVIEW

SECURITY DETAILS
────────────────────────────────────────────────────
Security:           Microsoft Corp. (MSFT)
CUSIP:              594918104

TRADE DETAILS
────────────────────────────────────────────────────
Trade Type:         SELL
Quantity:           [FIELD MISSING — SYSTEM ERROR]
Price:              $415.80 per share

DATES
────────────────────────────────────────────────────
Trade Date:         2024-06-05
Settlement Date:    2024-06-07 (T+2)

PARTIES
────────────────────────────────────────────────────
Counterparty:       Morgan Stanley & Co.
Portfolio:          HBCM-EQUITY-02
Trader:             A. Chen

════════════════════════════════════════════════════
NOTE: This confirmation has a data quality issue.
Please contact your prime broker immediately.
════════════════════════════════════════════════════
"""


def send_email(service, subject: str, body: str, label: str) -> str:
    """Send an email to self (raj@rajivshah.com) and return the message ID."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = "raj@rajivshah.com"
    msg["To"] = "raj@rajivshah.com"
    msg.attach(MIMEText(body, "plain"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()

    msg_id = result.get("id")
    print(f"  ✅ Sent [{label}] — Gmail Message ID: {msg_id}")
    return msg_id


def main():
    mode = "--both" if "--both" in sys.argv else ("--bad" if "--bad" in sys.argv else "--clean")

    print("🚀 Sending demo trade confirmation email(s) to raj@rajivshah.com")
    print(f"   Mode: {mode}")
    print()

    service = get_gmail_service()

    if mode in ("--clean", "--both"):
        send_email(
            service,
            subject="TRADE CONFIRMATION - TRD-2024-089234",
            body=CLEAN_TRADE,
            label="CLEAN — Apple AAPL BUY 50,000 @ $184.25",
        )

    if mode in ("--bad", "--both"):
        send_email(
            service,
            subject="TRADE CONFIRMATION - TRD-2024-089235",
            body=BAD_TRADE,
            label="EXCEPTION — Microsoft MSFT SELL (QUANTITY MISSING)",
        )

    print()
    print("📬 Email(s) sent. Watch the OpenHands automation fire within seconds.")
    print("   → https://app.all-hands.dev  (Automations tab)")
    print("   → https://app.lmnr.ai        (Laminar traces)")


if __name__ == "__main__":
    main()
