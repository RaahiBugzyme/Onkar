from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import database, models
from app.main import app, get_current_user
from app.services.dating_ml_adapter import DatingMLAdapter


def _add_person(db, tag, name, *, gender="male", era="genz", dob=None, verified=True,
                target_gender="any", match_era="any", orientation_consent=False,
                behavior_consent=False):
    user = models.User(username=f"{tag}_{name}", email=f"{tag}_{name}@example.test", hashed_password="unused")
    db.add(user)
    db.flush()
    profile = models.UserProfile(
        user_id=user.id,
        date_of_birth=dob or date.today() - timedelta(days=365 * 25),
        gender=gender,
        sexual_orientation="straight" if orientation_consent else None,
        sexual_orientation_consent=orientation_consent,
        behavioral_personalization_enabled=behavior_consent,
        city="Pune",
        era=era,
        target_gender_preference=target_gender,
        match_era_preference=match_era,
        is_face_verified=verified,
        is_id_verified=verified,
        verification_status="verified" if verified else "pending",
    )
    db.add(profile)
    db.flush()
    return user, profile


@pytest.fixture
def feed_client():
    with database.SessionLocal() as db:
        tag = f"feedopt_{uuid4().hex[:10]}"
        current, current_profile = _add_person(
            db, tag, "current", gender="female", era="genz",
            target_gender="male", match_era="genz",
        )
        outsider, _ = _add_person(db, tag, "outsider", gender="female", verified=False)
        db.commit()
        app.dependency_overrides[database.get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: current
        try:
            with TestClient(app) as client:
                yield client, db, current, current_profile, outsider
        finally:
            app.dependency_overrides.clear()


def test_sql_feed_excludes_blocks_swipes_preferences_minors_and_unverified(feed_client):
    client, db, current, _, _ = feed_client
    tag = f"cand_{uuid4().hex[:8]}"
    good, _ = _add_person(db, tag, "good", gender="male", era="genz")
    blocked_by_current, _ = _add_person(db, tag, "blockedby", gender="male", era="genz")
    blocker, _ = _add_person(db, tag, "blocker", gender="male", era="genz")
    swiped, _ = _add_person(db, tag, "swiped", gender="male", era="genz")
    wrong_gender, _ = _add_person(db, tag, "wronggender", gender="female", era="genz")
    wrong_bilateral, _ = _add_person(db, tag, "wrongbilateral", gender="male", era="genz", target_gender="male")
    wrong_era, _ = _add_person(db, tag, "wrongera", gender="male", era="millennial")
    minor, _ = _add_person(db, tag, "minor", gender="male", era="genz", dob=date.today() - timedelta(days=365 * 17))
    pending, _ = _add_person(db, tag, "pending", gender="male", era="genz", verified=False)
    db.add_all([
        models.UserBlock(blocker_id=current.id, blocked_id=blocked_by_current.id),
        models.UserBlock(blocker_id=blocker.id, blocked_id=current.id),
        models.Swipe(user_id=current.id, target_user_id=swiped.id, action="pass"),
    ])
    db.commit()

    response = client.get("/api/v1/feed")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert [row["user_id"] for row in data["profiles"]] == [good.id]
    row = data["profiles"][0]
    assert row["matching_status"] == "orientation_consent_required"
    assert row["compatibility_score"] is None
    assert all(candidate.id not in {r["user_id"] for r in data["profiles"]}
               for candidate in [blocked_by_current, blocker, swiped, wrong_gender,
                                 wrong_bilateral, wrong_era, minor, pending])


def test_behavior_off_does_not_query_history_or_personalize(feed_client, monkeypatch):
    client, _, _, current_profile, _ = feed_client
    current_profile.sexual_orientation = "straight"
    current_profile.sexual_orientation_consent = True
    current_profile.behavioral_personalization_enabled = False
    candidate_tag = f"off_{uuid4().hex[:8]}"
    # Add a verified candidate using the active session from the fixture override.
    session = app.dependency_overrides[database.get_db]()
    candidate, _ = _add_person(session, candidate_tag, "candidate", orientation_consent=True)
    session.commit()

    import app.main as main_module
    adapter = main_module.dating_ml_adapter

    def fail_if_queried(*args, **kwargs):
        raise AssertionError("behavior events should not be loaded while opt-in is off")

    monkeypatch.setattr(adapter, "load_behavior_history", fail_if_queried)

    class SpyRecommendationModel:
        def recommend(self, user, candidates, **kwargs):
            assert kwargs["interactions"] == []
            assert kwargs["privacy_settings"]["personalization_enabled"] is False
            return [{
                "candidate_id": str(candidate.id),
                "package_version": "2.2.0",
                "compatibility": {"score": 70.0, "confidence": 0.5, "adjusted_score": 60.0},
                "ranking": {"final_score": 65.0},
            }]

    monkeypatch.setattr(adapter, "recommendation_model", SpyRecommendationModel())
    response = client.get("/api/v1/feed")
    assert response.status_code == 200
    assert response.json()["profiles"][0]["user_id"] == candidate.id


def test_behavior_query_is_user_and_eligible_candidate_filtered_and_ordered(feed_client, monkeypatch):
    client, db, current, current_profile, _ = feed_client
    current_profile.sexual_orientation = "straight"
    current_profile.sexual_orientation_consent = True
    current_profile.behavioral_personalization_enabled = True
    tag = f"hist_{uuid4().hex[:8]}"
    candidate, _ = _add_person(db, tag, "fresh", orientation_consent=True)
    old_target, _ = _add_person(db, tag, "old", orientation_consent=True)
    new_target, _ = _add_person(db, tag, "new", orientation_consent=True)
    blocked_target, _ = _add_person(db, tag, "blocked", orientation_consent=True)
    other_user, _ = _add_person(db, tag, "other", gender="female", orientation_consent=True, verified=False)
    db.add_all([
        models.Swipe(user_id=current.id, target_user_id=new_target.id, action="like",
                     created_at=datetime(2025, 1, 2)),
        models.Swipe(user_id=current.id, target_user_id=old_target.id, action="pass",
                     created_at=datetime(2025, 1, 1)),
        models.Swipe(user_id=current.id, target_user_id=blocked_target.id, action="like",
                     created_at=datetime(2025, 1, 3)),
        models.Swipe(user_id=other_user.id, target_user_id=old_target.id, action="like",
                     created_at=datetime(2025, 1, 4)),
        models.UserBlock(blocker_id=blocked_target.id, blocked_id=current.id),
    ])
    db.commit()

    import app.main as main_module
    adapter = main_module.dating_ml_adapter

    class SpyRecommendationModel:
        def recommend(self, user, candidates, **kwargs):
            events = kwargs["interactions"]
            assert [event["candidate_id"] for event in events] == [str(old_target.id), str(new_target.id)]
            assert [event["action"] for event in events] == ["PASS", "LIKE"]
            assert all(event["user_id"] == str(current.id) for event in events)
            assert kwargs["privacy_settings"]["personalization_enabled"] is True
            assert kwargs["profile_lookup"](str(old_target.id))["location"]["city"] == "Pune"
            assert kwargs["profile_lookup"](str(blocked_target.id)) is None
            return [{
                "candidate_id": str(candidate.id),
                "package_version": "2.2.0",
                "compatibility": {"score": 70.0, "confidence": 0.5, "adjusted_score": 60.0},
                "ranking": {"final_score": 65.0},
            }]

    monkeypatch.setattr(adapter, "recommendation_model", SpyRecommendationModel())
    response = client.get("/api/v1/feed")
    assert response.status_code == 200
    assert [row["user_id"] for row in response.json()["profiles"]] == [candidate.id]


def test_feed_ranking_exception_returns_503_without_fallback(feed_client, monkeypatch):
    client, _, _, _, _ = feed_client
    import app.main as main_module

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic rank failure")

    monkeypatch.setattr(main_module.dating_ml_adapter, "rank_feed", fail)
    response = client.get("/api/v1/feed")
    assert response.status_code == 503
    assert response.json()["detail"] == "Matching service is temporarily unavailable"
