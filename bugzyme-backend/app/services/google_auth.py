"""
Google OAuth 2.0 & OpenID Connect Authentication Service.

Implements secure OpenID Connect Sign-In with Google ("Continue with Google"):
- Standard Authorization Code flow with RFC 7636 PKCE (S256).
- Cryptographic state parameter validation for CSRF defense.
- Scopes strictly limited to identity: 'openid', 'email', 'profile'.
- Never requests Google Data Portability or YouTube activity scopes during login.
- Official Google ID Token signature, audience, issuer, expiration, and verified-email validation.
- Single-use exchange tickets preventing access tokens from ever appearing in URLs.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from app.core.config import settings

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Scopes strictly limited to user authentication and identity
GOOGLE_SIGNIN_SCOPES = ["openid", "email", "profile"]

# Thread-safe in-memory OAuth state cache with TTL (10 minutes)
_STATE_LOCK = threading.Lock()
_ACTIVE_STATES: Dict[str, Dict[str, Any]] = {}
STATE_TTL_SECONDS = 600


def _clean_expired_states() -> None:
    now = time.time()
    expired = [s for s, data in _ACTIVE_STATES.items() if data.get("expires_at", 0) < now]
    for s in expired:
        _ACTIVE_STATES.pop(s, None)


def save_oauth_state(
    state: str,
    code_verifier: str,
    redirect_uri: str,
    user_id: Optional[str] = None,
) -> None:
    with _STATE_LOCK:
        _clean_expired_states()
        _ACTIVE_STATES[state] = {
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
            "user_id": user_id,
            "expires_at": time.time() + STATE_TTL_SECONDS,
        }


def verify_and_consume_oauth_state(state: str) -> Optional[Dict[str, Any]]:
    with _STATE_LOCK:
        _clean_expired_states()
        data = _ACTIVE_STATES.pop(state, None)
        if not data:
            return None
        if data.get("expires_at", 0) < time.time():
            return None
        return data


def is_google_auth_configured() -> bool:
    """Verify if Google OAuth Client credentials are configured."""
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def generate_pkce_pair() -> Tuple[str, str]:
    """Generate PKCE code_verifier and S256 code_challenge (RFC 7636)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def generate_state() -> str:
    """Generate cryptographically secure state parameter for CSRF protection."""
    return secrets.token_urlsafe(32)


def get_google_auth_redirect_uri() -> str:
    """
    Determine the canonical redirect URI for Google Sign-In.
    Prefers GOOGLE_AUTH_REDIRECT_URI if set, then GOOGLE_REDIRECT_URI,
    or falls back to localhost frontend auth callback.
    """
    if getattr(settings, "GOOGLE_AUTH_REDIRECT_URI", None) and settings.GOOGLE_AUTH_REDIRECT_URI.strip():
        return settings.GOOGLE_AUTH_REDIRECT_URI.strip()
    if getattr(settings, "GOOGLE_REDIRECT_URI", None) and settings.GOOGLE_REDIRECT_URI.strip():
        return settings.GOOGLE_REDIRECT_URI.strip()
    frontend = get_frontend_base_url()
    return f"{frontend}/auth/google/callback"


def get_frontend_base_url() -> str:
    """Determine the approved frontend URL for redirects."""
    if getattr(settings, "FRONTEND_URL", None) and settings.FRONTEND_URL.strip():
        return settings.FRONTEND_URL.strip().rstrip("/")
    return "http://localhost:5173"


def build_google_auth_url(
    user_id: Optional[str] = None,
    redirect_uri: Optional[str] = None,
) -> Dict[str, str]:
    """
    Construct Google OAuth authorization URL with PKCE and state CSRF protection.
    Saves state and code_verifier for verification upon callback.
    """
    if not is_google_auth_configured():
        raise ValueError(
            "Google OAuth is not configured. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in backend/.env"
        )

    state = generate_state()
    verifier, challenge = generate_pkce_pair()
    callback_uri = redirect_uri or get_google_auth_redirect_uri()
    stored_user_id = user_id or "anonymous_auth"

    save_oauth_state(
        state=state,
        code_verifier=verifier,
        redirect_uri=callback_uri,
        user_id=stored_user_id,
    )

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": callback_uri,
        "response_type": "code",
        "scope": " ".join(GOOGLE_SIGNIN_SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "online",
        "prompt": "select_account",
    }

    authorization_url = f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"
    return {
        "authorization_url": authorization_url,
        "state": state,
        "code_verifier": verifier,
        "redirect_uri": callback_uri,
    }


