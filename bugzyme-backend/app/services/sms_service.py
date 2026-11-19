"""
SMS delivery service for phone registration OTP verification using Twilio REST API.

Strict Security:
- Never logs OTP codes to stdout/logs.
- Sanitizes phone numbers in log messages.
- Uses official Twilio REST API without adding external dependencies.
- Fails securely if Twilio credentials are missing or transmission fails.
"""
from __future__ import annotations

import base64
import json
import logging
import urllib.parse
import urllib.request
import urllib.error
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


def is_sms_configured() -> bool:
    """Check if real Twilio SMS provider credentials are configured."""
    return bool(
        settings.TWILIO_ACCOUNT_SID
        and settings.TWILIO_AUTH_TOKEN
        and settings.TWILIO_PHONE_NUMBER
    )


def sanitize_phone_for_log(phone: str) -> str:
    """Mask phone number for privacy in logs (e.g. +91*****4321)."""
    clean = phone.strip()
    if len(clean) > 6:
        return f"{clean[:3]}*****{clean[-4:]}"
    return "****"


def send_sms_otp(phone_number: str, otp_code: str) -> None:
    """
    Dispatch a 6-digit OTP code to the recipient's phone number via Twilio SMS API.
    Does not log the OTP code.
    """
    if not is_sms_configured():
        raise RuntimeError(
            "SMS service is not configured. Please set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, "
            "and TWILIO_PHONE_NUMBER in backend/.env"
        )

    # Twilio Messages REST endpoint
    url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Messages.json"

    body_text = f"Your Raahi verification code is: {otp_code}. Valid for 5 minutes. Do not share this code."

    data = urllib.parse.urlencode({
        "To": phone_number.strip(),
        "From": settings.TWILIO_PHONE_NUMBER.strip(),
        "Body": body_text,
    }).encode("utf-8")

    # Basic auth with AccountSid:AuthToken
    auth_str = f"{settings.TWILIO_ACCOUNT_SID}:{settings.TWILIO_AUTH_TOKEN}"
    auth_b64 = base64.b64encode(auth_str.encode("utf-8")).decode("ascii")

    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Basic {auth_b64}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )

    masked_phone = sanitize_phone_for_log(phone_number)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_body = json.loads(resp.read().decode("utf-8"))
            sid = resp_body.get("sid", "unknown")
            logger.info("Successfully dispatched SMS OTP via Twilio to %s (SID: %s)", masked_phone, sid)
    except urllib.error.HTTPError as exc:
        err_msg = exc.read().decode("utf-8", errors="replace")
        logger.error("Twilio SMS request failed for %s: %d - %s", masked_phone, exc.code, err_msg)
        raise RuntimeError(f"Twilio SMS delivery failed ({exc.code}): {err_msg}") from exc
    except Exception as exc:
        logger.error("Twilio SMS network error for %s: %s", masked_phone, exc)
        raise RuntimeError(f"Twilio SMS delivery network error: {exc}") from exc
