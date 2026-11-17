"""Bugzyme backend: REST + WebSocket chat (Reply + Delete)."""

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import uuid
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from fastapi import (
    Body,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    File,
    Form,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pwdlib import PasswordHash
from sqlalchemy import and_, or_, func, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, load_only, selectinload
from starlette.concurrency import run_in_threadpool
from app.ai.graph import run_conversation_workflow
from app.ai.death_zone import analyze_death_zone, is_death_zone
from app.ai.targeting import analyze_participant_effort
from app.ai.recovery_strategy import PROMPT_VERSION
from app.ai.ai_evaluation import VALID_EVENTS, meaningful_response
from app.ai.provider_controls import (
    AIProviderConsentRequired,
    AIProviderUnavailable,
    assert_provider_consent,
    enforce_ai_rate_limit,
    provider_consent_scope,
)
from . import models, schemas, verification_storage
from . import storage as attachment_storage
from .connection_manager import ConnectionManager
from .database import Base, SessionLocal, engine, get_db
from .services.dating_ml_adapter import DatingMLAdapter, MatchingConsentRequired, MatchingNotAllowed

logger = logging.getLogger("bugzyme")

# ============================================================
# CONFIG
# ============================================================

SECRET_KEY = os.environ.get("SECRET_KEY", "")
if len(SECRET_KEY) < 32:
    raise RuntimeError(
        "Set the SECRET_KEY environment variable (32+ chars)."
    )

ALGORITHM = "HS256"
TOKEN_TTL_HOURS = int(os.getenv("TOKEN_TTL_HOURS", "24"))

ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "*").split(",")
    if o.strip()
]
PRODUCTION_MODE = os.getenv("RAAHI_ENVIRONMENT", "development").strip().lower() == "production"

IDLE_TIMEOUT = 70
ALLOWED_MESSAGE_REACTIONS = frozenset({"❤️", "😂", "👍", "🔥", "😮", "😢"})
ORIENTATION_MATCHING_CONSENT_VERSION = "orientation-matching-v1"
BEHAVIORAL_PERSONALIZATION_CONSENT_VERSION = "behavioral-personalization-v1"
ORIENTATION_MATCHING_DISCLOSURE = (
    "If enabled, the Dating ML eligibility check uses the orientation you chose and gender "
    "to determine whether attraction is mutual. Orientation stays private and is not shown "
    "on your public profile. This is optional and can be turned off at any time."
)
BEHAVIORAL_PERSONALIZATION_DISCLOSURE = (
    "If enabled in a future release, persisted likes, passes, and superlikes may be used "
    "to personalize profile ordering. Chat content and external-interest data are not used. "
    "This setting is optional, starts off, and can be turned off at any time."
)

password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")
manager = ConnectionManager()
dating_ml_adapter = DatingMLAdapter()


# ============================================================
# GENERAL HELPERS
# ============================================================

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt):
    if dt is None:
        return None
    return dt.isoformat() + "Z"


MAX_AI_CONTEXT_MESSAGES = 15
MAX_UNVIEWED_NOTIFICATION_AGE = timedelta(hours=24)
VIEWED_NOTIFICATION_LIFETIME = timedelta(seconds=30)
MIN_VOICE_DURATION_SECONDS = 1
MAX_VOICE_DURATION_SECONDS = 300


def provider_consent_guard(db: Session, user_ids: set[int] | list[int]):
    """Build a live, fail-closed consent check for every conversation participant."""
    participant_ids = tuple(sorted(set(user_ids)))
    if not participant_ids:
        return lambda: False

    def check() -> bool:
        enabled_count = db.query(models.User.id).filter(
            models.User.id.in_(participant_ids),
            models.User.ai_provider_processing_enabled.is_(True),
        ).count()
        return enabled_count == len(participant_ids)

    return check


def require_provider_consent(db: Session, user_ids: set[int] | list[int]) -> None:
    if not provider_consent_guard(db, user_ids)():
        raise HTTPException(
            status_code=403,
            detail={"code": "ai_provider_consent_required",
                    "message": "Both chat participants must enable AI provider processing."},
        )


def _enforce_manual_ai_limit(user_id: int, chat_id: int, operation: str = "manual") -> None:
    try:
        enforce_ai_rate_limit(user_id, chat_id, operation=operation)
    except AIProviderUnavailable as exc:
        raise HTTPException(
            status_code=429,
            detail={"code": "ai_rate_limited", "message": "Please wait before requesting AI assistance again."},
        ) from exc


# ============================================================
# APP
# ============================================================

def ensure_message_schema_columns(connection):
    """Add missing message metadata columns to an existing PostgreSQL table."""
    logger.info(
        "Checking message schema columns during startup (dialect=%s)",
        connection.dialect.name,
    )

    if connection.dialect.name != "postgresql":
        logger.info(
            "Skipping PostgreSQL message-schema check for dialect=%s",
            connection.dialect.name,
        )
        return

    statements = {
        "attachment_storage_key": (
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS "
            "attachment_storage_key VARCHAR(64) NULL"
        ),
        "attachment_name": (
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS "
            "attachment_name VARCHAR(255) NULL"
        ),
        "attachment_mime_type": (
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS "
            "attachment_mime_type VARCHAR(100) NULL"
        ),
        "attachment_size_bytes": (
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS "
            "attachment_size_bytes INTEGER NULL"
        ),
        "reaction_revision": (
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS "
            "reaction_revision INTEGER DEFAULT 0 NOT NULL"
        ),
        "read_at": (
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS "
            "read_at TIMESTAMP NULL"
        ),
    }

    try:
        existing = {
            column["name"]
            for column in inspect(connection).get_columns("messages")
        }
        missing = [name for name in statements if name not in existing]

        if missing:
            logger.warning(
                "Adding missing message schema columns to messages: %s",
                ", ".join(missing),
            )

            for name in missing:
                connection.exec_driver_sql(statements[name])

            connection.commit()
        else:
            logger.info(
                "All message schema columns already exist on messages"
            )

        remaining = {
            column["name"]
            for column in inspect(connection).get_columns("messages")
        }

        missing_after_check = [
            name for name in statements if name not in remaining
        ]

        if missing_after_check:
            raise RuntimeError(
                "Message schema columns still missing after startup check: "
                + ", ".join(missing_after_check)
            )

    except Exception:
        connection.rollback()
        logger.exception("Message schema startup check failed")
        raise

    logger.info("Message schema startup check passed")


def ensure_user_profile_columns(connection):
    """Add public profile fields to existing PostgreSQL user tables."""
    if connection.dialect.name != "postgresql":
        return
    statements = {
        "full_name": "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(80) NULL",
        "bio": "ALTER TABLE users ADD COLUMN IF NOT EXISTS bio TEXT NULL",
        "ai_memory_enabled": "ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_memory_enabled BOOLEAN NOT NULL DEFAULT FALSE",
        "ai_memory_processed_through_message_id": "ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_memory_processed_through_message_id INTEGER NULL",
        "activity_status_enabled": "ALTER TABLE users ADD COLUMN IF NOT EXISTS activity_status_enabled BOOLEAN NOT NULL DEFAULT TRUE",
    }
    existing = {column["name"] for column in inspect(connection).get_columns("users")}
    missing = [name for name in statements if name not in existing]
    try:
        for name in missing:
            connection.exec_driver_sql(statements[name])
        if missing:
            connection.commit()
        remaining = {column["name"] for column in inspect(connection).get_columns("users")}
        missing_after_check = [name for name in statements if name not in remaining]
        if missing_after_check:
            raise RuntimeError("User profile columns still missing after startup check: " + ", ".join(missing_after_check))
    except Exception:
        connection.rollback()
        logger.exception("User profile schema startup check failed")
        raise


@asynccontextmanager
async def lifespan(_: FastAPI):
    if PRODUCTION_MODE:
        logger.info(
            "Production schema is managed by Alembic; skipping startup schema and data mutations"
        )
    else:
        Base.metadata.create_all(bind=engine)

        with engine.connect() as connection:
            ensure_message_schema_columns(connection)
            ensure_user_profile_columns(connection)

        with SessionLocal() as db:
            db.query(models.User).update(
                {models.User.is_online: False},
                synchronize_session=False
            )
            db.commit()

    yield


app = FastAPI(
    title="Bugzyme",
    lifespan=lifespan
)

# Profile photos are intentionally public. Chat voice and file content is
# served only through authenticated, membership-checked routes below.
os.makedirs("uploads/profiles", exist_ok=True)
app.mount(
    "/uploads/profiles",
    StaticFiles(directory="uploads/profiles"),
    name="profile-uploads"
)


