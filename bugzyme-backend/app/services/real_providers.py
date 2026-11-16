"""
Real Provider Integration Service for Google and Instagram.

Implements official OAuth 2.0 authorization code flow with PKCE, state CSRF validation,
and official data fetching boundaries:
- Google: YouTube Data API v3 (youtube.readonly) for user-authorized channel subscriptions.
- Instagram: Meta Instagram Graph API (instagram_basic) for Creator/Business accounts.

Security & Privacy Guarantees:
1. Tokens are saved strictly in backend SQLite and NEVER exposed to frontend clients.
2. Least-privilege scopes only; no search, watch, or private browse history access.
3. Cryptographic PKCE (RFC 7636) and state CSRF validation.
4. Token revocation on disconnect and complete user isolation.
5. If credentials are not configured in environment, reports 'configured: false'
   with exact setup instructions, preserving the mock synthetic provider as a demo fallback.
"""
from __future__ import annotations

import base64
import hashlib
import html
import ipaddress
import json
import logging
import os
import re
import secrets
import shutil
import tempfile
import unicodedata
import urllib.parse
import urllib.request
import urllib.error
import zipfile
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.config import settings
from app.db.sqlite_repository import default_sqlite_repo
from app.services.dating_ml_model.external_interests import (
    normalize_interest_tag,
    infer_interest_category,
    _CATEGORY_KEYWORDS,
)

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3/subscriptions?part=snippet&mine=true&maxResults=50"

# Scopes supported for Google integration
GOOGLE_DATA_PORTABILITY_SCOPE = getattr(
    settings,
    "GOOGLE_DATA_PORTABILITY_SCOPE",
    "https://www.googleapis.com/auth/dataportability.myactivity.youtube",
)
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    GOOGLE_DATA_PORTABILITY_SCOPE,
]

# Google Data Portability API Endpoints
GOOGLE_PORTABILITY_INITIATE_URL = "https://dataportability.googleapis.com/v1/portabilityArchive:initiate"
GOOGLE_PORTABILITY_STATE_URL = "https://dataportability.googleapis.com/v1/archiveJobs/{archive_job_id}/portabilityArchiveState"
GOOGLE_PORTABILITY_RETRY_URL = "https://dataportability.googleapis.com/v1/archiveJobs/{archive_job_id}:retry"
GOOGLE_PORTABILITY_CANCEL_URL = "https://dataportability.googleapis.com/v1/archiveJobs/{archive_job_id}:cancel"

INSTAGRAM_AUTH_URL = "https://api.instagram.com/oauth/authorize"
INSTAGRAM_TOKEN_URL = "https://api.instagram.com/oauth/access_token"
INSTAGRAM_GRAPH_URL = "https://graph.instagram.com/me?fields=id,username,account_type"
INSTAGRAM_SCOPES = ["instagram_basic"]


