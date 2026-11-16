import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app import main, models
from app.ai.provider_controls import reset_ai_rate_limits


@pytest.fixture
def api_context():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine, tables=[
        models.User.__table__, models.Chat.__table__, models.Message.__table__,
        models.UserProfile.__table__, models.Match.__table__, models.UserBlock.__table__,
        models.AIRecoveryIntervention.__table__, models.AISuggestionRecord.__table__,
        models.AISuggestionEvent.__table__,
    ])
    factory = sessionmaker(bind=engine)
    db = factory()
    a = models.User(username="coach_api_a", email="coach_api_a@example.test", hashed_password="x")
    b = models.User(username="coach_api_b", email="coach_api_b@example.test", hashed_password="x")
    outsider = models.User(username="coach_api_c", email="coach_api_c@example.test", hashed_password="x")
    db.add_all([a, b, outsider]); db.flush()
    a.ai_provider_processing_enabled = True
    b.ai_provider_processing_enabled = True
    outsider.ai_provider_processing_enabled = True
    for user in (a, b, outsider):
        db.add(models.UserProfile(user_id=user.id, date_of_birth=date(1990, 1, 1),
            gender="any", city="Test", is_face_verified=True, is_id_verified=True,
            verification_status="verified"))
    chat = models.Chat(user1_id=a.id, user2_id=b.id)
    db.add(chat); db.flush()
    db.add(models.Match(user1_id=a.id, user2_id=b.id, chat_id=chat.id, is_active=True))
    db.add_all([
        models.Message(chat_id=chat.id, sender_id=a.id, content="I enjoy travelling and exploring new cities."),
        models.Message(chat_id=chat.id, sender_id=b.id, content="I love travelling too, especially by train."),
        models.Message(chat_id=chat.id, sender_id=a.id, content="I usually bring my camera on those trips."),
        models.Message(chat_id=chat.id, sender_id=b.id, content="The mountain views are beautiful."),
        models.Message(chat_id=chat.id, sender_id=a.id, content="I found a quiet route last weekend."),
        models.Message(chat_id=chat.id, sender_id=b.id, content="That sounds like a lovely afternoon."),
        models.Message(chat_id=chat.id, sender_id=a.id, content="Do you have a favorite place to visit?"),
        models.Message(chat_id=chat.id, sender_id=b.id, content="I like the old city near the river."),
    ])
    db.commit()

    def override_db():
        yield db

    main.app.dependency_overrides[main.get_db] = override_db
    client = TestClient(main.app)
    try:
        yield client, db, a, b, outsider, chat
    finally:
        main.app.dependency_overrides.pop(main.get_db, None)
        client.close(); db.close(); engine.dispose()
        reset_ai_rate_limits()


def _auth(user):
    return {"Authorization": f"Bearer {main.create_token(user.id)}"}


def test_coach_http_api_uses_requesting_users_profile_and_messages(api_context, monkeypatch):
    client, db, a, b, outsider, chat = api_context
    captured = {}

    def fake_model(messages, **kwargs):
        captured["prompt"] = messages[1]["content"]
        return json.dumps({"insights": [
            {"category": "Strength", "message": "You share clear personal context."},
            {"category": "Try next", "message": "Add a detail to your question."},
            {"category": "Example", "message": "I like this trail because it is quiet."},
        ]})

    monkeypatch.setattr("app.ai.conversation_coach._call_model", fake_model)
    response = client.get(f"/chats/{chat.id}/coach", headers=_auth(a))
    assert response.status_code == 200
    result = response.json()
    assert result["private"] is True and result["user_id"] == a.id
    assert [item["category"] for item in result["insights"]] == ["Strength", "Try next", "Example"]
    prompt = json.loads(captured["prompt"])
    assert prompt["my_recent_messages"]
    assert all("train" not in item.lower() for item in prompt["my_recent_messages"])

    response_b = client.get(f"/chats/{chat.id}/coach", headers=_auth(b))
    assert response_b.status_code == 200 and response_b.json()["user_id"] == b.id
    prompt_b = json.loads(captured["prompt"])
    assert any("train" in item.lower() for item in prompt_b["my_recent_messages"])
    assert all("travelling and exploring" not in item.lower() for item in prompt_b["my_recent_messages"])

    denied = client.get(f"/chats/{chat.id}/coach", headers=_auth(outsider))
    assert denied.status_code == 403


def test_coach_http_api_handles_empty_and_missing_personal_profile(api_context, monkeypatch):
    client, db, a, b, outsider, chat = api_context
    db.query(models.Message).filter_by(chat_id=chat.id).delete()
    db.commit()
    empty = client.get(f"/chats/{chat.id}/coach", headers=_auth(a))
    assert empty.status_code == 200 and empty.json()["reason"] == "no_context"

    db.add(models.Message(chat_id=chat.id, sender_id=b.id, content="I like travelling and museums."))
    db.commit()
    missing = client.get(f"/chats/{chat.id}/coach", headers=_auth(a))
    assert missing.status_code == 200 and missing.json()["reason"] == "missing_profile"


