"""Sends emails via the Gmail API using OAuth2.

Why Gmail API over SMTP: cloud platforms like Render block outbound SMTP
ports (465/587). The Gmail API is a regular HTTPS call so it works
everywhere without special firewall rules.

Required environment variables (generate once with scripts/generate_gmail_token.py):
    GMAIL_CLIENT_ID     — OAuth2 client ID from Google Cloud Console
    GMAIL_CLIENT_SECRET — OAuth2 client secret
    GMAIL_REFRESH_TOKEN — long-lived refresh token (never expires unless revoked)
    GMAIL_SENDER        — your Gmail address (shown in From field)

If any of these are missing, email functions log a warning and return False
so the game keeps running in demo mode without real email delivery.
"""
from __future__ import annotations

import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

# Human-readable pattern labels used in invite emails.
_PATTERN_LABELS: dict[str, str] = {
    "horizontal": "Any horizontal line",
    "vertical": "Any vertical line",
    "diagonal": "Any diagonal",
    "full_house": "Full house (entire card)",
    "row_1": "Row 1", "row_2": "Row 2", "row_3": "Row 3",
    "row_4": "Row 4", "row_5": "Row 5",
    "col_1": "Column 1", "col_2": "Column 2", "col_3": "Column 3",
    "col_4": "Column 4", "col_5": "Column 5",
    "diag_main": "Main diagonal ↘", "diag_anti": "Anti-diagonal ↙",
}


def _build_gmail_service(client_id: str, client_secret: str, refresh_token: str):
    """Return an authorised Gmail API service object.

    Uses a refresh token so no browser interaction is needed on the server.
    google-api-python-client and google-auth are already in requirements.txt
    (pulled in by google-generativeai).
    """
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/gmail.send"],
    )
    return build("gmail", "v1", credentials=creds)


def _send_via_gmail_api(
    to_address: str,
    subject: str,
    body_text: str,
    body_html: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    sender: str,
) -> bool:
    """Send a single email through the Gmail API. Returns True on success."""
    try:
        service = _build_gmail_service(client_id, client_secret, refresh_token)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = to_address
        msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        # Gmail API expects the raw RFC-2822 message base64url-encoded.
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()

        logger.info("Email sent to %s via Gmail API", to_address)
        return True

    except Exception:
        logger.exception("Gmail API error sending to %s", to_address)
        return False


def _gmail_credentials_from_config(
    client_id: str | None,
    client_secret: str | None,
    refresh_token: str | None,
    sender: str | None,
) -> bool:
    """Return True if all four Gmail API env vars are present."""
    if not all([client_id, client_secret, refresh_token, sender]):
        logger.warning(
            "Gmail API credentials incomplete — set GMAIL_CLIENT_ID, "
            "GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN, and GMAIL_SENDER "
            "to enable email delivery."
        )
        return False
    return True


def send_otp_email(
    to_address: str,
    otp_code: str,
    game_id: int,
    client_id: str | None,
    client_secret: str | None,
    refresh_token: str | None,
    sender: str | None,
    expiry_minutes: int = 10,
) -> bool:
    """Send a 6-digit OTP to ``to_address`` via the Gmail API.

    Returns True if the email was sent successfully, False otherwise.
    """
    if not _gmail_credentials_from_config(client_id, client_secret, refresh_token, sender):
        logger.warning("OTP for %s (game %d): %s", to_address, game_id, otp_code)
        return False

    subject = f"Your CGI Virtual Bingo verification code — Game #{game_id}"
    body_text = (
        f"Your one-time code is: {otp_code}\n\n"
        f"This code is valid for {expiry_minutes} minutes.\n\n"
        "If you did not request this code, you can safely ignore this email."
    )
    body_html = f"""
<html>
  <body style="font-family: system-ui, sans-serif; color: #1a1a2e; max-width: 480px; margin: 0 auto; padding: 24px;">
    <div style="background: #003da5; padding: 16px 24px; border-radius: 8px 8px 0 0;">
      <span style="color: white; font-size: 1.1rem; font-weight: 600;">CGI Virtual Bingo</span>
    </div>
    <div style="border: 1px solid #d0d5dd; border-top: none; padding: 24px; border-radius: 0 0 8px 8px;">
      <p style="margin-top: 0;">You're joining <strong>Game #{game_id}</strong>. Enter the code below to verify your identity:</p>
      <div style="background: #e8eef9; border: 1px solid #003da5; border-radius: 6px; padding: 16px; text-align: center; margin: 20px 0;">
        <span style="font-size: 2rem; font-weight: 700; letter-spacing: 0.4em; color: #003da5;">{otp_code}</span>
      </div>
      <p style="color: #5f6b7a; font-size: 0.9rem;">This code expires in {expiry_minutes} minutes. If you didn't request this, you can ignore this email.</p>
    </div>
  </body>
</html>
"""
    return _send_via_gmail_api(
        to_address, subject, body_text, body_html,
        client_id, client_secret, refresh_token, sender,  # type: ignore[arg-type]
    )


