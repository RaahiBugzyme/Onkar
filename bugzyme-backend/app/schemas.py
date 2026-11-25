from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
USERNAME_PATTERN = r"^[A-Za-z0-9_.-]+$"
MAX_MESSAGE_LEN = 2000
MODEL_ORIENTATION_VALUES = {
    "straight", "heterosexual", "gay", "lesbian", "homosexual", "bisexual", "bi"
}


def validate_model_orientation(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    if normalized not in MODEL_ORIENTATION_VALUES:
        raise ValueError("sexual_orientation must be a value supported by matching")
    return normalized


class _FromOrm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _none_to_false(v):
    return bool(v)


# ---------- users ----------
class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=30, pattern=USERNAME_PATTERN)
    email: str = Field(max_length=254, pattern=EMAIL_PATTERN)
    password: str = Field(min_length=8, max_length=128)


class UserPublic(_FromOrm):
    id: int
    username: str
    full_name: str | None = None
    bio: str | None = None
    is_online: bool = False
    last_seen: datetime | None = None
    photo_url: str | None = None
    photos: list[str] = Field(default_factory=list)

    _fix_online = field_validator("is_online", mode="before")(_none_to_false)


class UserResponse(UserPublic):
    email: str
    phone_number: str | None = None
    auth_provider: str = "local"
    ai_memory_enabled: bool = False
    ai_provider_processing_enabled: bool = False
    activity_status_enabled: bool = True


class UserProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=80)
    bio: str | None = Field(default=None, max_length=500)
    ai_memory_enabled: bool | None = None
    ai_provider_processing_enabled: bool | None = None


class AISuggestionEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal["viewed", "selected", "edited", "sent", "user_feedback"]
    event_key: str = Field(min_length=1, max_length=100)
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_key")
    @classmethod
    def validate_event_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("event_key must not be blank")
        return value.strip()

    @field_validator("details")
    @classmethod
    def bound_event_details(cls, value: dict[str, Any]) -> dict[str, Any]:
        import json
        if len(value) > 4 or len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 2048:
            raise ValueError("details exceed the allowed size")
        return value

    @model_validator(mode="after")
    def allowlist_event_details(self):
        allowed = {
            "viewed": set(),
            "selected": set(),
            "edited": {"changed"},
            "sent": {"message_id", "edited"},
            "user_feedback": {"rating"},
        }[self.event_type]
        if set(self.details) - allowed:
            raise ValueError("details contain unsupported fields")
        if self.event_type == "edited" and "changed" in self.details and not isinstance(self.details["changed"], bool):
            raise ValueError("changed must be a boolean")
        if self.event_type == "sent":
            message_id = self.details.get("message_id")
            if isinstance(message_id, bool) or not isinstance(message_id, int) or message_id <= 0:
                raise ValueError("message_id must be a positive integer")
            if "edited" in self.details and not isinstance(self.details["edited"], bool):
                raise ValueError("edited must be a boolean")
        if self.event_type == "user_feedback" and self.details.get("rating") not in {"helpful", "not_helpful"}:
            raise ValueError("rating must be helpful or not_helpful")
        return self


class UserMemoryResponse(_FromOrm):
    id: int
    memory_text: str
    memory_type: str
    confidence: float
    created_at: datetime


class UserMemoryUpdate(BaseModel):
    memory_text: str = Field(min_length=3, max_length=500)


class PresencePreferenceUpdate(BaseModel):
    activity_status_enabled: bool


class PresencePreferenceResponse(BaseModel):
    activity_status_enabled: bool
    is_online: bool
    last_seen: datetime | None = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- extended auth: google, phone, password reset ----------
PHONE_PATTERN = r"^\+[1-9]\d{6,14}$"


class GoogleAuthUrlResponse(BaseModel):
    authorization_url: str
    state: str


class GoogleCallbackRequest(BaseModel):
    code: str | None = None
    code_verifier: str | None = None
    state: str | None = None
    id_token: str | None = None


class PhoneSendOtpRequest(BaseModel):
    phone_number: str = Field(pattern=PHONE_PATTERN, description="E.164 phone number, e.g. +919876543210")


class PhoneVerifyOtpRequest(BaseModel):
    phone_number: str = Field(pattern=PHONE_PATTERN)
    otp: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    full_name: str | None = Field(default=None, max_length=80)
    username: str | None = Field(default=None, min_length=3, max_length=30, pattern=USERNAME_PATTERN)


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
    is_new_user: bool = False


class PasswordResetSendOtpRequest(BaseModel):
    email: str = Field(max_length=254, pattern=EMAIL_PATTERN)


class PasswordResetVerifyOtpRequest(BaseModel):
    email: str = Field(max_length=254, pattern=EMAIL_PATTERN)
    otp: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    new_password: str = Field(min_length=8, max_length=128)