def test_insights_http_api_returns_computed_topics_and_chat_scoped_results(api_context):
    client, db, a, b, outsider, chat = api_context
    response = client.get(f"/chats/{chat.id}/insights", headers=_auth(a))
    assert response.status_code == 200
    result = response.json()
    assert result["available"] is True
    assert result["message_count"] == 8
    assert result["mood"]["state"]
    assert isinstance(result["engagement_trend"]["explanation"], str)
    assert "travel" in result["shared_topics"]

    other = models.User(username="coach_api_d", email="coach_api_d@example.test", hashed_password="x")
    db.add(other); db.flush()
    db.add(models.UserProfile(user_id=other.id, date_of_birth=date(1990, 1, 1),
        gender="any", city="Test", is_face_verified=True, is_id_verified=True,
        verification_status="verified"))
    other_chat = models.Chat(user1_id=a.id, user2_id=other.id); db.add(other_chat); db.flush()
    db.add(models.Match(user1_id=a.id, user2_id=other.id, chat_id=other_chat.id, is_active=True))
    db.add(models.Message(chat_id=other_chat.id, sender_id=a.id, content="I love cooking pasta."))
    db.add(models.Message(chat_id=other_chat.id, sender_id=other.id, content="Cooking is fun.")); db.commit()
    other_result = client.get(f"/chats/{other_chat.id}/insights", headers=_auth(a)).json()
    assert other_result["message_count"] == 2
    assert other_result["shared_topics"] != result["shared_topics"]

    empty_chat = models.Chat(user1_id=a.id, user2_id=outsider.id); db.add(empty_chat); db.commit()
    db.add(models.Match(user1_id=a.id, user2_id=outsider.id, chat_id=empty_chat.id, is_active=True)); db.commit()
    empty = client.get(f"/chats/{empty_chat.id}/insights", headers=_auth(a))
    assert empty.status_code == 200 and empty.json()["reason"] == "no_context"


def test_coach_http_api_reports_provider_failure_without_leaking_details(api_context, monkeypatch):
    client, db, a, b, outsider, chat = api_context

    def fail_model(*args, **kwargs):
        raise RuntimeError("provider transport failed with secret=not-for-client")

    monkeypatch.setattr("app.ai.conversation_coach._call_model", fail_model)
    response = client.get(f"/chats/{chat.id}/coach", headers=_auth(a))
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "ai_provider_unavailable"
    assert "not-for-client" not in response.text


def test_coach_http_api_reports_invalid_model_response_for_retry(api_context, monkeypatch):
    client, db, a, b, outsider, chat = api_context
    monkeypatch.setattr("app.ai.conversation_coach._call_model", lambda *args, **kwargs: "not json")
    response = client.get(f"/chats/{chat.id}/coach", headers=_auth(a))
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "ai_provider_unavailable"


@pytest.mark.parametrize("relationship_change", ["unmatch", "block"])
def test_coach_and_insights_require_active_unblocked_match(api_context, relationship_change):
    client, db, a, b, _, chat = api_context
    match = db.query(models.Match).filter_by(chat_id=chat.id).one()
    if relationship_change == "unmatch":
        match.is_active = False
    else:
        db.add(models.UserBlock(blocker_id=a.id, blocked_id=b.id))
    db.commit()
    assert client.get(f"/chats/{chat.id}/coach", headers=_auth(a)).status_code == 403
    assert client.get(f"/chats/{chat.id}/insights", headers=_auth(a)).status_code == 403


def test_coach_is_disabled_without_provider_consent_even_when_memory_is_opted_in(api_context, monkeypatch):
    client, db, a, b, _, chat = api_context
    a.ai_memory_enabled = True
    a.ai_provider_processing_enabled = False
    db.commit()
    calls = []
    monkeypatch.setattr("app.ai.conversation_coach._call_model", lambda *args, **kwargs: calls.append(1))
    response = client.get(f"/chats/{chat.id}/coach", headers=_auth(a))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ai_provider_consent_required"
    assert calls == []


def test_provider_processing_preference_can_be_changed_independently(api_context):
    client, db, a, b, _, chat = api_context
    a.ai_memory_enabled = True
    a.ai_provider_processing_enabled = False
    db.commit()
    updated = client.patch("/me", headers=_auth(a), json={"ai_provider_processing_enabled": True})
    assert updated.status_code == 200
    assert updated.json()["ai_provider_processing_enabled"] is True
    assert updated.json()["ai_memory_enabled"] is True
    revoked = client.patch("/me", headers=_auth(a), json={"ai_provider_processing_enabled": False})
    assert revoked.status_code == 200
    assert revoked.json()["ai_provider_processing_enabled"] is False
    assert revoked.json()["ai_memory_enabled"] is True


def test_manual_suggestions_require_both_provider_consents(api_context, monkeypatch):
    client, db, a, b, _, chat = api_context
    a.ai_provider_processing_enabled = False
    db.commit()
    calls = []
    monkeypatch.setattr(main, "run_conversation_workflow", lambda **kwargs: calls.append(kwargs))
    response = client.post(f"/chats/{chat.id}/suggestions", headers=_auth(a), json={})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ai_provider_consent_required"
    assert calls == []


def test_lifecycle_event_endpoint_rejects_invalid_and_oversized_payloads(api_context):
    client, db, a, _, _, chat = api_context
    record = models.AISuggestionRecord(
        chat_id=chat.id, user_id=a.id, suggestion_hash="a" * 64,
        strategy="test", prompt_version="test-v1", model_id="test",
    )
    db.add(record); db.commit(); db.refresh(record)
    path = f"/ai-suggestions/{record.id}/events"
    invalid = client.post(path, headers=_auth(a), json={
        "event_type": "unknown", "event_key": "bad-event", "details": {},
    })
    assert invalid.status_code == 422
    oversized = client.post(path, headers=_auth(a), json={
        "event_type": "selected", "event_key": "large-event",
        "details": {"comment": "x" * 3000},
    })
    assert oversized.status_code == 422
