from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import database, models
from app.main import app, get_current_user
from app.services.dating_ml_adapter import DatingMLAdapter


@pytest.fixture
def api_contract_client():
    with database.SessionLocal() as db:
        tag = uuid4().hex[:12]
        users = [
            models.User(username=f"contract_{tag}_{i}", email=f"contract_{tag}_{i}@example.test", hashed_password="unused")
            for i in range(3)
        ]
        db.add_all(users)
        db.flush()
        profiles = [
            models.UserProfile(
                user_id=user.id,
                date_of_birth=date.today() - timedelta(days=365 * (30 + index)),
                gender="female" if index == 0 else "male",
                sexual_orientation="straight",
                sexual_orientation_consent=True,
                city="Pune",
                era="millennial",
                target_gender_preference="any",
                match_era_preference="any",
                is_face_verified=True,
                is_id_verified=True,
                verification_status="verified",
            )
            for index, user in enumerate(users)
        ]
        db.add_all(profiles)
        db.commit()
        app.dependency_overrides[database.get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: users[0]
        try:
            with TestClient(app) as client:
                yield client, db, users, profiles
        finally:
            app.dependency_overrides.clear()


def _make_match(db, first, second):
    low, high = sorted((first.id, second.id))
    chat = models.Chat(user1_id=low, user2_id=high)
    db.add(chat)
    db.flush()
    match = models.Match(user1_id=low, user2_id=high, chat_id=chat.id)
    db.add(match)
    db.commit()
    db.refresh(match)
    return match


def _assert_legacy_fields(payload):
    assert payload["compatibility_score"] == 85
    assert payload["compatibility_score_status"] == "legacy_placeholder"


def _assert_alignment(payload):
    alignment = payload["profile_alignment"]
    assert alignment is not None
    assert alignment["package_version"] == "2.2.0"
    assert alignment["engine_version"] == "2.1.0"
    assert alignment["score_type"] == "profile_alignment"
    assert alignment["is_success_probability"] is False
    assert isinstance(alignment["score"], (int, float))


def test_match_list_serializes_legacy_and_populated_profile_alignment(api_contract_client):
    client, db, users, _ = api_contract_client
    legacy = _make_match(db, users[0], users[1])
    response = client.get("/api/v1/matches")
    assert response.status_code == 200
    data = response.json()
    assert {"matches", "total", "limit", "offset", "has_more"}.issubset(data)
    legacy_payload = next(item for item in data["matches"] if item["id"] == legacy.id)
    _assert_legacy_fields(legacy_payload)
    assert legacy_payload["profile_alignment"] is None
    assert "created_at" in legacy_payload
    assert legacy_payload["matched_user"]["id"] == users[1].id

    populated = DatingMLAdapter().predict_and_persist_match(db, legacy)
    db.commit()
    response = client.get("/api/v1/matches")
    populated_payload = next(item for item in response.json()["matches"] if item["id"] == legacy.id)
    _assert_legacy_fields(populated_payload)
    _assert_alignment(populated_payload)
    assert populated_payload["profile_alignment"]["score"] == pytest.approx(populated["compatibility_score"])


def test_match_detail_serializes_null_and_populated_alignment_and_hides_from_nonparticipant(api_contract_client):
    client, db, users, _ = api_contract_client
    match = _make_match(db, users[0], users[1])
    response = client.get(f"/api/v1/matches/{match.id}")
    assert response.status_code == 200
    _assert_legacy_fields(response.json())
    assert response.json()["profile_alignment"] is None

    DatingMLAdapter().predict_and_persist_match(db, match)
    db.commit()
    response = client.get(f"/api/v1/matches/{match.id}")
    assert response.status_code == 200
    _assert_alignment(response.json())

    app.dependency_overrides[get_current_user] = lambda: users[2]
    response = client.get(f"/api/v1/matches/{match.id}")
    assert response.status_code == 404


def test_swipe_match_response_serializes_legacy_label_and_populated_alignment(api_contract_client):
    client, db, users, _ = api_contract_client
    db.add(models.Swipe(user_id=users[1].id, target_user_id=users[0].id, action="like"))
    db.commit()

    response = client.post("/api/v1/swipe", json={"target_user_id": users[1].id, "action": "like"})
    assert response.status_code == 200
    data = response.json()
    assert data["is_match"] is True
    assert data["match"]["matched_user"]["id"] == users[1].id
    _assert_legacy_fields(data["match"])
    _assert_alignment(data["match"])
