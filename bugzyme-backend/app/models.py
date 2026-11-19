
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    Date,
    text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    username = Column(
        String(30),
        unique=True,
        index=True,
        nullable=False
    )

    full_name = Column(
        String(80),
        nullable=True
    )

    bio = Column(
        Text,
        nullable=True
    )

    email = Column(
        String(254),
        unique=True,
        index=True,
        nullable=False
    )

    hashed_password = Column(
        String,
        nullable=False
    )

    is_online = Column(
        Boolean,
        default=False,
        nullable=False
    )

    activity_status_enabled = Column(
        Boolean,
        default=True,
        nullable=False,
        server_default=text("true"),
    )

    last_seen = Column(
        DateTime,
        nullable=True
    )

    # Personal AI memory is opt-in and private to this account.
    ai_memory_enabled = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    ai_memory_processed_through_message_id = Column(Integer, nullable=True)
    # Separate explicit consent for sending chat-derived content to Groq.
    ai_provider_processing_enabled = Column(Boolean, nullable=False, default=False, server_default=text("false"))

    phone_number = Column(
        String(30),
        unique=True,
        index=True,
        nullable=True,
    )

    auth_provider = Column(
        String(30),
        nullable=False,
        default="local",
        server_default=text("'local'"),
    )

    chats_as_user1 = relationship(
        "Chat",
        foreign_keys="Chat.user1_id",
        back_populates="user1",
    )

    chats_as_user2 = relationship(
        "Chat",
        foreign_keys="Chat.user2_id",
        back_populates="user2",
    )

    sent_messages = relationship(
        "Message",
        foreign_keys="Message.sender_id",
        back_populates="sender",
    )


class Chat(Base):
    __tablename__ = "chats"

    __table_args__ = (
        UniqueConstraint(
            "user1_id",
            "user2_id",
            name="uq_chat_users"
        ),

        Index(
            "ix_chats_user1",
            "user1_id"
        ),

        Index(
            "ix_chats_user2",
            "user2_id"
        ),
    )

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    user1_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    user2_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    # ========================================
    # Per-user conversation deletion
    # ========================================

    deleted_by_user1 = Column(
        Boolean,
        default=False,
        nullable=False
    )

    deleted_by_user2 = Column(
        Boolean,
        default=False,
        nullable=False
    )


    # ========================================
    # Relationships
    # ========================================

    user1 = relationship(
        "User",
        foreign_keys=[user1_id],
        back_populates="chats_as_user1",
    )

    user2 = relationship(
        "User",
        foreign_keys=[user2_id],
        back_populates="chats_as_user2",
    )

    messages = relationship(
        "Message",
        back_populates="chat",
        cascade="all, delete-orphan",
    )


class Message(Base):
    __tablename__ = "messages"

    __table_args__ = (
        Index(
            "ix_messages_chat_id_id",
            "chat_id",
            "id"
        ),

        Index(
            "ix_messages_unread",
            "chat_id",
            "sender_id",
            "is_read"
        ),

        Index(
            "ix_messages_undelivered",
            "chat_id",
            "sender_id",
            "is_delivered"
        ),
    )

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    chat_id = Column(
        Integer,
        ForeignKey("chats.id"),
        nullable=False,
        index=True
    )

    sender_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    content = Column(
        String(2000),
        nullable=True
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    is_delivered = Column(
        Boolean,
        default=False,
        nullable=False
    )

    is_read = Column(
        Boolean,
        default=False,
        nullable=False
    )

    read_at = Column(
        DateTime,
        nullable=True
    )

    # ========================================
    # Delete message support
    # ========================================

    is_deleted = Column(
        Boolean,
        default=False,
        nullable=False
    )

    deleted_at = Column(
        DateTime,
        nullable=True
    )

    # ========================================
    # Reply support
    # ========================================

    reply_to_id = Column(
        Integer,
        ForeignKey("messages.id"),
        nullable=True,
        index=True
    )

    # ========================================
    # Voice message support
    # ========================================

    message_type = Column(
        String(20),
        default="text",
        nullable=False
    )

    audio_url = Column(
        String(500),
        nullable=True
    )

    audio_duration = Column(
        Integer,
        nullable=True
    )

    audio_mime_type = Column(
        String(100),
        nullable=True
    )

    # Photo and document attachment metadata. The file itself is stored
    # outside the public uploads directory and addressed by a generated key.
    attachment_storage_key = Column(
        String(64),
        nullable=True
    )

    attachment_name = Column(
        String(255),
        nullable=True
    )

    attachment_mime_type = Column(
        String(100),
        nullable=True
    )

    attachment_size_bytes = Column(
        Integer,
        nullable=True
    )

    reaction_revision = Column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    # ========================================
    # Relationships
    # ========================================

    chat = relationship(
        "Chat",
        back_populates="messages"
    )

    sender = relationship(
        "User",
        foreign_keys=[sender_id],
        back_populates="sent_messages"
    )

    reply_to = relationship(
        "Message",
        remote_side=[id],
        foreign_keys=[reply_to_id],
        backref="replies"
    )

    reactions = relationship(
        "MessageReaction",
        back_populates="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class MessageReaction(Base):
    __tablename__ = "message_reactions"

    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "user_id",
            name="uq_message_reaction_user",
        ),
        CheckConstraint(
            "reaction IN ('❤️', '😂', '👍', '🔥', '😮', '😢')",
            name="ck_message_reaction_allowed",
        ),
    )

    id = Column(Integer, primary_key=True)
    message_id = Column(
        Integer,
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    reaction = Column(String(16), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    message = relationship("Message", back_populates="reactions")



class UserMemory(Base):
    __tablename__ = "user_memories"

    __table_args__ = (
        Index("ix_user_memories_user_id", "user_id"),
        Index("ix_user_memories_user_type", "user_id", "memory_type"),
    )

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    memory_text = Column(Text, nullable=False)

    memory_type = Column(
        String(30),
        nullable=False,
        default="general",
    )

    confidence = Column(
        Float,
        nullable=False,
        default=0.8,
    )

    source_message_id = Column(
        Integer,
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )

    # 384-dimensional multilingual embedding
    embedding = Column(Vector(384), nullable=True)

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


class DeathZoneConversationState(Base):
    """Current conversation episode state used to deduplicate notifications."""

    __tablename__ = "death_zone_conversation_states"

    chat_id = Column(Integer, ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True)
    active = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    target_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    last_message_id = Column(Integer, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class DeathZoneNotification(Base):
    """A chat-specific, target-user-only AI suggestion notification."""

    __tablename__ = "death_zone_notifications"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", "event_key", name="uq_death_zone_user_event"),
        Index("ix_death_zone_user_state", "user_id", "status", "expires_at"),
        Index("ix_death_zone_chat_event", "chat_id", "event_key"),
    )

    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_key = Column(String(100), nullable=False)
    trigger_message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(20), nullable=False, default="generating", server_default="generating")
    suggestions_json = Column(Text, nullable=True)
    death_zone_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    viewed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)