def generate_pkce_pair() -> Tuple[str, str]:
    """Generate PKCE code_verifier and S256 code_challenge (RFC 7636)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def generate_state() -> str:
    """Generate cryptographically secure state parameter for CSRF protection."""
    return secrets.token_urlsafe(32)


# ── Configuration Status ───────────────────────────────────────────────────────

def is_google_configured() -> bool:
    """Check if Google OAuth Client credentials are provided."""
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def is_instagram_configured() -> bool:
    """Check if Meta/Instagram OAuth Client credentials are provided."""
    return bool(settings.INSTAGRAM_CLIENT_ID and settings.INSTAGRAM_CLIENT_SECRET)


def get_provider_metadata(provider: str, user_id: str, repo=None) -> Dict[str, Any]:
    """
    Return comprehensive metadata for an external provider:
    configuration state, connection status, supported scopes, and setup instructions.
    """
    p = provider.lower()
    active_repo = repo or default_sqlite_repo
    token = active_repo.get_oauth_token(user_id, p)
    connected = token is not None

    if p == "google":
        configured = is_google_configured()
        active_job = active_repo.get_latest_portability_job(user_id, provider="google") if hasattr(active_repo, "get_latest_portability_job") else None
        has_portability_scope = False
        if token:
            scope_str = token.get("scope", "") or ""
            has_portability_scope = (
                GOOGLE_DATA_PORTABILITY_SCOPE in scope_str
                or "dataportability.myactivity.youtube" in scope_str
            )

        return {
            "id": "google",
            "name": "Google / YouTube",
            "is_mock": False,
            "is_configured": configured,
            "is_connected": connected,
            "has_portability_scope": has_portability_scope,
            "auth_type": "OAuth 2.0 (Authorization Code + PKCE)",
            "supported_scopes": GOOGLE_SCOPES,
            "data_source": "YouTube Subscriptions (Data API v3) & YouTube Activity (Data Portability API)",
            "description": (
                "Supports asynchronous export of authorized YouTube viewing activity via the Google Data Portability API, "
                "or fast subscription import via the YouTube Data API v3. "
                "Google Search, Chrome history, and private recommendations are never requested."
            ),
            "disclaimer": (
                "Official Google Data Portability API (myactivity.youtube) & YouTube Data API v3 integration. "
                "Requires user approval. Raw watch history archives are processed in a secure sandbox; only minimal topic tags are persisted, "
                "and raw viewing logs are purged immediately. Does not access Google Search or Chrome browsing history."
            ),
            "data_portability": {
                "supported": True,
                "resource": "myactivity.youtube",
                "scope": GOOGLE_DATA_PORTABILITY_SCOPE,
                "latest_job": active_job,
            },
            "setup_required": not configured,
            "setup_documentation": {
                "portal": "Google Cloud Console (https://console.cloud.google.com/)",
                "api_name": "Google Data Portability API & YouTube Data API v3",
                "env_keys": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI"],
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "required_scopes": GOOGLE_SCOPES,
            },
        }

    if p == "instagram":
        configured = is_instagram_configured()
        return {
            "id": "instagram",
            "name": "Instagram / Meta",
            "is_mock": False,
            "is_configured": configured,
            "is_connected": connected,
            "auth_type": "OAuth 2.0 (Instagram Graph API)",
            "supported_scopes": INSTAGRAM_SCOPES,
            "data_source": "Instagram Creator/Business Account Category & Public Profile (Graph API)",
            "description": (
                "Imports professional interest categories for Creator or Business Instagram accounts. "
                "Personal likes, saved collections, Explore feed, and DM history are not accessible."
            ),
            "disclaimer": (
                "Meta Instagram Graph API integration. Note: Meta deprecated the Instagram Basic Display API in Dec 2024. "
                "Current integration requires a Creator or Business account and Meta App Review. "
                "Consumer likes, saved posts, and private Explore feeds are strictly prohibited by Meta."
            ),
            "setup_required": not configured,
            "setup_documentation": {
                "portal": "Meta for Developers (https://developers.facebook.com/)",
                "api_name": "Instagram Graph API",
                "env_keys": ["INSTAGRAM_CLIENT_ID", "INSTAGRAM_CLIENT_SECRET", "INSTAGRAM_REDIRECT_URI"],
                "redirect_uri": settings.INSTAGRAM_REDIRECT_URI,
                "required_scopes": INSTAGRAM_SCOPES,
                "notes": "Requires Instagram Professional account (Creator/Business) and completed App Review.",
            },
        }

    raise ValueError(f"Unknown provider '{provider}'")


# ── Authorization Flow ────────────────────────────────────────────────────────

def create_authorization_url(
    provider: str,
    user_id: str,
    repo=None,
) -> Dict[str, Any]:
    """
    Generate an OAuth authorization URL with PKCE and state CSRF protection.
    Raises ValueError if provider is not configured.
    """
    p = provider.lower()
    active_repo = repo or default_sqlite_repo
    state = generate_state()
    verifier, challenge = generate_pkce_pair()

    if p == "google":
        if not is_google_configured():
            raise ValueError(
                "Google OAuth is not configured. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in backend/.env"
            )
        redirect_uri = settings.GOOGLE_REDIRECT_URI
        active_repo.save_oauth_state(state, user_id, "google", code_verifier=verifier, redirect_uri=redirect_uri)
        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(GOOGLE_SCOPES),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        }
        auth_url = f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"
        return {"provider": "google", "authorization_url": auth_url, "state": state}

    if p == "instagram":
        if not is_instagram_configured():
            raise ValueError(
                "Instagram OAuth is not configured. Please set INSTAGRAM_CLIENT_ID and INSTAGRAM_CLIENT_SECRET in backend/.env"
            )
        redirect_uri = settings.INSTAGRAM_REDIRECT_URI
        active_repo.save_oauth_state(state, user_id, "instagram", code_verifier=verifier, redirect_uri=redirect_uri)
        params = {
            "client_id": settings.INSTAGRAM_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": ",".join(INSTAGRAM_SCOPES),
            "state": state,
        }
        auth_url = f"{INSTAGRAM_AUTH_URL}?{urllib.parse.urlencode(params)}"
        return {"provider": "instagram", "authorization_url": auth_url, "state": state}

    raise ValueError(f"Unsupported provider: {provider}")


def handle_oauth_callback(
    provider: str,
    code: str,
    state: str,
    repo=None,
) -> Dict[str, Any]:
    """
    Validate CSRF state, exchange authorization code for tokens, and store tokens securely.
    """
    p = provider.lower()
    active_repo = repo or default_sqlite_repo
    state_record = active_repo.verify_and_consume_oauth_state(state, p)
    if not state_record:
        raise PermissionError("Invalid or expired OAuth state parameter (CSRF protection failed).")

    user_id = state_record["user_id"]
    code_verifier = state_record.get("code_verifier")
    redirect_uri = state_record.get("redirect_uri")

    if p == "google":
        token_data = _exchange_google_code(code, code_verifier, redirect_uri)
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
        scope = token_data.get("scope", "")

        active_repo.save_oauth_token(
            user_id=user_id,
            provider="google",
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            scope=scope,
        )
        return {"user_id": user_id, "provider": "google", "connected": True}

    if p == "instagram":
        token_data = _exchange_instagram_code(code, redirect_uri)
        access_token = token_data["access_token"]
        user_id_ext = str(token_data.get("user_id", ""))
        active_repo.save_oauth_token(
            user_id=user_id,
            provider="instagram",
            access_token=access_token,
            scope="instagram_basic",
        )
        return {"user_id": user_id, "provider": "instagram", "connected": True, "external_user_id": user_id_ext}

    raise ValueError(f"Unsupported provider: {provider}")


def _exchange_google_code(code: str, code_verifier: Optional[str], redirect_uri: Optional[str]) -> Dict[str, Any]:
    """Exchange authorization code with Google token endpoint."""
    body = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri or settings.GOOGLE_REDIRECT_URI,
    }
    if code_verifier:
        body["code_verifier"] = code_verifier
    data = urllib.parse.urlencode(body).encode("utf-8")
    req = urllib.request.Request(GOOGLE_TOKEN_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_msg = e.read().decode("utf-8")
        logger.error("Google token exchange failed: %s", error_msg)
        raise RuntimeError(f"Google token exchange failed: {error_msg}") from e


def _exchange_instagram_code(code: str, redirect_uri: Optional[str]) -> Dict[str, Any]:
    """Exchange authorization code with Instagram token endpoint."""
    body = {
        "client_id": settings.INSTAGRAM_CLIENT_ID,
        "client_secret": settings.INSTAGRAM_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri or settings.INSTAGRAM_REDIRECT_URI,
    }
    data = urllib.parse.urlencode(body).encode("utf-8")
    req = urllib.request.Request(INSTAGRAM_TOKEN_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_msg = e.read().decode("utf-8")
        logger.error("Instagram token exchange failed: %s", error_msg)
        raise RuntimeError(f"Instagram token exchange failed: {error_msg}") from e


# ── Real Data Synchronization ─────────────────────────────────────────────────

def sync_provider_interests(
    provider: str,
    user_id: str,
    repo=None,
) -> Dict[str, Any]:
    """
    Fetch authorized interest signals from real provider API, normalize them
    into canonical taxonomy tokens, and save to SQLite external_interests table.
    """
    p = provider.lower()
    active_repo = repo or default_sqlite_repo
    token_record = active_repo.get_oauth_token(user_id, p)
    if not token_record:
        raise PermissionError(f"No authorized account found for '{provider}'. Please authorize first.")

    access_token = token_record["access_token"]

    if p == "google":
        return _sync_google_youtube_interests(user_id, access_token, active_repo)

    if p == "instagram":
        return _sync_instagram_interests(user_id, access_token, active_repo)

    raise ValueError(f"Unsupported provider: {provider}")


def _sync_google_youtube_interests(user_id: str, access_token: str, repo) -> Dict[str, Any]:
    """
    Call YouTube Data API v3 subscriptions endpoint, extract channel topics,
    normalize into canonical interest tokens, and save.
    """
    req = urllib.request.Request(GOOGLE_YOUTUBE_API_URL, method="GET")
    req.add_header("Authorization", f"Bearer {access_token}")
    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        logger.error("Failed to fetch YouTube subscriptions: %s", e)
        raise RuntimeError(f"YouTube API call failed: {e.code}") from e

    items = data.get("items", [])
    extracted_interests: List[Dict[str, Any]] = []

    for item in items:
        snippet = item.get("snippet", {})
        title = snippet.get("title", "").strip()
        desc = snippet.get("description", "").strip()
        if not title:
            continue

        token = normalize_interest_tag(title)
        if not token:
            continue

        category = infer_interest_category(token)
        canonical = f"interest_tag:{token}"

        extracted_interests.append({
            "canonical_token": canonical,
            "display_name": title,
            "category": category,
            "provider": "google",
            "source_detail": "youtube_subscription",
            "confidence": 0.85,
            "affinity": 1.0,
            "user_confirmed": True,
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "raw_data": {"channel_id": snippet.get("resourceId", {}).get("channelId"), "title": title},
        })

    if extracted_interests:
        repo.save_external_interests(user_id, "google", extracted_interests)

    return {
        "user_id": user_id,
        "provider": "google",
        "imported_count": len(extracted_interests),
        "interests": extracted_interests,
    }


def _sync_instagram_interests(user_id: str, access_token: str, repo) -> Dict[str, Any]:
    """
    Call Meta Instagram Graph API me endpoint, extract profile category,
    normalize into canonical interest tokens, and save.
    """
    req = urllib.request.Request(f"{INSTAGRAM_GRAPH_URL}&access_token={urllib.parse.quote(access_token)}", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        logger.error("Failed to fetch Instagram profile: %s", e)
        raise RuntimeError(f"Instagram Graph API call failed: {e.code}") from e

    extracted_interests: List[Dict[str, Any]] = []
    account_type = data.get("account_type", "").lower()
    username = data.get("username", "")

    if account_type in ("creator", "business"):
        token = normalize_interest_tag(f"{account_type}_creator")
        if token:
            extracted_interests.append({
                "canonical_token": f"interest_tag:{token}",
                "display_name": f"{account_type.capitalize()} Creator ({username})",
                "category": "arts",
                "provider": "instagram",
                "source_detail": f"instagram_{account_type}",
                "confidence": 0.80,
                "affinity": 1.0,
                "user_confirmed": True,
                "imported_at": datetime.now(timezone.utc).isoformat(),
            })

    if extracted_interests:
        repo.save_external_interests(user_id, "instagram", extracted_interests)

    return {
        "user_id": user_id,
        "provider": "instagram",
        "imported_count": len(extracted_interests),
        "interests": extracted_interests,
    }


# ── Account Disconnect & Token Revocation ─────────────────────────────────────

def disconnect_provider(
    provider: str,
    user_id: str,
    repo=None,
) -> Dict[str, Any]:
    """
    Revoke upstream token if supported, purge stored credentials from backend SQLite,
    delete imported provider interests, and withdraw consent.
    """
    p = provider.lower()
    active_repo = repo or default_sqlite_repo
    token_record = active_repo.get_oauth_token(user_id, p)

    if token_record and p == "google":
        # Revoke token with Google
        try:
            token = token_record.get("access_token")
            if token:
                data = urllib.parse.urlencode({"token": token}).encode("utf-8")
                req = urllib.request.Request(GOOGLE_REVOKE_URL, data=data, method="POST")
                req.add_header("Content-Type", "application/x-www-form-urlencoded")
                urllib.request.urlopen(req, timeout=5.0)
        except Exception as e:
            logger.warning("Could not revoke Google token with upstream: %s", e)

    # Purge token from local database
    active_repo.delete_oauth_token(user_id, p)

    # Purge imported interests for this provider
    deleted_interests = active_repo.delete_external_interests(user_id, provider=p)

    # Purge portability jobs for this provider if supported
    if hasattr(active_repo, "delete_portability_jobs"):
        active_repo.delete_portability_jobs(user_id, provider=p)

    # Withdraw provider consent in privacy settings
    active_repo.save_privacy_settings(user_id, {
        "external_interests_consent": {p: False}
    })

    return {
        "user_id": user_id,
        "provider": p,
        "disconnected": True,
        "deleted_interests_count": deleted_interests,
    }


def delete_google_interests_data(user_id: str, repo=None) -> Dict[str, Any]:
    """Delete all imported Google/YouTube external interests without disconnecting account."""
    active_repo = repo or default_sqlite_repo
    deleted = active_repo.delete_external_interests(user_id, provider="google")
    return {
        "user_id": user_id,
        "provider": "google",
        "deleted_interests_count": deleted,
    }


# ── Google Data Portability API (myactivity.youtube) ─────────────────────────

# Approved Google hostnames and root domains for archive downloads
APPROVED_DOWNLOAD_DOMAINS = (
    "storage.googleapis.com",
    "dataportability.googleapis.com",
    "takeout.google.com",
    "googleusercontent.com",
)


def is_safe_download_url(url: str) -> bool:
    """
    Validate that the archive download URL uses HTTPS, resolves to an approved
    Google storage hostname using strict boundary-aware domain matching,
    and does not target internal or private networks (anti-SSRF).
    
    A hostname is valid if and only if:
      hostname == approved_domain OR hostname.endswith("." + approved_domain)
    
    Lookalike hostnames such as 'evilstorage.googleapis.com', 'evildataportability.googleapis.com',
    or 'storage.googleapis.com.attacker.com' are strictly rejected.
    """
    try:
        if not url or not isinstance(url, str):
            return False

        parsed = urllib.parse.urlparse(url.strip())
        if parsed.scheme.lower() != "https":
            return False

        # Reject embedded credentials (e.g. https://user:pass@storage.googleapis.com/...)
        if parsed.username or parsed.password:
            return False

        # Reject unexpected ports (only default HTTPS port 443 or omitted allowed)
        if parsed.port is not None and parsed.port != 443:
            return False

        hostname = (parsed.hostname or "").lower().rstrip(".")
        if not hostname:
            return False

        # Reject loopback, localhost, and cloud metadata endpoints
        if hostname in ("localhost", "127.0.0.1", "::1", "metadata.google.internal", "169.254.169.254"):
            return False

        # Reject private/reserved IP ranges
        try:
            ip = ipaddress.ip_address(hostname)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                return False
        except ValueError:
            pass  # It is a valid DNS hostname

        # Boundary-aware matching: must equal approved domain or be a subdomain separated by a dot
        return any(
            hostname == d or (hostname.endswith("." + d) and not hostname.startswith("."))
            for d in APPROVED_DOWNLOAD_DOMAINS
        )
    except Exception:
        return False


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """
    Validates redirect targets to prevent SSRF via HTTP 3xx redirects.
    Enforces that every redirect hop uses HTTPS and resolves to an approved hostname.
    Limits maximum redirect hops to prevent redirect loops.
    """
    MAX_REDIRECTS = 3

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._redirect_count = 0

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Optional[urllib.request.Request]:
        self._redirect_count += 1
        if self._redirect_count > self.MAX_REDIRECTS:
            raise urllib.error.HTTPError(
                newurl, code, f"Too many redirects ({self._redirect_count} > {self.MAX_REDIRECTS})", headers, fp
            )
        # Validate that redirect protocol is strictly HTTPS
        if not str(newurl).lower().startswith("https://"):
            raise urllib.error.HTTPError(
                newurl, code, f"Security violation: Insecure non-HTTPS redirect rejected: {newurl}", headers, fp
            )
        # Validate that the redirect destination is an approved, safe HTTPS URL
        if not is_safe_download_url(newurl):
            raise urllib.error.HTTPError(
                newurl,
                code,
                f"Security violation: Redirect to unsafe or disallowed destination rejected: {newurl}",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# ── Sensitive Topic Sanitization & Heuristic Filtering (GDPR Art. 9) ─────────
# Heuristic defense-in-depth filter for sensitive personal traits.
# Note: This is a best-effort heuristic filter and does NOT claim complete or exhaustive detection.

SENSITIVE_TERM_PATTERNS = [
    # Religious, spiritual, theological, and worship terms
    r"\b(religion|religious|theology|prayer|praying|worship|quran|koran|bible|biblical|torah|talmud|gita|bhagavad|mosque|church|synagogue|temple|monastery|pastor|imam|priest|rabbi|hindu|hinduism|muslim|islam|islamic|christian|christianity|judaism|jewish|sikh|sikhism|buddhist|buddhism|atheism|atheist|deity|gospel|evangelical|salvation)\b",
    # Political, electoral, partisan, ideological terms
    r"\b(republican|democrat|democratic|election|elections|electoral|political|politics|ballot|voting|congress|senate|parliament|bjp|labour_party|tory|tories|left_wing|right_wing|authoritarian|socialism|socialist|communist|communism|marxist|fascist|fascism|regime|protest|activism|partisan|propaganda|campaign)\b",
    # Medical conditions, mental health, oncology, chronic diseases, psychiatric terms
    r"\b(cancer|oncology|chemotherapy|tumor|depression|depressed|depressive|anxiety_disorder|adhd|bipolar|schizophrenia|psychiatric|psychosis|antidepressants|medication|prescription|diagnosis|diagnosed|hospitalized|illness|disease|chronic_illness|diabetes|hiv|aids|dementia|alzheimer|suicide|self_harm|addiction|rehab|biopsy|terminal)\b",
    # Sexual orientation, gender identity, adult/NSFW/fetish terms
    r"\b(lgbt|lgbtq|lgbtqia|gay|lesbian|bisexual|queer|transgender|transsexual|trans_identity|gender_dysphoria|crossdresser|erotic|nsfw|porn|pornography|onlyfans|fetish|bdsm|kink|escort|hookup|sexuality)\b",
]
_SENSITIVE_REGEX = re.compile("|".join(SENSITIVE_TERM_PATTERNS), re.IGNORECASE)


def sanitize_and_normalize_text(text: str) -> str:
    """
    Decodes HTML entities and normalizes Unicode to eliminate obfuscation bypasses:
    1. Unescapes HTML entities (&quot;, &#x27;, &#112;rayer, etc.).
    2. Decomposes Unicode (NFKD) and removes combining diacritical marks.
    3. Normalizes compatibility characters (NFKC) to handle full-width characters.
    4. Strips zero-width characters and soft hyphens.
    5. Maps common Cyrillic / Greek homoglyphs to ASCII equivalents.
    """
    if not text:
        return ""
    # 1. Unescape HTML entities
    unescaped = html.unescape(text)

    # 2. Unicode NFKD decomposition + strip combining characters (e.g. accents: dépression -> depression)
    nfkd = unicodedata.normalize("NFKD", unescaped)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))

    # 3. Unicode NFKC compatibility normalization (e.g. full-width ｐｒａｙｅｒ -> prayer)
    nfkc = unicodedata.normalize("NFKC", stripped)

    # 4. Remove zero-width spaces, joiners, and soft hyphens
    clean = re.sub(r"[\u200b\u200c\u200d\ufeff\u00ad]", "", nfkc)

    # 5. Common Cyrillic homoglyphs mapping to ASCII
    homoglyphs = {
        "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0440": "p", "\u0441": "c",
        "\u0443": "y", "\u0445": "x", "\u0456": "i", "\u0458": "j",
        "\u0410": "A", "\u0415": "E", "\u041e": "O", "\u0420": "P", "\u0421": "C",
        "\u0422": "T", "\u0425": "X",
    }
    for cyr, lat in homoglyphs.items():
        clean = clean.replace(cyr, lat)

    return clean


def contains_sensitive_content(text: str) -> bool:
    """
    Returns True if the text contains sensitive personal traits.
    Applies HTML unescaping, Unicode normalization, and homoglyph resolution before pattern matching.
    """
    if not text:
        return False
    normalized = sanitize_and_normalize_text(text)
    if _SENSITIVE_REGEX.search(normalized):
        return True
    if _SENSITIVE_REGEX.search(normalized.replace("_", " ")):
        return True
    return False


def safe_extract_zip_archive(zip_path: str, extract_dir: str) -> List[str]:
    """
    Safely extract files from an archive applying strict defensive quotas:
    1. Zip Slip / directory traversal prevention.
    2. Absolute path and drive reference rejection.
    3. Symlink escape detection and rejection.
    4. Malformed/corrupted archive rejection.
    5. Max file count limit (anti-zip bomb).
    6. Max single file size limit.
    7. Max cumulative uncompressed bytes limit.
    8. Rejection of unpermitted file types.
    """
    if not zipfile.is_zipfile(zip_path):
        raise ValueError("Malformed, corrupt, or unsupported archive format.")

    max_files = getattr(settings, "MAX_ARCHIVE_FILE_COUNT", 500)
    max_single_size = getattr(settings, "MAX_ARCHIVE_SINGLE_FILE_BYTES", 25 * 1024 * 1024)
    max_total_size = getattr(settings, "MAX_ARCHIVE_UNCOMPRESSED_BYTES", 100 * 1024 * 1024)

    resolved_extract_dir = os.path.abspath(extract_dir)
    extracted_paths: List[str] = []

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            infolist = zf.infolist()
            if len(infolist) > max_files:
                raise ValueError(f"Archive exceeds maximum file count limit ({len(infolist)} > {max_files}).")

            total_uncompressed = 0
            for member in infolist:
                # Absolute path and drive letter check
                if os.path.isabs(member.filename) or member.filename.startswith(("/", "\\")):
                    raise ValueError(f"Security error: Absolute path detected in member '{member.filename}'.")
                if re.match(r"^[a-zA-Z]:", member.filename):
                    raise ValueError(f"Security error: Drive letter reference detected in member '{member.filename}'.")

                # Symlink detection
                is_symlink = ((member.external_attr >> 16) & 0o170000 == 0o120000) or (
                    hasattr(member, "is_symlink") and member.is_symlink()
                )
                if is_symlink:
                    raise ValueError(f"Security error: Symlinks are forbidden in archive member '{member.filename}'.")

                # Check individual uncompressed size
                if member.file_size > max_single_size:
                    raise ValueError(
                        f"Archive member '{member.filename}' exceeds single-file limit ({member.file_size} > {max_single_size} bytes)."
                    )

                total_uncompressed += member.file_size
                if total_uncompressed > max_total_size:
                    raise ValueError(
                        f"Archive cumulative uncompressed size exceeds threshold ({total_uncompressed} > {max_total_size} bytes)."
                    )

                # Zip Slip canonical path check
                target_path = os.path.abspath(os.path.join(resolved_extract_dir, member.filename))
                if not target_path.startswith(resolved_extract_dir + os.sep) and target_path != resolved_extract_dir:
                    raise ValueError(f"Security error: Detected Zip Slip path traversal in member '{member.filename}'.")

                # Check file extension whitelist
                ext = os.path.splitext(member.filename)[1].lower()
                if not member.is_dir():
                    if ext not in (".json", ".html", ".htm", ".txt", ".csv"):
                        # Disallow executable or unknown file types
                        continue

                zf.extract(member, resolved_extract_dir)
                if os.path.islink(target_path):
                    raise ValueError(f"Security error: Extracted member '{member.filename}' created a symlink.")
                extracted_paths.append(target_path)
    except zipfile.BadZipFile as e:
        raise ValueError(f"Malformed, corrupt, or unsupported archive format: {e}") from e

    return extracted_paths


def extract_topics_from_youtube_activity(extract_dir: str) -> List[Dict[str, Any]]:
    """
    Scan extracted Takeout files for watch-history.json / watch-history.html,
    extract high-level explainable interest topics, filter sensitive attributes,
    and return normalized interest records.
    
    Zero raw watch titles, URLs, or full records are preserved.
    Notice: Search-history fallback is strictly removed; processing is limited solely
    to user-consented YouTube watch-history data.
    """
    found_history_files: List[Tuple[str, str]] = []  # (path, 'json' | 'html')

    for root, _, files in os.walk(extract_dir):
        for f in files:
            f_lower = f.lower()
            if "watch-history" in f_lower or "watch_history" in f_lower:
                ext = "json" if f_lower.endswith(".json") else ("html" if f_lower.endswith((".html", ".htm")) else "")
                if ext:
                    found_history_files.append((os.path.join(root, f), ext))

    if not found_history_files:
        raise ValueError("Unsupported or empty archive layout: no YouTube watch-history file found.")

    # Tally candidate topic occurrences
    topic_counts: Dict[str, int] = {}

    for file_path, ftype in found_history_files:
        if ftype == "json":
            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as jf:
                    data = json.load(jf)
                    if isinstance(data, list):
                        for entry in data:
                            if not isinstance(entry, dict):
                                continue
                            raw_title = entry.get("title", "")
                            # If raw title contains any sensitive topic (even mixed with non-sensitive),
                            # discard the entire entry immediately (defense-in-depth heuristic)
                            if not raw_title or contains_sensitive_content(raw_title):
                                continue

                            # Strip common Takeout prefix
                            title_clean = re.sub(r"^watched\s+", "", raw_title, flags=re.IGNORECASE).strip()
                            if not title_clean or contains_sensitive_content(title_clean):
                                continue

                            # Also check channel/subtitles if present
                            subtitles = entry.get("subtitles", [])
                            channel_sensitive = False
                            if isinstance(subtitles, list):
                                for s in subtitles:
                                    if isinstance(s, dict) and contains_sensitive_content(s.get("name", "")):
                                        channel_sensitive = True
                                        break
                            if channel_sensitive:
                                continue

                            # Extract matched keywords from standardized taxonomy
                            clean_norm = normalize_interest_tag(title_clean) or ""
                            for cat, kw_set in _CATEGORY_KEYWORDS.items():
                                for kw in kw_set:
                                    if kw in clean_norm or kw in title_clean.lower():
                                        topic_counts[kw] = topic_counts.get(kw, 0) + 1
            except Exception as e:
                logger.warning("Error reading JSON watch history: %s", e)

        elif ftype == "html":
            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as hf:
                    content = hf.read()
                    # Extract link text inside content cells
                    matches = re.findall(r"(?:>|\s|^)Watched\s+<a[^>]*>(.*?)</a>", content, re.IGNORECASE)
                    for m in matches:
                        # If raw match has sensitive content (e.g. HTML entities or Unicode), discard
                        if contains_sensitive_content(m):
                            continue
                        clean_m = re.sub(r"<[^>]+>", "", m).strip()
                        if not clean_m or contains_sensitive_content(clean_m):
                            continue
                        clean_norm = normalize_interest_tag(clean_m) or ""
                        for cat, kw_set in _CATEGORY_KEYWORDS.items():
                            for kw in kw_set:
                                if kw in clean_norm or kw in clean_m.lower():
                                    topic_counts[kw] = topic_counts.get(kw, 0) + 1
            except Exception as e:
                logger.warning("Error reading HTML watch history: %s", e)

    # Sort topics by frequency, select top distinct topics (max 15)
    sorted_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:15]

    now_iso = datetime.now(timezone.utc).isoformat()
    extracted_interests: List[Dict[str, Any]] = []

    for topic, count in sorted_topics:
        category = infer_interest_category(topic)
        display_name = topic.replace("_", " ").title()
        canonical = f"interest_tag:{topic}"

        # Affinity increases moderately with repeat viewing frequency (0.60 -> 1.0)
        affinity = min(1.0, 0.60 + min(count, 8) * 0.05)

        extracted_interests.append({
            "canonical_token": canonical,
            "display_name": display_name,
            "category": category,
            "provider": "google",
            "source_detail": "youtube_activity_portability",
            "confidence": 0.85,
            "affinity": round(affinity, 2),
            "user_confirmed": True,
            "imported_at": now_iso,
            # Only aggregated frequency metadata is saved; raw titles are deleted
            "raw_data": {"event_count": count},
        })

    return extracted_interests


def check_user_google_portability_scope(token_record: Dict[str, Any]) -> bool:
    """Verify that the user's OAuth token has granted the Data Portability scope."""
    scope_str = token_record.get("scope", "") or ""
    scopes = set(scope_str.split())
    return (
        GOOGLE_DATA_PORTABILITY_SCOPE in scopes
        or "https://www.googleapis.com/auth/dataportability.myactivity.youtube" in scopes
        or any("dataportability.myactivity.youtube" in s for s in scopes)
    )


def initiate_google_portability_export(user_id: str, repo=None) -> Dict[str, Any]:
    """
    Call Google Data Portability API portabilityArchive:initiate to start an asynchronous export
    of YouTube activity (myactivity.youtube). Persists a job record in SQLite.
    """
    active_repo = repo or default_sqlite_repo
    token_record = active_repo.get_oauth_token(user_id, "google")
    if not token_record:
        raise PermissionError("Google account is not connected. Please authorize Google first.")

    # Verify granted scope
    if not check_user_google_portability_scope(token_record):
        raise PermissionError(
            "Connected Google account lacks the required 'dataportability.myactivity.youtube' permission. "
            "Please reconnect your account with Data Portability permissions."
        )

    access_token = token_record["access_token"]
    req = urllib.request.Request(
        GOOGLE_PORTABILITY_INITIATE_URL,
        data=json.dumps({"resources": ["myactivity.youtube"]}).encode("utf-8"),
        method="POST",
    )
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        status_code = e.code
        err_body = e.read().decode("utf-8", errors="replace")
        logger.error("Data Portability initiation failed (%d): %s", status_code, err_body)
        if status_code == 403:
            raise PermissionError(
                "Google Data Portability API returned 403 Forbidden. "
                "Ensure the API is enabled in Google Cloud Console and the OAuth app has CASA verification."
            ) from e
        if status_code == 429:
            raise RuntimeError(
                "Google Data Portability cooldown period active. Google restricts exports to once per 24 hours to 30 days."
            ) from e
        raise RuntimeError(f"Google Data Portability API initiation failed with HTTP {status_code}.") from e

    archive_job_id = data.get("archiveJobId")
    if not archive_job_id:
        raise RuntimeError("Google Data Portability API returned an invalid response (missing archiveJobId).")

    # Persist job record in SQLite
    job = active_repo.create_portability_job(
        user_id=user_id,
        provider="google",
        resource="myactivity.youtube",
        archive_job_id=archive_job_id,
        status="IN_PROGRESS",
    )
    return job


def get_google_portability_job_status(user_id: str, job_id: Optional[str] = None, repo=None) -> Dict[str, Any]:
    """
    Check the status of a Data Portability export job.
    Queries the Google archiveJobs state endpoint if currently in progress.
    """
    active_repo = repo or default_sqlite_repo
    if job_id:
        job = active_repo.get_portability_job(job_id, user_id)
    else:
        job = active_repo.get_latest_portability_job(user_id, provider="google", resource="myactivity.youtube")

    if not job:
        return {"status": "NOT_STARTED", "message": "No active or previous export job found."}

    # If job is already finished locally, return status
    if job.get("status") in ("COMPLETED", "FAILED", "CANCELLED"):
        return job

    # If in progress, poll upstream Google API
    archive_job_id = job.get("archive_job_id")
    if not archive_job_id:
        return job

    token_record = active_repo.get_oauth_token(user_id, "google")
    if not token_record:
        return job

    access_token = token_record["access_token"]
    state_url = GOOGLE_PORTABILITY_STATE_URL.format(archive_job_id=urllib.parse.quote(archive_job_id))
    req = urllib.request.Request(state_url, method="GET")
    req.add_header("Authorization", f"Bearer {access_token}")

    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        logger.error("Failed to query Google archive job state: %s", e)
        return job

    upstream_state = data.get("state", "").upper()
    urls = data.get("urls", [])

    if upstream_state == "COMPLETE":
        job = active_repo.update_portability_job(
            job["id"],
            user_id,
            status="READY",
        )
        return {**job, "urls_available": bool(urls)}
    elif upstream_state in ("FAILED", "CANCELLED"):
        job = active_repo.update_portability_job(
            job["id"],
            user_id,
            status=upstream_state,
            error_code=f"UPSTREAM_{upstream_state}",
        )
        return job

    return job


def sync_google_portability_export(user_id: str, job_id: Optional[str] = None, repo=None) -> Dict[str, Any]:
    """
    Download a completed Google Data Portability archive, safely decompress it,
    extract high-level topic tags, persist to external_interests, and delete all raw data.
    """
    active_repo = repo or default_sqlite_repo
    if job_id:
        job = active_repo.get_portability_job(job_id, user_id)
    else:
        job = active_repo.get_latest_portability_job(user_id, provider="google", resource="myactivity.youtube")

    if not job:
        raise ValueError("No export job found to synchronize.")

    archive_job_id = job.get("archive_job_id")
    if not archive_job_id:
        raise ValueError("Job record is missing Google archiveJobId.")

    token_record = active_repo.get_oauth_token(user_id, "google")
    if not token_record:
        raise PermissionError("Google account is not connected.")

    access_token = token_record["access_token"]

    # Retrieve signed download URLs from Google
    state_url = GOOGLE_PORTABILITY_STATE_URL.format(archive_job_id=urllib.parse.quote(archive_job_id))
    req = urllib.request.Request(state_url, method="GET")
    req.add_header("Authorization", f"Bearer {access_token}")

    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            state_data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        logger.error("Failed to get Google archive state: %s", e)
        raise RuntimeError(f"Google Data Portability status query failed ({e.code}).") from e

    state = state_data.get("state", "").upper()
    if state != "COMPLETE":
        raise ValueError(f"Archive is not yet complete (Google state: {state}). Please wait and retry.")

    urls = state_data.get("urls", [])
    if not urls:
        raise ValueError("Google reported export COMPLETE but provided no download URLs.")

    download_url = urls[0]
    if not is_safe_download_url(download_url):
        raise ValueError("Security violation: Download URL failed anti-SSRF hostname validation.")

    # Create temporary directory for safe download, decompression, and parsing
    temp_dir = tempfile.mkdtemp(prefix="heartmatch_portability_")
    try:
        temp_zip_path = os.path.join(temp_dir, "archive.zip")
        max_download_bytes = getattr(settings, "MAX_ARCHIVE_DOWNLOAD_BYTES", 50 * 1024 * 1024)

        # Download with streaming byte limit
        dl_req = urllib.request.Request(download_url, method="GET")
        dl_req.add_header("User-Agent", "HeartMatch-Portability-Worker/1.0")

        bytes_downloaded = 0
        opener = urllib.request.build_opener(SafeRedirectHandler())
        with opener.open(dl_req, timeout=30.0) as dl_resp, open(temp_zip_path, "wb") as out_f:
            while True:
                chunk = dl_resp.read(65536)
                if not chunk:
                    break
                bytes_downloaded += len(chunk)
                if bytes_downloaded > max_download_bytes:
                    raise ValueError(
                        f"Archive download exceeded maximum allowed compressed size ({bytes_downloaded} > {max_download_bytes} bytes)."
                    )
                out_f.write(chunk)

        # Decompress safely
        extract_dir = os.path.join(temp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        safe_extract_zip_archive(temp_zip_path, extract_dir)

        # Extract topics and map to standard categories
        extracted_interests = extract_topics_from_youtube_activity(extract_dir)

        # Persist normalized interests
        if extracted_interests:
            active_repo.save_external_interests(user_id, "google", extracted_interests)

        now_iso = datetime.now(timezone.utc).isoformat()
        updated_job = active_repo.update_portability_job(
            job["id"],
            user_id,
            status="COMPLETED",
            items_extracted=len(extracted_interests),
            completed_at=now_iso,
        )

        return {
            "user_id": user_id,
            "job_id": job["id"],
            "status": "COMPLETED",
            "imported_count": len(extracted_interests),
            "interests": extracted_interests,
        }
    finally:
        # Guarantee raw download and extracted files are completely purged from disk
        shutil.rmtree(temp_dir, ignore_errors=True)



