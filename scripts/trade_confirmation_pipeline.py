"""
Trade Confirmation Monitoring Pipeline
=======================================
Triggered by: OpenHands automation (Gmail Pub/Sub webhook event)

Flow:
  Gmail inbox → fetch recent trade confirmation emails
  → structured field extraction
  → LLM validation/judgment (traced in Laminar)
  → write to Google Sheet
  → print summary

Environment variables (all available as OpenHands secrets):
  GMAIL_TOKEN_JSON       - OAuth token (needs gmail.readonly + spreadsheets scopes)
  LMNR_PROJECT_API_KEY   - Laminar observability tracing
  ANTHROPIC_API_KEY      - Claude for validation reasoning
  TRADE_SHEET_ID         - Google Sheet ID to write results into
"""

import base64
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

# ── Laminar — init first so all LLM calls are traced ──────────────────────────
try:
    from lmnr import Laminar, observe
    _lmnr_key = os.environ.get("LMNR_PROJECT_API_KEY")
    if _lmnr_key:
        Laminar.initialize(project_api_key=_lmnr_key)
        print("✅ Laminar tracing active")
    else:
        print("⚠️  LMNR_PROJECT_API_KEY not set — tracing disabled")
        def observe(func=None, **kwargs):  # no-op decorator
            return func if func else lambda f: f
except ImportError:
    print("⚠️  lmnr not installed — run: uv add lmnr")
    def observe(func=None, **kwargs):
        return func if func else lambda f: f

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# ── Required fields for a valid trade confirmation ─────────────────────────────
REQUIRED_FIELDS = ["trade_id", "security_name", "trade_type", "quantity", "price",
                   "trade_date", "counterparty"]

SHEET_HEADERS = [
    "Status", "Trade ID", "Security", "CUSIP", "Type",
    "Quantity", "Price", "Trade Date", "Settlement Date",
    "Counterparty", "Portfolio", "Notes", "Email Subject", "Processed At"
]


# ── Gmail auth ─────────────────────────────────────────────────────────────────

def get_credentials() -> Credentials:
    token_env = os.environ.get("GMAIL_TOKEN_JSON", "")
    if not token_env:
        raise RuntimeError("GMAIL_TOKEN_JSON environment variable not set")

    data = json.loads(base64.b64decode(token_env).decode())
    scopes = data.get("scopes", [data.get("scope", "")])
    creds = Credentials.from_authorized_user_info(data, scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


# ── Gmail: fetch recent trade confirmation emails ──────────────────────────────

def fetch_recent_trade_emails(service, lookback_minutes: int = 30) -> list[dict]:
    """Fetch emails with TRADE CONFIRMATION in subject from the last N minutes."""
    after_ts = int((datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)).timestamp())
    query = f'subject:"TRADE CONFIRMATION" after:{after_ts}'

    result = service.users().messages().list(
        userId="me", q=query, maxResults=20
    ).execute()

    messages = result.get("messages", [])
    if not messages:
        print(f"No trade confirmation emails found in the last {lookback_minutes} minutes")
        return []

    emails = []
    for msg_ref in messages:
        msg = service.users().messages().get(
            userId="me", id=msg_ref["id"], format="full"
        ).execute()
        emails.append(msg)

    print(f"📬 Found {len(emails)} trade confirmation email(s)")
    return emails


def parse_email_body(msg: dict) -> tuple[str, str, str]:
    """Return (subject, from_address, body_text) from a Gmail message."""
    headers = msg.get("payload", {}).get("headers", [])
    subject = next((h["value"] for h in headers if h["name"].lower() == "subject"), "")
    from_addr = next((h["value"] for h in headers if h["name"].lower() == "from"), "")

    body = _extract_text(msg.get("payload", {}))
    return subject, from_addr, body


def _extract_text(payload: dict) -> str:
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace") if data else ""
    if mime == "text/html":
        data = payload.get("body", {}).get("data", "")
        if data:
            html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            return re.sub(r"<[^>]+>", " ", html)  # strip tags
    if "parts" in payload:
        for part in payload["parts"]:
            text = _extract_text(part)
            if text.strip():
                return text
    return ""


# ── Structured field extraction ────────────────────────────────────────────────