def send_invite_email(
    to_address: str,
    join_url: str,
    host_name: str,
    topic: str,
    pattern: str,
    game_id: int,
    client_id: str | None,
    client_secret: str | None,
    refresh_token: str | None,
    sender: str | None,
) -> bool:
    """Send a game invitation email containing the join link and game details.

    Returns True on successful delivery, False otherwise.
    """
    if not _gmail_credentials_from_config(client_id, client_secret, refresh_token, sender):
        logger.warning("Invite for %s (game %d): %s", to_address, game_id, join_url)
        return False

    pattern_label = _PATTERN_LABELS.get(pattern, pattern)
    subject = f"You're invited to play Virtual Bingo — Game #{game_id}"

    body_text = (
        f"{host_name} has invited you to a game of Virtual Bingo!\n\n"
        f"Topic:         {topic}\n"
        f"Win condition: {pattern_label}\n\n"
        f"Join link: {join_url}\n\n"
        "You will be asked to verify this email address when you join.\n"
        "If you did not expect this invitation, you can safely ignore it."
    )
    body_html = f"""
<html>
  <body style="font-family:system-ui,sans-serif;color:#1a1a2e;max-width:480px;margin:0 auto;padding:24px;">
    <div style="background:#cc0000;padding:16px 24px;border-radius:8px 8px 0 0;">
      <span style="color:white;font-size:1.05rem;font-weight:600;">CGI Virtual Bingo</span>
    </div>
    <div style="border:1px solid #e2e8f0;border-top:none;padding:24px;border-radius:0 0 8px 8px;">
      <p style="margin-top:0;font-size:1rem;">
        <strong>{host_name}</strong> has invited you to play <strong>Virtual Bingo</strong>!
      </p>
      <table style="width:100%;border-collapse:collapse;margin:16px 0;font-size:0.88rem;border:1px solid #e2e8f0;border-radius:6px;overflow:hidden;">
        <tr>
          <td style="padding:9px 14px;background:#f4f6fb;color:#64748b;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.05em;white-space:nowrap;">Topic</td>
          <td style="padding:9px 14px;background:#f4f6fb;font-weight:600;">{topic}</td>
        </tr>
        <tr>
          <td style="padding:9px 14px;background:#f8fafc;color:#64748b;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.05em;white-space:nowrap;">Win condition</td>
          <td style="padding:9px 14px;background:#f8fafc;">{pattern_label}</td>
        </tr>
      </table>
      <a href="{join_url}"
         style="display:block;background:#cc0000;color:white;text-decoration:none;
                text-align:center;padding:13px 24px;border-radius:7px;
                font-weight:600;font-size:0.95rem;margin:20px 0;">
        Join Game #{game_id} →
      </a>
      <p style="color:#94a3b8;font-size:0.82rem;margin-bottom:0;">
        You'll need to verify this email address when you join.
        If you didn't expect this, you can ignore it.
      </p>
    </div>
  </body>
</html>
"""
    return _send_via_gmail_api(
        to_address, subject, body_text, body_html,
        client_id, client_secret, refresh_token, sender,  # type: ignore[arg-type]
    )
