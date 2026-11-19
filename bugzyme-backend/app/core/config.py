"""Application configuration loaded from environment and .env."""
import os
from pathlib import Path
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BACKEND_DIR / ".env", override=False)
load_dotenv(override=False)


def _safe_int(val: str | None, default: int) -> int:
    if val is None:
        return default
    try:
        cleaned = str(val).strip(' "\'')
        return int(cleaned) if cleaned else default
    except Exception:
        return default


class Settings:
    # Core app & security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "temporary-insecure-secret-key-change-in-production-min32chars")
    TOKEN_TTL_HOURS: int = _safe_int(os.getenv("TOKEN_TTL_HOURS", "24"), 24)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:5173")

    # Google OAuth 2.0 & OpenID Connect
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_AUTH_REDIRECT_URI: str = os.getenv("GOOGLE_AUTH_REDIRECT_URI", "")
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "")

    # Email Service (SMTP)
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = _safe_int(os.getenv("SMTP_PORT", "587"), 587)
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM_EMAIL: str = os.getenv("SMTP_FROM_EMAIL", "noreply@raahi.app")
    SMTP_FROM_NAME: str = os.getenv("SMTP_FROM_NAME", "Raahi Dating")
    SMTP_USE_TLS: bool = os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")

    # SMS Service (Twilio)
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_PHONE_NUMBER: str = os.getenv("TWILIO_PHONE_NUMBER", "")


settings = Settings()