class PasswordResetSendLinkRequest(BaseModel):
    email: str = Field(max_length=254, pattern=EMAIL_PATTERN)


class PasswordResetConfirmLinkRequest(BaseModel):
    token: str = Field(min_length=16, max_length=128)
    email: str = Field(max_length=254, pattern=EMAIL_PATTERN)
    new_password: str = Field(min_length=8, max_length=128)


class AuthMessageResponse(BaseModel):
    message: str
    success: bool = True


# ---------- chats / messages ----------
class ChatCreate(BaseModel):
    user2_id: int


class ChatResponse(_FromOrm):
    id: int
    user1_id: int
    user2_id: int


class MessageCreate(BaseModel):
    chat_id: int
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_LEN)
    reply_to_id: int | None = None

    @field_validator("content")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Message cannot be empty")
        return v


class MessageReactionResponse(_FromOrm):
    user_id: int
    reaction: str


class MessageResponse(_FromOrm):
    id: int
    chat_id: int
    sender_id: int
    content: str | None = None
    created_at: datetime | None = None
    read_at: datetime | None = None
    is_delivered: bool = False
    is_read: bool = False
    is_deleted: bool = False
    reply_to_id: int | None = None

    # Voice message support
    message_type: str = "text"
    audio_url: str | None = None
    audio_duration: int | None = None
    audio_mime_type: str | None = None

    # Photo and document attachment metadata (never includes a storage path).
    attachment_name: str | None = None
    attachment_mime_type: str | None = None
    attachment_size_bytes: int | None = None
    reactions: list[MessageReactionResponse] = Field(default_factory=list)
    reaction_revision: int = 0

    _fix_delivered = field_validator(
        "is_delivered",
        mode="before"
    )(_none_to_false)

    _fix_read = field_validator(
        "is_read",
        mode="before"
    )(_none_to_false)

    _fix_deleted = field_validator(
        "is_deleted",
        mode="before"
    )(_none_to_false)

class MessageDelete(BaseModel):
    for_everyone: bool = True


class ChatSummary(BaseModel):
    chat_id: int
    user: UserPublic
    last_message: MessageResponse | None = None
    unread_count: int = 0


# ---------- dating domain ----------

AGE_MINIMUM = 18
ERAS = ["genz", "zillenial", "millennial"]
GENDERS = ["male", "female", "nonbinary", "other", "prefer_not_to_say"]
VERIFICATION_STATUSES = ["unverified", "pending", "verified", "rejected"]


def validate_minimum_age(value: str) -> str:
    """Validate that the date of birth makes the user at least 18 years old."""
    try:
        dob = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("date_of_birth must be a valid ISO date (YYYY-MM-DD)")

    today = date.today()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    if age < AGE_MINIMUM:
        raise ValueError(f"User must be at least {AGE_MINIMUM} years old")
    if age > 120:
        raise ValueError("Invalid date_of_birth: age cannot exceed 120 years")
    return value


def validate_era(value: str) -> str:
    """Validate era is one of the allowed values."""
    if value not in ERAS:
        raise ValueError(f"era must be one of: {', '.join(ERAS)}")
    return value


def validate_gender(value: str) -> str:
    """Validate gender is one of the allowed values."""
    if value not in GENDERS:
        raise ValueError(f"gender must be one of: {', '.join(GENDERS)}")
    return value


def validate_verification_status(value: str) -> str:
    """Validate verification status is one of the allowed values."""
    if value not in VERIFICATION_STATUSES:
        raise ValueError(f"verification_status must be one of: {', '.join(VERIFICATION_STATUSES)}")
    return value


class DatingProfileCreate(BaseModel):
    date_of_birth: str
    gender: str
    sexual_orientation: str | None = Field(
        default=None,
        description="Optional and voluntary. Used for mutual matching eligibility only after you explicitly consent.",
    )
    target_gender_preference: str = "any"
    city: str = Field(max_length=60)
    era: str = "genz"
    vibe_tag: str | None = Field(default=None, max_length=60)
    match_era_preference: str = "any"
    full_name: str | None = Field(default=None, max_length=80)
    bio: str | None = Field(default=None, max_length=500)
    profession: str | None = Field(default=None, max_length=100)
    education: str | None = Field(default=None, max_length=100)
    relationship_intentions: str | None = Field(default=None, max_length=60)
    interests: list[str] | None = Field(default=None)

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, v: str) -> str:
        return validate_minimum_age(v)

    @field_validator("gender")
    @classmethod
    def validate_gender_field(cls, v: str) -> str:
        return validate_gender(v)

    @field_validator("sexual_orientation")
    @classmethod
    def validate_orientation_field(cls, value: str | None) -> str | None:
        return validate_model_orientation(value)

    @field_validator("era")
    @classmethod
    def validate_era_field(cls, v: str) -> str:
        return validate_era(v)


