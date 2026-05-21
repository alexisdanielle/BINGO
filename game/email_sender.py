"""Sends OTP verification emails via Gmail SMTP.

Why smtplib over a third-party library: it ships with Python, requires no
extra pip install, and is straightforward to explain line-by-line. Gmail's
SSL port (465) is used because it requires no STARTTLS negotiation — simpler
and marginally harder to misconfigure.

Set SMTP_USER and SMTP_PASSWORD (a Google App Password) in your .env file.
If either is missing, ``send_otp_email`` logs a warning and returns False so
the game can keep running in demo mode without real email delivery.
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

_GMAIL_HOST = "smtp.gmail.com"
_GMAIL_PORT = 465  # SSL — no STARTTLS needed

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


def send_otp_email(
    to_address: str,
    otp_code: str,
    game_id: int,
    smtp_user: str | None,
    smtp_password: str | None,
    expiry_minutes: int = 10,
) -> bool:
    """Send a 6-digit OTP to ``to_address`` via Gmail SSL.

    Args:
        to_address: The player's email address.
        otp_code: The 6-digit code to include in the email.
        game_id: Shown in the email subject for context.
        smtp_user: Gmail address used as sender (from SMTP_USER env var).
        smtp_password: Google App Password (from SMTP_PASSWORD env var).
        expiry_minutes: How long the code is valid — shown in the email body.

    Returns:
        True if the email was sent successfully, False otherwise.
    """
    if not smtp_user or not smtp_password:
        # In local dev without SMTP credentials, log the code to the console
        # so you can still test the auth flow without a real email account.
        logger.warning(
            "SMTP credentials not set. OTP for %s (game %d): %s",
            to_address,
            game_id,
            otp_code,
        )
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

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_address
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP_SSL(_GMAIL_HOST, _GMAIL_PORT) as server:
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, to_address, msg.as_string())
        logger.info("OTP email sent to %s for game %d", to_address, game_id)
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error(
            "SMTP authentication failed. Check SMTP_USER / SMTP_PASSWORD in .env"
        )
        return False
    except Exception:
        logger.exception("Unexpected error sending OTP email to %s", to_address)
        return False


def send_invite_email(
    to_address: str,
    join_url: str,
    host_name: str,
    topic: str,
    pattern: str,
    game_id: int,
    smtp_user: str | None,
    smtp_password: str | None,
) -> bool:
    """Send a game invitation email containing the join link and game details.

    Called when the host opens the lobby so every invited player receives
    the link directly without the host needing to forward it manually.

    Returns True on successful delivery, False otherwise (same as send_otp_email).
    """
    if not smtp_user or not smtp_password:
        logger.warning(
            "SMTP not configured. Invite for %s (game %d): %s",
            to_address, game_id, join_url,
        )
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
      <span style="color:white;font-size:1.05rem;font-weight:600;">🎱 CGI Virtual Bingo</span>
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

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_address
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP_SSL(_GMAIL_HOST, _GMAIL_PORT) as server:
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, to_address, msg.as_string())
        logger.info("Invite email sent to %s for game %d", to_address, game_id)
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP auth failed sending invite to %s for game %d", to_address, game_id)
        return False
    except Exception:
        logger.exception("Error sending invite to %s for game %d", to_address, game_id)
        return False