def extract_fields(body: str, subject: str) -> dict:
    """
    Fast regex-based extraction of trade confirmation fields.
    Handles common formats: key: value, key - value, key  value (tabular).
    """
    text = body + "\n" + subject

    def find(patterns: list[str], flags=re.IGNORECASE) -> Optional[str]:
        for pat in patterns:
            m = re.search(pat, text, flags)
            if m:
                return m.group(1).strip()
        return None

    trade_id = find([
        r"(?:trade\s*(?:id|ref(?:erence)?|#|number|no\.?))[\s:–\-]+([A-Z0-9\-]+)",
        r"TRD-(\d+)",
        r"REF[\s:]+([A-Z0-9\-]+)",
    ])
    if not trade_id:
        # Try subject line for TRD-XXXXXXX pattern
        m = re.search(r"TRD-[\d\-]+", subject, re.IGNORECASE)
        trade_id = m.group(0) if m else None

    security_name = find([
        r"(?:security|instrument|stock|asset)[\s:–\-]+([A-Za-z][A-Za-z0-9 &,.']+?)(?:\s*[\(\n\|]|$)",
    ])
    ticker = find([
        r"\(([A-Z]{1,5})\)",
        r"ticker[\s:]+([A-Z]{1,5})",
        r"symbol[\s:]+([A-Z]{1,5})",
    ])
    cusip = find([
        r"cusip[\s:]+([A-Z0-9]{9})",
        r"\b([A-Z0-9]{9})\b(?=.*cusip|\bCUSIP\b)",
    ])
    isin = find([r"isin[\s:]+([A-Z]{2}[A-Z0-9]{10})"])

    trade_type = find([
        r"(?:trade\s*type|action|side|direction)[\s:–\-]+(BUY|SELL|BUY TO OPEN|SELL TO CLOSE)",
        r"\b(BUY|SELL)\b",
    ])

    quantity_raw = find([
        r"(?:quantity|qty|shares?|units?|contracts?)[\s:–\-]+([\d,]+(?:\.\d+)?)",
        r"([\d,]+(?:\.\d+)?)\s+shares?",
    ])
    quantity = quantity_raw.replace(",", "") if quantity_raw else None

    price_raw = find([
        r"(?:price|px|rate)[\s:@–\-]+\$?([\d,]+(?:\.\d+)?)",
        r"\$\s*([\d,]+\.\d{2})\s*(?:per\s+share)?",
    ])
    price = price_raw.replace(",", "") if price_raw else None

    trade_date = find([
        r"(?:trade\s*date|execution\s*date|date(?:\s+of\s+trade)?)[\s:–\-]+([\d]{4}[-/][\d]{2}[-/][\d]{2}|[\d]{1,2}[-/][\d]{1,2}[-/][\d]{4})",
        r"(?:trade\s*date|execution\s*date)[\s:–\-]+(\w+ \d{1,2},? \d{4})",
    ])
    settlement_date = find([
        r"(?:settlement\s*date|settle\s*date|value\s*date)[\s:–\-]+([\d]{4}[-/][\d]{2}[-/][\d]{2}|[\d]{1,2}[-/][\d]{1,2}[-/][\d]{4})",
    ])
    counterparty = find([
        r"(?:counterparty|contra(?:\s*firm)?|broker|dealer)[\s:–\-]+([A-Za-z][A-Za-z0-9 &,.']+?)(?:\s*[\n\|]|$)",
    ])
    portfolio = find([
        r"(?:portfolio|account|fund|book|entity)[\s:–\-]+([A-Za-z0-9\-_]+)",
    ])
    trader = find([
        r"(?:trader|executed\s*by|salesperson)[\s:–\-]+([A-Za-z][A-Za-z .]+?)(?:\s*[\n\|]|$)",
    ])

    # Compose security display name
    security_display = security_name or ""
    if ticker and ticker not in (security_display or ""):
        security_display = f"{security_display} ({ticker})" if security_display else ticker

    return {
        "trade_id": trade_id,
        "security_name": security_display.strip() or None,
        "ticker": ticker,
        "cusip": cusip,
        "isin": isin,
        "trade_type": trade_type,
        "quantity": quantity,
        "price": price,
        "trade_date": trade_date,
        "settlement_date": settlement_date,
        "counterparty": counterparty,
        "portfolio": portfolio,
        "trader": trader,
    }


# ── LLM validation — this call shows up in Laminar ───────────────────────────

@observe(name="validate_trade_confirmation")
def validate_trade_with_llm(fields: dict, subject: str, body_snippet: str) -> tuple[str, str]:
    """
    Use Claude to reason about field completeness and flag anomalies.
    This call is traced in Laminar — the observability moment in the demo.
    """
    import anthropic

    missing = [f for f in REQUIRED_FIELDS if not fields.get(f)]
    extracted_summary = json.dumps({k: v for k, v in fields.items() if v}, indent=2)

    prompt = f"""You are a trade confirmation validation agent for a hedge fund.

EXTRACTED FIELDS:
{extracted_summary}

EMAIL SUBJECT: {subject}

EMAIL SNIPPET:
{body_snippet[:800]}

REQUIRED FIELDS: {', '.join(REQUIRED_FIELDS)}

MISSING REQUIRED FIELDS: {', '.join(missing) if missing else 'NONE'}

Your task:
1. Confirm whether all required fields are present and look valid
2. Flag any values that look suspicious or incorrectly parsed (e.g., obviously wrong price, future settlement that's before trade date)
3. Return a JSON response with exactly these keys:
   - "status": "CONFIRMED" or "EXCEPTION"
   - "notes": brief explanation (1-2 sentences max). If CONFIRMED and all looks good, say "All required fields validated."

Respond with ONLY the JSON object, no other text."""

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model="claude-3-5-haiku-20241022",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    try:
        result = json.loads(raw)
        status = result.get("status", "EXCEPTION")
        notes = result.get("notes", "Validation response unparseable")
    except json.JSONDecodeError:
        status = "EXCEPTION"
        notes = f"Validation error: {raw[:100]}"

    return status, notes


