"""Encrypted, private storage for identity verification evidence.

This directory is deliberately separate from ``/uploads``. Evidence is
encrypted before it is written and can only be decrypted by reviewer routes.
"""

import os
import re
import uuid
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


MAX_EVIDENCE_BYTES = 10 * 1024 * 1024
CHUNK_SIZE = 64 * 1024
EVIDENCE_KEY_PATTERN = re.compile(r"^[a-f0-9]{32}$")


class EvidenceConfigurationError(RuntimeError):
    """The encryption key or private storage configuration is unavailable."""


def reviewer_user_ids() -> set[int]:
    """Read reviewer account IDs from operator-managed server configuration."""
    raw_ids = os.getenv("RAAHI_VERIFICATION_REVIEWER_IDS", "").strip()
    if not raw_ids:
        return set()

    values = [value.strip() for value in raw_ids.split(",")]
    if any(not value.isdecimal() or int(value) < 1 for value in values):
        raise EvidenceConfigurationError("Reviewer ID configuration is invalid")
    return {int(value) for value in values}


def _fernet() -> Fernet:
    key = os.getenv("RAAHI_VERIFICATION_FERNET_KEY", "").strip()
    if not key:
        raise EvidenceConfigurationError("Verification encryption is not configured")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise EvidenceConfigurationError("Verification encryption is not configured") from exc


def workflow_available() -> bool:
    try:
        _fernet()
        private_evidence_root()
        return bool(reviewer_user_ids())
    except EvidenceConfigurationError:
        return False


def require_workflow_configuration() -> None:
    _fernet()
    private_evidence_root()
    if not reviewer_user_ids():
        raise EvidenceConfigurationError("Verification review is not configured")


def private_evidence_root() -> Path:
    configured = os.getenv(
        "RAAHI_VERIFICATION_STORAGE_DIR",
        "storage/private_verification",
    )
    root = Path(configured).expanduser().resolve()
    public_root = Path("uploads").resolve()
    try:
        root.relative_to(public_root)
    except ValueError:
        return root
    raise EvidenceConfigurationError("Private verification storage cannot use the public upload directory")


def identify_evidence(content: bytes, verification_type: str) -> str:
    """Validate signatures and return the media type without trusting filenames."""
    if not content:
        raise ValueError("Evidence file is empty")

    if verification_type == "face":
        allowed = {
            "image/jpeg": content.startswith(b"\xff\xd8\xff"),
            "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/webp": len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP",
        }
    else:
        allowed = {
            "application/pdf": content.startswith(b"%PDF-"),
            "image/jpeg": content.startswith(b"\xff\xd8\xff"),
            "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/webp": len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP",
        }

    for media_type, matches in allowed.items():
        if matches:
            return media_type
    raise ValueError("Evidence file type is not supported")


def save_evidence(content: bytes) -> str:
    """Encrypt and persist evidence under an opaque generated key."""
    if len(content) > MAX_EVIDENCE_BYTES:
        raise ValueError("Evidence file exceeds the 10 MiB limit")

    encryptor = _fernet()
    root = private_evidence_root()
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        # Encryption remains mandatory; deployment ACLs protect Windows paths.
        pass

    evidence_key = uuid.uuid4().hex
    target = evidence_path(evidence_key)
    encrypted = encryptor.encrypt(content)
    with target.open("xb") as output:
        output.write(encrypted)
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return evidence_key


def evidence_path(evidence_key: str) -> Path:
    if not EVIDENCE_KEY_PATTERN.fullmatch(evidence_key or ""):
        raise ValueError("Invalid evidence key")
    return private_evidence_root() / evidence_key


def read_evidence(evidence_key: str) -> bytes:
    path = evidence_path(evidence_key)
    try:
        encrypted = path.read_bytes()
    except OSError as exc:
        raise FileNotFoundError("Verification evidence is unavailable") from exc
    try:
        return _fernet().decrypt(encrypted)
    except InvalidToken as exc:
        raise EvidenceConfigurationError("Verification evidence cannot be decrypted") from exc


def delete_evidence(evidence_key: str | None) -> bool:
    if not evidence_key:
        return True
    try:
        evidence_path(evidence_key).unlink(missing_ok=True)
        return True
    except (OSError, ValueError, EvidenceConfigurationError):
        # Do not log sensitive paths or let cleanup failures leak evidence.
        return False
