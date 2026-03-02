"""Gmail API client for polling the dedicated newsletter inbox."""

import base64
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from app.config import settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

LABEL_NAME = "DailyMe"


@dataclass
class EmailMessage:
    gmail_id: str
    subject: str
    from_address: str
    received_at: datetime
    html_body: str | None
    text_body: str | None


def get_gmail_service():
    """Authenticate and return a Gmail API service.

    Credentials can come from:
    1. GMAIL_TOKEN_JSON env var (base64-encoded token.json content — for cloud)
    2. token.json file on disk (local dev)
    3. OAuth flow via credentials.json (initial setup only)
    """
    creds = None
    token_path = Path(settings.gmail_token_json)
    creds_path = Path(settings.gmail_credentials_json)

    # Cloud path: load from env var
    token_env = os.environ.get("GMAIL_TOKEN_JSON")
    if token_env:
        try:
            token_data = base64.b64decode(token_env).decode()
            creds = Credentials.from_authorized_user_info(json.loads(token_data), SCOPES)
            logger.info("Loaded Gmail credentials from GMAIL_TOKEN_JSON env var")
        except Exception as e:
            logger.warning("Failed to load GMAIL_TOKEN_JSON env var: %s", e)

    # Local path: load from file
    if not creds and token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Persist refreshed token
            if token_env:
                # Update env var hint — actual persistence is in Railway/etc
                logger.info("Token refreshed (update GMAIL_TOKEN_JSON env var if needed)")
            elif token_path.parent.exists():
                token_path.write_text(creds.to_json())
        else:
            if not creds_path.exists():
                raise FileNotFoundError(
                    f"Gmail credentials not found at {creds_path}. "
                    "Download from Google Cloud Console or set GMAIL_TOKEN_JSON env var."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)
            token_path.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def _extract_header(headers: list[dict], name: str) -> str:
    """Extract a header value from Gmail message headers."""
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _extract_body(payload: dict) -> tuple[str | None, str | None]:
    """Extract HTML and text body from Gmail message payload.

    Handles both simple and multipart MIME structures.
    """
    html_body = None
    text_body = None

    mime_type = payload.get("mimeType", "")

    if mime_type == "text/html":
        data = payload.get("body", {}).get("data", "")
        if data:
            html_body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    elif mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            text_body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    elif "parts" in payload:
        for part in payload["parts"]:
            h, t = _extract_body(part)
            if h:
                html_body = h
            if t:
                text_body = t

    return html_body, text_body


def _get_label_id(service) -> str | None:
    """Find the DailyMe label ID."""
    labels = service.users().labels().list(userId="me").execute()
    for label in labels.get("labels", []):
        if label["name"] == LABEL_NAME:
            return label["id"]
    return None


def fetch_labeled_emails(service=None, max_results: int = 20, max_age_days: int = 7) -> list[EmailMessage]:
    """Fetch emails with the DailyMe label from the last max_age_days."""
    if service is None:
        service = get_gmail_service()

    label_id = _get_label_id(service)
    if not label_id:
        logger.error("Label '%s' not found in Gmail. Create it first.", LABEL_NAME)
        return []

    # Only fetch emails newer than max_age_days
    after_date = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).strftime("%Y/%m/%d")
    results = service.users().messages().list(
        userId="me",
        labelIds=[label_id],
        q=f"after:{after_date}",
        maxResults=max_results,
    ).execute()

    messages = results.get("messages", [])
    if not messages:
        logger.info("No emails with label '%s'.", LABEL_NAME)
        return []

    emails = []
    for msg_ref in messages:
        msg = service.users().messages().get(
            userId="me",
            id=msg_ref["id"],
            format="full",
        ).execute()

        headers = msg.get("payload", {}).get("headers", [])
        subject = _extract_header(headers, "Subject")
        from_addr = _extract_header(headers, "From")
        date_str = _extract_header(headers, "Date")

        try:
            received_at = parsedate_to_datetime(date_str)
        except (ValueError, TypeError):
            received_at = datetime.now(timezone.utc)

        html_body, text_body = _extract_body(msg.get("payload", {}))

        emails.append(EmailMessage(
            gmail_id=msg["id"],
            subject=subject,
            from_address=from_addr,
            received_at=received_at,
            html_body=html_body,
            text_body=text_body,
        ))

    logger.info("Fetched %d emails with label '%s'.", len(emails), LABEL_NAME)
    return emails


# Keep old name as alias for pipeline compatibility
fetch_unread_emails = fetch_labeled_emails


def mark_as_read(service, gmail_id: str):
    """No-op for readonly scope. Label stays; pipeline uses gmail_id for idempotency."""
    logger.debug("Readonly scope — skipping mark_as_read for %s", gmail_id)
