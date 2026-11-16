from datetime import date, timedelta
from uuid import uuid4

import pytest

from app import database, models
from app.services.dating_ml_adapter import (
    DatingMLAdapter,
    MatchingConsentRequired,
    MatchingNotAllowed,
)


@pytest.fixture
def matched_pair():
    with database.SessionLocal() as db:
        tag = uuid4().hex[:12]
        first = models.User(username=f"ml_first_{tag}", email=f"ml_first_{tag}@example.test", hashed_password="unused")
        second = models.User(username=f"ml_second_{tag}", email=f"ml_second_{tag}@example.test", hashed_password="unused")
        db.add_all([first, second])
        db.flush()
        profile_a = models.UserProfile(
            user_id=first.id,
            date_of_birth=date.today() - timedelta(days=365 * 30),
            gender="female",
            sexual_orientation="straight",
            sexual_orientation_consent=True,
            city="Pune",
            era="millennial",
            is_face_verified=True,
            is_id_verified=True,
            verification_status="verified",
        )
        profile_b = models.UserProfile(
            user_id=second.id,
            date_of_birth=date.today() - timedelta(days=365 * 31),
            gender="male",
            sexual_orientation="straight",
            sexual_orientation_consent=True,
            city="Pune",
            era="millennial",
            is_face_verified=True,
            is_id_verified=True,
            verification_status="verified",
        )
        db.add_all([profile_a, profile_b])
        chat = models.Chat(user1_id=min(first.id, second.id), user2_id=max(first.id, second.id))
        db.add(chat)
        db.flush()
        match = models.Match(
            user1_id=min(first.id, second.id),
            user2_id=max(first.id, second.id),
            chat_id=chat.id,
        )
        db.add(match)
        db.commit()
        db.refresh(match)
        yield db, first, second, profile_a, profile_b, match


def test_legacy_match_keeps_score_85_but_has_no_ml_prediction(matched_pair):
    _, _, _, _, _, match = matched_pair
    assert match.compatibility_score == 85
    assert match.raw_compatibility_score is None
    assert match.confidence_score is None
    assert match.adjusted_score is None
    assert match.model_version is None
    assert match.eligibility_status is None
    assert match.calculated_at is None
    assert match.prediction_provenance == "legacy"


def test_real_model_result_persists_scores_separately_without_replacing_legacy(matched_pair):
    db, first, second, _, _, match = matched_pair
    adapter = DatingMLAdapter()
    result = adapter.predict_and_persist_match(db, match)
    db.commit()
    db.refresh(match)

    assert result["eligible"] is True
    assert float(match.raw_compatibility_score) == pytest.approx(result["compatibility_score"])
    assert float(match.confidence_score) == pytest.approx(result["confidence_score"])
    assert float(match.adjusted_score) == pytest.approx(result["adjusted_score"])
    assert match.raw_compatibility_score != match.confidence_score
    assert match.model_version == result["model_version"]
    assert match.eligibility_status is True
    assert match.eligibility_reason == result["eligibility_reason"]
    assert match.explanation == result["explanation"]
    assert match.component_scores == result["components"]
    assert match.prediction_provenance == "dating_ml_v3"
    assert match.calculated_at is not None
    assert match.compatibility_score == 85  # legacy field remains intact


def test_unsupported_gender_is_persisted_as_ineligible_without_fabricated_scores(matched_pair):
    db, _, _, _, profile_b, match = matched_pair
    profile_b.gender = "nonbinary"
    result = DatingMLAdapter().predict_and_persist_match(db, match)
    db.commit()
    db.refresh(match)

    assert result["eligible"] is False
    assert match.eligibility_status is False
    assert match.raw_compatibility_score is None
    assert match.confidence_score is None
    assert "sex or orientation missing" in match.eligibility_reason.lower()
    assert match.prediction_provenance == "dating_ml_v3"
    assert match.compatibility_score == 85


def test_unverified_underage_and_blocked_profiles_never_reach_model(matched_pair):
    db, first, second, profile_a, profile_b, match = matched_pair

    class SpyModel:
        called = False

        def predict_pair(self, *args):
            self.called = True
            raise AssertionError("model must not run when matching is not allowed")

    model = SpyModel()
    adapter = DatingMLAdapter(model=model)
    profile_b.verification_status = "pending"
    with pytest.raises(MatchingNotAllowed):
        adapter.predict_and_persist_match(db, match)
    assert model.called is False

    profile_b.verification_status = "verified"
    profile_b.date_of_birth = date.today() - timedelta(days=365 * 17)
    with pytest.raises(MatchingNotAllowed):
        adapter.predict_and_persist_match(db, match)
    assert model.called is False

    profile_b.date_of_birth = date.today() - timedelta(days=365 * 31)
    db.add(models.UserBlock(blocker_id=first.id, blocked_id=second.id))
    db.flush()
    with pytest.raises(MatchingNotAllowed):
        adapter.predict_and_persist_match(db, match)
    assert model.called is False


def test_revoked_orientation_consent_blocks_model_evaluation(matched_pair):
    db, _, _, profile_a, _, match = matched_pair
    profile_a.sexual_orientation_consent = False
    adapter = DatingMLAdapter()
    with pytest.raises(MatchingConsentRequired):
        adapter.predict_and_persist_match(db, match)
    assert match.raw_compatibility_score is None
    assert match.prediction_provenance == "legacy"