# ── Google Sheets writer ───────────────────────────────────────────────────────

def write_to_sheet(creds: Credentials, sheet_id: str, row: list) -> bool:
    """Append a row to the Google Sheet. Returns True on success."""
    try:
        sheets_service = build("sheets", "v4", credentials=creds)
        sheets_service.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range="Sheet1!A:N",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()
        return True
    except Exception as e:
        print(f"⚠️  Google Sheets write failed: {e}")
        print("   (If this is a scope error, re-run OAuth with spreadsheets scope)")
        return False


def format_sheet_row(status: str, fields: dict, subject: str, notes: str) -> list:
    status_icon = "✅ CONFIRMED" if status == "CONFIRMED" else "⚠️ EXCEPTION"
    return [
        status_icon,
        fields.get("trade_id") or "",
        fields.get("security_name") or "",
        fields.get("cusip") or fields.get("isin") or "",
        fields.get("trade_type") or "",
        fields.get("quantity") or "",
        fields.get("price") or "",
        fields.get("trade_date") or "",
        fields.get("settlement_date") or "",
        fields.get("counterparty") or "",
        fields.get("portfolio") or "",
        notes,
        subject,
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    ]


# ── Deduplication: check if Trade ID already in Sheet ─────────────────────────

def already_processed(creds: Credentials, sheet_id: str, trade_id: str) -> bool:
    """Return True if this trade_id already exists in column B of the sheet."""
    if not trade_id:
        return False
    try:
        sheets_service = build("sheets", "v4", credentials=creds)
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=sheet_id, range="Sheet1!B:B"
        ).execute()
        existing_ids = [r[0] for r in result.get("values", []) if r]
        return trade_id in existing_ids
    except Exception:
        return False  # assume not processed if we can't check


# ── Main pipeline ──────────────────────────────────────────────────────────────

def main():
    sheet_id = os.environ.get("TRADE_SHEET_ID", "")
    lookback = int(os.environ.get("TRADE_LOOKBACK_MINUTES", "30"))

    print("=" * 60)
    print("  TRADE CONFIRMATION MONITORING PIPELINE")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)

    if not sheet_id:
        print("⚠️  TRADE_SHEET_ID not set — will extract and print, skip Sheets write")

    creds = get_credentials()
    gmail_service = build("gmail", "v1", credentials=creds)

    emails = fetch_recent_trade_emails(gmail_service, lookback_minutes=lookback)
    if not emails:
        print("Nothing to process. Done.")
        return

    processed = skipped = errors = 0

    for msg in emails:
        subject, from_addr, body = parse_email_body(msg)
        print(f"\n{'─'*60}")
        print(f"📧 Subject : {subject}")
        print(f"   From    : {from_addr}")

        fields = extract_fields(body, subject)
        trade_id = fields.get("trade_id")

        # Dedup check
        if sheet_id and trade_id and already_processed(creds, sheet_id, trade_id):
            print(f"⏭️  Trade {trade_id} already in Sheet — skipping")
            skipped += 1
            continue

        # Print extracted fields
        print("\n  EXTRACTED FIELDS:")
        for k, v in fields.items():
            if v:
                print(f"    {k:20} {v}")

        # LLM validation (Laminar traces this call)
        print("\n  🤖 Running LLM validation...")
        try:
            status, notes = validate_trade_with_llm(fields, subject, body)
        except Exception as e:
            status, notes = "EXCEPTION", f"Validation error: {e}"

        icon = "✅" if status == "CONFIRMED" else "⚠️ "
        print(f"  {icon} Status : {status}")
        print(f"     Notes  : {notes}")

        # Write to Google Sheet
        if sheet_id:
            row = format_sheet_row(status, fields, subject, notes)
            success = write_to_sheet(creds, sheet_id, row)
            if success:
                print(f"  📊 Written to Google Sheet")
            processed += 1
        else:
            print(f"\n  [Sheet write skipped — set TRADE_SHEET_ID to enable]")
            processed += 1

    print(f"\n{'='*60}")
    print(f"  SUMMARY: {processed} processed | {skipped} skipped (already in sheet) | {errors} errors")
    print("=" * 60)


if __name__ == "__main__":
    main()