@app.middleware("http")
async def catch_unhandled(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:
        logger.exception(
            "Unhandled error on %s %s",
            request.method,
            request.url.path
        )
        return JSONResponse(
            {"detail": "Internal server error"},
            status_code=500
        )


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# AUTH
# ============================================================

def create_token(user_id: int):
    expire_time = datetime.now(timezone.utc) + timedelta(
        hours=TOKEN_TTL_HOURS
    )

    return jwt.encode(
        {
            "sub": str(user_id),
            "exp": expire_time
        },
        SECRET_KEY,
        algorithm=ALGORITHM
    )


def decode_token(token: str):
    try:
        return int(
            jwt.decode(
                token,
                SECRET_KEY,
                algorithms=[ALGORITHM]
            )["sub"]
        )
    except (JWTError, KeyError, ValueError, TypeError):
        return None


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    user_id = decode_token(token)

    if user_id is None:
        raise HTTPException(
            401,
            "Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )

    user = db.get(models.User, user_id)

    if not user:
        raise HTTPException(401, "User not found")

    return user


# ============================================================
# CHAT HELPERS
# ============================================================

def other_user(chat: models.Chat, user_id: int):
    if chat.user1_id == user_id:
        return chat.user2_id
    return chat.user1_id


def member_chat(db: Session, chat_id: int, user_id: int):
    chat = db.get(models.Chat, chat_id)

    if chat and user_id in (
        chat.user1_id,
        chat.user2_id
    ):
        return chat

    return None


def active_chat_for_interaction(db: Session, chat_id: int, user_id: int):
    """Return a chat only while its dating match is active and unblocked.

    Historical chat reads remain member-authorized through ``member_chat``;
    this stricter helper is for new writes and live interaction only.
    """
    chat = member_chat(db, chat_id, user_id)
    if not chat:
        return None
    partner_id = other_user(chat, user_id)
    match = db.query(models.Match.id).filter(
        models.Match.chat_id == chat.id,
        models.Match.user1_id == min(user_id, partner_id),
        models.Match.user2_id == max(user_id, partner_id),
        models.Match.is_active.is_(True),
    ).first()
    if not match:
        return None
    blocked = db.query(models.UserBlock.id).filter(or_(
        and_(models.UserBlock.blocker_id == user_id, models.UserBlock.blocked_id == partner_id),
        and_(models.UserBlock.blocker_id == partner_id, models.UserBlock.blocked_id == user_id),
    )).first()
    if blocked:
        return None
    profiles = db.query(models.UserProfile).filter(
        models.UserProfile.user_id.in_([user_id, partner_id])
    ).all()
    if len(profiles) != 2 or any(not _is_discoverable_profile(profile) for profile in profiles):
        return None
    return chat


def find_chat(db: Session, user1_id: int, user2_id: int):
    return db.query(models.Chat).filter(
        or_(
            (models.Chat.user1_id == user1_id) &
            (models.Chat.user2_id == user2_id),

            (models.Chat.user1_id == user2_id) &
            (models.Chat.user2_id == user1_id)
        )
    ).first()

def get_partners(db: Session, user_id: int):
    chats = db.query(models.Chat).filter(
        or_(
            and_(
                models.Chat.user1_id == user_id,
                models.Chat.deleted_by_user1.is_(False)
            ),
            and_(
                models.Chat.user2_id == user_id,
                models.Chat.deleted_by_user2.is_(False)
            )
        )
    ).all()

    return {
        chat.id: other_user(chat, user_id)
        for chat in chats
        if active_chat_for_interaction(db, chat.id, user_id)
    }
# ============================================================
# MESSAGE SAVE
# ============================================================

def save_message(
    db: Session,
    sender_id: int,
    chat_id: int,
    content: str,
    reply_to_id: int | None = None
):
    chat = active_chat_for_interaction(db, chat_id, sender_id)

    if not chat:
        return None

    # Validate reply
    if reply_to_id is not None:
        parent = db.get(models.Message, reply_to_id)

        if (
            not parent
            or parent.chat_id != chat_id
            or parent.is_deleted
        ):
            return None

    message = models.Message(
        chat_id=chat_id,
        sender_id=sender_id,
        content=content,
        created_at=utcnow(),
        is_delivered=False,
        is_read=False,
        is_deleted=False,
        reply_to_id=reply_to_id,
    )

    db.add(message)
    db.commit()
    db.refresh(message)

    return {
        "id": message.id,
        "chat_id": chat_id,
        "sender_id": sender_id,
        "content": message.content,
        "created_at": iso(message.created_at),
        "read_at": iso(message.read_at),
        "is_delivered": False,
        "is_read": False,
        "is_deleted": False,
        "reply_to_id": message.reply_to_id,
        "receiver_id": other_user(chat, sender_id),
    }



def save_voice_message(
    db: Session,
    sender_id: int,
    chat_id: int,
    storage_key: str,
    filename: str,
    audio_mime_type: str,
    size_bytes: int,
    audio_duration: int | None,
):
    valid_voice_types = {
        (mime, kind, extension)
        for extension, (mime, kind) in attachment_storage.ALLOWED_TYPES.items()
        if kind == "voice"
    }
    filename = Path((filename or "").replace("\\", "/")).name
    metadata_valid = (
        isinstance(storage_key, str)
        and re.fullmatch(r"[a-f0-9]{32}", storage_key) is not None
        and (audio_mime_type, "voice", Path(filename).suffix.lower()) in valid_voice_types
        and isinstance(size_bytes, int)
        and not isinstance(size_bytes, bool)
        and 0 < size_bytes <= attachment_storage.MAX_ATTACHMENT_BYTES
        and (
            audio_duration is None
            or (isinstance(audio_duration, int) and not isinstance(audio_duration, bool)
                and MIN_VOICE_DURATION_SECONDS <= audio_duration <= MAX_VOICE_DURATION_SECONDS)
        )
    )
    if not metadata_valid:
        return None

    chat = active_chat_for_interaction(
        db,
        chat_id,
        sender_id
    )

    if not chat:
        return None

    message = models.Message(
        chat_id=chat_id,
        sender_id=sender_id,
        content=None,
        created_at=utcnow(),
        is_delivered=False,
        is_read=False,
        is_deleted=False,
        reply_to_id=None,

        message_type="voice",
        attachment_storage_key=storage_key,
        attachment_name=filename,
        attachment_mime_type=audio_mime_type,
        attachment_size_bytes=size_bytes,
        audio_duration=audio_duration,
        audio_mime_type=audio_mime_type,
    )

    db.add(message)
    db.flush()
    message.audio_url = f"/attachments/{message.id}/content"
    db.commit()
    db.refresh(message)

    return {
        "id": message.id,
        "chat_id": chat_id,
        "sender_id": sender_id,
        "content": None,
        "created_at": iso(message.created_at),
        "read_at": iso(message.read_at),
        "is_delivered": False,
        "is_read": False,
        "is_deleted": False,
        "reply_to_id": None,

        "message_type": "voice",
        "audio_url": message.audio_url,
        "audio_duration": message.audio_duration,
        "audio_mime_type": message.audio_mime_type,

        "receiver_id": other_user(
            chat,
            sender_id
        ),
    }


def save_attachment_message(
    db: Session,
    sender_id: int,
    chat_id: int,
    content: str | None,
    reply_to_id: int | None,
    storage_key: str,
    filename: str,
    mime_type: str,
    size_bytes: int,
    message_type: str,
):
    chat = active_chat_for_interaction(db, chat_id, sender_id)
    if not chat:
        return None

    if content is not None:
        content = content.strip()
        if len(content) > schemas.MAX_MESSAGE_LEN:
            return None
        content = content or None

    if reply_to_id is not None:
        parent = db.get(models.Message, reply_to_id)
        if not parent or parent.chat_id != chat_id or parent.is_deleted:
            return None

    message = models.Message(
        chat_id=chat_id,
        sender_id=sender_id,
        content=content,
        created_at=utcnow(),
        is_delivered=False,
        is_read=False,
        is_deleted=False,
        reply_to_id=reply_to_id,
        message_type=message_type,
        attachment_storage_key=storage_key,
        attachment_name=filename,
        attachment_mime_type=mime_type,
        attachment_size_bytes=size_bytes,
    )
    db.add(message)
    db.commit()
    db.refresh(message)

    return {
        "id": message.id,
        "chat_id": chat_id,
        "sender_id": sender_id,
        "content": message.content,
        "created_at": iso(message.created_at),
        "read_at": iso(message.read_at),
        "is_delivered": message.is_delivered,
        "is_read": message.is_read,
        "is_deleted": message.is_deleted,
        "reply_to_id": message.reply_to_id,
        "message_type": message.message_type,
        "attachment_name": message.attachment_name,
        "attachment_mime_type": message.attachment_mime_type,
        "attachment_size_bytes": message.attachment_size_bytes,
        "receiver_id": other_user(chat, sender_id),
    }


# ============================================================
# MESSAGE DELETE
# ============================================================

def soft_delete_message(
    db: Session,
    user_id: int,
    message_id: int,
    for_everyone: bool = True
):
    # Per-user message hiding has no storage representation yet. Never map a
    # false request onto the shared-row soft-delete operation.
    if not for_everyone:
        return None

    message = db.get(models.Message, message_id)

    if not message or message.is_deleted:
        return None

    chat = active_chat_for_interaction(
        db,
        message.chat_id,
        user_id
    )

    if not chat:
        return None

    # Only sender can delete for everyone
    if for_everyone and message.sender_id != user_id:
        return None

    # Messages are soft-deleted, so explicitly remove their reactions.
    db.query(models.MessageReaction).filter(
        models.MessageReaction.message_id == message.id
    ).delete(synchronize_session=False)

    message.is_deleted = True
    message.deleted_at = utcnow()
    message.content = None

    db.commit()

    return {
        "message_id": message.id,
        "chat_id": message.chat_id,
        "sender_id": message.sender_id,
        "for_everyone": for_everyone,
        "receiver_id": other_user(chat, user_id),
        "attachment_storage_key": message.attachment_storage_key,
    }


def toggle_message_reaction(
    db: Session,
    user_id: int,
    chat_id: int,
    message_id: int,
    reaction: str,
):
    if reaction not in ALLOWED_MESSAGE_REACTIONS:
        return None

    chat = active_chat_for_interaction(db, chat_id, user_id)
    if not chat:
        return None

    # Lock the owning message before reading or changing a user's reaction.
    # This serializes all reaction mutations for this message in PostgreSQL.
    for attempt in range(2):
        message = (
            db.query(models.Message)
            .filter(
                models.Message.id == message_id,
                models.Message.chat_id == chat_id,
                models.Message.is_deleted.is_(False),
            )
            .with_for_update()
            .first()
        )
        if not message:
            return None

        current = db.query(models.MessageReaction).filter_by(
            message_id=message_id,
            user_id=user_id,
        ).first()

        if current and current.reaction == reaction:
            db.delete(current)
        elif current:
            current.reaction = reaction
            current.created_at = utcnow()
        else:
            db.add(models.MessageReaction(
                message_id=message_id,
                user_id=user_id,
                reaction=reaction,
                created_at=utcnow(),
            ))

        message.reaction_revision = (message.reaction_revision or 0) + 1
        try:
            db.commit()
            break
        except IntegrityError:
            # The message row lock serializes normal callers. Retrying once
            # also handles a concurrent insert from a legacy/unlocked caller;
            # the unique constraint remains the final guard.
            db.rollback()
            if attempt:
                raise

    # Generate the canonical snapshot only after the mutation is committed.
    # Re-locking the message keeps the revision and reaction rows stable while
    # they are read. A later update can still broadcast first; clients order
    # these committed snapshots by revision.
    snapshot_message = (
        db.query(models.Message)
        .filter(
            models.Message.id == message_id,
            models.Message.chat_id == chat_id,
            models.Message.is_deleted.is_(False),
        )
        .with_for_update()
        .first()
    )
    if not snapshot_message:
        return None

    reactions = db.query(models.MessageReaction).filter_by(
        message_id=message_id
    ).order_by(models.MessageReaction.user_id).all()
    revision = snapshot_message.reaction_revision or 0
    db.commit()

    return {
        "chat_id": chat_id,
        "message_id": message_id,
        "revision": revision,
        "receiver_id": other_user(chat, user_id),
        "reactions": [
            {"user_id": row.user_id, "reaction": row.reaction}
            for row in reactions
        ],
    }


# ============================================================
# CHAT DELETE
# ============================================================
def delete_chat_from_database(
    db: Session,
    chat_id: int,
    user_id: int
):
    chat = db.get(models.Chat, chat_id)

    if not chat:
        return None

    if user_id not in (
        chat.user1_id,
        chat.user2_id
    ):
        return None

    # Mark conversation as deleted only
    # for the current user's side.
    if chat.user1_id == user_id:
        chat.deleted_by_user1 = True
    else:
        chat.deleted_by_user2 = True

    # IMPORTANT:
    # Do NOT delete messages.
    # Do NOT delete the chat.
    db.commit()

    return {
        "chat_id": chat_id,
        "user_id": user_id,
        "other_user_id": other_user(chat, user_id)
    }
# ============================================================
# DELIVERY / READ
# ============================================================

def mark_delivered(db: Session, ids: list[int]):
    if not ids:
        return

    db.query(models.Message).filter(
        models.Message.id.in_(ids)
    ).update(
        {models.Message.is_delivered: True},
        synchronize_session=False
    )

    db.commit()


def mark_read(
    db: Session,
    user_id: int,
    chat_id: int,
    message_id: int | None
):
    chat = active_chat_for_interaction(
        db,
        chat_id,
        user_id
    )

    if not chat:
        return None

    query = db.query(models.Message).filter(
        models.Message.chat_id == chat_id,
        models.Message.sender_id == other_user(chat, user_id),
        models.Message.is_read.is_not(True),
        models.Message.is_deleted.is_not(True),
    )

    if message_id is not None:
        query = query.filter(
            models.Message.id == message_id
        )

    messages = query.all()

    for message in messages:
        message.is_read = True
        message.is_delivered = True
        message.read_at = utcnow()

    db.commit()

    return {
        "sender": other_user(chat, user_id),
        "ids": [message.id for message in messages],
        "read_at": {message.id: iso(message.read_at) for message in messages},
    }


# ============================================================
# ONLINE / OFFLINE
# ============================================================

def set_online(
    db: Session,
    user_id: int,
    online: bool
):
    user = db.get(models.User, user_id)

    if not user:
        return None

    online = bool(online and user.activity_status_enabled)
    was_online = bool(user.is_online)
    user.is_online = online

    if not online and was_online:
        user.last_seen = utcnow()

    db.commit()

    return {
        "is_online": online,
        "activity_status_enabled": bool(user.activity_status_enabled),
        "last_seen": iso(user.last_seen),
    }


def visible_online_ids(db: Session):
    connected_ids = manager.online_ids()
    if not connected_ids:
        return []
    return [row[0] for row in db.query(models.User.id).filter(
        models.User.id.in_(connected_ids),
        models.User.activity_status_enabled.is_(True),
    ).all()]


def visible_online_partner_ids(db: Session, partner_ids: set[int] | list[int]):
    candidates = set(partner_ids)
    if not candidates:
        return []
    connected_ids = manager.online_ids() & candidates
    if not connected_ids:
        return []
    return [row[0] for row in db.query(models.User.id).filter(
        models.User.id.in_(connected_ids),
        models.User.activity_status_enabled.is_(True),
    ).all()]


def load_context(
    db: Session,
    user_id: int,
    bound_chat_id: int | None
):
    user = db.get(models.User, user_id)

    if not user:
        return None

    partners = get_partners(db, user_id)

    if (
        bound_chat_id is not None
        and bound_chat_id not in partners
    ):
        return None

    # A user with no chats has no pending messages to load. Avoid using a
    # fabricated chat ID as an empty-result sentinel in the SQL query.
    if not partners:
        return {
            "username": user.username,
            "partners": partners,
            "delivered": [],
            "activity_status_enabled": user.activity_status_enabled,
        }

    query = db.query(models.Message).filter(
        models.Message.chat_id.in_(list(partners)),
        models.Message.sender_id != user_id,
        models.Message.is_delivered.is_not(True),
        models.Message.is_deleted.is_not(True),
    )

    if bound_chat_id is not None:
        query = query.filter(
            models.Message.chat_id == bound_chat_id
        )

    pending = query.all()

    for message in pending:
        message.is_delivered = True

    db.commit()

    return {
        "username": user.username,
        "partners": partners,
        "activity_status_enabled": user.activity_status_enabled,
        "delivered": [
            (
                message.sender_id,
                message.chat_id,
                message.id
            )
            for message in pending
        ]
    }


# ============================================================
# DATABASE ASYNC HELPER
# ============================================================

async def db_call(function, *args):
    def run():
        with SessionLocal() as db:
            return function(db, *args)

    return await run_in_threadpool(run)


# ============================================================
# WEBSOCKET HELPERS
# ============================================================

async def safe_send(
    websocket: WebSocket,
    payload: dict
):
    with contextlib.suppress(Exception):
        await websocket.send_json(payload)


async def broadcast_presence(
    user_id: int,
    status: str,
    last_seen=None,
    activity_status_enabled=None,
    partners: dict[int, int] | None = None,
):
    if partners is None:
        partners = await db_call(get_partners, user_id)
    if activity_status_enabled is None:
        activity_status_enabled = await db_call(
            get_activity_status_preference, user_id
        )
    if not activity_status_enabled:
        status = "hidden"
        last_seen = None

    payload = {
        "type": "presence",
        "user_id": user_id,
        "status": status,
        "last_seen": last_seen if activity_status_enabled else None,
        "activity_status_enabled": bool(activity_status_enabled),
    }
    for chat_id, recipient_id in partners.items():
        await manager.send_to_user(
            recipient_id,
            {**payload, "chat_id": chat_id},
            chat_id,
        )


def get_activity_status_preference(db: Session, user_id: int) -> bool:
    user = db.get(models.User, user_id)
    return bool(user and user.activity_status_enabled)


async def notify_chat_access_revoked(
    chat_id: int | None,
    user_ids: set[int] | list[int],
    event: dict,
    *,
    close_chat_sockets: bool = True,
):
    """Notify only affected participants and close chat-bound sockets."""
    for user_id in set(user_ids):
        await manager.send_to_user(user_id, event, chat_id)
    if chat_id is not None and close_chat_sockets:
        await manager.close_chat_sockets(
            set(user_ids), chat_id, code=1008,
            reason="Chat access is no longer active",
        )


def invalidate_chat_ai_notifications(db: Session, chat_id: int) -> None:
    """Suppress pending notifications without deleting historical payloads."""
    db.query(models.DeathZoneNotification).filter(
        models.DeathZoneNotification.chat_id == chat_id,
        models.DeathZoneNotification.status.in_(("generating", "ready")),
    ).update(
        {models.DeathZoneNotification.status: "invalidated"},
        synchronize_session=False,
    )
    state = db.get(models.DeathZoneConversationState, chat_id)
    if state is not None:
        state.active = False
        state.target_user_id = None


# ============================================================
# BACKGROUND TASKS
# ============================================================

_bg_tasks = set()


def spawn(coro):
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(coro)
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)
    except RuntimeError:
        try:
            asyncio.run(coro)
        except Exception:
            logger.exception("Failed to run background coroutine")


async def go_offline(user_id: int):
    try:
        if manager.is_online(user_id):
            return

        presence = await db_call(
            set_online,
            user_id,
            False
        )

        if manager.is_online(user_id):
            presence = await db_call(
                set_online,
                user_id,
                True
            )
            if presence["is_online"]:
                return

        await broadcast_presence(
            user_id,
            "offline",
            presence["last_seen"],
            presence["activity_status_enabled"],
        )

    except Exception:
        logger.exception(
            "go_offline failed for user %s",
            user_id
        )


# ============================================================
# PROCESS MESSAGE
# ============================================================

async def process_message(
    sender_id,
    sender_name,
    chat_id,
    content,
    client_id=None,
    origin=None,
    reply_to_id=None
):
    try:
        message = await db_call(
            save_message,
            sender_id,
            chat_id,
            content,
            reply_to_id
        )
    except Exception:
        logger.exception("Message persistence failed for chat_id=%s", chat_id)
        if origin is not None:
            await safe_send(origin, {
                "type": "message_failed",
                "chat_id": chat_id,
                "client_id": client_id,
                "detail": "Message could not be saved. Please try again.",
            })
        return {"failed": True}

    if message is None:
        return None

    # Tell sender actual message ID
    if origin is not None:
        await safe_send(
            origin,
            {
                "type": "message_sent",
                "chat_id": chat_id,
                "message_id": message["id"],
                "client_id": client_id,
                "created_at": message["created_at"],
                "reply_to_id": message["reply_to_id"],
            }
        )

    # Message event
    payload = {
        "type": "message",
        "chat_id": chat_id,
        "message_id": message["id"],
        "sender_id": sender_id,
        "sender_name": sender_name,
        "content": message["content"],
        "created_at": message["created_at"],
        "is_delivered": False,
        "is_read": False,
        "read_at": None,
        "reply_to_id": message["reply_to_id"],
    }

    delivered = await manager.send_to_user(
        message["receiver_id"],
        payload,
        chat_id
    )

    if delivered:
        await db_call(
            mark_delivered,
            [message["id"]]
        )

        message["is_delivered"] = True

        delivered_event = {
            "type": "message_delivered",
            "chat_id": chat_id,
            "message_id": message["id"],
        }

        if origin is not None:
            await safe_send(
                origin,
                delivered_event
            )
        else:
            await manager.send_to_user(
                sender_id,
                delivered_event,
                chat_id
            )

    # Detection and suggestion preparation run after persistence/delivery so
    # the normal send acknowledgement is never held up by the AI provider.
    spawn(evaluate_ai_response(chat_id, sender_id, message["id"]))
    spawn(prepare_death_zone_notification(chat_id, message["id"]))

    return message


def _chat_ai_context(db: Session, chat_id: int, limit: int = MAX_AI_CONTEXT_MESSAGES):
    rows = (
        db.query(models.Message)
        .filter(
            models.Message.chat_id == chat_id,
            models.Message.is_deleted.is_(False),
            models.Message.message_type == "text",
        )
        .order_by(models.Message.id.desc())
        .limit(limit)
        .all()
    )
    rows.reverse()
    sender_ids = {row.sender_id for row in rows}
    users = db.query(models.User).filter(models.User.id.in_(sender_ids)).all() if sender_ids else []
    usernames = {user.id: user.username for user in users}
    messages = [
        {
            "sender_name": usernames.get(row.sender_id, "Unknown"),
            "sender_id": row.sender_id,
            "message_id": row.id,
            "content": row.content or "",
            "created_at": row.created_at,
        }
        for row in rows if row.content and row.content.strip()
    ]
    return rows, messages, {user.id: user for user in users}


def _notification_payload(notification: models.DeathZoneNotification) -> dict:
    now = utcnow()
    unviewed_deadline = notification.created_at + MAX_UNVIEWED_NOTIFICATION_AGE
    active = notification.status == "ready" and (
        (notification.viewed_at is None and now < unviewed_deadline
         and (notification.expires_at is None or notification.expires_at > now))
        or (notification.viewed_at is not None and notification.expires_at is not None
            and notification.expires_at > now)
    )
    return {
        "id": notification.id,
        "chat_id": notification.chat_id,
        "user_id": notification.user_id,
        "event_key": notification.event_key,
        "status": notification.status,
        "suggestions": json.loads(notification.suggestions_json or "[]"),
        "death_zone": json.loads(notification.death_zone_json or "{}"),
        "created_at": iso(notification.created_at),
        "viewed_at": iso(notification.viewed_at),
        "expires_at": iso(notification.expires_at),
        "active": active,
    }


def expire_ai_notifications(db: Session, user_id: int) -> None:
    """Expire stale unviewed rows after 24h and viewed rows after their short window."""
    now = utcnow()
    cutoff = now - MAX_UNVIEWED_NOTIFICATION_AGE
    changed = db.query(models.DeathZoneNotification).filter(
        models.DeathZoneNotification.user_id == user_id,
        models.DeathZoneNotification.status == "ready",
        or_(
            and_(models.DeathZoneNotification.viewed_at.is_(None),
                 or_(models.DeathZoneNotification.created_at <= cutoff,
                     and_(models.DeathZoneNotification.expires_at.is_not(None),
                          models.DeathZoneNotification.expires_at <= now))),
            and_(models.DeathZoneNotification.viewed_at.is_not(None),
                 models.DeathZoneNotification.expires_at.is_not(None),
                 models.DeathZoneNotification.expires_at <= now),
        ),
    ).update(
        {models.DeathZoneNotification.status: "expired"},
        synchronize_session=False,
    )
    if changed:
        db.commit()


def notification_status_for_suggestion(db: Session, record: models.AISuggestionRecord) -> str | None:
    """Return ready/expired/invalidated when a suggestion came from a notification."""
    rows = db.query(models.DeathZoneNotification).filter(
        models.DeathZoneNotification.chat_id == record.chat_id,
        models.DeathZoneNotification.user_id == record.user_id,
        models.DeathZoneNotification.suggestions_json.is_not(None),
    ).all()
    for row in rows:
        try:
            payload = json.loads(row.suggestions_json or "[]")
        except (TypeError, ValueError):
            continue
        if any(isinstance(item, dict) and item.get("suggestion_id") == record.id for item in payload):
            return row.status
    return None


def _persist_ai_suggestions(db: Session, chat_id: int, user_id: int,
                            trigger_message_id: int | None, suggestions: list,
                            recovery: dict | None = None) -> list:
    """Best-effort lifecycle metadata; never persist suggestion text here."""
    from app.ai.extraction import MODEL_NAME
    recovery = recovery or {"strategy": "natural_continuation", "reason": "conversation_context"}
    try:
        intervention = db.query(models.AIRecoveryIntervention).filter_by(
            chat_id=chat_id, user_id=user_id, trigger_message_id=trigger_message_id,
        ).first()
        if intervention is None:
            intervention = models.AIRecoveryIntervention(
                chat_id=chat_id, user_id=user_id, trigger_message_id=trigger_message_id,
                recovery_reason=str(recovery.get("reason", "conversation_context"))[:80],
                strategy=str(recovery.get("strategy", "natural_continuation"))[:60],
                prompt_version=PROMPT_VERSION,
            )
            db.add(intervention)
            db.flush()
        result = []
        for item in suggestions:
            text = str(item.get("message", ""))
            strategy = str(item.get("strategy") or (recovery.get("strategy") if item.get("style") == "natural" else item.get("style")))[:60]
            record = models.AISuggestionRecord(
                intervention_id=intervention.id, chat_id=chat_id, user_id=user_id,
                suggestion_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                strategy=strategy, prompt_version=PROMPT_VERSION,
                model_id=MODEL_NAME, validation_passed=True,
            )
            db.add(record)
            db.flush()
            db.add(models.AISuggestionEvent(
                suggestion_id=record.id, chat_id=chat_id, user_id=user_id,
                event_key=f"generated-{record.id}", event_type="generated",
            ))
            result.append({**item, "suggestion_id": record.id, "strategy": strategy,
                           "prompt_version": PROMPT_VERSION})
        db.commit()
        return result
    except Exception:
        db.rollback()
        logger.exception("Could not persist AI suggestion lifecycle metadata for chat_id=%s", chat_id)
        return suggestions


def _record_suggestion_event(db: Session, suggestion_id: int, user_id: int,
                             event_type: str, event_key: str, details: dict | None = None):
    record = db.query(models.AISuggestionRecord).filter_by(
        id=suggestion_id, user_id=user_id
    ).first()
    if record is None:
        raise HTTPException(status_code=404, detail="AI suggestion not found")
    if event_type not in VALID_EVENTS:
        raise HTTPException(status_code=422, detail="Unsupported suggestion event")
    # Unique event key makes retries idempotent while permitting repeated
    # views/selections when the caller supplies a fresh event key.
    event = models.AISuggestionEvent(
        suggestion_id=record.id, chat_id=record.chat_id, user_id=user_id,
        event_key=event_key[:100], event_type=event_type,
        details_json=json.dumps(details or {}, ensure_ascii=False),
    )
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    if event_type == "user_feedback":
        intervention = db.get(models.AIRecoveryIntervention, record.intervention_id) if record.intervention_id else None
        if intervention:
            rating = (details or {}).get("rating")
            intervention.status = "unsuccessful" if rating == "not_helpful" else "user_endorsed" if rating == "helpful" else intervention.status
            intervention.evaluated_at = utcnow()
            intervention.outcome_json = json.dumps({"user_feedback": rating})
            db.commit()
            if rating == "not_helpful":
                state = db.get(models.DeathZoneConversationState, record.chat_id)
                if state:
                    state.active = False
                    state.target_user_id = None
                    db.commit()
    return {"ok": True}


def _evaluate_ai_response(db: Session, chat_id: int, sender_id: int, message_id: int):
    """Record observable outcomes only after the non-target participant replies."""
    from app.ai.ai_evaluation import meaningful_response
    intervention = db.query(models.AIRecoveryIntervention).filter(
        models.AIRecoveryIntervention.chat_id == chat_id,
        models.AIRecoveryIntervention.user_id != sender_id,
        models.AIRecoveryIntervention.status == "generated",
    ).order_by(models.AIRecoveryIntervention.created_at.desc()).first()
    if intervention is None:
        return
    suggestion_rows = db.query(models.AISuggestionRecord).filter_by(
        intervention_id=intervention.id,
    ).all()
    sent_ids = {
        event.suggestion_id for event in db.query(models.AISuggestionEvent).filter(
            models.AISuggestionEvent.event_type == "sent",
            models.AISuggestionEvent.suggestion_id.in_([row.id for row in suggestion_rows] or [-1]),
        ).all()
    }
    if not sent_ids:
        return
    message = db.get(models.Message, message_id)
    if message is None or message.sender_id == intervention.user_id:
        return
    key = f"reply-{message_id}"
    response_ok = meaningful_response(message.content)
    rows = db.query(models.Message).filter(
        models.Message.chat_id == chat_id,
        models.Message.is_deleted.is_(False),
        models.Message.message_type == "text",
        models.Message.id <= message_id,
    ).order_by(models.Message.id.desc()).limit(24).all()
    rows.reverse()
    baseline_rows = [row for row in rows if row.id <= (intervention.trigger_message_id or 0)][-24:]
    from app.ai.user_engagement import analyze_engagement
    before_score = analyze_engagement(baseline_rows)["scores"].get(str(intervention.user_id))
    after_score = analyze_engagement(rows)["scores"].get(str(intervention.user_id))
    improved = before_score is not None and after_score is not None and after_score >= before_score + 5
    for row in suggestion_rows:
        if row.id not in sent_ids:
            continue
        event_types = ["continued"]
        if response_ok:
            event_types.append("meaningful_response")
        if improved:
            event_types.append("engagement_improved")
        for event_type in event_types:
            event_key = f"{event_type}-{key}"
            already_recorded = db.query(models.AISuggestionEvent).filter_by(
                suggestion_id=row.id, event_key=event_key,
            ).first()
            if already_recorded:
                continue
            db.add(models.AISuggestionEvent(
                suggestion_id=row.id, chat_id=chat_id, user_id=intervention.user_id,
                event_key=event_key, event_type=event_type,
                details_json=json.dumps({"reply_message_id": message_id,
                                         "meaningful": response_ok,
                                         "engagement_delta": round(after_score - before_score, 1) if improved else None}),
            ))
    intervention.status = "observed_improvement" if improved else "responded" if response_ok else "awaiting_more_context"
    intervention.outcome_json = json.dumps({"reply_message_id": message_id, "meaningful_response": response_ok,
                                             "engagement_before": before_score, "engagement_after": after_score,
                                             "engagement_improved": improved})
    intervention.evaluated_at = utcnow()
    db.commit()


async def evaluate_ai_response(chat_id: int, sender_id: int, message_id: int):
    try:
        await db_call(_evaluate_ai_response, chat_id, sender_id, message_id)
    except Exception:
        logger.exception("AI suggestion outcome evaluation failed for chat_id=%s", chat_id)


def _prepare_death_zone_notification(db: Session, chat_id: int, trigger_message_id: int):
    chat = db.get(models.Chat, chat_id)
    if chat is None:
        return None
    # Do not generate or persist private AI content after the relationship is
    # no longer an active, verified, unblocked match.
    if not active_chat_for_interaction(db, chat_id, chat.user1_id):
        invalidate_chat_ai_notifications(db, chat_id)
        db.commit()
        return None
    participants = {chat.user1_id, chat.user2_id}
    consent_guard = provider_consent_guard(db, participants)
    if not consent_guard():
        return None
    state = db.get(models.DeathZoneConversationState, chat_id)
    if state is None:
        state = models.DeathZoneConversationState(chat_id=chat_id)
        db.add(state)
        db.flush()
    rows, messages, users = _chat_ai_context(db, chat_id, limit=60)
    if not messages or not rows or rows[-1].id != trigger_message_id:
        return None

    analysis = analyze_death_zone(messages)
    effort = analyze_participant_effort(messages)
    target_id = effort.get("target_user_id")
    qualifies = (
        is_death_zone(analysis)
        and effort.get("eligible") is True
        and target_id in (chat.user1_id, chat.user2_id)
    )
    if not qualifies:
        state.active = False
        state.target_user_id = None
        state.last_message_id = trigger_message_id
        db.commit()
        return None

    if state.active and state.target_user_id == target_id:
        state.last_message_id = trigger_message_id
        db.commit()
        return None

    event_key = f"message-{trigger_message_id}"
    existing = db.query(models.DeathZoneNotification).filter_by(
        chat_id=chat_id, user_id=target_id, event_key=event_key
    ).first()
    if existing:
        return None

    # Claim this unique event before calling the model. A concurrent task will
    # see the claim and skip, preventing duplicate suggestion generation.
    notification = models.DeathZoneNotification(
        chat_id=chat_id,
        user_id=target_id,
        event_key=event_key,
        trigger_message_id=trigger_message_id,
        status="generating",
        expires_at=utcnow() + MAX_UNVIEWED_NOTIFICATION_AGE,
        death_zone_json=json.dumps({**analysis, "participant_effort": effort}, ensure_ascii=False),
    )
    db.add(notification)
    state.active = True
    state.target_user_id = target_id
    state.last_message_id = trigger_message_id
    try:
        db.commit()
        db.refresh(notification)
    except IntegrityError:
        db.rollback()
        return None

    target = users.get(target_id)
    if target is None:
        notification.status = "failed"
        db.commit()
        return None

    try:
        with provider_consent_scope(consent_guard):
            if target.ai_memory_enabled:
                try:
                    from app.ai.memory import extract_and_save_opt_in_memories
                    extract_and_save_opt_in_memories(db, target, messages[-MAX_AI_CONTEXT_MESSAGES:])
                except AIProviderConsentRequired:
                    raise
                except Exception:
                    db.rollback()
                    logger.warning("Opt-in AI memory extraction failed for user_id=%s", target_id)
            result = run_conversation_workflow(
                db=db,
                requesting_user_id=target_id,
                requesting_user="You",
                messages=messages[-MAX_AI_CONTEXT_MESSAGES:],
                chat_id=chat_id,
            )
            assert_provider_consent()
        suggestions = (result.get("suggestion_result") or {}).get("suggestions", [])
        if result.get("should_generate") is not True or len(suggestions) != 3:
            notification.status = "failed"
            state.active = False
            state.target_user_id = None
            db.commit()
            return None
        suggestions = _persist_ai_suggestions(
            db, chat_id, target_id, trigger_message_id, suggestions,
            result.get("recovery"),
        )
        # The provider may have been running while either participant blocked
        # or unmatched. Recheck before exposing generated content.
        if not active_chat_for_interaction(db, chat_id, target_id):
            notification.status = "invalidated"
            state.active = False
            state.target_user_id = None
            db.commit()
            return None
        notification.suggestions_json = json.dumps(suggestions, ensure_ascii=False)
        notification.status = "ready"
        db.commit()
        db.refresh(notification)
        return _notification_payload(notification)
    except AIProviderConsentRequired:
        db.rollback()
        revoked = db.get(models.DeathZoneNotification, notification.id)
        if revoked:
            revoked.status = "invalidated"
        revoked_state = db.get(models.DeathZoneConversationState, chat_id)
        if revoked_state:
            revoked_state.active = False
            revoked_state.target_user_id = None
        db.commit()
        return None
    except Exception:
        db.rollback()
        logger.exception("Automatic AI notification failed for chat_id=%s", chat_id)
        failed = db.get(models.DeathZoneNotification, notification.id)
        if failed:
            failed.status = "failed"
            failed_state = db.get(models.DeathZoneConversationState, chat_id)
            if failed_state:
                failed_state.active = False
                failed_state.target_user_id = None
            db.commit()
        return None


async def prepare_death_zone_notification(chat_id: int, trigger_message_id: int):
    try:
        payload = await db_call(_prepare_death_zone_notification, chat_id, trigger_message_id)
        if payload and payload.get("active"):
            await manager.send_to_user(
                payload["user_id"],
                {"type": "death_zone_notification", "notification": payload},
                chat_id,
            )
    except Exception:
        logger.exception("Death-zone notification preparation failed for chat_id=%s", chat_id)


# ============================================================
# BASIC ROUTES
# ============================================================

@app.get("/")
def home():
    return {
        "message": "Bugzyme Backend is running"
    }


@app.get("/health")
def health():
    return {
        "status": "ok"
    }




# ============================================================
# REGISTER
# ============================================================

@app.post(
    "/register",
    response_model=schemas.UserResponse,
    status_code=201
)
def register_user(
    user: schemas.UserCreate,
    db: Session = Depends(get_db)
):
    email = user.email.strip().lower()
    username = user.username.strip()

    if db.query(models.User).filter(
        func.lower(models.User.email) == email
    ).first():
        raise HTTPException(
            409,
            "Email already registered"
        )

    if db.query(models.User).filter(
        func.lower(models.User.username)
        == username.lower()
    ).first():
        raise HTTPException(
            409,
            "Username already taken"
        )

    new_user = models.User(
        username=username,
        email=email,
        hashed_password=password_hash.hash(
            user.password
        ),
        is_online=False,
    )

    db.add(new_user)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409,
            "Email or username already registered"
        )

    db.refresh(new_user)

    return new_user
