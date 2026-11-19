"""
Email delivery service for verification OTPs and secure password-reset links.

Strict Security:
- Never logs OTP codes or reset tokens to stdout/logs.
- Uses standard RFC 5322 MIME messages and STARTTLS/SSL for SMTP delivery.
- Fails securely if SMTP configuration is missing or transmission fails.
- Never falls back to logging codes in logs when unconfigured.
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# Testing hook for unit and integration testing without network
_mock_deliveries: list[dict] = []
_mock_mode: bool = False


def enable_mock_delivery(enabled: bool = True) -> None:
    """Toggle mock delivery mode for testing."""
    global _mock_mode
    _mock_mode = enabled
    if not enabled:
        _mock_deliveries.clear()


def get_mock_deliveries() -> list[dict]:
    """Retrieve captured mock email deliveries for test assertions."""
    return list(_mock_deliveries)


def clear_mock_deliveries() -> None:
    """Clear captured mock deliveries."""
    _mock_deliveries.clear()


def is_email_configured() -> bool:
    """Check if SMTP credentials are configured or mock mode is active."""
    if _mock_mode:
        return True
    return bool(settings.SMTP_HOST and settings.SMTP_HOST.strip())


def send_password_reset_otp_email(recipient_email: str, otp_code: str) -> None:
    """
    Send a 6-digit OTP code to the recipient's email address for password recovery.
    Does not log the OTP code.
    """
    if not is_email_configured():
        raise RuntimeError(
            "Email service is not configured. Please set SMTP_HOST, SMTP_PORT, SMTP_USER, "
            "and SMTP_PASSWORD in backend/.env"
        )

    subject = "Your Raahi Password Reset Code"
    text_content = (
        f"Hello,\n\n"
        f"We received a request to reset your password for your Raahi account.\n\n"
        f"Your 6-digit verification code is:\n"
        f"{otp_code}\n\n"
        f"This code will expire in 10 minutes.\n\n"
        f"If you did not request this password reset, please ignore this email.\n\n"
        f"— The Raahi Team"
    )

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #0d0a1a; color: #ffffff; margin: 0; padding: 24px; }}
    .container {{ max-width: 500px; margin: 0 auto; background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(168, 85, 247, 0.3); border-radius: 16px; padding: 32px; }}
    .header {{ font-size: 24px; font-weight: 700; color: #a855f7; margin-bottom: 12px; }}
    .code-box {{ display: inline-block; font-size: 32px; font-weight: 800; letter-spacing: 6px; padding: 14px 28px; background: rgba(168, 85, 247, 0.15); border: 1px solid rgba(168, 85, 247, 0.4); border-radius: 12px; color: #ec4899; margin: 20px 0; }}
    .footer {{ font-size: 13px; color: rgba(255, 255, 255, 0.6); margin-top: 24px; line-height: 1.5; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">Raahi ✨</div>
    <p>We received a request to reset your password.</p>
    <p>Your one-time 6-digit verification code is:</p>
    <div class="code-box">{otp_code}</div>
    <p>This code expires in <strong>10 minutes</strong>.</p>
    <p class="footer">If you did not request a password reset, you can safely ignore this email.</p>
  </div>
</body>
</html>"""

    _send_smtp_email(recipient_email, subject, text_content, html_content)


def send_password_reset_link_email(recipient_email: str, reset_url: str) -> None:
    """
    Send a secure password-reset link to the recipient's email address.
    Does not log the reset token or URL.
    """
    if not is_email_configured():
        raise RuntimeError(
            "Email service is not configured. Please set SMTP_HOST, SMTP_PORT, SMTP_USER, "
            "and SMTP_PASSWORD in backend/.env"
        )

    subject = "Reset Your Raahi Password"
    text_content = (
        f"Hello,\n\n"
        f"We received a request to reset your password for your Raahi account.\n\n"
        f"Click the link below to set a new password:\n"
        f"{reset_url}\n\n"
        f"This link will expire in 1 hour and can only be used once.\n\n"
        f"If you did not request this, please ignore this email.\n\n"
        f"— The Raahi Team"
    )

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #0d0a1a; color: #ffffff; margin: 0; padding: 24px; }}
    .container {{ max-width: 500px; margin: 0 auto; background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(168, 85, 247, 0.3); border-radius: 16px; padding: 32px; }}
    .header {{ font-size: 24px; font-weight: 700; color: #a855f7; margin-bottom: 12px; }}
    .button {{ display: inline-block; font-size: 16px; font-weight: 600; padding: 14px 28px; background: linear-gradient(135deg, #a855f7, #ec4899); border-radius: 999px; color: #ffffff; text-decoration: none; margin: 20px 0; }}
    .footer {{ font-size: 13px; color: rgba(255, 255, 255, 0.6); margin-top: 24px; line-height: 1.5; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">Raahi ✨</div>
    <p>We received a request to reset your password.</p>
    <p>Click the button below to choose a new password:</p>
    <p><a class="button" href="{reset_url}">Reset Password</a></p>
    <p>This link expires in <strong>1 hour</strong> and can only be used once.</p>
    <p class="footer">If you did not request a password reset, you can safely ignore this email.</p>
  </div>
</body>
</html>"""

    _send_smtp_email(recipient_email, subject, text_content, html_content)


def _send_smtp_email(to_email: str, subject: str, text_content: str, html_content: Optional[str] = None) -> None:
    if _mock_mode:
        _mock_deliveries.append({
            "to": to_email,
            "subject": subject,
            "text": text_content,
            "html": html_content,
        })
        logger.info("Mock email recorded for recipient domain: %s", to_email.split("@")[-1])
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    from_email = settings.SMTP_FROM_EMAIL
    if (not from_email or from_email == "noreply@raahi.app") and settings.SMTP_USER and "@" in settings.SMTP_USER:
        from_email = settings.SMTP_USER
    from_addr = f"{settings.SMTP_FROM_NAME} <{from_email}>" if settings.SMTP_FROM_NAME else from_email
    msg["From"] = from_addr
    msg["To"] = to_email

    msg.attach(MIMEText(text_content, "plain", "utf-8"))
    if html_content:
        msg.attach(MIMEText(html_content, "html", "utf-8"))

    server = None
    try:
        if settings.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15)
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15)
            if settings.SMTP_USE_TLS:
                server.starttls()

        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)

        server.sendmail(from_email, [to_email], msg.as_string())
        logger.info("Successfully dispatched email to recipient domain: %s", to_email.split("@")[-1])
    except Exception as exc:
        logger.error("Failed to send email via SMTP: %s", exc)
        raise RuntimeError(f"Could not send email: {exc}") from exc
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                try:
                    server.close()
                except Exception:
                    pass
