"""
Account deletion and authentication brute-force protection services.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models

logger = logging.getLogger(__name__)

# Sliding-window login brute-force protection
_LOGIN_LOCK = threading.Lock()
_ACCOUNT_FAILURES: dict[str, deque[float]] = defaultdict(deque)
_IP_FAILURES: dict[str, deque[float]] = defaultdict(deque)

LOGIN_WINDOW_SECONDS = 300
MAX_ACCOUNT_FAILURES = 10
MAX_IP_FAILURES = 30


def _prune_window(bucket: deque[float], now: float) -> None:
    cutoff = now - LOGIN_WINDOW_SECONDS
    while bucket and bucket[0] < cutoff:
        bucket.popleft()


def enforce_login_rate_limit(identifier: str, client_ip: str = "unknown") -> None:
    """Reject login attempts with HTTP 429 if failure thresholds are exceeded."""
    now = time.monotonic()
    acct_key = f"{identifier.strip().lower()}|{client_ip}"
    with _LOGIN_LOCK:
        acct_bucket = _ACCOUNT_FAILURES[acct_key]
        ip_bucket = _IP_FAILURES[client_ip]
        _prune_window(acct_bucket, now)
        _prune_window(ip_bucket, now)
        if len(acct_bucket) >= MAX_ACCOUNT_FAILURES or len(ip_bucket) >= MAX_IP_FAILURES:
            raise HTTPException(
                status_code=429,
                detail="Too many failed login attempts. Please wait a few minutes and try again.",
                headers={"Retry-After": str(LOGIN_WINDOW_SECONDS)},
            )


def record_login_failure(identifier: str, client_ip: str = "unknown") -> None:
    """Record a failed login attempt for rate-limiting."""
    now = time.monotonic()
    acct_key = f"{identifier.strip().lower()}|{client_ip}"
    with _LOGIN_LOCK:
        _ACCOUNT_FAILURES[acct_key].append(now)
        _IP_FAILURES[client_ip].append(now)


def clear_login_failures(identifier: str, client_ip: str = "unknown") -> None:
    """Clear failure counters on successful login."""
    acct_key = f"{identifier.strip().lower()}|{client_ip}"
    with _LOGIN_LOCK:
        _ACCOUNT_FAILURES.pop(acct_key, None)


def reset_login_rate_limits() -> None:
    """Clear all login rate-limit state (testing helper)."""
    with _LOGIN_LOCK:
        _ACCOUNT_FAILURES.clear()
        _IP_FAILURES.clear()


def delete_user_account_data(
    db: Session,
    user: models.User,
    *,
    upload_profiles_dir: Path,
    verification_storage_module: Any = None,
    attachment_storage_obj: Any = None,
) -> dict[str, Any]:
    """
    Permanently delete a user account and all dependent records and media files.

    Deletes Chats/Messages explicitly (since Chat/Message FKs do not specify
    ondelete="CASCADE") before deleting the User and cascading dating/safety rows.
    """
    user_id = user.id
    user_email = (user.email or "").strip().lower()
    user_phone = (user.phone_number or "").strip()

    # 1. Collect files to remove from disk after DB commit succeeds
    profile_photo_files: list[Path] = []
    profile = db.query(models.UserProfile).filter(models.UserProfile.user_id == user_id).first()
    if profile:
        photos = db.query(models.ProfilePhoto).filter(models.ProfilePhoto.profile_id == profile.id).all()
        for p in photos:
            if p.photo_url:
                fname = os.path.basename(p.photo_url)
                if fname:
                    profile_photo_files.append(upload_profiles_dir / fname)

    verification_keys: list[str] = [
        v.evidence_key
        for v in db.query(models.UserVerification).filter(models.UserVerification.user_id == user_id).all()
        if getattr(v, "evidence_key", None)
    ]

    user_chats = db.query(models.Chat).filter(
        or_(models.Chat.user1_id == user_id, models.Chat.user2_id == user_id)
    ).all()
    chat_ids = [c.id for c in user_chats]

    attachment_keys: list[str] = []
    legacy_voice_files: list[Path] = []
    if chat_ids:
        chat_messages = db.query(models.Message).filter(models.Message.chat_id.in_(chat_ids)).all()
        for msg in chat_messages:
            if getattr(msg, "attachment_storage_key", None):
                attachment_keys.append(msg.attachment_storage_key)
            if getattr(msg, "audio_url", None) and str(msg.audio_url).startswith("/uploads/voice/"):
                vname = os.path.basename(str(msg.audio_url))
                if vname:
                    legacy_voice_files.append(Path("uploads/voice") / vname)

    # 2. Delete dependent rows without CASCADE FKs first
    if chat_ids:
        db.query(models.Message).filter(models.Message.chat_id.in_(chat_ids)).update(
            {models.Message.reply_to_id: None}, synchronize_session=False
        )
        msg_ids_subq = db.query(models.Message.id).filter(models.Message.chat_id.in_(chat_ids))
        db.query(models.MessageReaction).filter(
            models.MessageReaction.message_id.in_(msg_ids_subq)
        ).delete(synchronize_session=False)
        db.query(models.DeathZoneConversationState).filter(
            models.DeathZoneConversationState.chat_id.in_(chat_ids)
        ).delete(synchronize_session=False)
        db.query(models.DeathZoneNotification).filter(
            models.DeathZoneNotification.chat_id.in_(chat_ids)
        ).delete(synchronize_session=False)
        db.query(models.AIRecoveryIntervention).filter(
            models.AIRecoveryIntervention.chat_id.in_(chat_ids)
        ).delete(synchronize_session=False)
        db.query(models.AISuggestionEvent).filter(
            models.AISuggestionEvent.chat_id.in_(chat_ids)
        ).delete(synchronize_session=False)
        db.query(models.AISuggestionRecord).filter(
            models.AISuggestionRecord.chat_id.in_(chat_ids)
        ).delete(synchronize_session=False)
        db.query(models.Message).filter(models.Message.chat_id.in_(chat_ids)).delete(
            synchronize_session=False
        )
        db.query(models.Chat).filter(models.Chat.id.in_(chat_ids)).delete(
            synchronize_session=False
        )

    # Any stray messages authored by user
    db.query(models.Message).filter(models.Message.sender_id == user_id).update(
        {models.Message.reply_to_id: None}, synchronize_session=False
    )
    db.query(models.Message).filter(models.Message.sender_id == user_id).delete(
        synchronize_session=False
    )

    # Clear auth verification OTPs for this account's identifiers
    if user_email:
        db.query(models.AuthVerificationCode).filter(
            models.AuthVerificationCode.identifier == user_email
        ).delete(synchronize_session=False)
    if user_phone:
        db.query(models.AuthVerificationCode).filter(
            models.AuthVerificationCode.identifier == user_phone
        ).delete(synchronize_session=False)

    # Delete dating, safety, memory, and profile rows explicitly for DB portability
    db.query(models.Match).filter(
        or_(models.Match.user1_id == user_id, models.Match.user2_id == user_id)
    ).delete(synchronize_session=False)
    db.query(models.Swipe).filter(
        or_(models.Swipe.user_id == user_id, models.Swipe.target_user_id == user_id)
    ).delete(synchronize_session=False)
    db.query(models.UserBlock).filter(
        or_(models.UserBlock.blocker_id == user_id, models.UserBlock.blocked_id == user_id)
    ).delete(synchronize_session=False)
    db.query(models.UserReport).filter(
        or_(models.UserReport.reporter_id == user_id, models.UserReport.reported_id == user_id)
    ).delete(synchronize_session=False)
    db.query(models.UserVerification).filter(models.UserVerification.user_id == user_id).delete(
        synchronize_session=False
    )
    db.query(models.UserMemory).filter(models.UserMemory.user_id == user_id).delete(
        synchronize_session=False
    )
    if profile:
        db.query(models.ProfilePhoto).filter(models.ProfilePhoto.profile_id == profile.id).delete(
            synchronize_session=False
        )
        db.delete(profile)

    db.delete(user)
    db.commit()

    # 3. Best-effort disk media cleanup after successful DB deletion
    for path in profile_photo_files + legacy_voice_files:
        try:
            if path.is_file():
                path.unlink()
        except Exception as exc:
            logger.warning("Could not remove user media file during account deletion: %s", exc)

    if verification_storage_module is not None:
        for key in verification_keys:
            try:
                verification_storage_module.delete_evidence(key)
            except Exception as exc:
                logger.warning("Could not remove verification evidence during deletion: %s", exc)

    if attachment_storage_obj is not None:
        for key in attachment_keys:
            try:
                attachment_storage_obj.remove_attachment(key)
            except Exception as exc:
                logger.warning("Could not remove attachment during deletion: %s", exc)

    logger.info("Account deleted cleanly for user_id=%s", user_id)
    return {"deleted": True, "user_id": user_id, "chats_removed": len(chat_ids)}