class DatingProfileUpdate(BaseModel):
    date_of_birth: str | None = Field(default=None)
    gender: str | None = Field(default=None)
    sexual_orientation: str | None = Field(
        default=None,
        description="Optional and voluntary. Used for mutual matching eligibility only after you explicitly consent.",
    )
    target_gender_preference: str | None = Field(default=None)
    city: str | None = Field(default=None, max_length=60)
    era: str | None = Field(default=None)
    vibe_tag: str | None = Field(default=None, max_length=60)
    match_era_preference: str | None = Field(default=None)
    full_name: str | None = Field(default=None, max_length=80)
    bio: str | None = Field(default=None, max_length=500)
    profession: str | None = Field(default=None, max_length=100)
    education: str | None = Field(default=None, max_length=100)
    relationship_intentions: str | None = Field(default=None, max_length=60)
    interests: list[str] | None = Field(default=None)

    @model_validator(mode="before")
    @classmethod
    def reject_verification_fields(cls, values):
        if isinstance(values, dict):
            protected_fields = {"is_face_verified", "is_id_verified", "verification_status"}
            attempted_fields = protected_fields.intersection(values)
            if attempted_fields:
                names = ", ".join(sorted(attempted_fields))
                raise ValueError(f"Verification fields are server-controlled: {names}")
        return values

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def validate_dob(cls, v: str) -> str:
        if v is None:
            return v
        return validate_minimum_age(v)

    @field_validator("gender")
    @classmethod
    def validate_gender_field(cls, v: str) -> str:
        if v is None:
            return v
        return validate_gender(v)

    @field_validator("sexual_orientation")
    @classmethod
    def validate_orientation_field(cls, value: str | None) -> str | None:
        return validate_model_orientation(value)

    @field_validator("era")
    @classmethod
    def validate_era_field(cls, v: str) -> str:
        if v is None:
            return v
        return validate_era(v)


class ProfilePhotoResponse(BaseModel):
    """Response for profile photo operations."""
    id: int
    photo_url: str
    is_primary: bool = False
    display_order: int = 0

    model_config = ConfigDict(from_attributes=True)


class ProfilePhotosReorderRequest(BaseModel):
    """Request payload to reorder profile photos."""
    photo_ids: list[int]