@app.post("/upload-voice")
async def upload_voice(
    file: UploadFile = File(...),
    chat_id: int = Query(...),
    duration: int | None = Query(default=None, ge=MIN_VOICE_DURATION_SECONDS, le=MAX_VOICE_DURATION_SECONDS),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # -----------------------------------------
    # 1. Check chat membership
    # -----------------------------------------

    chat = active_chat_for_interaction(
        db,
        chat_id,
        current_user.id
    )

    if not chat:
        raise HTTPException(
            status_code=403,
            detail="You are not a member of this chat"
        )

    try:
        storage_key, filename, mime_type, size_bytes, message_type = (
            await attachment_storage.save_upload(file)
        )
        if message_type != "voice":
            await run_in_threadpool(attachment_storage.remove_attachment, storage_key)
            raise HTTPException(400, "Unsupported voice recording format")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        await file.close()

    # -----------------------------------------
    # 3. Create voice message in DB
    # -----------------------------------------

    try:
        message = await db_call(
            save_voice_message,
            current_user.id,
            chat_id,
            storage_key,
            filename,
            mime_type,
            size_bytes,
            duration,
        )
    except Exception:
        await run_in_threadpool(attachment_storage.remove_attachment, storage_key)
        raise

    if message is None:
        await run_in_threadpool(attachment_storage.remove_attachment, storage_key)

        raise HTTPException(
            status_code=400,
            detail="Could not create voice message"
        )

    # Database errors must not strand a private file without a message record.

    # -----------------------------------------
    # 4. Send voice message to receiver
    # -----------------------------------------

    payload = {
        "type": "voice_message",
        "chat_id": chat_id,
        "message_id": message["id"],
        "sender_id": current_user.id,
        "sender_name": current_user.username,
        "content": None,
        "created_at": message["created_at"],
        "is_delivered": False,
        "is_read": False,
        "read_at": None,
        "reply_to_id": None,
        "message_type": "voice",
        "audio_url": message["audio_url"],
        "audio_duration": message["audio_duration"],
        "audio_mime_type": message["audio_mime_type"],
    }

    delivered = await manager.send_to_user(
        message["receiver_id"],
        payload,
        chat_id
    )

    # -----------------------------------------
    # 5. Mark delivered if receiver is online
    # -----------------------------------------

    if delivered:
        await db_call(
            mark_delivered,
            [message["id"]]
        )

        message["is_delivered"] = True

    # -----------------------------------------
    # 6. Return message to sender
    # -----------------------------------------

    return {
        "success": True,
        "message": message,
        "delivered": delivered,
    }


@app.post(
    "/chats/{chat_id}/attachments",
    response_model=schemas.MessageResponse,
    status_code=201,
)
async def upload_chat_attachment(
    chat_id: int,
    file: UploadFile = File(...),
    caption: str | None = Form(default=None),
    reply_to_id: int | None = Form(default=None),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not active_chat_for_interaction(db, chat_id, current_user.id):
        raise HTTPException(403, "An active, unblocked match is required to add attachments")

    if caption is not None and len(caption) > schemas.MAX_MESSAGE_LEN:
        raise HTTPException(400, "Caption exceeds the 2000 character limit")

    try:
        storage_key, filename, mime_type, size_bytes, message_type = (
            await attachment_storage.save_upload(file)
        )
        if message_type == "voice":
            await run_in_threadpool(attachment_storage.remove_attachment, storage_key)
            raise HTTPException(400, "Use the voice message upload endpoint for audio")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        await file.close()

    try:
        message = await db_call(
            save_attachment_message,
            current_user.id,
            chat_id,
            caption,
            reply_to_id,
            storage_key,
            filename,
            mime_type,
            size_bytes,
            message_type,
        )
    except Exception:
        await run_in_threadpool(attachment_storage.remove_attachment, storage_key)
        raise

    if message is None:
        await run_in_threadpool(attachment_storage.remove_attachment, storage_key)
        raise HTTPException(400, "Could not create attachment message or invalid reply")

    payload = {
        "type": "message",
        "chat_id": chat_id,
        "message_id": message["id"],
        "sender_id": current_user.id,
        "sender_name": current_user.username,
        "content": message["content"],
        "created_at": message["created_at"],
        "is_delivered": False,
        "is_read": False,
        "read_at": None,
        "reply_to_id": message["reply_to_id"],
        "message_type": message_type,
        "attachment_name": filename,
        "attachment_mime_type": mime_type,
        "attachment_size_bytes": size_bytes,
    }
    delivered = await manager.send_to_user(
        message["receiver_id"], payload, chat_id
    )

    if delivered:
        await db_call(mark_delivered, [message["id"]])
        message["is_delivered"] = True
        await manager.send_to_user(
            current_user.id,
            {
                "type": "message_delivered",
                "chat_id": chat_id,
                "message_id": message["id"],
            },
            chat_id,
        )

    return message


@app.get("/attachments/{message_id}/content")
def get_attachment_content(
    message_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    message = db.get(models.Message, message_id)
    if (
        not message
        or message.is_deleted
        or not message.attachment_storage_key
        or message.message_type not in {"image", "file", "voice"}
    ):
        raise HTTPException(404, "Attachment not found")

    chat = member_chat(db, message.chat_id, current_user.id)
    if not chat:
        raise HTTPException(404, "Attachment not found")

    try:
        path = attachment_storage.attachment_path(message.attachment_storage_key)
    except ValueError as exc:
        logger.error("Invalid attachment key on message %s", message_id)
        raise HTTPException(404, "Attachment not found") from exc
    if not path.is_file():
        raise HTTPException(404, "Attachment content not found")

    mime_type = message.attachment_mime_type
    if mime_type not in {value[0] for value in attachment_storage.ALLOWED_TYPES.values()}:
        mime_type = "application/octet-stream"

    filename = Path(message.attachment_name or "attachment").name.replace("\r", "").replace("\n", "")
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace('"', "'")
    disposition = "inline" if message.message_type == "image" else "attachment"
    if message.message_type == "voice":
        disposition = "inline"

    def stream_file():
        with path.open("rb") as source:
            while chunk := source.read(64 * 1024):
                yield chunk

    headers = {
        "Content-Disposition": (
            f'{disposition}; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(filename, safe='')}"
        ),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    }
    return StreamingResponse(stream_file(), media_type=mime_type, headers=headers)


@app.get("/uploads/voice/{filename}")
def get_legacy_voice_content(
    filename: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Serve legacy voice files only to a participant in their owning chat."""
    if not re.fullmatch(r"[a-fA-F0-9-]{36}\.[A-Za-z0-9]{1,8}", filename):
        raise HTTPException(404, "Voice recording not found")
    message = db.query(models.Message).filter(
        models.Message.audio_url == f"/uploads/voice/{filename}",
        models.Message.message_type == "voice",
        models.Message.is_deleted.is_(False),
    ).first()
    if not message or not member_chat(db, message.chat_id, current_user.id):
        raise HTTPException(404, "Voice recording not found")
    root = Path("uploads/voice").resolve()
    path = (root / filename).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(404, "Voice recording not found")

    def stream_legacy_voice():
        with path.open("rb") as source:
            while chunk := source.read(64 * 1024):
                yield chunk

    mime_type = message.audio_mime_type or "application/octet-stream"
    if not mime_type.startswith("audio/"):
        mime_type = "application/octet-stream"
    return StreamingResponse(
        stream_legacy_voice(),
        media_type=mime_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
        },
    )
# ============================================================
# LOGIN
# ============================================================

@app.post(
    "/login",
    response_model=schemas.Token
)
def login_user(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    email = form_data.username.strip().lower()

    user = db.query(models.User).filter(
        func.lower(models.User.email) == email
    ).first()

    if (
        not user
        or not password_hash.verify(
            form_data.password,
            user.hashed_password
        )
    ):
        raise HTTPException(
            401,
            "Invalid email or password"
        )

    return {
        "access_token": create_token(user.id),
        "token_type": "bearer"
    }


# ============================================================
# CURRENT USER
# ============================================================

@app.get(
    "/me",
    response_model=schemas.UserResponse
)
def me(
    current_user: models.User = Depends(
        get_current_user
    )
):
    return current_user


@app.patch("/me", response_model=schemas.UserResponse)
def update_me_profile(
    changes: schemas.UserProfileUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    values = changes.model_dump(exclude_unset=True)
    for field in ("full_name", "bio", "ai_memory_enabled", "ai_provider_processing_enabled"):
        if field not in values:
            continue
        value = values[field]
        if field in {"ai_memory_enabled", "ai_provider_processing_enabled"}:
            setattr(current_user, field, bool(value))
        else:
            value = value.strip() if isinstance(value, str) else None
            setattr(current_user, field, value or None)
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return current_user


@app.patch("/me/presence", response_model=schemas.PresencePreferenceResponse)
async def update_presence_preference(
    changes: schemas.PresencePreferenceUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    enabled = bool(changes.activity_status_enabled)
    changed = current_user.activity_status_enabled != enabled
    was_online = bool(current_user.is_online)
    visible_online = enabled and manager.is_online(current_user.id)
    current_user.activity_status_enabled = enabled
    current_user.is_online = visible_online
    if was_online and not visible_online:
        current_user.last_seen = utcnow()
    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    last_seen = iso(current_user.last_seen)
    if changed or was_online != visible_online:
        await broadcast_presence(
            current_user.id,
            "online" if visible_online else "offline",
            last_seen,
            enabled,
            partners=get_partners(db, current_user.id),
        )
    return {
        "activity_status_enabled": enabled,
        "is_online": visible_online,
        "last_seen": current_user.last_seen,
    }


@app.get("/me/ai-memories", response_model=list[schemas.UserMemoryResponse])
def list_my_ai_memories(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(models.UserMemory)
        .filter(models.UserMemory.user_id == current_user.id)
        .order_by(models.UserMemory.created_at.desc(), models.UserMemory.id.desc())
        .limit(100)
        .all()
    )


@app.patch("/me/ai-memories/{memory_id}", response_model=schemas.UserMemoryResponse)
def update_my_ai_memory(
    memory_id: int,
    changes: schemas.UserMemoryUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    memory = db.query(models.UserMemory).filter(
        models.UserMemory.id == memory_id,
        models.UserMemory.user_id == current_user.id,
    ).first()
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    value = changes.memory_text.strip()
    if not value:
        raise HTTPException(status_code=422, detail="Memory cannot be blank")
    from app.ai.memory import generate_embedding
    memory.memory_text = value
    memory.embedding = generate_embedding(value)
    db.commit()
    db.refresh(memory)
    return memory


@app.delete("/me/ai-memories/{memory_id}")
def delete_my_ai_memory(
    memory_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    memory = db.query(models.UserMemory).filter(
        models.UserMemory.id == memory_id,
        models.UserMemory.user_id == current_user.id,
    ).first()
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    db.delete(memory)
    db.commit()
    return {"deleted": True}


@app.delete("/me/ai-memories")
def clear_my_ai_memories(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(models.UserMemory).filter(
        models.UserMemory.user_id == current_user.id
    ).delete(synchronize_session=False)
    # Do not immediately recreate cleared memories from old history.
    current_user.ai_memory_processed_through_message_id = (
        db.query(func.max(models.Message.id))
        .filter(models.Message.sender_id == current_user.id)
        .scalar()
    )
    db.commit()
    return {"deleted": True}


# ============================================================
# USERS
# ============================================================

@app.get(
    "/users",
    response_model=list[schemas.UserPublic]
)
def get_users(
    current_user: models.User = Depends(
        get_current_user
    ),
    db: Session = Depends(get_db)
):
    users = db.query(
        models.User
    ).order_by(
        models.User.username
    ).all()
    visible_partners = set(get_partners(db, current_user.id).values())

    return [
        schemas.UserPublic(
            id=user.id,
            username=user.username,
            full_name=user.full_name,
            bio=user.bio,
            is_online=(
                user.id in visible_partners
                and manager.is_online(user.id)
                and user.activity_status_enabled
            ),
            last_seen=(
                user.last_seen
                if user.id in visible_partners and user.activity_status_enabled
                else None
            ),
        )
        for user in users
    ]


# ============================================================
# CREATE CHAT
# ============================================================

@app.post(
    "/chats",
    response_model=schemas.ChatResponse
)
def create_chat(
    chat: schemas.ChatCreate,
    current_user: models.User = Depends(
        get_current_user
    ),
    db: Session = Depends(get_db)
):
    if current_user.id == chat.user2_id:
        raise HTTPException(
            400,
            "You cannot chat with yourself"
        )

    target = db.get(models.User, chat.user2_id)
    if not target:
        raise HTTPException(
            404,
            "User not found"
        )

    match = db.query(models.Match).filter(
        models.Match.user1_id == min(current_user.id, chat.user2_id),
        models.Match.user2_id == max(current_user.id, chat.user2_id),
        models.Match.is_active.is_(True),
    ).first()
    if not match or _has_block_between(db, current_user.id, chat.user2_id):
        raise HTTPException(403, "An active, unblocked match is required to create a chat")
    if not active_chat_for_interaction(db, match.chat_id, current_user.id):
        raise HTTPException(403, "Both matched profiles must remain verified to create a chat")

    existing = db.get(models.Chat, match.chat_id)
    if existing and current_user.id in (existing.user1_id, existing.user2_id):
        return existing
    raise HTTPException(404, "Active match chat not found")


# ============================================================
# DELETE CHAT
# ============================================================

@app.delete("/chats/{chat_id}")
async def delete_chat(
    chat_id: int,
    current_user: models.User = Depends(
        get_current_user
    )
):
    result = await db_call(
        delete_chat_from_database,
        chat_id,
        current_user.id
    )

    if result is None:
        raise HTTPException(
            404,
            "Chat not found or you are not a member"
        )

    event = {
        "type": "chat_deleted",
        "chat_id": result["chat_id"],
        "deleted_for_user_id": current_user.id,
    }
    # Conversation removal is per-user; the other participant keeps their view.
    await manager.send_to_user(current_user.id, event, chat_id)

    return {
        "ok": True,
        "message": "Chat deleted successfully"
    }


# ============================================================
# GET CHATS
# ============================================================

@app.get("/chats", response_model=list[schemas.ChatSummary])
def list_chats(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    my_id = current_user.id

    chats = db.query(models.Chat).filter(
        or_(
            and_(
                models.Chat.user1_id == my_id,
                models.Chat.deleted_by_user1.is_(False),
            ),
            and_(
                models.Chat.user2_id == my_id,
                models.Chat.deleted_by_user2.is_(False),
            ),
        )
    ).all()

    if not chats:
        return []

    chat_ids = [chat.id for chat in chats]

    latest_ids = dict(
        db.query(
            models.Message.chat_id,
            func.max(models.Message.id)
        )
        .filter(
            models.Message.chat_id.in_(chat_ids),
            models.Message.is_deleted.is_not(True)
        )
        .group_by(models.Message.chat_id)
        .all()
    )

    latest_messages = {}

    if latest_ids:
        latest_messages = {
            message.chat_id: message
            for message in db.query(models.Message)
            .filter(
                models.Message.id.in_(list(latest_ids.values()))
            )
            .all()
        }

    unread = dict(
        db.query(
            models.Message.chat_id,
            func.count(models.Message.id)
        )
        .filter(
            models.Message.chat_id.in_(chat_ids),
            models.Message.sender_id != my_id,
            models.Message.is_read.is_not(True),
            models.Message.is_deleted.is_not(True)
        )
        .group_by(models.Message.chat_id)
        .all()
    )

    partner_ids = {
        other_user(chat, my_id)
        for chat in chats
    }
    visible_partners = set(get_partners(db, my_id).values())

    users = {
        user.id: user
        for user in db.query(models.User)
        .filter(models.User.id.in_(partner_ids))
        .all()
    }

    result = []

    for chat in chats:
        partner = users.get(
            other_user(chat, my_id)
        )

        if not partner:
            continue

        last_message = latest_messages.get(chat.id)

        result.append(
            schemas.ChatSummary(
                chat_id=chat.id,
                user=schemas.UserPublic(
                    id=partner.id,
                    username=partner.username,
                    full_name=partner.full_name,
                    bio=partner.bio,
                    is_online=(
                        partner.id in visible_partners
                        and manager.is_online(partner.id)
                        and partner.activity_status_enabled
                    ),
                    last_seen=(
                        partner.last_seen
                        if partner.id in visible_partners and partner.activity_status_enabled
                        else None
                    ),
                ),
                last_message=(
                    schemas.MessageResponse.model_validate(last_message)
                    if last_message
                    else None
                ),
                unread_count=unread.get(chat.id, 0)
            )
        )

    result.sort(
        key=lambda chat: chat.last_message.id if chat.last_message else 0,
        reverse=True
    )

    return result

# ============================================================
# SEND MESSAGE
# ============================================================

@app.post(
    "/messages",
    response_model=schemas.MessageResponse,
    status_code=201
)
async def send_message(
    message: schemas.MessageCreate,
    current_user: models.User = Depends(
        get_current_user
    )
):
    result = await process_message(
        current_user.id,
        current_user.username,
        message.chat_id,
        message.content,
        reply_to_id=message.reply_to_id
    )

    if result is None:
        raise HTTPException(
            403,
            "You are not a member of this chat or invalid reply"
        )

    return result


# ============================================================
# DELETE MESSAGE
# ============================================================

@app.delete("/messages/{message_id}")
async def delete_message(
    message_id: int,
    for_everyone: bool = True,
    current_user: models.User = Depends(
        get_current_user
    )
):
    if not for_everyone:
        raise HTTPException(
            status_code=422,
            detail="Private message deletion is not supported",
        )

    result = await db_call(
        soft_delete_message,
        current_user.id,
        message_id,
        for_everyone
    )

    if result is None:
        raise HTTPException(
            403,
            "Cannot delete this message"
        )

    event = {
        "type": "message_deleted",
        "chat_id": result["chat_id"],
        "message_id": result["message_id"],
        "for_everyone": result["for_everyone"],
    }

    # Sender
    await manager.send_to_user(
        current_user.id,
        event,
        result["chat_id"]
    )

    # Receiver
    await manager.send_to_user(
        result["receiver_id"],
        event,
        result["chat_id"]
    )

    await run_in_threadpool(
        attachment_storage.remove_attachment,
        result.get("attachment_storage_key"),
    )

    return {
        "ok": True,
        "message_id": message_id
    }


# ============================================================
# GET MESSAGES
# ============================================================

@app.get(
    "/messages/{chat_id}",
    response_model=list[schemas.MessageResponse]
)
def get_messages(
    chat_id: int,
    limit: int = Query(
        200,
        ge=1,
        le=500
    ),
    before_id: int | None = None,
    current_user: models.User = Depends(
        get_current_user
    ),
    db: Session = Depends(get_db)
):
    chat = db.get(
        models.Chat,
        chat_id
    )

    if not chat:
        raise HTTPException(
            404,
            "Chat not found"
        )

    if current_user.id not in (
        chat.user1_id,
        chat.user2_id
    ):
        raise HTTPException(
            403,
            "You are not a member of this chat"
        )

    query = db.query(
        models.Message
    ).options(
        selectinload(models.Message.reactions)
    ).filter(
        models.Message.chat_id == chat_id
    )

    if before_id is not None:
        query = query.filter(
            models.Message.id < before_id
        )

    messages = query.order_by(
        models.Message.id.desc()
    ).limit(
        limit
    ).all()

    messages.reverse()

    return messages


# ============================================================
# AI CONVERSATION SUGGESTIONS
# ============================================================

@app.get("/ai-notifications")
def list_ai_notifications(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    expire_ai_notifications(db, current_user.id)
    query = db.query(models.DeathZoneNotification).filter(
        models.DeathZoneNotification.user_id == current_user.id,
        models.DeathZoneNotification.status == "ready",
        or_(
            models.DeathZoneNotification.viewed_at.is_(None),
            models.DeathZoneNotification.expires_at > utcnow(),
        ),
    ).order_by(models.DeathZoneNotification.created_at.desc(),
               models.DeathZoneNotification.id.desc())
    visible = []
    cursor = None
    while len(visible) < 100:
        batch_query = query
        if cursor is not None:
            cursor_created_at, cursor_id = cursor
            batch_query = batch_query.filter(or_(
                models.DeathZoneNotification.created_at < cursor_created_at,
                and_(models.DeathZoneNotification.created_at == cursor_created_at,
                     models.DeathZoneNotification.id < cursor_id),
            ))
        rows = batch_query.limit(100).all()
        if not rows:
            break
        for row in rows:
            if active_chat_for_interaction(db, row.chat_id, current_user.id):
                visible.append(_notification_payload(row))
                if len(visible) == 100:
                    break
            else:
                row.status = "invalidated"
        last = rows[-1]
        cursor = (last.created_at, last.id)
    if db.dirty:
        db.commit()
    return {"notifications": visible}


@app.post("/ai-notifications/{notification_id}/view")
def view_ai_notification(
    notification_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    expire_ai_notifications(db, current_user.id)
    notification = db.query(models.DeathZoneNotification).filter(
        models.DeathZoneNotification.id == notification_id,
        models.DeathZoneNotification.user_id == current_user.id,
        models.DeathZoneNotification.status == "ready",
    ).first()
    if notification is None:
        raise HTTPException(status_code=404, detail="AI notification not found")
    if not active_chat_for_interaction(db, notification.chat_id, current_user.id):
        notification.status = "invalidated"
        db.commit()
        raise HTTPException(status_code=404, detail="AI notification not found")
    now = utcnow()
    if notification.viewed_at is None:
        notification.viewed_at = now
        short_expiry = now + VIEWED_NOTIFICATION_LIFETIME
        notification.expires_at = min(notification.expires_at, short_expiry) if notification.expires_at else short_expiry
        db.commit()
        db.refresh(notification)
        for suggestion in json.loads(notification.suggestions_json or "[]"):
            suggestion_id = suggestion.get("suggestion_id") if isinstance(suggestion, dict) else None
            if suggestion_id:
                try:
                    _record_suggestion_event(
                        db, suggestion_id, current_user.id, "viewed",
                        f"notification-{notification.id}-view",
                    )
                except HTTPException:
                    logger.info("Suggestion lifecycle row missing for notification=%s", notification.id)
    payload = _notification_payload(notification)
    return payload


@app.post("/ai-suggestions/{suggestion_id}/events")
def track_ai_suggestion_event(
    suggestion_id: int,
    payload: schemas.AISuggestionEventCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = db.query(models.AISuggestionRecord).filter_by(
        id=suggestion_id, user_id=current_user.id
    ).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if not active_chat_for_interaction(db, record.chat_id, current_user.id):
        raise HTTPException(status_code=403, detail="An active, unblocked match is required")
    _enforce_manual_ai_limit(current_user.id, record.chat_id, operation="events")
    expire_ai_notifications(db, current_user.id)
    linked_notification_status = notification_status_for_suggestion(db, record)
    if linked_notification_status is not None and linked_notification_status != "ready":
        raise HTTPException(status_code=404, detail="Suggestion is no longer available")

    event_type = payload.event_type
    event_key = payload.event_key
    details = payload.details
    if event_type == "sent":
        message_id = details.get("message_id")
        message = db.get(models.Message, message_id) if isinstance(message_id, int) and not isinstance(message_id, bool) else None
        if record is None or message is None or message.chat_id != record.chat_id or message.sender_id != current_user.id:
            raise HTTPException(status_code=422, detail="Sent event must reference your persisted chat message")
        selected = db.query(models.AISuggestionEvent).filter_by(suggestion_id=suggestion_id, user_id=current_user.id, event_type="selected").first()
        edited = db.query(models.AISuggestionEvent).filter_by(suggestion_id=suggestion_id, user_id=current_user.id, event_type="edited").first()
        digest = hashlib.sha256((message.content or "").encode("utf-8")).hexdigest()
        if selected is None or (digest != record.suggestion_hash and edited is None):
            raise HTTPException(status_code=422, detail="Suggestion must be selected before it can be recorded as sent")
    if event_type == "user_feedback":
        details = {"rating": details["rating"]}
    elif event_type == "viewed":
        details = {}
    elif event_type == "edited":
        details = {"changed": bool(details.get("changed", True))}
    elif event_type == "sent":
        details = {"message_id": int(details["message_id"]), "edited": bool(details.get("edited", False))}
    else:
        details = {}
    response = _record_suggestion_event(db, suggestion_id, current_user.id, event_type, event_key, details)
    if event_type == "sent":
        next_reply = db.query(models.Message).filter(
            models.Message.chat_id == record.chat_id,
            models.Message.id > message_id,
            models.Message.sender_id != current_user.id,
            models.Message.is_deleted.is_(False),
        ).order_by(models.Message.id.asc()).first()
        if next_reply:
            _evaluate_ai_response(db, record.chat_id, next_reply.sender_id, next_reply.id)
    return response


@app.get("/chats/{chat_id}/coach")
def get_private_conversation_coach(
    chat_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chat = db.get(models.Chat, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    if current_user.id not in (chat.user1_id, chat.user2_id):
        raise HTTPException(status_code=403, detail="You are not a member of this chat")
    if not active_chat_for_interaction(db, chat_id, current_user.id):
        raise HTTPException(status_code=403, detail="An active, unblocked match is required")
    participants = {chat.user1_id, chat.user2_id}
    require_provider_consent(db, participants)
    _enforce_manual_ai_limit(current_user.id, chat_id)
    consent_guard = provider_consent_guard(db, participants)
    _, messages, _ = _chat_ai_context(db, chat_id)
    from app.ai.conversation_intelligence import build_conversation_intelligence
    from app.ai.conversation_coach import CoachServiceError, generate_private_coaching
    from app.ai.conversation_insights import build_conversation_insights
    if not messages:
        return {"chat_id": chat_id, "user_id": current_user.id,
                "available": False, "reason": "no_context", "insights": []}
    intelligence = build_conversation_intelligence(messages)
    own = intelligence.get("participant_views", {}).get(str(current_user.id), {})
    if not own:
        return {"chat_id": chat_id, "user_id": current_user.id,
                "available": False, "reason": "missing_profile", "insights": []}
    shared = build_conversation_insights(messages)
    try:
        with provider_consent_scope(consent_guard):
            coaching = generate_private_coaching(messages, current_user.id, own, {
                "mood": (shared.get("mood") or {}).get("state", "uncertain"),
                "shared_topics": shared.get("shared_topics", []),
                "engagement_trend": (shared.get("engagement_trend") or {}).get("state", "unknown"),
            })
            assert_provider_consent()
    except AIProviderConsentRequired as exc:
        raise HTTPException(403, detail={"code": "ai_provider_consent_required",
            "message": "AI provider processing consent is no longer enabled."}) from exc
    except AIProviderUnavailable as exc:
        raise HTTPException(503, detail={"code": "ai_provider_unavailable",
            "message": "AI assistance is temporarily unavailable. Please try again later."}) from exc
    except CoachServiceError as exc:
        logger.exception("Private coach generation failed for chat_id=%s user_id=%s code=%s",
                         chat_id, current_user.id, exc.code)
        raise HTTPException(status_code=503, detail={"code": "ai_provider_unavailable",
            "message": "AI assistance is temporarily unavailable. Please try again later."}) from exc
    except Exception as exc:
        logger.exception("Unexpected private coach error for chat_id=%s user_id=%s", chat_id, current_user.id)
        raise HTTPException(status_code=500, detail={"code": "coach_internal_error", "message": "Private coaching could not be prepared. Please retry."}) from exc
    return {"chat_id": chat_id, "user_id": current_user.id, **coaching}


@app.get("/chats/{chat_id}/insights")
def get_private_conversation_insights(
    chat_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chat = db.get(models.Chat, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    if current_user.id not in (chat.user1_id, chat.user2_id):
        raise HTTPException(status_code=403, detail="You are not a member of this chat")
    if not active_chat_for_interaction(db, chat_id, current_user.id):
        raise HTTPException(status_code=403, detail="An active, unblocked match is required")
    _, messages, _ = _chat_ai_context(db, chat_id)
    from app.ai.conversation_insights import build_conversation_insights
    try:
        report = build_conversation_insights(messages)
    except Exception as exc:
        logger.exception("Conversation insights failed for chat_id=%s user_id=%s", chat_id, current_user.id)
        raise HTTPException(status_code=500, detail={"code": "insights_internal_error", "message": "Conversation insights could not be prepared. Please retry."}) from exc
    return {"chat_id": chat_id, "user_id": current_user.id, **report}

@app.post("/chats/{chat_id}/suggestions")
def get_chat_suggestions(
    chat_id: int,
    payload: dict = Body(default={}),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 1. Verify chat exists
    chat = db.get(models.Chat, chat_id)

    if not chat:
        raise HTTPException(
            status_code=404,
            detail="Chat not found",
        )

    # Suggestions create new chat-derived state, so require a current match.
    if not active_chat_for_interaction(db, chat_id, current_user.id):
        raise HTTPException(
            status_code=403,
            detail="An active, unblocked match is required",
        )

    participants = {chat.user1_id, chat.user2_id}
    require_provider_consent(db, participants)
    _enforce_manual_ai_limit(current_user.id, chat_id)
    consent_guard = provider_consent_guard(db, participants)

    # 3. Fetch recent, non-deleted text messages
    db_messages = (
        db.query(models.Message)
        .filter(
            models.Message.chat_id == chat_id,
            models.Message.is_deleted.is_(False),
            models.Message.message_type == "text",
        )
        .order_by(models.Message.id.desc())
        .limit(MAX_AI_CONTEXT_MESSAGES)
        .all()
    )

    # AI needs chronological order
    db_messages.reverse()

    if not db_messages:
        raise HTTPException(
            status_code=400,
            detail="No text messages available for AI analysis",
        )

    # 4. Fetch sender usernames
    sender_ids = {message.sender_id for message in db_messages}

    users = (
        db.query(models.User)
        .filter(models.User.id.in_(sender_ids))
        .all()
    )
    usernames = {user.id: user.username for user in users}

    # 5. Prepare the message format expected by the AI
    messages = [
        {
            "sender_name": usernames.get(message.sender_id, "Unknown"),
            "sender_id": message.sender_id,
            "message_id": message.id,
            "content": message.content or "",
            "created_at": message.created_at,
        }
        for message in db_messages
        if message.content and message.content.strip()
    ]

    if not messages:
        raise HTTPException(
            status_code=400,
            detail="No usable text messages available for AI analysis",
        )

    avoid_suggestions = payload.get("avoid_suggestions", []) if isinstance(payload, dict) else []
    if not isinstance(avoid_suggestions, list):
        avoid_suggestions = []
    avoid_suggestions = [item[:300] for item in avoid_suggestions if isinstance(item, str) and item.strip()][:3]

    effort = analyze_participant_effort(messages)
    death_zone = analyze_death_zone(messages)
    # Manual suggestions are available to either chat participant.
    # Automatic death-zone targeting remains unchanged.

    try:
        with provider_consent_scope(consent_guard):
            if current_user.ai_memory_enabled:
                try:
                    from app.ai.memory import extract_and_save_opt_in_memories
                    extract_and_save_opt_in_memories(db, current_user, messages)
                except AIProviderConsentRequired:
                    raise
                except Exception:
                    db.rollback()
                    logger.warning("Opt-in AI memory extraction failed for user_id=%s", current_user.id)

            result = run_conversation_workflow(
                db=db,
                requesting_user_id=current_user.id,
                requesting_user="You",
                messages=messages,
                chat_id=chat_id,
                avoid_suggestions=avoid_suggestions,
                manual_request=True,
            )
            assert_provider_consent()
    except AIProviderConsentRequired as exc:
        raise HTTPException(403, detail={"code": "ai_provider_consent_required",
            "message": "AI provider processing consent is no longer enabled."}) from exc
    except AIProviderUnavailable as exc:
        raise HTTPException(503, detail={"code": "ai_provider_unavailable",
            "message": "AI assistance is temporarily unavailable. Please try again later."}) from exc
    except Exception:
        logger.exception("AI suggestion workflow failed for chat_id=%s", chat_id)
        raise HTTPException(
            status_code=500,
            detail={"code": "ai_generation_failed", "message": "Could not generate AI conversation suggestions."},
        )

    # 7. Return death-zone analysis and suggestions
    death_zone = result.get("death_zone", {})
    suggestion_result = result.get("suggestion_result")
    suggestions = (suggestion_result or {}).get("suggestions", [])
    if suggestions:
        suggestions = _persist_ai_suggestions(
            db, chat_id, current_user.id, db_messages[-1].id,
            suggestions, result.get("recovery"),
        )

    return {
        "chat_id": chat_id,
        "death_zone": death_zone,
        "should_generate": result.get("should_generate", False),
        "target_user_id": current_user.id if result.get("should_generate") else result.get("participant_effort", {}).get("target_user_id"),
        "eligible": result.get("should_generate", False),
        "recovery": result.get("recovery", {}),
        "suggestions": suggestions,
        "analysis": (
            suggestion_result.get("analysis")
            if suggestion_result
            else None
        ),
        "memories_used": (
            suggestion_result.get("memories_used", [])
            if suggestion_result
            else []
        ),
    }





# ============================================================
# WEBSOCKET
# ============================================================

async def handle_socket(
    websocket: WebSocket,
    token: str,
    bound_chat_id: int | None
):
    await websocket.accept()

    user_id = decode_token(token)

    if user_id is None:
        await websocket.close(
            code=1008,
            reason="Invalid or expired token"
        )
        return

    context = await db_call(
        load_context,
        user_id,
        bound_chat_id
    )

    if context is None:
        await websocket.close(
            code=1008,
            reason="Not allowed"
        )
        return

    partners = context["partners"]
    username = context["username"]

    first = manager.connect(
        user_id,
        websocket,
        bound_chat_id
    )

    try:
        if first:
            presence = await db_call(set_online, user_id, True)
            await broadcast_presence(
                user_id,
                "online" if presence["is_online"] else "offline",
                presence["last_seen"],
                presence["activity_status_enabled"],
                partners=partners,
            )

        await safe_send(
            websocket,
            {
                "type": "ready",
                "user_id": user_id,
                "online_user_ids": [
                    online_id for online_id in await db_call(
                        visible_online_partner_ids, set(partners.values())
                    ) if online_id != user_id
                ],
            }
        )

        for (
            sender_id,
            chat_id,
            message_id
        ) in context["delivered"]:

            await manager.send_to_user(
                sender_id,
                {
                    "type": "message_delivered",
                    "chat_id": chat_id,
                    "message_id": message_id
                },
                chat_id
            )

        timeout = (
            IDLE_TIMEOUT
            if bound_chat_id is None
            else None
        )

        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout
                )

            except asyncio.TimeoutError:
                await websocket.close(
                    code=1001,
                    reason="Idle timeout"
                )
                break

            except ValueError:
                await safe_send(
                    websocket,
                    {
                        "type": "error",
                        "detail": "Invalid JSON"
                    }
                )
                continue

            if not isinstance(data, dict):
                continue

            event_type = data.get("type")

            chat_id = (
                bound_chat_id
                if bound_chat_id is not None
                else data.get("chat_id")
            )

            if (
                isinstance(chat_id, bool)
                or (
                    chat_id is not None
                    and not isinstance(
                        chat_id,
                        int
                    )
                )
            ):
                chat_id = None

            chat_scoped_events = {
                "message", "message_reaction", "delete_message",
                "delete_chat", "typing", "read", "read_chat",
            }
            if event_type in chat_scoped_events and chat_id is not None:
                current_partners = await db_call(get_partners, user_id)
                partners.clear()
                partners.update(current_partners)
                if chat_id not in partners:
                    if bound_chat_id is not None:
                        await websocket.close(
                            code=1008,
                            reason="Chat access is no longer active",
                        )
                        break
                    await safe_send(websocket, {
                        "type": "error",
                        "chat_id": chat_id,
                        "detail": "Chat access is no longer active",
                    })
                    continue

            # =================================================
            # PING
            # =================================================

            if event_type == "ping":

                await safe_send(
                    websocket,
                    {
                        "type": "pong"
                    }
                )

            # =================================================
            # MESSAGE
            # =================================================

            elif event_type == "message":

                content = data.get("content")
                reply_to_id = data.get(
                    "reply_to_id"
                )

                if (
                    not isinstance(
                        content,
                        str
                    )
                    or chat_id is None
                ):
                    continue

                content = content.strip()

                if not content:
                    continue

                if len(content) > schemas.MAX_MESSAGE_LEN:

                    await safe_send(
                        websocket,
                        {
                            "type": "message_failed",
                            "chat_id": chat_id,
                            "client_id": data.get("client_id"),
                            "detail": "Message too long"
                        }
                    )

                    continue

                result = await process_message(
                    user_id,
                    username,
                    chat_id,
                    content,
                    data.get("client_id"),
                    websocket,
                    reply_to_id
                )

                if result is None:

                    await safe_send(
                        websocket,
                        {
                            "type": "message_failed",
                            "chat_id": chat_id,
                            "client_id": data.get("client_id"),
                            "detail":
                            "Not a member of this chat or invalid reply"
                        }
                    )

            # =================================================
            # MESSAGE REACTION
            # =================================================

            elif event_type == "message_reaction":

                message_id = data.get("message_id")
                reaction = data.get("reaction")
                request_id = data.get("request_id")

                if (
                    chat_id is None
                    or isinstance(message_id, bool)
                    or not isinstance(message_id, int)
                    or not isinstance(reaction, str)
                    or reaction not in ALLOWED_MESSAGE_REACTIONS
                ):
                    await safe_send(
                        websocket,
                        {
                            "type": "message_reaction_error",
                            "chat_id": chat_id,
                            "message_id": message_id,
                            "request_id": request_id,
                            "detail": "Invalid message reaction",
                        },
                    )
                    continue

                result = await db_call(
                    toggle_message_reaction,
                    user_id,
                    chat_id,
                    message_id,
                    reaction,
                )
                if result is None:
                    await safe_send(
                        websocket,
                        {
                            "type": "message_reaction_error",
                            "chat_id": chat_id,
                            "message_id": message_id,
                            "request_id": request_id,
                            "detail": "Message not found or you are not a chat participant",
                        },
                    )
                    continue

                reaction_event = {
                    "type": "message_reaction",
                    "chat_id": result["chat_id"],
                    "message_id": result["message_id"],
                    "revision": result["revision"],
                    "request_id": request_id,
                    "reactions": result["reactions"],
                }
                await manager.send_to_user(
                    user_id,
                    reaction_event,
                    result["chat_id"],
                )
                await manager.send_to_user(
                    result["receiver_id"],
                    reaction_event,
                    result["chat_id"],
                )

            # =================================================
            # DELETE MESSAGE
            # =================================================

            elif event_type == "delete_message":

                message_id = data.get(
                    "message_id"
                )

                for_everyone = data.get(
                    "for_everyone",
                    True
                )

                if isinstance(message_id, bool) or not isinstance(message_id, int):
                    continue

                if for_everyone is not True:
                    await safe_send(websocket, {
                        "type": "message_delete_error",
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "detail": "Private message deletion is not supported",
                    })
                    continue

                result = await db_call(
                    soft_delete_message,
                    user_id,
                    message_id,
                    for_everyone
                )

                if result:

                    delete_event = {
                        "type": "message_deleted",
                        "chat_id": result["chat_id"],
                        "message_id": result["message_id"],
                        "for_everyone":
                            result["for_everyone"]
                    }

                    # Send to sender
                    await manager.send_to_user(
                        user_id,
                        delete_event,
                        result["chat_id"]
                    )

                    # Send to receiver
                    await manager.send_to_user(
                        result["receiver_id"],
                        delete_event,
                        result["chat_id"]
                    )

                    await run_in_threadpool(
                        attachment_storage.remove_attachment,
                        result.get("attachment_storage_key"),
                    )

            # =================================================
            # DELETE CHAT
            # =================================================

            elif event_type == "delete_chat":

                if chat_id is None:
                    continue

                result = await db_call(
                    delete_chat_from_database,
                    chat_id,
                    user_id
                )

                if result is None:

                    await safe_send(
                        websocket,
                        {
                            "type": "error",
                            "detail":
                            "Chat not found or you are not a member"
                        }
                    )

                    continue

                delete_chat_event = {
                    "type": "chat_deleted",
                    "chat_id": result["chat_id"],
                    "deleted_for_user_id": user_id,
                }

                await manager.send_to_user(user_id, delete_chat_event, chat_id)
                await manager.close_chat_sockets(
                    {user_id}, chat_id, reason="Conversation removed for this user"
                )

            # =================================================
            # TYPING
            # =================================================

            elif event_type == "typing":

                if chat_id is None:
                    continue

                if chat_id not in partners:

                    partners.clear()

                    partners.update(
                        await db_call(
                            get_partners,
                            user_id
                        )
                    )

                if chat_id in partners and await db_call(
                    active_chat_for_interaction, chat_id, user_id
                ):

                    await manager.send_to_user(
                        partners[chat_id],
                        {
                            "type": "typing",
                            "chat_id": chat_id,
                            "user_id": user_id
                        },
                        chat_id
                    )

            # =================================================
            # READ
            # =================================================

            elif event_type in (
                "read",
                "read_chat"
            ):

                if chat_id is None:
                    continue

                if event_type == "read":

                    message_id = data.get(
                        "message_id"
                    )

                else:

                    message_id = None

                if (
                    message_id is not None
                    and (
                        isinstance(
                            message_id,
                            bool
                        )
                        or not isinstance(
                            message_id,
                            int
                        )
                    )
                ):
                    continue

                result = await db_call(
                    mark_read,
                    user_id,
                    chat_id,
                    message_id
                )

                if result:

                    for read_id in result["ids"]:

                        await manager.send_to_user(
                            result["sender"],
                            {
                                "type": "message_read",
                                "chat_id": chat_id,
                                "message_id": read_id,
                                "reader_id": user_id,
                                "read_at": result["read_at"].get(read_id),
                            },
                            chat_id
                        )

    except WebSocketDisconnect:
        pass

    except Exception:
        logger.exception(
            "WebSocket error for user %s",
            user_id
        )

    finally:

        if manager.disconnect(
            user_id,
            websocket
        ):

            spawn(
                go_offline(
                    user_id
                )
            )


# ============================================================
# WEBSOCKET ROUTES
# ============================================================

@app.websocket("/ws")
async def ws_global(
    websocket: WebSocket,
    token: str = Query(default="")
):
    await handle_socket(
        websocket,
        token,
        None
    )


@app.websocket("/ws/{chat_id}")
async def ws_chat(
    websocket: WebSocket,
    chat_id: int,
    token: str = Query(default="")
):
    await handle_socket(
        websocket,
        token,
        chat_id
    )


# ============================================================
# DATING PROFILE ENDPOINTS
# ============================================================

def _profile_age(profile: models.UserProfile, today: date | None = None) -> int | None:
    if not profile.date_of_birth:
        return None
    current_date = today or date.today()
    return current_date.year - profile.date_of_birth.year - (
        (current_date.month, current_date.day)
        < (profile.date_of_birth.month, profile.date_of_birth.day)
    )


def _is_discoverable_profile(profile: models.UserProfile | None) -> bool:
    """Return whether the profile meets server-side discovery requirements."""
    age = _profile_age(profile) if profile else None
    return bool(
        profile
        and age is not None
        and age >= schemas.AGE_MINIMUM
        and profile.is_face_verified
        and profile.is_id_verified
        and profile.verification_status == "verified"
    )


def _profiles_match_preferences(
    first: models.UserProfile,
    second: models.UserProfile,
) -> bool:
    """Apply both users' existing gender and era preferences symmetrically."""
    first_gender_preference = first.target_gender_preference or "any"
    second_gender_preference = second.target_gender_preference or "any"
    if first_gender_preference != "any" and first_gender_preference != second.gender:
        return False
    if second_gender_preference != "any" and second_gender_preference != first.gender:
        return False

    first_era_preference = first.match_era_preference or "any"
    second_era_preference = second.match_era_preference or "any"
    if first_era_preference != "any" and first_era_preference != second.era:
        return False
    if second_era_preference != "any" and second_era_preference != first.era:
        return False
    return True


def _has_block_between(db: Session, first_user_id: int, second_user_id: int) -> bool:
    return db.query(models.UserBlock.id).filter(
        or_(
            and_(
                models.UserBlock.blocker_id == first_user_id,
                models.UserBlock.blocked_id == second_user_id,
            ),
            and_(
                models.UserBlock.blocker_id == second_user_id,
                models.UserBlock.blocked_id == first_user_id,
            ),
        )
    ).first() is not None


def _require_verified_profile(db: Session, user_id: int) -> models.UserProfile:
    profile = db.query(models.UserProfile).filter(
        models.UserProfile.user_id == user_id
    ).first()
    if not profile:
        raise HTTPException(404, "Dating profile not found. Create one first.")
    if not _is_discoverable_profile(profile):
        raise HTTPException(
            status_code=403,
            detail="Verification required: Both face and ID verification must be approved before accessing discovery.",
        )
    return profile


# Swipe rate limiting constants. These are intentionally generous for a
# dating product where swiping is the core interaction, but still cap the
# maximum rate to mitigate automated abuse.
SWIPE_RATE_LIMIT_COUNT = 120
SWIPE_RATE_LIMIT_WINDOW_SECONDS = 60


def _enforce_swipe_rate_limit(db: Session, user_id: int) -> None:
    """Reject swipes that exceed the configured rate limit.

    Uses the database as the rate-limit store so the limit survives across
    workers and restarts. The window is a simple sliding count of swipes in
    the last N seconds.
    """
    cutoff = utcnow() - timedelta(seconds=SWIPE_RATE_LIMIT_WINDOW_SECONDS)
    recent = db.query(models.Swipe.id).filter(
        models.Swipe.user_id == user_id,
        models.Swipe.created_at >= cutoff,
    ).count()
    if recent >= SWIPE_RATE_LIMIT_COUNT:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Swipe rate limit exceeded. Maximum {SWIPE_RATE_LIMIT_COUNT} "
                f"swipes per {SWIPE_RATE_LIMIT_WINDOW_SECONDS} seconds."
            ),
        )

@app.post(
    "/api/v1/profile",
    response_model=schemas.DatingProfileResponse,
    status_code=201
)
def create_dating_profile(
    profile: schemas.DatingProfileCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a dating profile for the current user."""
    # Check if profile already exists
    existing = db.query(models.UserProfile).filter(
        models.UserProfile.user_id == current_user.id
    ).first()
    if existing:
        raise HTTPException(
            409,
            "Dating profile already exists. Use PUT /api/v1/profile/me to update."
        )

    # Parse date of birth
    try:
        dob = datetime.fromisoformat(profile.date_of_birth).date()
    except ValueError:
        raise HTTPException(400, "Invalid date_of_birth format. Use YYYY-MM-DD.")

    db_profile = models.UserProfile(
        user_id=current_user.id,
        date_of_birth=dob,
        gender=profile.gender,
        sexual_orientation=profile.sexual_orientation,
        target_gender_preference=profile.target_gender_preference,
        city=profile.city,
        era=profile.era,
        vibe_tag=profile.vibe_tag,
        match_era_preference=profile.match_era_preference,
        is_face_verified=False,
        is_id_verified=False,
        verification_status="unverified"
    )

    db.add(db_profile)
    db.commit()
    db.refresh(db_profile)

    return db_profile


@app.get(
    "/api/v1/profile/me",
    response_model=schemas.DatingProfileResponse
)
def get_dating_profile(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get the current user's dating profile."""
    profile = db.query(models.UserProfile).filter(
        models.UserProfile.user_id == current_user.id
    ).first()

    if not profile:
        raise HTTPException(404, "Dating profile not found. Create one first.")

    return profile


@app.put(
    "/api/v1/profile/me",
    response_model=schemas.DatingProfileResponse
)
def update_dating_profile(
    updates: schemas.DatingProfileUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update the current user's dating profile."""
    profile = db.query(models.UserProfile).filter(
        models.UserProfile.user_id == current_user.id
    ).first()

    if not profile:
        raise HTTPException(404, "Dating profile not found. Create one first with POST /api/v1/profile")

    values = updates.model_dump(exclude_unset=True)

    if "date_of_birth" in values and values["date_of_birth"] is not None:
        try:
            values["date_of_birth"] = datetime.fromisoformat(values["date_of_birth"]).date()
        except ValueError:
            raise HTTPException(400, "Invalid date_of_birth format. Use YYYY-MM-DD.")

    # Assign only fields explicitly declared as user-editable. The request
    # schema rejects protected verification fields before reaching this point.
    for field, value in values.items():
        setattr(profile, field, value)

    db.commit()
    db.refresh(profile)

    return profile


@app.get(
    "/api/v1/profile/me/privacy",
    response_model=schemas.MatchingPrivacySettingsResponse,
)
def get_matching_privacy_settings(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Read only the authenticated user's private matching and personalization settings."""
    profile = db.query(models.UserProfile).filter(
        models.UserProfile.user_id == current_user.id
    ).first()
    if not profile:
        raise HTTPException(404, "Dating profile not found")
    return {
        "sexual_orientation": profile.sexual_orientation,
        "orientation_matching": {
            "consent": profile.sexual_orientation_consent,
            "version": profile.sexual_orientation_consent_version,
            "updated_at": profile.sexual_orientation_consent_at if profile.sexual_orientation_consent else profile.sexual_orientation_consent_revoked_at,
            "disclosure": ORIENTATION_MATCHING_DISCLOSURE,
        },
        "behavioral_personalization": {
            "consent": profile.behavioral_personalization_enabled,
            "version": profile.behavioral_personalization_consent_version,
            "updated_at": profile.behavioral_personalization_consent_at if profile.behavioral_personalization_enabled else profile.behavioral_personalization_consent_revoked_at,
            "disclosure": BEHAVIORAL_PERSONALIZATION_DISCLOSURE,
        },
    }


@app.put(
    "/api/v1/profile/me/orientation-consent",
    response_model=schemas.ConsentStatus,
    description=(
        "Explicitly allow or revoke use of your optional sexual orientation for matching. "
        + ORIENTATION_MATCHING_DISCLOSURE
    ),
)
def update_orientation_matching_consent(
    request: schemas.ConsentUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.query(models.UserProfile).filter(
        models.UserProfile.user_id == current_user.id
    ).first()
    if not profile:
        raise HTTPException(404, "Dating profile not found")
    if request.consent and not profile.sexual_orientation:
        raise HTTPException(409, "Choose a supported sexual orientation before consenting")
    was_consented = profile.sexual_orientation_consent
    profile.sexual_orientation_consent = request.consent
    profile.sexual_orientation_consent_version = (
        ORIENTATION_MATCHING_CONSENT_VERSION if request.consent
        else profile.sexual_orientation_consent_version
    )
    if request.consent:
        profile.sexual_orientation_consent_at = datetime.now(timezone.utc)
        profile.sexual_orientation_consent_revoked_at = None
    elif was_consented:
        profile.sexual_orientation_consent_revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "consent": profile.sexual_orientation_consent,
        "version": profile.sexual_orientation_consent_version,
        "updated_at": profile.sexual_orientation_consent_at if profile.sexual_orientation_consent else profile.sexual_orientation_consent_revoked_at,
        "disclosure": ORIENTATION_MATCHING_DISCLOSURE,
    }


@app.put(
    "/api/v1/profile/me/behavioral-personalization-consent",
    response_model=schemas.ConsentStatus,
    description=(
        "Set the independent behavioral-personalization preference. It is currently not used "
        "to rank profiles. " + BEHAVIORAL_PERSONALIZATION_DISCLOSURE
    ),
)
def update_behavioral_personalization_consent(
    request: schemas.ConsentUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.query(models.UserProfile).filter(
        models.UserProfile.user_id == current_user.id
    ).first()
    if not profile:
        raise HTTPException(404, "Dating profile not found")
    was_enabled = profile.behavioral_personalization_enabled
    profile.behavioral_personalization_enabled = request.consent
    profile.behavioral_personalization_consent_version = (
        BEHAVIORAL_PERSONALIZATION_CONSENT_VERSION if request.consent
        else profile.behavioral_personalization_consent_version
    )
    if request.consent:
        profile.behavioral_personalization_consent_at = datetime.now(timezone.utc)
        profile.behavioral_personalization_consent_revoked_at = None
    elif was_enabled:
        profile.behavioral_personalization_consent_revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "consent": profile.behavioral_personalization_enabled,
        "version": profile.behavioral_personalization_consent_version,
        "updated_at": profile.behavioral_personalization_consent_at if profile.behavioral_personalization_enabled else profile.behavioral_personalization_consent_revoked_at,
        "disclosure": BEHAVIORAL_PERSONALIZATION_DISCLOSURE,
    }


@app.get(
    "/api/v1/profile/{user_id}",
    response_model=schemas.PublicProfileResponse
)
def get_public_profile(
    user_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Return a minimal profile only when both users may discover each other."""
    requester_profile = _require_verified_profile(db, current_user.id)
    profile = db.query(models.UserProfile).filter(
        models.UserProfile.user_id == user_id
    ).first()

    if (
        user_id == current_user.id
        or not _is_discoverable_profile(profile)
        or _has_block_between(db, current_user.id, user_id)
        or not _profiles_match_preferences(requester_profile, profile)
    ):
        # Use one response for absent, ineligible, preference-mismatched, and
        # blocked profiles so callers cannot enumerate hidden accounts.
        raise HTTPException(404, "User profile not found")

    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(404, "User profile not found")

    return schemas.PublicProfileResponse(
        user_id=profile.user_id,
        username=user.username,
        full_name=user.full_name,
        age=_profile_age(profile),
        city=profile.city,
        era=profile.era,
        vibe_tag=profile.vibe_tag,
        bio=user.bio,
    )


# ============================================================
# PROFILE PHOTOS ENDPOINTS
# ============================================================

@app.post(
    "/api/v1/profile/photos",
    status_code=201
)
async def upload_profile_photo(
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload a profile photo for the current user."""
    import shutil
    import uuid as uuid_module

    # Check user has a profile
    profile = db.query(models.UserProfile).filter(
        models.UserProfile.user_id == current_user.id
    ).first()

    if not profile:
        raise HTTPException(404, "Dating profile not found")

    # Validate file size (max 10MB for profile photos)
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        await file.close()
        raise HTTPException(400, "File too large. Maximum size is 10MB")

    # Validate file signature (magic numbers)
    # Read first 8 bytes for signature detection
    header = content[:8]
    is_valid_image = False
    mime_type = None

    # PNG: 89 50 4E 47 0D 0A 1A 0A
    # JPEG: FF D8 FF
    # WEBP: 52 49 46 46 XX XX XX XX 57 45 42 50
    # GIF: 47 49 46 38
    # AVIF: 61 76 69 66

    if header[:8] == b'\x89PNG\r\n\x1a\n':
        is_valid_image = True
        mime_type = "image/png"
    elif header[:3] == b'\xff\xd8\xff':
        is_valid_image = True
        mime_type = "image/jpeg"
    elif header[:4] == b'RIFF' and header[8:12] == b'WEBP':
        is_valid_image = True
        mime_type = "image/webp"
    elif header[:6] in (b'gif87a', b'gif89a'):
        is_valid_image = True
        mime_type = "image/gif"
    elif header[:4] == b'ftyp':
        is_valid_image = True
        mime_type = "image/avif"

    if not is_valid_image:
        await file.close()
        raise HTTPException(400, "Invalid file. Only PNG, JPEG, WEBP, GIF, and AVIF images are allowed")

    # Generate storage key
    storage_key = f"profile_{uuid_module.uuid4().hex[:16]}"
    photo_path = Path(f"uploads/profiles/{storage_key}.webp")

    # Ensure directory exists
    os.makedirs(os.path.dirname(photo_path), exist_ok=True)

    # Write file (convert to webp if needed, or store as-is for simplicity)
    # For now, save as original format
    ext = Path(file.filename or "image").suffix.lower() or ".png"
    actual_path = str(photo_path).replace('.webp', ext) if ext != '.webp' else str(photo_path)

    with open(actual_path, 'wb') as f:
        f.write(content)

    await file.close()

    # Get max display order
    max_order = db.query(func.max(models.ProfilePhoto.display_order)).filter(
        models.ProfilePhoto.profile_id == profile.id
    ).scalar() or 0

    # Create profile photo record
    db_photo = models.ProfilePhoto(
        profile_id=profile.id,
        storage_key=storage_key,
        photo_url=f"/uploads/profiles/{os.path.basename(actual_path)}",
        display_order=max_order + 1,
        is_primary=(max_order == 0)  # First photo is primary
    )

    db.add(db_photo)
    db.commit()
    db.refresh(db_photo)

    return {
        "id": db_photo.id,
        "photo_url": db_photo.photo_url,
        "is_primary": db_photo.is_primary,
        "display_order": db_photo.display_order
    }


@app.get(
    "/api/v1/profile/me/photos",
    response_model=list[schemas.DatingProfileResponse]
)
def list_profile_photos(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all profile photos for the current user."""
    profile = db.query(models.UserProfile).filter(
        models.UserProfile.user_id == current_user.id
    ).first()

    if not profile:
        raise HTTPException(404, "Dating profile not found")

    photos = db.query(models.ProfilePhoto).filter(
        models.ProfilePhoto.profile_id == profile.id
    ).order_by(models.ProfilePhoto.display_order).all()

    return [{
        "id": photo.id,
        "photo_url": photo.photo_url,
        "is_primary": photo.is_primary,
        "display_order": photo.display_order
    } for photo in photos]


@app.delete("/api/v1/profile/photos/{photo_id}")
def delete_profile_photo(
    photo_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a profile photo."""
    # Verify ownership through profile
    profile = db.query(models.UserProfile).filter(
        models.UserProfile.user_id == current_user.id
    ).first()

    if not profile:
        raise HTTPException(404, "Dating profile not found")

    photo = db.query(models.ProfilePhoto).filter(
        models.ProfilePhoto.id == photo_id,
        models.ProfilePhoto.profile_id == profile.id
    ).first()

    if not photo:
        raise HTTPException(404, "Photo not found or access denied")

    # Delete file
    if os.path.exists(photo.photo_url):
        os.remove(photo.photo_url)

    db.delete(photo)
    db.commit()

    return {"deleted": True}


# ============================================================
# VERIFICATION ENDPOINTS
# ============================================================

VERIFICATION_EVIDENCE_RETENTION_DAYS = 30
VERIFICATION_ID_TYPES = {"id_college", "id_work", "id_govt"}
VERIFICATION_RETENTION_LOCK_ID = 0x5241414849


def _verification_details(record: models.UserVerification) -> dict:
    try:
        value = json.loads(record.details_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _save_verification_details(record: models.UserVerification, details: dict) -> None:
    record.details_json = json.dumps(details, separators=(",", ":"))


def _refresh_profile_verification_status(db: Session, user_id: int) -> None:
    profile = db.query(models.UserProfile).filter(
        models.UserProfile.user_id == user_id
    ).first()
    if not profile:
        return

    if profile.is_face_verified and profile.is_id_verified:
        profile.verification_status = "verified"
        return

    rows = db.query(models.UserVerification.status).filter(
        models.UserVerification.user_id == user_id,
        models.UserVerification.verification_type.in_(
            {"face", *VERIFICATION_ID_TYPES}
        ),
    ).all()
    states = {row[0] for row in rows}
    if "pending" in states or profile.is_face_verified or profile.is_id_verified:
        profile.verification_status = "pending"
    elif "failed" in states:
        profile.verification_status = "rejected"
    else:
        profile.verification_status = "unverified"


def _cleanup_finalized_verification_evidence(
    db: Session, user_id: int | None = None
) -> None:
    """Retry deletion of finalized evidence and persist observable failures."""
    query = db.query(models.UserVerification).filter(
        models.UserVerification.status != "pending"
    )
    if user_id is not None:
        query = query.filter(models.UserVerification.user_id == user_id)
    # Row locks serialize concurrent API workers retrying the same finalized
    # evidence cleanup. Pending requests are excluded before any storage access.
    records = query.with_for_update(skip_locked=True).all()
    changed = False
    for record in records:
        details = _verification_details(record)
        evidence_key = details.get("evidence_key")
        if not evidence_key:
            continue
        cleanup = details.get("evidence_cleanup")
        cleanup = cleanup if isinstance(cleanup, dict) else {}
        try:
            attempts = max(0, int(cleanup.get("attempts", 0))) + 1
        except (TypeError, ValueError):
            attempts = 1
        if verification_storage.delete_evidence(evidence_key):
            details["evidence_key"] = None
            details["evidence_cleanup"] = {
                "status": "deleted",
                "attempts": attempts,
                "last_attempt_at": utcnow().isoformat(),
            }
        else:
            details["evidence_cleanup"] = {
                "status": "retry_pending",
                "attempts": attempts,
                "last_attempt_at": utcnow().isoformat(),
            }
            logger.error(
                "Verification evidence deletion failed; retry_pending verification_id=%s attempts=%s",
                record.id,
                attempts,
            )
        _save_verification_details(record, details)
        changed = True
    if changed:
        db.commit()


def _expire_stale_verification_requests(
    db: Session, user_id: int | None = None
) -> None:
    cutoff = utcnow() - timedelta(days=VERIFICATION_EVIDENCE_RETENTION_DAYS)
    query = db.query(models.UserVerification).filter(
        models.UserVerification.status == "pending"
    )
    if user_id is not None:
        query = query.filter(models.UserVerification.user_id == user_id)
    pending = query.with_for_update().all()
    stale = []
    for record in pending:
        details = _verification_details(record)
        evidence_key = details.get("evidence_key")
        # Legacy pending rows with no evidence cannot be reviewed. Expire them
        # immediately instead of leaving them pending forever or blocking resubmission.
        if not evidence_key or record.reviewed_at < cutoff:
            stale.append(record)
    for record in stale:
        details = _verification_details(record)
        evidence_key = details.get("evidence_key")
        now = utcnow()
        details["retention"] = {
            "action": "expired" if evidence_key else "legacy_missing_evidence",
            "actor": "system",
            "expired_at": now.isoformat(),
        }
        audit = details.get("audit_events")
        if not isinstance(audit, list):
            audit = []
        audit.append({
            "event": "expired",
            "actor": "system",
            "occurred_at": now.isoformat(),
            "reason": "missing_evidence" if not evidence_key else "retention_period_elapsed",
        })
        details["audit_events"] = audit
        record.status = "failed"
        record.reviewed_at = now
        _save_verification_details(record, details)
        profile = db.query(models.UserProfile).filter(
            models.UserProfile.user_id == record.user_id
        ).first()
        if profile:
            if record.verification_type == "face":
                profile.is_face_verified = False
            elif record.verification_type in VERIFICATION_ID_TYPES:
                profile.is_id_verified = False
    if stale:
        # SessionLocal disables autoflush; make state transitions visible to
        # the status aggregation query before refreshing profile state.
        db.flush()
        for user_id in {record.user_id for record in stale}:
            _refresh_profile_verification_status(db, user_id)
        db.commit()
        # Finalized-row cleanup persists retry metadata if storage is unavailable.
        _cleanup_finalized_verification_evidence(db)


def _run_verification_retention_maintenance(db: Session) -> bool:
    """Run one daily sweep under a PostgreSQL session advisory lock.

    The lock coordinates external scheduler invocations across processes and
    hosts sharing PostgreSQL. FastAPI workers do not run this job themselves.
    """
    if db.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Verification retention maintenance requires PostgreSQL")

    try:
        acquired = db.execute(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": VERIFICATION_RETENTION_LOCK_ID},
        ).scalar_one()
        db.commit()
    except Exception:
        db.rollback()
        raise

    if not acquired:
        logger.info("Verification retention maintenance skipped; another scheduler holds the lock")
        return False

    try:
        _expire_stale_verification_requests(db)
        _cleanup_finalized_verification_evidence(db)
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        try:
            if db.in_transaction():
                db.rollback()
            unlocked = db.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": VERIFICATION_RETENTION_LOCK_ID},
            ).scalar_one()
            db.commit()
            if not unlocked:
                logger.error("Verification retention advisory lock was not held at release")
        except Exception:
            db.rollback()
            logger.exception("Failed to release verification retention advisory lock")


def _require_verification_workflow() -> None:
    try:
        verification_storage.require_workflow_configuration()
    except verification_storage.EvidenceConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail="Identity verification is not configured. No evidence was accepted.",
        ) from exc


def require_verification_reviewer(
    current_user: models.User = Depends(get_current_user),
) -> models.User:
    try:
        reviewer_ids = verification_storage.reviewer_user_ids()
        verification_storage.require_workflow_configuration()
    except verification_storage.EvidenceConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail="Identity verification review is not configured.",
        ) from exc
    if current_user.id not in reviewer_ids:
        raise HTTPException(status_code=403, detail="Verification reviewer access required")
    return current_user


async def _read_verification_upload(file: UploadFile, verification_type: str) -> tuple[bytes, str]:
    chunks: list[bytes] = []
    size = 0
    try:
        while True:
            chunk = await file.read(min(
                verification_storage.CHUNK_SIZE,
                verification_storage.MAX_EVIDENCE_BYTES + 1 - size,
            ))
            if not chunk:
                break
            size += len(chunk)
            if size > verification_storage.MAX_EVIDENCE_BYTES:
                raise HTTPException(413, "Evidence file exceeds the 10 MiB limit")
            chunks.append(chunk)
    finally:
        await file.close()

    content = b"".join(chunks)
    try:
        media_type = verification_storage.identify_evidence(content, verification_type)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return content, media_type


async def _submit_verification_request(
    verification_type: str,
    file: UploadFile,
    current_user: models.User,
    db: Session,
) -> dict:
    _require_verification_workflow()
    _expire_stale_verification_requests(db, current_user.id)
    _cleanup_finalized_verification_evidence(db, current_user.id)

    profile = db.query(models.UserProfile).filter(
        models.UserProfile.user_id == current_user.id
    ).with_for_update().first()
    if not profile:
        raise HTTPException(404, "Dating profile not found. Complete your profile first.")

    is_face = verification_type == "face"
    if (profile.is_face_verified if is_face else profile.is_id_verified):
        raise HTTPException(409, "This verification type is already approved")

    related_types = {"face"} if is_face else VERIFICATION_ID_TYPES
    pending = db.query(models.UserVerification.id).filter(
        models.UserVerification.user_id == current_user.id,
        models.UserVerification.verification_type.in_(related_types),
        models.UserVerification.status == "pending",
    ).first()
    if pending:
        raise HTTPException(409, "A request for this verification type is already pending")

    content, media_type = await _read_verification_upload(file, verification_type)
    evidence_key = verification_storage.save_evidence(content)
    verification = models.UserVerification(
        user_id=current_user.id,
        verification_type=verification_type,
        status="pending",
        details_json=json.dumps({
            "evidence_key": evidence_key,
            "content_type": media_type,
            "sha256": hashlib.sha256(content).hexdigest(),
            "submitted_at": utcnow().isoformat(),
        }, separators=(",", ":")),
    )
    db.add(verification)
    profile.verification_status = "pending"
    try:
        db.commit()
        db.refresh(verification)
    except Exception:
        db.rollback()
        if not verification_storage.delete_evidence(evidence_key):
            cleanup_record = models.UserVerification(
                user_id=current_user.id,
                verification_type=verification_type,
                status="failed",
                details_json=json.dumps({
                    "evidence_key": evidence_key,
                    "content_type": media_type,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "audit_events": [{
                        "event": "submission_persistence_failed",
                        "actor": "system",
                        "occurred_at": utcnow().isoformat(),
                    }],
                    "evidence_cleanup": {
                        "status": "retry_pending",
                        "attempts": 1,
                        "last_attempt_at": utcnow().isoformat(),
                    },
                }, separators=(",", ":")),
            )
            try:
                db.add(cleanup_record)
                db.commit()
            except Exception:
                db.rollback()
                logger.error(
                    "Verification evidence cleanup could not be persisted after submission failure; orphan requires operator cleanup"
                )
            else:
                logger.error(
                    "Verification evidence deletion failed after submission persistence error; retry_pending verification_id=%s",
                    cleanup_record.id,
                )
        raise

    return {
        "verification_id": verification.id,
        "verification_type": verification_type,
        "status": "pending",
        "submitted_at": verification.reviewed_at,
    }


@app.post(
    "/api/v1/verification/face",
    status_code=201
)
async def upload_face_verification(
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Submit a selfie for manual review; upload alone never proves identity."""
    return await _submit_verification_request("face", file, current_user, db)


@app.post(
    "/api/v1/verification/id",
    status_code=201
)
async def upload_id_verification(
    id_type: str = Form(...),
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Submit one supported ID type for private manual review."""
    if id_type not in VERIFICATION_ID_TYPES:
        raise HTTPException(
            400,
            f"Invalid id_type. Must be one of: {', '.join(sorted(VERIFICATION_ID_TYPES))}",
        )
    return await _submit_verification_request(id_type, file, current_user, db)


@app.get("/api/v1/verification/status")
def get_verification_status(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get the current user's verification history and status."""
    _expire_stale_verification_requests(db, current_user.id)
    _cleanup_finalized_verification_evidence(db, current_user.id)
    verifications = db.query(models.UserVerification).filter(
        models.UserVerification.user_id == current_user.id,
        models.UserVerification.status.in_(["passed", "failed", "pending", "cancelled"])
    ).order_by(models.UserVerification.reviewed_at.desc()).all()

    profile = db.query(models.UserProfile).filter(
        models.UserProfile.user_id == current_user.id
    ).first()

    latest_status = None
    if profile:
        latest_status = profile.verification_status

    return {
        "verifications": [
            schemas.UserVerificationResponse(
                id=v.id,
                user_id=v.user_id,
                verification_type=v.verification_type,
                status=v.status,
                reviewed_at=v.reviewed_at
            ) for v in verifications
        ],
        "current_status": latest_status,
        "is_face_verified": profile.is_face_verified if profile else False,
        "is_id_verified": profile.is_id_verified if profile else False,
        "verification_available": verification_storage.workflow_available()
    }


@app.delete("/api/v1/verification/{verification_id}")
def cancel_verification_request(
    verification_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cancel an owned pending request and delete its encrypted evidence."""
    _expire_stale_verification_requests(db, current_user.id)
    record = db.query(models.UserVerification).filter(
        models.UserVerification.id == verification_id,
        models.UserVerification.user_id == current_user.id,
        models.UserVerification.status == "pending",
    ).with_for_update().first()
    if not record:
        finalized = db.get(models.UserVerification, verification_id)
        finalized_details = _verification_details(finalized) if finalized else {}
        retention = finalized_details.get("retention")
        if (
            finalized
            and finalized.user_id == current_user.id
            and finalized.status == "failed"
            and isinstance(retention, dict)
            and retention.get("action") in {"expired", "legacy_missing_evidence"}
        ):
            raise HTTPException(410, "Verification evidence expired; submit a new request")
        raise HTTPException(404, "Pending verification request not found")

    details = _verification_details(record)
    now = utcnow()
    audit = details.get("audit_events")
    if not isinstance(audit, list):
        audit = []
    audit.append({
        "event": "cancelled",
        "actor_user_id": current_user.id,
        "occurred_at": now.isoformat(),
    })
    details["audit_events"] = audit
    record.status = "cancelled"
    record.reviewed_at = now
    _save_verification_details(record, details)
    db.flush()
    _refresh_profile_verification_status(db, current_user.id)
    db.commit()
    _cleanup_finalized_verification_evidence(db, current_user.id)
    record = db.get(models.UserVerification, verification_id)
    return {
        "verification_id": verification_id,
        "status": "cancelled",
        "evidence_deletion_pending": bool(_verification_details(record).get("evidence_key")),
    }


@app.get("/api/v1/reviewer/verifications")
def list_pending_verifications(
    reviewer: models.User = Depends(require_verification_reviewer),
    db: Session = Depends(get_db),
):
    """List pending requests without exposing evidence or private profile data."""
    _expire_stale_verification_requests(db)
    _cleanup_finalized_verification_evidence(db)
    records = db.query(models.UserVerification).filter(
        models.UserVerification.status == "pending",
        models.UserVerification.verification_type.in_({"face", *VERIFICATION_ID_TYPES}),
    ).order_by(models.UserVerification.reviewed_at.asc()).all()

    pending = []
    for record in records:
        if record.user_id == reviewer.id:
            continue
        details = _verification_details(record)
        if not details.get("evidence_key"):
            continue
        pending.append({
            "verification_id": record.id,
            "user_id": record.user_id,
            "verification_type": record.verification_type,
            "submitted_at": record.reviewed_at,
        })
    return {"items": pending}


@app.get("/api/v1/reviewer/verifications/{verification_id}/evidence")
def get_verification_evidence(
    verification_id: int,
    reviewer: models.User = Depends(require_verification_reviewer),
    db: Session = Depends(get_db),
):
    """Download evidence only for a pending request owned by another user."""
    _expire_stale_verification_requests(db)
    record = db.query(models.UserVerification).filter(
        models.UserVerification.id == verification_id,
        models.UserVerification.status == "pending",
    ).first()
    if not record:
        finalized = db.get(models.UserVerification, verification_id)
        if finalized and finalized.status == "failed":
            finalized_details = _verification_details(finalized)
            retention = finalized_details.get("retention")
            if isinstance(retention, dict) and retention.get("action") in {
                "expired", "legacy_missing_evidence"
            }:
                raise HTTPException(410, "Verification evidence expired")
        raise HTTPException(404, "Pending verification evidence not found")
    if record.user_id == reviewer.id:
        raise HTTPException(404, "Pending verification evidence not found")

    details = _verification_details(record)
    evidence_key = details.get("evidence_key")
    media_type = details.get("content_type")
    if not evidence_key or media_type not in {
        "image/jpeg", "image/png", "image/webp", "application/pdf"
    }:
        raise HTTPException(404, "Pending verification evidence not found")
    try:
        content = verification_storage.read_evidence(evidence_key)
    except ValueError as exc:
        logger.error("Invalid verification evidence key; verification_id=%s", record.id)
        raise HTTPException(410, "Verification evidence is no longer available") from exc
    except FileNotFoundError as exc:
        raise HTTPException(410, "Verification evidence is no longer available") from exc
    except verification_storage.EvidenceConfigurationError as exc:
        raise HTTPException(503, "Verification evidence is unavailable") from exc

    extension = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "application/pdf": "pdf",
    }[media_type]
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Cache-Control": "private, no-store",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="verification-evidence.{extension}"',
        },
    )


@app.post("/api/v1/reviewer/verifications/{verification_id}/decision")
def decide_verification(
    verification_id: int,
    decision: schemas.VerificationDecision,
    reviewer: models.User = Depends(require_verification_reviewer),
    db: Session = Depends(get_db),
):
    """Record an allowlisted reviewer's decision; never infer approval from upload."""
    _expire_stale_verification_requests(db)
    record = db.query(models.UserVerification).filter(
        models.UserVerification.id == verification_id,
        models.UserVerification.status == "pending",
        models.UserVerification.verification_type.in_({"face", *VERIFICATION_ID_TYPES}),
    ).with_for_update().first()
    if not record:
        finalized = db.get(models.UserVerification, verification_id)
        if finalized and finalized.status == "failed":
            finalized_details = _verification_details(finalized)
            retention = finalized_details.get("retention")
            if isinstance(retention, dict) and retention.get("action") in {
                "expired", "legacy_missing_evidence"
            }:
                raise HTTPException(410, "Verification evidence expired; user must resubmit")
        raise HTTPException(404, "Pending verification request not found")
    if record.user_id == reviewer.id:
        raise HTTPException(403, "Reviewers cannot decide their own requests")

    details = _verification_details(record)
    evidence_key = details.get("evidence_key")
    if not evidence_key:
        raise HTTPException(409, "Evidence is unavailable; the user must resubmit")
    try:
        # Check that the evidence is decryptable before recording a decision.
        verification_storage.read_evidence(evidence_key)
    except ValueError as exc:
        logger.error("Invalid verification evidence key; verification_id=%s", record.id)
        raise HTTPException(409, "Evidence is unavailable; the user must resubmit") from exc
    except FileNotFoundError as exc:
        raise HTTPException(409, "Evidence is unavailable; the user must resubmit") from exc
    except verification_storage.EvidenceConfigurationError as exc:
        raise HTTPException(503, "Verification evidence is unavailable") from exc

    profile = db.query(models.UserProfile).filter(
        models.UserProfile.user_id == record.user_id
    ).with_for_update().first()
    if not profile:
        raise HTTPException(404, "Dating profile not found")

    approved = decision.decision == "approve"
    now = utcnow()
    if record.verification_type == "face":
        profile.is_face_verified = approved
    else:
        profile.is_id_verified = approved

    record.status = "passed" if approved else "failed"
    record.reviewed_at = now
    audit = details.get("audit_events")
    if not isinstance(audit, list):
        audit = []
    audit.append({
        "event": "review_decision",
        "reviewer_user_id": reviewer.id,
        "decision": decision.decision,
        "reason": decision.reason,
        "occurred_at": now.isoformat(),
        "evidence_sha256": details.get("sha256"),
    })
    details["audit_events"] = audit
    # Retain the established report/API audit shape for existing consumers.
    details["review"] = {
        "reviewer_user_id": reviewer.id,
        "decision": decision.decision,
        "reason": decision.reason,
        "decided_at": now.isoformat(),
        "evidence_sha256": details.get("sha256"),
    }
    _save_verification_details(record, details)
    db.flush()
    _refresh_profile_verification_status(db, record.user_id)
    db.commit()

    _cleanup_finalized_verification_evidence(db, record.user_id)
    return {
        "verification_id": record.id,
        "verification_type": record.verification_type,
        "status": record.status,
        "current_status": profile.verification_status,
        "evidence_deletion_pending": bool(_verification_details(record).get("evidence_key")),
    }


# ============================================================
# SWIPE ENDPOINTS
# ============================================================

@app.post(
    "/api/v1/swipe",
    response_model=schemas.SwipeResponse
)
def create_swipe(
    swipe: schemas.SwipeCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Record a swipe action (like, pass, superlike) and evaluate match."""
    # Only profiles approved by the trusted verification path may interact.
    profile = _require_verified_profile(db, current_user.id)

    # Prevent self-swiping
    if swipe.target_user_id == current_user.id:
        raise HTTPException(400, "Cannot swipe on yourself")

    # Rate limiting: reject excessive swipe volume from a single account.
    _enforce_swipe_rate_limit(db, current_user.id)

    # Check if user exists
    target_user = db.get(models.User, swipe.target_user_id)
    if not target_user:
        raise HTTPException(404, "Target user not found")

    # Check if the target is an eligible discovery profile.
    target_profile = db.query(models.UserProfile).filter(
        models.UserProfile.user_id == swipe.target_user_id
    ).first()
    if (
        not _is_discoverable_profile(target_profile)
        or not _profiles_match_preferences(profile, target_profile)
    ):
        raise HTTPException(404, "Target user profile not found")

    # Blocks in either direction make the other profile unavailable.
    if _has_block_between(db, current_user.id, swipe.target_user_id):
        raise HTTPException(404, "Target user profile not found")

    # Check if already swiped on this user
    existing_swipe = db.query(models.Swipe).filter(
        models.Swipe.user_id == current_user.id,
        models.Swipe.target_user_id == swipe.target_user_id
    ).first()
    if existing_swipe:
        # Return existing swipe (idempotent)
        return existing_swipe

    # Record the swipe
    db_swipe = models.Swipe(
        user_id=current_user.id,
        target_user_id=swipe.target_user_id,
        action=swipe.action
    )
    db.add(db_swipe)

    # Check for mutual match (reverse swipe)
    reverse_swipe = db.query(models.Swipe).filter(
        models.Swipe.user_id == swipe.target_user_id,
        models.Swipe.target_user_id == current_user.id,
        models.Swipe.action != "pass"  # Like or superlike
    ).first()

    match = None
    chat = None

    if reverse_swipe and swipe.action != "pass":
        # Mutual match! Create chat and match record.
        # Lock the canonical pair rows so concurrent swipes from both users
        # cannot create duplicate Match/Chat rows. The unique constraint on
        # (user1_id, user2_id) is the final backstop.
        u1, u2 = _user_pair_ids(current_user.id, swipe.target_user_id)
        db.query(models.Match).filter(
            models.Match.user1_id == u1,
            models.Match.user2_id == u2,
        ).with_for_update().first()

        existing_match = db.query(models.Match).filter(
            models.Match.user1_id == u1,
            models.Match.user2_id == u2,
            models.Match.is_active == True,  # noqa: E712
        ).first()
        if not existing_match:
            new_chat = models.Chat(
                user1_id=u1,
                user2_id=u2
            )
            db.add(new_chat)
            db.flush()  # Get chat.id

            new_match = models.Match(
                user1_id=u1,
                user2_id=u2,
                chat_id=new_chat.id,
                compatibility_score=85
            )
            db.add(new_match)
            match = new_match
            chat = new_chat

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # A concurrent request created the match first; re-read the state.
        existing_match = db.query(models.Match).filter(
            models.Match.user1_id == _user_pair_ids(current_user.id, swipe.target_user_id)[0],
            models.Match.user2_id == _user_pair_ids(current_user.id, swipe.target_user_id)[1],
            models.Match.is_active == True,  # noqa: E712
        ).first()
        if existing_match:
            match = existing_match
            chat = db.get(models.Chat, existing_match.chat_id)
        else:
            db.rollback()
            raise HTTPException(500, "Failed to record swipe due to conflict")

    if match:
        try:
            dating_ml_adapter.predict_and_persist_match(db, match)
            db.commit()
            db.refresh(match)
        except (MatchingConsentRequired, MatchingNotAllowed):
            # Matching remains available under the existing preference gate;
            # orientation-based scoring is withheld unless both consent now.
            db.rollback()
        except Exception:
            db.rollback()
            logger.exception("Dating ML match result persistence failed for match_id=%s", match.id)

    db.refresh(db_swipe)

    result = {
        "id": db_swipe.id,
        "user_id": current_user.id,
        "target_user_id": swipe.target_user_id,
        "action": swipe.action,
        "created_at": db_swipe.created_at
    }

    if match and chat:
        result["is_match"] = True
        result["match"] = {
            "id": match.id,
            "chat_id": chat.id,
            "matched_user": {
                "id": target_user.id,
                "username": target_user.username,
                "full_name": target_user.full_name,
                "bio": target_user.bio
            },
            "compatibility_score": match.compatibility_score,
            "compatibility_score_status": "legacy_placeholder",
            "profile_alignment": _profile_alignment_payload(match),
        }
    else:
        result["is_match"] = False

    return result


# ============================================================
# BLOCK ENDPOINTS
# ============================================================

@app.post(
    "/api/v1/blocks",
    response_model=schemas.BlockResponse
)
def block_user(
    block: schemas.BlockCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Block a user."""
    # Prevent self-blocking
    if block.blocked_id == current_user.id:
        raise HTTPException(400, "Cannot block yourself")

    # Check if user exists
    blocked_user = db.get(models.User, block.blocked_id)
    if not blocked_user:
        raise HTTPException(404, "User not found")

    # Check if already blocked
    existing_block = db.query(models.UserBlock).filter(
        models.UserBlock.blocker_id == current_user.id,
        models.UserBlock.blocked_id == block.blocked_id
    ).first()
    if existing_block:
        return existing_block

    # Create block
    db_block = models.UserBlock(
        blocker_id=current_user.id,
        blocked_id=block.blocked_id
    )
    db.add(db_block)

    # Remove any existing matches/chats
    match = db.query(models.Match).filter(
        or_(
            (models.Match.user1_id == current_user.id) & (models.Match.user2_id == block.blocked_id),
            (models.Match.user1_id == block.blocked_id) & (models.Match.user2_id == current_user.id)
        )
    ).first()
    chat = db.get(models.Chat, match.chat_id) if match else find_chat(
        db, current_user.id, block.blocked_id
    )

    if match:
        match.is_active = False
        match.unmatched_at = utcnow()
        match.unmatch_reason = "user_blocked"
    if chat:
        invalidate_chat_ai_notifications(db, chat.id)

    # Remove existing swipes in both directions
    db.query(models.Swipe).filter(
        models.Swipe.user_id == current_user.id,
        models.Swipe.target_user_id == block.blocked_id
    ).delete(synchronize_session=False)

    db.query(models.Swipe).filter(
        models.Swipe.user_id == block.blocked_id,
        models.Swipe.target_user_id == current_user.id
    ).delete(synchronize_session=False)

    db.commit()
    db.refresh(db_block)

    # Notify only the two affected participants; never reveal the block to
    # unrelated users through the global presence channel.
    if chat:
        spawn(notify_chat_access_revoked(
            chat.id,
            {current_user.id, block.blocked_id},
            {"type": "user_blocked", "blocker_id": current_user.id,
             "blocked_id": block.blocked_id, "chat_id": chat.id},
        ))

    return db_block


@app.delete("/api/v1/blocks/{blocked_id}")
def unblock_user(
    blocked_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Unblock a user."""
    block = db.query(models.UserBlock).filter(
        models.UserBlock.blocker_id == current_user.id,
        models.UserBlock.blocked_id == blocked_id
    ).first()

    if not block:
        raise HTTPException(404, "Block not found")

    db.delete(block)
    db.commit()

    return {"unblocked": True}


# ============================================================
# REPORT ENDPOINTS
# ============================================================

@app.post(
    "/api/v1/reports",
    response_model=schemas.ReportResponse
)
def report_user(
    report: schemas.ReportCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Report a user for misconduct."""
    # Prevent self-reporting
    if report.reported_id == current_user.id:
        raise HTTPException(400, "Cannot report yourself")

    # Check if user exists
    reported_user = db.get(models.User, report.reported_id)
    if not reported_user:
        raise HTTPException(404, "User not found")

    # Check if already reported
    existing_report = db.query(models.UserReport).filter(
        models.UserReport.reporter_id == current_user.id,
        models.UserReport.reported_id == report.reported_id
    ).first()
    if existing_report:
        raise HTTPException(409, "You have already reported this user")

    # Create report
    db_report = models.UserReport(
        reporter_id=current_user.id,
        reported_id=report.reported_id,
        reason=report.reason,
        details=report.details,
        status="pending"
    )
    db.add(db_report)
    db.commit()
    db.refresh(db_report)

    # Broadcast report event
    spawn(broadcast_presence(
        current_user.id,
        "user_reported",
        None,
        None
    ))

    return db_report


# ============================================================
# MATCHES ENDPOINTS
# ============================================================

def _user_pair_ids(user_id: int, other_id: int) -> tuple[int, int]:
    """Return canonical (min, max) ordering for a user pair."""
    return (min(user_id, other_id), max(user_id, other_id))


def _get_match_for_pair(db: Session, user_id: int, other_id: int):
    """Return the active match row for a pair, or None."""
    u1, u2 = _user_pair_ids(user_id, other_id)
    return db.query(models.Match).filter(
        models.Match.user1_id == u1,
        models.Match.user2_id == u2,
        models.Match.is_active == True,  # noqa: E712
    ).first()


def _profile_alignment_payload(match: models.Match) -> dict[str, Any] | None:
    """Return a real deterministic alignment or null for legacy/unscored matches."""
    if match.prediction_provenance != "dating_ml_v3" or match.calculated_at is None:
        return None
    return {
        "score": float(match.raw_compatibility_score) if match.raw_compatibility_score is not None else None,
        "confidence": float(match.confidence_score) if match.confidence_score is not None else None,
        "adjusted_score": float(match.adjusted_score) if match.adjusted_score is not None else None,
        "package_version": dating_ml_adapter.package_version,
        "engine_version": match.model_version or dating_ml_adapter.engine_version,
        "provenance": match.prediction_provenance,
        "eligibility_status": match.eligibility_status,
        "eligibility_reason": match.eligibility_reason,
        "explanation": match.explanation,
        "components": match.component_scores,
        "score_type": "profile_alignment",
        "is_success_probability": False,
        "weights_validated": False,
    }


@app.get(
    "/api/v1/matches",
    response_model=schemas.MatchListResponse
)
def list_matches(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """List the current user's active matches.

    Only matches where the current user is a participant are returned.
    Inactive matches (unmatched or blocked) are excluded.
    """
    _require_verified_profile(db, current_user.id)
    rows = db.query(models.Match).filter(
        or_(
            models.Match.user1_id == current_user.id,
            models.Match.user2_id == current_user.id,
        ),
        models.Match.is_active == True,  # noqa: E712
    ).order_by(models.Match.created_at.desc()).all()

    eligible_rows = []
    for match in rows:
        other_id = match.user2_id if match.user1_id == current_user.id else match.user1_id
        if _has_block_between(db, current_user.id, other_id):
            continue
        other_profile = db.query(models.UserProfile).filter(
            models.UserProfile.user_id == other_id
        ).first()
        if _is_discoverable_profile(other_profile):
            eligible_rows.append((match, other_id, other_profile))

    total = len(eligible_rows)
    page = eligible_rows[offset:offset + limit]

    results = []
    for match, other_id, other_profile in page:
        other_user = db.get(models.User, other_id)
        results.append({
            "id": match.id,
            "chat_id": match.chat_id,
            "matched_user": {
                "id": other_user.id if other_user else None,
                "username": other_user.username if other_user else None,
                "full_name": other_user.full_name if other_user else None,
                "bio": other_user.bio if other_user else None,
            },
            "compatibility_score": match.compatibility_score,
            "compatibility_score_status": "legacy_placeholder",
            "profile_alignment": _profile_alignment_payload(match),
            "created_at": match.created_at,
            "age": _profile_age(other_profile) if other_profile else None,
            "city": other_profile.city if other_profile else None,
            "era": other_profile.era if other_profile else None,
            "vibe_tag": other_profile.vibe_tag if other_profile else None,
        })

    return {
        "matches": results,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + limit < total,
    }


@app.get(
    "/api/v1/matches/{match_id}",
    response_model=schemas.MatchDetailResponse
)
def get_match(
    match_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a single match by ID, only if the current user is a participant."""
    _require_verified_profile(db, current_user.id)
    match = db.get(models.Match, match_id)
    if not match:
        raise HTTPException(404, "Match not found")

    if match.user1_id != current_user.id and match.user2_id != current_user.id:
        # Use the same response as not-found so callers cannot enumerate
        # matches belonging to other users.
        raise HTTPException(404, "Match not found")

    if not match.is_active:
        raise HTTPException(410, "Match is no longer active")

    other_id = match.user2_id if match.user1_id == current_user.id else match.user1_id
    if _has_block_between(db, current_user.id, other_id):
        raise HTTPException(404, "Match not found")
    other_user = db.get(models.User, other_id)
    other_profile = db.query(models.UserProfile).filter(
        models.UserProfile.user_id == other_id
    ).first()

    if not _is_discoverable_profile(other_profile):
        raise HTTPException(404, "Match not found")

    return {
        "id": match.id,
        "chat_id": match.chat_id,
        "matched_user": {
            "id": other_user.id if other_user else None,
            "username": other_user.username if other_user else None,
            "full_name": other_user.full_name if other_user else None,
            "bio": other_user.bio if other_user else None,
        },
        "compatibility_score": match.compatibility_score,
        "compatibility_score_status": "legacy_placeholder",
        "profile_alignment": _profile_alignment_payload(match),
        "created_at": match.created_at,
        "age": _profile_age(other_profile) if other_profile else None,
        "city": other_profile.city if other_profile else None,
        "era": other_profile.era if other_profile else None,
        "vibe_tag": other_profile.vibe_tag if other_profile else None,
    }


@app.delete(
    "/api/v1/matches/{match_id}",
    response_model=dict
)
def unmatch(
    match_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Unmatch: deactivate a match without deleting chat history.

    The chat room is preserved for Bugzyme compatibility; only the dating
    match relationship is deactivated. Blocked users cannot re-match through
    this endpoint.
    """
    match = db.get(models.Match, match_id)
    if not match:
        raise HTTPException(404, "Match not found")

    if match.user1_id != current_user.id and match.user2_id != current_user.id:
        raise HTTPException(404, "Match not found")

    if not match.is_active:
        return {"unmatched": True, "already_inactive": True}

    # Do not allow unmatch if the other user has blocked the current user.
    if _has_block_between(db, current_user.id, match.user1_id if match.user2_id == current_user.id else match.user2_id):
        raise HTTPException(403, "Cannot unmatch a user who has blocked you")

    match.is_active = False
    match.unmatched_at = utcnow()
    match.unmatch_reason = "user_unmatched"
    invalidate_chat_ai_notifications(db, match.chat_id)
    db.commit()

    other_id = match.user2_id if match.user1_id == current_user.id else match.user1_id
    spawn(notify_chat_access_revoked(
        match.chat_id,
        {current_user.id, other_id},
        {"type": "match_unmatched", "actor_user_id": current_user.id,
         "other_user_id": other_id, "chat_id": match.chat_id},
    ))

    return {"unmatched": True, "match_id": match.id}


# ============================================================
# FEED ENDPOINT
# ============================================================

def _feed_eligibility_filters(profile: models.UserProfile, today: date) -> list[Any]:
    """SQL equivalents of verified-adult and bilateral gender/era feed gates."""
    try:
        adult_birthdate_cutoff = date(today.year - schemas.AGE_MINIMUM, today.month, today.day)
    except ValueError:  # Feb 29: matches the existing age calculation's calendar comparison.
        adult_birthdate_cutoff = date(today.year - schemas.AGE_MINIMUM, 2, 28)

    filters = [
        models.UserProfile.date_of_birth <= adult_birthdate_cutoff,
        models.UserProfile.is_face_verified.is_(True),
        models.UserProfile.is_id_verified.is_(True),
        models.UserProfile.verification_status == "verified",
    ]

    own_gender_preference = profile.target_gender_preference or "any"
    other_gender_preference = models.UserProfile.target_gender_preference
    own_era_preference = profile.match_era_preference or "any"
    other_era_preference = models.UserProfile.match_era_preference

    if own_gender_preference != "any":
        filters.append(models.UserProfile.gender == own_gender_preference)
    filters.append(or_(
        other_gender_preference.is_(None), other_gender_preference == "",
        other_gender_preference == "any", other_gender_preference == profile.gender,
    ))
    if own_era_preference != "any":
        filters.append(models.UserProfile.era == own_era_preference)
    filters.append(or_(
        other_era_preference.is_(None), other_era_preference == "",
        other_era_preference == "any", other_era_preference == profile.era,
    ))
    return filters


def _feed_block_exists(db: Session, current_user_id: int):
    return db.query(models.UserBlock.id).filter(or_(
        and_(models.UserBlock.blocker_id == current_user_id,
             models.UserBlock.blocked_id == models.User.id),
        and_(models.UserBlock.blocker_id == models.User.id,
             models.UserBlock.blocked_id == current_user_id),
    )).exists()

@app.get(
    "/api/v1/feed",
    response_model=dict
)
def get_feed(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Get a page of eligible candidate profiles.

    Pagination is deterministic: candidates are ordered by a stable composite
    key (compatibility score desc, then user_id asc) so that successive pages
    do not repeat or skip profiles. The response envelope includes the page
    metadata callers need to render infinite-scroll or pager UI.
    """
    # Only a profile approved by the trusted verification path may discover.
    profile = _require_verified_profile(db, current_user.id)

    # One profile per user is guaranteed by uq_user_profile. NOT EXISTS avoids
    # multiplying rows through block/swipe joins and keeps exclusions in SQL.
    eligibility_filters = _feed_eligibility_filters(profile, date.today())
    no_block = ~_feed_block_exists(db, current_user.id)
    eligible_candidate_ids = db.query(models.User.id).join(
        models.UserProfile,
        models.User.id == models.UserProfile.user_id
    ).filter(
        models.User.id != current_user.id,
        *eligibility_filters,
        no_block,
    ).subquery()

    already_swiped = db.query(models.Swipe.id).filter(
        models.Swipe.user_id == current_user.id,
        models.Swipe.target_user_id == models.User.id,
    ).exists()
    required_profiles = db.query(models.User, models.UserProfile).join(
        models.UserProfile,
        models.User.id == models.UserProfile.user_id,
    ).filter(
        models.User.id != current_user.id,
        *eligibility_filters,
        no_block,
        ~already_swiped,
    ).options(
        load_only(models.User.id, models.User.username, models.User.full_name, models.User.bio),
        load_only(
            models.UserProfile.user_id, models.UserProfile.date_of_birth,
            models.UserProfile.gender, models.UserProfile.sexual_orientation,
            models.UserProfile.sexual_orientation_consent, models.UserProfile.city,
            models.UserProfile.era, models.UserProfile.vibe_tag,
            models.UserProfile.target_gender_preference, models.UserProfile.match_era_preference,
            models.UserProfile.is_face_verified, models.UserProfile.is_id_verified,
            models.UserProfile.verification_status,
            models.UserProfile.behavioral_personalization_enabled,
        ),
    )
    eligible_profiles = required_profiles.all()

    try:
        return dating_ml_adapter.rank_feed(
            db,
            authenticated_user=current_user,
            user_profile=profile,
            eligible_rows=eligible_profiles,
            swiped_ids=set(),  # Exclusion has already occurred in SQL.
            limit=limit,
            offset=offset,
            eligible_candidate_ids=eligible_candidate_ids,
        )
    except Exception as exc:
        logger.exception("Dating ML feed ranking failed")
        raise HTTPException(status_code=503, detail="Matching service is temporarily unavailable") from exc
