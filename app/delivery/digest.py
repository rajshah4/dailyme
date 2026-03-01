"""Daily digest: build and send the morning email."""

import logging
from datetime import datetime, timezone

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Content, Mail, To

from app.config import settings
from app.processing.ranker import RankedStory

logger = logging.getLogger(__name__)


def build_digest_html(stories: list[RankedStory], date: datetime) -> str:
    """Build the HTML email content for the daily digest."""
    date_str = date.strftime("%A, %B %d, %Y")

    stories_html = ""
    for i, story in enumerate(stories[:15], 1):
        link = f'<a href="{story.url}">{story.title}</a>' if story.url else story.title
        source = f" — via {story.newsletter_name}" if story.newsletter_name else ""
        coverage = (
            f' <span style="color:#888">(in {story.newsletter_count} newsletters)</span>'
            if story.newsletter_count > 1
            else ""
        )
        summary = f"<p style='color:#555;margin:4px 0 0 0'>{story.summary[:200]}...</p>" if story.summary else ""

        stories_html += f"""
        <div style="margin-bottom:20px;padding-bottom:16px;border-bottom:1px solid #eee">
            <div style="font-size:11px;color:#888;margin-bottom:4px">{story.topic_label}{source}{coverage}</div>
            <div style="font-size:16px;font-weight:600">{link}</div>
            {summary}
        </div>
        """

    return f"""
    <html>
    <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#222">
        <h1 style="font-size:24px;margin-bottom:4px">📰 DailyMe</h1>
        <p style="color:#888;margin-top:0">{date_str} · {len(stories)} stories</p>
        <hr style="border:none;border-top:2px solid #222;margin:16px 0">
        {stories_html}
        <p style="color:#aaa;font-size:12px;margin-top:32px">
            Built with OpenHands · Personalized AI news from your newsletters
        </p>
    </body>
    </html>
    """


def send_digest(stories: list[RankedStory]) -> bool:
    """Send the daily digest email via SendGrid."""
    if not settings.sendgrid_api_key:
        logger.warning("SendGrid API key not configured. Skipping digest send.")
        return False

    if not settings.digest_to_email:
        logger.warning("Digest recipient email not configured. Skipping.")
        return False

    now = datetime.now(timezone.utc)
    html = build_digest_html(stories, now)

    message = Mail(
        from_email=settings.digest_from_email,
        to_emails=To(settings.digest_to_email),
        subject=f"📰 DailyMe — {now.strftime('%b %d')} · {len(stories)} stories",
        html_content=Content("text/html", html),
    )

    try:
        sg = SendGridAPIClient(settings.sendgrid_api_key)
        response = sg.send(message)
        logger.info("Digest sent. Status: %s", response.status_code)
        return response.status_code in (200, 201, 202)
    except Exception:
        logger.exception("Failed to send digest email")
        return False