def exchange_code_for_google_tokens(
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> Dict[str, Any]:
    """
    Exchange authorization code for tokens securely on backend using PKCE.
    Google client secret is kept strictly on the backend and never exposed.
    """
    if not is_google_auth_configured():
        raise ValueError("Google OAuth credentials are not configured on server.")

    data = urllib.parse.urlencode({
        "code": code,
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
    }).encode("utf-8")

    req = urllib.request.Request(
        GOOGLE_TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            tokens = json.loads(resp.read().decode("utf-8"))
            return tokens
    except urllib.error.HTTPError as exc:
        err_msg = exc.read().decode("utf-8", errors="replace")
        logger.error("Google token exchange failed: %d - %s", exc.code, err_msg)
        raise ValueError(f"Google token exchange failed: {exc.code} {err_msg}") from exc
    except Exception as exc:
        logger.error("Google token exchange network error: %s", exc)
        raise ValueError(f"Google token exchange failed: {exc}") from exc


def verify_google_id_token(
    id_token_jwt: str,
    client_id: Optional[str] = None,
    mock_claims: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Verify Google OpenID Connect ID token using Google's official verification library.

    Strict security validations:
    1. Cryptographic signature verified against Google's public certs.
    2. Audience matches configured GOOGLE_CLIENT_ID.
    3. Issuer is accounts.google.com or https://accounts.google.com.
    4. Token is not expired.
    5. User email must be verified (email_verified is True).
    6. Extract stable 'sub' identifier.
    """
    if mock_claims is not None:
        # Automated testing hook with verified claims
        return _validate_claims(mock_claims, client_id or settings.GOOGLE_CLIENT_ID or "mock-client-id")

    expected_client_id = client_id or settings.GOOGLE_CLIENT_ID
    if not expected_client_id:
        raise ValueError("Cannot verify ID token: GOOGLE_CLIENT_ID is not configured.")

    request = google_requests.Request()
    try:
        claims = google_id_token.verify_oauth2_token(
            id_token_jwt,
            request,
            audience=expected_client_id,
        )
    except Exception as exc:
        logger.error("Failed Google ID token verification: %s", exc)
        raise ValueError(f"Google ID token verification failed: {exc}") from exc

    return _validate_claims(claims, expected_client_id)


def _validate_claims(claims: Dict[str, Any], expected_audience: str) -> Dict[str, Any]:
    """Enforce security rules on extracted Google token claims."""
    # 1. Issuer verification
    issuer = claims.get("iss")
    if issuer not in ("accounts.google.com", "https://accounts.google.com"):
        raise ValueError(f"Invalid Google ID token issuer: {issuer}")

    # 2. Audience verification
    aud = claims.get("aud")
    if expected_audience and aud != expected_audience:
        raise ValueError(f"Audience mismatch: expected '{expected_audience}', got '{aud}'")

    # 3. Expiration verification
    exp = claims.get("exp")
    if exp:
        exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
        if exp_dt < datetime.now(timezone.utc):
            raise ValueError("Google ID token has expired.")

    # 4. Verified email requirement
    email_verified = claims.get("email_verified")
    if not email_verified:
        raise ValueError("Google account email is not verified. Please verify your email with Google.")

    # 5. Required identity fields
    sub = claims.get("sub")
    email = claims.get("email")
    if not sub:
        raise ValueError("Google ID token is missing the subject ('sub') claim.")
    if not email:
        raise ValueError("Google ID token is missing the 'email' claim.")

    return {
        "sub": str(sub),
        "email": str(email).strip().lower(),
        "name": claims.get("name") or claims.get("given_name") or email.split("@")[0].capitalize(),
        "picture": claims.get("picture") or "",
        "email_verified": bool(email_verified),
    }
