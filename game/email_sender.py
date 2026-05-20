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
