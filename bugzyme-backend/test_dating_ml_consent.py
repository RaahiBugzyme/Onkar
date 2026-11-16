from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import database, models, schemas
from app.main import app, get_current_user
from app.services.dating_ml_adapter import DatingMLAdapter, MatchingConsentRequired
from app.services.dating_ml_model import CompatibilityModel


@pytest.fixture
def consent_client():
    with database.SessionLocal() as db:
        user = models.User(
            username="consent_test_user", email="consent_test_user@example.test",
            hashed_password="not-used",
        )
        db.add(user)
        db.flush()
        profile = models.UserProfile(
            user_id=user.id, date_of_birth=date(1990, 1, 1), gender="female",
            sexual_orientation="straight", city="Pune", era="millennial",
            is_face_verified=True, is_id_verified=True, verification_status="verified",
        )
        other_user = models.User(
            username="consent_test_other", email="consent_test_other@example.test",
            hashed_password="not-used",
        )
        db.add(other_user)
        db.flush()
        other = models.UserProfile(
            user_id=other_user.id, date_of_birth=date(1991, 1, 1), gender="male",
            city="Pune", era="millennial",
            is_face_verified=True, is_id_verified=True, verification_status="verified",
        )
        db.add_all([profile, other])
        db.commit()
        app.dependency_overrides[database.get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: user
        try:
            with TestClient(app) as client:
                yield client, db, user, profile, other
        finally:
            app.dependency_overrides.clear()


def test_missing_orientation_is_unknown_and_model_ineligible():
    first = {"id": "a", "age": 30, "sex": "female", "orientation": None}
    second = {"id": "b", "age": 31, "sex": "male", "orientation": "straight"}
    result = CompatibilityModel().predict_pair(first, second)
    assert result["eligible"] is False
    assert result["compatibility_score"] is None
    assert "orientation missing" in result["eligibility_reason"].lower()


@pytest.mark.parametrize(
    "orientation", ["straight", "heterosexual", "gay", "lesbian", "homosexual", "bisexual", "bi"]
)
def test_model_supported_orientation_values_are_accepted(orientation):
    request = schemas.DatingProfileUpdate(sexual_orientation=f" {orientation.upper()} ")
    assert request.sexual_orientation == orientation


def test_invalid_orientation_is_rejected():
    with pytest.raises(ValidationError):
        schemas.DatingProfileUpdate(sexual_orientation="questioning")


def test_unsupported_gender_is_ineligible_not_coerced():
    first = {"id": "a", "age": 30, "sex": "nonbinary", "orientation": "straight"}
    second = {"id": "b", "age": 31, "sex": "female", "orientation": "straight"}
    result = CompatibilityModel().predict_pair(first, second)
    assert result["eligible"] is False
    assert result["compatibility_score"] is None
    assert "sex or orientation missing" in result["eligibility_reason"].lower()


def test_adapter_requires_both_orientation_consents_and_revoke_blocks_use(consent_client):
    _, db, user, profile, other = consent_client

    class SpyModel:
        called = False

        def predict_pair(self, first, second):
            self.called = True
            return {"eligible": True}

    model = SpyModel()
    adapter = DatingMLAdapter(model=model)
    with pytest.raises(MatchingConsentRequired):
        adapter.predict_pair(db, user.id, other.user_id)
    assert model.called is False

    profile.sexual_orientation_consent = True
    other.sexual_orientation_consent = True
    db.commit()
    result = adapter.predict_pair(db, user.id, other.user_id)
    assert result["eligible"] is True
    assert result["package_version"] == "2.2.0"
    assert model.called is True

    profile.sexual_orientation_consent = False
    db.commit()
    model.called = False
    with pytest.raises(MatchingConsentRequired):
        adapter.predict_pair(db, user.id, other.user_id)
    assert model.called is False


def test_private_orientation_and_explicit_revocable_consent(consent_client):
    client, _, _, profile, other = consent_client
    private_response = client.get("/api/v1/profile/me")
    assert private_response.status_code == 200
    assert private_response.json()["sexual_orientation"] == "straight"
    assert private_response.json()["sexual_orientation_consent"] is False

    public_response = client.get(f"/api/v1/profile/{other.user_id}")
    assert public_response.status_code == 200
    assert "sexual_orientation" not in public_response.json()

    state = client.get("/api/v1/profile/me/privacy")
    assert state.status_code == 200
    assert state.json()["orientation_matching"]["consent"] is False
    assert "optional" in state.json()["orientation_matching"]["disclosure"].lower()

    granted = client.put("/api/v1/profile/me/orientation-consent", json={"consent": True})
    assert granted.status_code == 200
    assert granted.json()["consent"] is True
    assert granted.json()["version"] == "orientation-matching-v1"
    revoked = client.put("/api/v1/profile/me/orientation-consent", json={"consent": False})
    assert revoked.status_code == 200
    assert revoked.json()["consent"] is False
    assert revoked.json()["updated_at"] is not None


def test_orientation_consent_requires_a_selected_value(consent_client):
    client, _, _, profile, _ = consent_client
    profile.sexual_orientation = None
    response = client.put("/api/v1/profile/me/orientation-consent", json={"consent": True})
    assert response.status_code == 409


def test_behavioral_personalization_is_separate_opt_in_and_opt_out(consent_client):
    client, _, _, profile, _ = consent_client
    assert profile.behavioral_personalization_enabled is False
    enabled = client.put(
        "/api/v1/profile/me/behavioral-personalization-consent", json={"consent": True}
    )
    assert enabled.status_code == 200
    assert enabled.json()["consent"] is True
    assert enabled.json()["version"] == "behavioral-personalization-v1"
    assert "chat content" in enabled.json()["disclosure"].lower()
    disabled = client.put(
        "/api/v1/profile/me/behavioral-personalization-consent", json={"consent": False}
    )
    assert disabled.status_code == 200
    assert disabled.json()["consent"] is False


def test_existing_profile_defaults_preserve_unknown_orientation_and_off_consents(consent_client):
    _, db, _, _, other = consent_client
    existing = db.query(models.UserProfile).filter_by(user_id=other.user_id).one()
    assert existing.sexual_orientation is None
    assert existing.sexual_orientation_consent is False
    assert existing.behavioral_personalization_enabled is False
    assert "sexual_orientation" not in schemas.PublicProfileResponse.model_fields


def test_privacy_endpoints_require_authentication():
    with TestClient(app) as client:
        app.dependency_overrides.clear()
        response = client.get("/api/v1/profile/me/privacy")
    assert response.status_code == 401
