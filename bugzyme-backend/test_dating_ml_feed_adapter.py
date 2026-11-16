from datetime import date
from types import SimpleNamespace

from app.services.dating_ml_adapter import DatingMLAdapter, map_raahi_profile


def make_profile(user_id, *, gender="female", orientation="straight", consent=False, age=30):
    return SimpleNamespace(
        user_id=user_id,
        date_of_birth=date(1990, 5, 4) if age == 36 else date(1996, 1, 1),
        gender=gender,
        sexual_orientation=orientation,
        sexual_orientation_consent=consent,
        city="Pune",
        era="millennial",
        vibe_tag="slow-burn",
        target_gender_preference="any",
        match_era_preference="any",
        is_face_verified=True,
        is_id_verified=True,
        verification_status="verified",
        behavioral_personalization_enabled=False,
    )


def test_mapper_uses_dob_and_keeps_unavailable_fields_unknown():
    profile = make_profile(7, age=36)
    mapped = map_raahi_profile(profile, reference_date=date(2026, 11, 12))
    assert mapped["age"] == 36
    assert mapped["birth_year"] == 1990
    assert mapped["sex"] == "f"
    assert mapped["orientation"] is None
    assert mapped["education"] is None
    assert mapped["job"] is None
    assert mapped["religion"] is None
    assert mapped["ethnicity"] is None
    assert mapped["location"] == {"city": "Pune", "region": None, "country": None}


def test_orientation_is_mapped_only_after_explicit_consent():
    profile = make_profile(9, consent=True)
    assert map_raahi_profile(profile)["orientation"] is None
    assert map_raahi_profile(profile, orientation_authorized=True)["orientation"] == "straight"
    profile.sexual_orientation_consent = False
    assert map_raahi_profile(profile, orientation_authorized=True)["orientation"] is None


def test_unknown_gender_is_not_coerced():
    assert map_raahi_profile(make_profile(3, gender="nonbinary"))["sex"] is None


def test_serving_configuration_disables_sensitive_and_untrained_signals():
    adapter = DatingMLAdapter()
    config = adapter.recommendation_model.config
    assert {"religion", "ethnicity"}.issubset(set(config["disabled_components"]))
    assert config["mutual_interest_enabled"] is False
    assert config["final_ranking"]["weights"]["mutual_interest"] == 0
    assert config["final_ranking"]["weights"]["interests"] == 0


def test_feed_keeps_unconsented_profiles_without_fabricated_scores():
    adapter = DatingMLAdapter()
    current = SimpleNamespace(id=1)
    user_profile = make_profile(1, consent=False)
    candidate = SimpleNamespace(id=2, username="candidate", full_name="Candidate", bio="hello")
    candidate_profile = make_profile(2, consent=False)

    class NoCallRecommendationModel:
        def recommend(self, *args, **kwargs):
            raise AssertionError("orientation-unconsented profiles must not be scored")

    adapter.recommendation_model = NoCallRecommendationModel()
    result = adapter.rank_feed(
        db=object(), authenticated_user=current, user_profile=user_profile,
        eligible_rows=[(candidate, candidate_profile)], swiped_ids=set(), limit=20, offset=0,
    )
    row = result["profiles"][0]
    assert result["total"] == 1
    assert row["matching_status"] == "orientation_consent_required"
    assert row["compatibility_score"] is None
    assert row["recommendation_score"] is None
    assert row["score_type"] is None


def test_feed_uses_package_ranking_for_mutually_consented_candidates():
    adapter = DatingMLAdapter()
    current = SimpleNamespace(id=1)
    user_profile = make_profile(1, consent=True)
    candidate = SimpleNamespace(id=2, username="candidate", full_name="Candidate", bio="hello")
    candidate_profile = make_profile(2, gender="male", consent=True)

    class SpyRecommendationModel:
        def __init__(self):
            self.called = False

        def recommend(self, user, candidates, **kwargs):
            self.called = True
            assert user["id"] == "1"
            assert user["orientation"] == "straight"
            assert candidates[0]["orientation"] == "straight"
            assert kwargs["privacy_settings"]["personalization_enabled"] is False
            return [{
                "candidate_id": "2",
                "package_version": "2.2.0",
                "compatibility": {"score": 82.0, "confidence": 0.5, "adjusted_score": 66.0},
                "ranking": {"final_score": 68.0},
            }]

    spy = SpyRecommendationModel()
    adapter.recommendation_model = spy
    result = adapter.rank_feed(
        db=object(), authenticated_user=current, user_profile=user_profile,
        eligible_rows=[(candidate, candidate_profile)], swiped_ids=set(), limit=20, offset=0,
    )
    row = result["profiles"][0]
    assert spy.called is True
    assert row["compatibility_score"] == 82.0
    assert row["adjusted_score"] == 66.0
    assert row["recommendation_score"] == 68.0
    assert row["score_type"] == "profile_alignment"
    assert row["model_version"] == "2.2.0"


def test_complete_candidate_set_is_ranked_before_pagination_with_stable_ties():
    adapter = DatingMLAdapter()
    current = SimpleNamespace(id=99)
    user_profile = make_profile(99, consent=True)
    candidates = [
        (SimpleNamespace(id=user_id, username=f"u{user_id}", full_name=None, bio=None),
         make_profile(user_id, gender="male", consent=True))
        for user_id in (3, 1, 2)
    ]

    class EqualScoreRecommendationModel:
        received_count = 0

        def recommend(self, user, candidate_profiles, **kwargs):
            self.received_count = len(candidate_profiles)
            return [{
                "candidate_id": item["id"],
                "package_version": "2.2.0",
                "compatibility": {"score": 70.0, "confidence": 0.5, "adjusted_score": 60.0},
                "ranking": {"final_score": 65.0},
            } for item in candidate_profiles]

    spy = EqualScoreRecommendationModel()
    adapter.recommendation_model = spy
    result = adapter.rank_feed(
        db=object(), authenticated_user=current, user_profile=user_profile,
        eligible_rows=candidates, swiped_ids=set(), limit=1, offset=1,
    )
    assert spy.received_count == 3
    assert result["total"] == 3
    assert result["profiles"][0]["user_id"] == 2

