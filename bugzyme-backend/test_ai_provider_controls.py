import threading

import pytest

from app import models
from app.ai import extraction, provider_controls as controls


class FakeCompletions:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, outcomes):
        self.chat = type("Chat", (), {"completions": FakeCompletions(outcomes)})()


def test_user_provider_preference_defaults_off_and_is_separate_from_memory():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine, tables=[models.User.__table__])
    db = sessionmaker(bind=engine)()
    try:
        user = models.User(username="provider_default", email="provider_default@example.test", hashed_password="x")
        db.add(user); db.flush()
        assert user.ai_memory_enabled is False
        assert user.ai_provider_processing_enabled is False
        user.ai_memory_enabled = True
        db.flush()
        assert user.ai_provider_processing_enabled is False
    finally:
        db.close(); engine.dispose()


def test_provider_guard_fails_closed_without_explicit_scope():
    with pytest.raises(controls.AIProviderConsentRequired):
        controls.assert_provider_consent()


def test_provider_consent_is_rechecked_before_each_request():
    enabled = [True]
    client = FakeClient([object(), object()])
    with controls.provider_consent_scope(lambda: enabled[0]):
        controls.provider_completion(client)
        enabled[0] = False
        with pytest.raises(controls.AIProviderConsentRequired):
            controls.provider_completion(client)
    assert client.chat.completions.calls == 1


def test_provider_retries_one_transient_timeout_but_not_client_errors():
    timeout = type("APITimeoutError", (Exception,), {})("timeout")
    client = FakeClient([timeout, "ok"])
    with controls.provider_consent_scope(lambda: True):
        assert controls.provider_completion(client) == "ok"
    assert client.chat.completions.calls == 2

    bad_request = type("BadRequest", (Exception,), {"status_code": 400})("invalid")
    client = FakeClient([bad_request, "should not run"])
    with controls.provider_consent_scope(lambda: True):
        with pytest.raises(controls.AIProviderUnavailable):
            controls.provider_completion(client)
    assert client.chat.completions.calls == 1


def test_concurrency_limit_fails_fast_without_calling_provider(monkeypatch):
    semaphore = threading.BoundedSemaphore(1)
    assert semaphore.acquire(blocking=False)
    monkeypatch.setattr(controls, "_provider_slots", semaphore)
    monkeypatch.setattr(controls, "_CONCURRENCY_WAIT_SECONDS", 0.01)
    client = FakeClient(["unused"])
    try:
        with controls.provider_consent_scope(lambda: True):
            with pytest.raises(controls.AIProviderUnavailable):
                controls.provider_completion(client)
    finally:
        semaphore.release()
    assert client.chat.completions.calls == 0


def test_manual_ai_rate_limit_is_bounded_and_per_user_and_chat():
    controls.reset_ai_rate_limits()
    user_id, chat_id = 710001, 710002
    for _ in range(5):
        controls.enforce_ai_rate_limit(user_id, chat_id)
    with pytest.raises(controls.AIProviderUnavailable):
        controls.enforce_ai_rate_limit(user_id, chat_id)
    # A distinct user is separately tracked, even in the same chat.
    controls.enforce_ai_rate_limit(user_id + 1, chat_id)
    controls.reset_ai_rate_limits()


def test_groq_client_has_explicit_timeout_and_sdk_retries_disabled(monkeypatch):
    captured = {}

    def fake_groq(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setenv("GROQ_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(extraction, "Groq", fake_groq)
    extraction.get_groq_client()
    assert captured["timeout"] == extraction.GROQ_REQUEST_TIMEOUT_SECONDS
    assert captured["max_retries"] == 0


def test_event_schema_rejects_unknown_event_types_fields_and_oversize_payloads():
    from app.schemas import AISuggestionEventCreate

    assert AISuggestionEventCreate(event_type="edited", event_key="e-1", details={"changed": True})
    with pytest.raises(Exception):
        AISuggestionEventCreate(event_type="not-real", event_key="e-1")
    with pytest.raises(Exception):
        AISuggestionEventCreate(event_type="user_feedback", event_key="e-1", details={"rating": "helpful", "extra": "x"})
    with pytest.raises(Exception):
        AISuggestionEventCreate(event_type="edited", event_key="e-1", details={"changed": "yes"})
    with pytest.raises(Exception):
        AISuggestionEventCreate(event_type="selected", event_key="e-1", details={"comment": "x" * 3000})


def test_provider_text_redacts_credentials_and_government_id_patterns():
    text = "password: hunter2 PAN: ABCDE1234F Aadhaar 1234 5678 9012 normal text"
    cleaned = controls.sanitize_provider_text(text)
    assert "hunter2" not in cleaned
    assert "ABCDE1234F" not in cleaned
    assert "1234 5678 9012" not in cleaned
    assert "normal text" in cleaned


def test_suggestion_prompt_uses_minimal_pseudonymous_recent_context(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.ai import suggestions

    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine, tables=[models.User.__table__])
    db = sessionmaker(bind=engine)()
    captured = {}
    monkeypatch.setattr(suggestions, "_analyze_conversation", lambda transcript: {
        "current_topic": "travel", "conversation_tone": "friendly",
        "last_message_intent": "share", "conversation_state": "flowing",
        "next_reply_strategy": "continue",
    })

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return [
            {"style": "natural", "message": "Thanks for sharing."},
            {"style": "playful", "message": "That sounds fun."},
            {"style": "thoughtful", "message": "What did you enjoy most?"},
        ]

    monkeypatch.setattr(suggestions, "_generate_suggestions", fake_generate)
    try:
        suggestions.suggest_next_messages(
            db=db, requesting_user_id=77, requesting_user="real_username_77",
            messages=[
                {"sender_id": 77, "sender_name": "real_username_77", "message_id": 123456,
                 "created_at": "private-timestamp", "content": "password: hunter2 I like hiking."},
                {"sender_id": 88, "sender_name": "other_username_88", "message_id": 123457,
                 "created_at": "private-timestamp", "content": "Aadhaar 1234 5678 9012?"},
            ],
        )
    finally:
        db.close(); engine.dispose()
    transcript = captured["transcript"]
    assert "real_username_77" not in transcript and "other_username_88" not in transcript
    assert "123456" not in transcript and "private-timestamp" not in transcript
    assert "hunter2" not in transcript and "1234 5678 9012" not in transcript
    assert "You:" in transcript and "Other participant:" in transcript