class AIRecoveryIntervention(Base):
    """One bounded recovery episode owned by its target user and chat."""
    __tablename__ = "ai_recovery_interventions"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", "trigger_message_id", name="uq_ai_recovery_trigger"),
        Index("ix_ai_recovery_chat_user", "chat_id", "user_id", "created_at"),
    )
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    trigger_message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    recovery_reason = Column(String(80), nullable=False)
    strategy = Column(String(60), nullable=False)
    prompt_version = Column(String(40), nullable=False)
    status = Column(String(20), nullable=False, default="generated", server_default="generated")
    outcome_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    evaluated_at = Column(DateTime, nullable=True)


class AISuggestionRecord(Base):
    """Private suggestion metadata; text stays in existing notification/API flow."""
    __tablename__ = "ai_suggestion_records"
    __table_args__ = (
        Index("ix_ai_suggestion_chat_user", "chat_id", "user_id", "created_at"),
    )
    id = Column(Integer, primary_key=True)
    intervention_id = Column(Integer, ForeignKey("ai_recovery_interventions.id", ondelete="SET NULL"), nullable=True)
    chat_id = Column(Integer, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    suggestion_hash = Column(String(64), nullable=False)
    strategy = Column(String(60), nullable=False)
    prompt_version = Column(String(40), nullable=False)
    model_id = Column(String(100), nullable=False)
    validation_passed = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AISuggestionEvent(Base):
    """Append-only lifecycle events, scoped to the owning user and chat."""
    __tablename__ = "ai_suggestion_events"
    __table_args__ = (
        UniqueConstraint("suggestion_id", "event_key", name="uq_ai_suggestion_event_key"),
        Index("ix_ai_suggestion_event_chat_user", "chat_id", "user_id", "event_type"),
    )
    id = Column(Integer, primary_key=True)
    suggestion_id = Column(Integer, ForeignKey("ai_suggestion_records.id", ondelete="CASCADE"), nullable=False)
    chat_id = Column(Integer, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_key = Column(String(100), nullable=False)
    event_type = Column(String(32), nullable=False)
    details_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


# ========================================
# Dating Domain Models
# ========================================


class UserProfile(Base):
    """Extended dating profile data for each user."""
    __tablename__ = "user_profiles"

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_profile"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    date_of_birth = Column(Date, nullable=False)
    gender = Column(String(30), nullable=False)
    # Voluntary private field. The dating model uses it only after explicit consent.
    sexual_orientation = Column(String(30), nullable=True)
    sexual_orientation_consent = Column(Boolean, nullable=False, server_default=text("false"))
    sexual_orientation_consent_version = Column(String(40), nullable=True)
    sexual_orientation_consent_at = Column(DateTime(timezone=True), nullable=True)
    sexual_orientation_consent_revoked_at = Column(DateTime(timezone=True), nullable=True)
    # Kept independent from orientation and AI-memory consent; off by default.
    behavioral_personalization_enabled = Column(Boolean, nullable=False, server_default=text("false"))
    behavioral_personalization_consent_version = Column(String(40), nullable=True)
    behavioral_personalization_consent_at = Column(DateTime(timezone=True), nullable=True)
    behavioral_personalization_consent_revoked_at = Column(DateTime(timezone=True), nullable=True)
    target_gender_preference = Column(String(30), nullable=False, server_default="any")
    city = Column(String(60), nullable=False)
    era = Column(String(20), nullable=False, server_default="genz") # 'genz', 'zillenial', 'millennial'
    vibe_tag = Column(String(60), nullable=True)             # e.g., 'Situationship', 'Talking stage'
    match_era_preference = Column(String(20), nullable=False, server_default="any")
    is_face_verified = Column(Boolean, nullable=False, server_default=text("false"))
    is_id_verified = Column(Boolean, nullable=False, server_default=text("false"))
    verification_status = Column(String(20), nullable=False, server_default="unverified") # 'unverified', 'pending', 'verified', 'rejected'
    profession = Column(String(100), nullable=True)
    education = Column(String(100), nullable=True)
    relationship_intentions = Column(String(60), nullable=True)
    interests = Column(JSON, nullable=True, default=list)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    photos = relationship(
        "ProfilePhoto",
        backref="profile",
        cascade="all, delete-orphan",
        order_by="ProfilePhoto.display_order",
        lazy="selectin",
    )


class ProfilePhoto(Base):
    """Ordered profile pictures associated with a UserProfile."""
    __tablename__ = "profile_photos"

    __table_args__ = (
        Index("ix_profile_photos_profile_id", "profile_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    storage_key = Column(String(64), nullable=False)
    photo_url = Column(String(255), nullable=False)
    display_order = Column(Integer, nullable=False, server_default="0")
    is_primary = Column(Boolean, nullable=False, server_default=text("false"))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Swipe(Base):
    """User swipe actions (like, pass, superlike)."""
    __tablename__ = "swipes"

    __table_args__ = (
        UniqueConstraint("user_id", "target_user_id", name="uq_user_target_swipe"),
        CheckConstraint("action IN ('like', 'pass', 'superlike')", name="ck_swipe_action_valid"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    target_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(20), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Match(Base):
    """Confirmed mutual match linked to a chat room."""
    __tablename__ = "matches"

    __table_args__ = (
        UniqueConstraint("user1_id", "user2_id", name="uq_match_user_pair"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user1_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    user2_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, unique=True)
    compatibility_score = Column(Integer, nullable=False, server_default="85") # 0-100%
    # Genuine model output is stored separately; compatibility_score remains legacy-only.
    raw_compatibility_score = Column(Numeric(7, 4), nullable=True)
    confidence_score = Column(Numeric(7, 4), nullable=True)
    adjusted_score = Column(Numeric(7, 4), nullable=True)
    model_version = Column(String(80), nullable=True)
    eligibility_status = Column(Boolean, nullable=True)
    eligibility_reason = Column(Text, nullable=True)
    explanation = Column(JSON, nullable=True)
    component_scores = Column(JSON, nullable=True)
    prediction_provenance = Column(String(40), nullable=True, default="legacy", server_default="legacy")
    calculated_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    unmatched_at = Column(DateTime, nullable=True)
    unmatch_reason = Column(String(100), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class UserBlock(Base):
    """Blocks one user from another."""
    __tablename__ = "user_blocks"

    __table_args__ = (
        UniqueConstraint("blocker_id", "blocked_id", name="uq_blocker_blocked_pair"),
    )

    id = Column(Integer, primary_key=True, index=True)
    blocker_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    blocked_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class UserReport(Base):
    """Moderation reports filed by users."""
    __tablename__ = "user_reports"

    __table_args__ = (
        Index("ix_user_reports_reporter_id", "reporter_id"),
        Index("ix_user_reports_reported_id", "reported_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    reporter_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reported_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reason = Column(String(100), nullable=False)
    details = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, server_default="pending") # 'pending', 'reviewed', 'actioned'
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class UserVerification(Base):
    """Verification history and logs per user."""
    __tablename__ = "user_verifications"

    __table_args__ = (
        Index("ix_user_verifications_user_id", "user_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    verification_type = Column(String(30), nullable=False) # 'face', 'id_college', 'id_work', 'id_govt'
    status = Column(String(20), nullable=False) # 'passed', 'failed'
    details_json = Column(Text, nullable=True)
    reviewed_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AuthVerificationCode(Base):
    """Secure OTP verification codes and password reset tokens."""
    __tablename__ = "auth_verification_codes"

    __table_args__ = (
        Index("ix_auth_codes_identifier_purpose", "identifier", "purpose"),
    )

    id = Column(Integer, primary_key=True, index=True)
    identifier = Column(String(254), nullable=False, index=True)  # Email or E.164 phone number
    purpose = Column(String(50), nullable=False)  # 'phone_otp', 'password_reset_otp', 'password_reset_link'
    code_hash = Column(String(128), nullable=False)  # SHA-256 hash of code/token
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    attempts = Column(Integer, nullable=False, default=0, server_default=text("0"))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
