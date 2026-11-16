"""Fail-closed consent and bounded resource controls for external AI calls."""
from __future__ import annotations

from collections import defaultdict, deque
from contextlib import contextmanager
from contextvars import ContextVar, Token
import os
import re
import threading
import time
from typing import Callable, Iterator


class AIProviderConsentRequired(PermissionError):
    """Raised when current explicit consent is absent or has been revoked."""


class AIProviderUnavailable(RuntimeError):
    """Safe, provider-neutral failure for timeout, overload, or provider outage."""


_consent_guard: ContextVar[Callable[[], bool] | None] = ContextVar(
    "raahi_ai_provider_consent_guard", default=None
)

_WINDOW_SECONDS = 60.0
_MANUAL_USER_LIMIT = 5
_MANUAL_CHAT_LIMIT = 10
_EVENT_USER_LIMIT = 120
_EVENT_CHAT_LIMIT = 300
_rate_lock = threading.Lock()
_rate_events: dict[tuple[str, int], deque[float]] = defaultdict(deque)

try:
    _MAX_CONCURRENT_CALLS = max(1, min(16, int(os.getenv("GROQ_MAX_CONCURRENT_CALLS", "4"))))
except ValueError:
    _MAX_CONCURRENT_CALLS = 4
try:
    _CONCURRENCY_WAIT_SECONDS = max(0.1, min(10.0, float(os.getenv("GROQ_CONCURRENCY_WAIT_SECONDS", "2"))))
except ValueError:
    _CONCURRENCY_WAIT_SECONDS = 2.0

_provider_slots = threading.BoundedSemaphore(_MAX_CONCURRENT_CALLS)
_SECRET_LABEL_PATTERN = re.compile(
    r"(?i)\b(password|passcode|otp|one[- ]time code|api key|secret|token)\s*[:=]\s*[^\s,;]+"
)
_NATIONAL_ID_PATTERN = re.compile(r"\b(?:\d[ -]?){11}\d\b")
_PAN_PATTERN = re.compile(r"(?i)\b[A-Z]{5}\d{4}[A-Z]\b")
_LABELED_ID_PATTERN = re.compile(
    r"(?i)\b(?:aadhaar|aadhar|pan|passport|government id|national id)\s*(?:number|no\.?|#)?\s*[:=]?\s*[A-Z0-9 -]{5,20}"
)


def reset_ai_rate_limits() -> None:
    """Clear in-memory buckets; used by isolated test fixtures only."""
    with _rate_lock:
        _rate_events.clear()


def sanitize_provider_text(value: str) -> str:
    """Redact obvious credentials and government-ID patterns from chat text."""
    if not isinstance(value, str) or not value:
        return ""
    redacted = _SECRET_LABEL_PATTERN.sub(r"\1: [redacted]", value)
    redacted = _LABELED_ID_PATTERN.sub("[redacted ID]", redacted)
    redacted = _PAN_PATTERN.sub("[redacted ID]", redacted)
    return _NATIONAL_ID_PATTERN.sub("[redacted ID]", redacted)


@contextmanager
def provider_consent_scope(guard: Callable[[], bool]) -> Iterator[None]:
    token: Token = _consent_guard.set(guard)
    try:
        assert_provider_consent()
        yield
    finally:
        _consent_guard.reset(token)


def assert_provider_consent() -> None:
    guard = _consent_guard.get()
    if guard is None or not guard():
        raise AIProviderConsentRequired("Explicit AI provider-processing consent is required")


def provider_completion(client, **kwargs):
    """Make one bounded Groq call, rechecking consent just before each attempt."""
    if not _provider_slots.acquire(timeout=_CONCURRENCY_WAIT_SECONDS):
        raise AIProviderUnavailable("AI provider is temporarily busy")
    try:
        for attempt in range(2):
            assert_provider_consent()
            try:
                return client.chat.completions.create(**kwargs)
            except Exception as exc:
                name = type(exc).__name__
                status_code = getattr(exc, "status_code", None)
                retryable = (
                    name in {"APITimeoutError", "APIConnectionError", "RateLimitError", "InternalServerError"}
                    or status_code == 429
                    or (isinstance(status_code, int) and status_code >= 500)
                )
                if attempt == 0 and retryable:
                    time.sleep(0.2)
                    continue
                raise AIProviderUnavailable("AI provider request failed") from exc
        raise AIProviderUnavailable("AI provider request failed")
    finally:
        _provider_slots.release()


def enforce_ai_rate_limit(
    user_id: int,
    chat_id: int,
    *,
    operation: str = "manual",
) -> None:
    """Apply process-local fixed-window limits to manual AI and lifecycle calls."""
    if operation == "events":
        user_limit, chat_limit = _EVENT_USER_LIMIT, _EVENT_CHAT_LIMIT
    else:
        user_limit, chat_limit = _MANUAL_USER_LIMIT, _MANUAL_CHAT_LIMIT
    now = time.monotonic()
    keys = ((f"{operation}:user", user_id), (f"{operation}:chat", chat_id))
    with _rate_lock:
        for existing_key, entries in list(_rate_events.items()):
            while entries and now - entries[0] >= _WINDOW_SECONDS:
                entries.popleft()
            if not entries:
                _rate_events.pop(existing_key, None)
        for key in keys:
            entries = _rate_events[key]
            limit = user_limit if key[0].endswith("user") else chat_limit
            if len(entries) >= limit:
                raise AIProviderUnavailable("AI request rate limit exceeded")
        for key in keys:
            _rate_events[key].append(now)


@contextmanager
def provider_call_slot_for_test() -> Iterator[None]:
    """Expose the production semaphore boundary for deterministic tests."""
    if not _provider_slots.acquire(timeout=_CONCURRENCY_WAIT_SECONDS):
        raise AIProviderUnavailable("AI provider is temporarily busy")
    try:
        yield
    finally:
        _provider_slots.release()