class DatingProfileResponse(_FromOrm):
    id: int
    user_id: int
    date_of_birth: str | date | None = None  # Formatted as string (year-only or ISO YYYY-MM-DD)
    gender: str
    sexual_orientation: str | None = None
    sexual_orientation_consent: bool = False
    sexual_orientation_consent_version: str | None = None
    sexual_orientation_consent_at: datetime | None = None
    sexual_orientation_consent_revoked_at: datetime | None = None
    behavioral_personalization_enabled: bool = False
    behavioral_personalization_consent_version: str | None = None
    behavioral_personalization_consent_at: datetime | None = None
    behavioral_personalization_consent_revoked_at: datetime | None = None
    city: str
    era: str
    vibe_tag: str | None = None
    match_era_preference: str
    is_face_verified: bool
    is_id_verified: bool
    verification_status: str
    full_name: str | None = None
    bio: str | None = None
    profession: str | None = None
    education: str | None = None
    relationship_intentions: str | None = None
    interests: list[str] = Field(default_factory=list)
    photos: list[ProfilePhotoResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def format_dob(cls, v):
        if v is None:
            return None
        if isinstance(v, (date, datetime)):
            return v.isoformat()
        return str(v)


class ConsentUpdate(BaseModel):
    consent: bool


class ConsentStatus(BaseModel):
    consent: bool
    version: str | None
    updated_at: datetime | None
    disclosure: str


class MatchingPrivacySettingsResponse(BaseModel):
    sexual_orientation: str | None
    orientation_matching: ConsentStatus
    behavioral_personalization: ConsentStatus


class SwipeCreate(BaseModel):
    target_user_id: int
    action: str  # 'like', 'pass', 'superlike'


class MatchedUserSummary(BaseModel):
    id: int
    username: str
    full_name: str | None = None
    bio: str | None = None
    photo_url: str | None = None
    photos: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ProfileAlignmentResponse(BaseModel):
    """Nullable deterministic profile alignment; it is not a success probability."""

    score: float | None = Field(default=None, description="Deterministic profile-alignment score, not a success probability.")
    confidence: float | None = None
    adjusted_score: float | None = None
    package_version: str | None = None
    engine_version: str | None = None
    provenance: str | None = None
    eligibility_status: bool | None = None
    eligibility_reason: str | None = None
    explanation: dict | list | str | None = None
    components: dict | list | None = None
    score_type: Literal["profile_alignment"] = "profile_alignment"
    is_success_probability: Literal[False] = False
    weights_validated: bool = False


class MatchDetail(BaseModel):
    id: int
    chat_id: int
    matched_user: MatchedUserSummary
    compatibility_score: int = Field(description="Legacy placeholder value; consult compatibility_score_status.")
    compatibility_score_status: Literal["legacy_placeholder"]
    profile_alignment: ProfileAlignmentResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class MatchDetailResponse(MatchDetail):
    created_at: datetime
    age: int | None = None
    city: str | None = None
    era: str | None = None
    vibe_tag: str | None = None
    profession: str | None = None
    education: str | None = None
    relationship_intentions: str | None = None
    interests: list[str] = Field(default_factory=list)
    photos: list[str] = Field(default_factory=list)


class SwipeResponse(_FromOrm):
    id: int
    user_id: int
    target_user_id: int
    action: str
    created_at: datetime
    is_match: bool | None = False
    match: MatchDetail | None = None

    model_config = ConfigDict(from_attributes=True)


class MatchResponse(_FromOrm):
    id: int
    user1_id: int
    user2_id: int
    chat_id: int
    compatibility_score: int
    is_active: bool
    unmatched_at: datetime | None = None
    unmatch_reason: str | None = None

    model_config = ConfigDict(from_attributes=True)


class MatchListUser(BaseModel):
    id: int | None = None
    username: str | None = None
    full_name: str | None = None
    bio: str | None = None
    photo_url: str | None = None
    photos: list[str] = Field(default_factory=list)


class MatchListItem(BaseModel):
    id: int
    chat_id: int
    matched_user: MatchListUser
    compatibility_score: int = Field(description="Legacy placeholder value; consult compatibility_score_status.")
    compatibility_score_status: Literal["legacy_placeholder"]
    profile_alignment: ProfileAlignmentResponse | None = None
    created_at: datetime
    age: int | None = None
    city: str | None = None
    era: str | None = None
    vibe_tag: str | None = None
    profession: str | None = None
    education: str | None = None
    relationship_intentions: str | None = None
    interests: list[str] = Field(default_factory=list)
    photos: list[str] = Field(default_factory=list)


class MatchListResponse(BaseModel):
    matches: list[MatchListItem]
    total: int
    limit: int
    offset: int
    has_more: bool


class BlockCreate(BaseModel):
    blocked_id: int


class BlockResponse(_FromOrm):
    id: int
    blocker_id: int
    blocked_id: int

    model_config = ConfigDict(from_attributes=True)


class BlockedUserItem(BaseModel):
    id: int
    user_id: int
    username: str
    full_name: str | None = None
    photo_url: str | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ReportCreate(BaseModel):
    reported_id: int
    reason: str
    details: str | None = None


class ReportResponse(_FromOrm):
    id: int
    reporter_id: int
    reported_id: int
    reason: str
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserVerificationCreate(BaseModel):
    verification_type: str  # 'face', 'id_college', 'id_work', 'id_govt'
    status: str  # 'passed', 'failed'


class UserVerificationResponse(_FromOrm):
    id: int
    user_id: int
    verification_type: str
    status: str
    reviewed_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VerificationDecision(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=5, max_length=500)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 5:
            raise ValueError("A brief review reason is required")
        return value


class PublicProfileResponse(BaseModel):
    """Minimal public profile data required by the dating experience."""
    user_id: int
    username: str
    full_name: str | None = None
    age: int | None = None
    city: str | None = None
    era: str | None = None
    vibe_tag: str | None = None
    bio: str | None = None
    profession: str | None = None
    education: str | None = None
    relationship_intentions: str | None = None
    interests: list[str] = Field(default_factory=list)
    photos: list[str] = Field(default_factory=list)
    compatibility_score: int | None = None


class SearchCandidateResponse(BaseModel):
    user_id: int
    username: str
    full_name: str | None = None
    age: int | None = None
    city: str | None = None
    era: str | None = None
    vibe_tag: str | None = None
    bio: str | None = None
    profession: str | None = None
    education: str | None = None
    relationship_intentions: str | None = None
    interests: list[str] = Field(default_factory=list)
    photos: list[str] = Field(default_factory=list)
    photo_url: str | None = None
    is_verified: bool = True
    shared_interests: list[str] = Field(default_factory=list)
    shared_interests_count: int = 0
    relevance_score: float = 0.0


class SearchListResponse(BaseModel):
    results: list[SearchCandidateResponse]
    total: int
    limit: int
    offset: int
    has_more: bool
