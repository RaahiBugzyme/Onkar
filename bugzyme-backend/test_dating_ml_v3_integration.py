"""Comprehensive integration tests for Dating ML V3 in Raahi backend.

Validates:
- Multi-signal profile mapping (profession, education, relationship intention, interests, era, city).
- Safe handling of NULL / missing fields without invented data.
- Profile completeness scoring.
- Feed recommendation TTL caching.
- Fallback resilience and privacy preservation.
"""
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app import models
from app.services.dating_ml_adapter import (
    DatingMLAdapter,
    calculate_profile_completeness,
    map_raahi_profile,
    _FeedRecommendationCache,
)


def test_map_raahi_profile_all_signals():
    """All genuine profile fields are correctly mapped for Dating ML inference."""
    profile = models.UserProfile(
        user_id=101,
        date_of_birth=date(1998, 5, 15),
        gender="female",
        sexual_orientation="straight",
        sexual_orientation_consent=True,
        city="Pune",
        era="genz",
        vibe_tag="Serious relationship",
        profession="computer / hardware / software",
        education="college/university",
        relationship_intentions="long-term",
        interests=["trekking", "music", "coding"],
    )
    mapped = map_raahi_profile(profile, orientation_authorized=True, reference_date=date(2026, 6, 1))
    assert mapped["id"] == "101"
    assert mapped["age"] == 28
    assert mapped["birth_year"] == 1998
    assert mapped["sex"] == "f"
    assert mapped["orientation"] == "straight"
    assert mapped["job"] == "computer / hardware / software"
    assert mapped["education"] == "college/university"
    assert mapped["relationship_intention"] == "long-term"
    assert mapped["interests"] == ["trekking", "music", "coding"]
    assert mapped["era"] == "genz"
    assert mapped["location"]["city"] == "Pune"
    assert mapped["location"]["country"] is None


def test_map_raahi_profile_sparse_and_null_tolerance():
    """Profiles with missing optional fields degrade gracefully without crashing or fabricating data."""
    profile = models.UserProfile(
        user_id=102,
        date_of_birth=date(2000, 1, 1),
        gender="male",
        sexual_orientation=None,
        sexual_orientation_consent=False,
        city=None,
        era="genz",
        profession=None,
        education=None,
        relationship_intentions=None,
        interests=None,
    )
    mapped = map_raahi_profile(profile, orientation_authorized=False)
    assert mapped["id"] == "102"
    assert mapped["sex"] == "m"
    assert mapped["orientation"] is None
    assert mapped["job"] is None
    assert mapped["education"] is None
    assert mapped["relationship_intention"] is None
    assert mapped["interests"] == []
    assert mapped["location"]["city"] is None
    assert mapped["location"]["country"] is None


def test_profile_completeness_calculation():
    """Profile completeness is calculated accurately across all required profile fields."""
    user = SimpleNamespace(bio="Exploring mountains and tech")
    complete_profile = SimpleNamespace(
        user_id=1,
        date_of_birth=date(1995, 3, 20),
        gender="female",
        city="Mumbai",
        era="millennial",
        profession="medicine / health",
        education="med school",
        relationship_intentions="marriage",
        interests=["travel", "reading"],
        photos=[SimpleNamespace(photo_url="https://example.com/p1.jpg")],
    )
    score_complete = calculate_profile_completeness(user, complete_profile)
    assert score_complete == 100.0

    # Incomplete profile (missing bio, profession, education, relationship_intentions, interests, photos)
    empty_user = SimpleNamespace(bio="")
    sparse_profile = SimpleNamespace(
        user_id=2,
        date_of_birth=date(1997, 8, 10),
        gender="male",
        city="Pune",
        era="genz",
        profession=None,
        education=None,
        relationship_intentions=None,
        interests=[],
        photos=[],
    )
    score_sparse = calculate_profile_completeness(empty_user, sparse_profile)
    # 4 filled out of 10 checks = 40.0%
    assert score_sparse == 40.0


def test_feed_cache_ttl_and_lru():
    """Feed cache respects TTL expiry and maximum size limits."""
    cache = _FeedRecommendationCache(ttl_seconds=0.1, max_size=2)
    cache.set("k1", [{"candidate_id": "1", "score": 90}])
    cache.set("k2", [{"candidate_id": "2", "score": 80}])
    assert cache.get("k1") is not None
    assert cache.get("k2") is not None

    # Exceed capacity: k3 should evict least recently used (k1)
    cache.set("k3", [{"candidate_id": "3", "score": 70}])
    assert cache.get("k1") is None
    assert cache.get("k2") is not None
    assert cache.get("k3") is not None

    # Wait for TTL expiry
    import time
    time.sleep(0.15)
    assert cache.get("k2") is None
    assert cache.get("k3") is None


def test_multi_signal_compatibility_evaluation():
    """Deterministic compatibility engine scores multi-signal alignment across education, profession, and age."""
    adapter = DatingMLAdapter()
    profile_a = {
        "id": "1",
        "age": 27,
        "birth_year": 1999,
        "sex": "f",
        "orientation": "straight",
        "education": "college/university",
        "job": "computer / hardware / software",
        "location": {"city": "Pune", "region": "Maharashtra", "country": "India"},
    }
    # Similar candidate: same age, same profession, same education, same city
    profile_b_similar = {
        "id": "2",
        "age": 28,
        "birth_year": 1998,
        "sex": "m",
        "orientation": "straight",
        "education": "college/university",
        "job": "computer / hardware / software",
        "location": {"city": "Pune", "region": "Maharashtra", "country": "India"},
    }
    # Dissimilar candidate: large age gap, different education, different profession
    profile_c_dissimilar = {
        "id": "3",
        "age": 45,
        "birth_year": 1981,
        "sex": "m",
        "orientation": "straight",
        "education": "high school",
        "job": "hospitality / travel",
        "location": {"city": "Delhi", "region": "Delhi", "country": "India"},
    }

    result_similar = adapter.model.predict_pair(profile_a, profile_b_similar)
    result_dissimilar = adapter.model.predict_pair(profile_a, profile_c_dissimilar)

    assert result_similar["eligible"] is True
    assert result_dissimilar["eligible"] is True
    assert result_similar["compatibility_score"] > result_dissimilar["compatibility_score"]
    assert result_similar["adjusted_score"] > result_dissimilar["adjusted_score"]


def test_rank_feed_with_cached_results():
    """rank_feed utilizes in-memory cache on subsequent requests with identical parameters."""
    adapter = DatingMLAdapter()
    user = SimpleNamespace(id=1, username="u1", full_name="User One", bio="Hello")
    user_profile = models.UserProfile(
        user_id=1,
        date_of_birth=date(1995, 1, 1),
        gender="female",
        sexual_orientation="straight",
        sexual_orientation_consent=True,
        city="Pune",
        era="millennial",
        profession="computer / hardware / software",
        education="college/university",
        relationship_intentions="serious",
        interests=["ai"],
        photos=[],
    )
    candidate_user = SimpleNamespace(id=2, username="u2", full_name="User Two", bio="Hi")
    candidate_profile = models.UserProfile(
        user_id=2,
        date_of_birth=date(1994, 1, 1),
        gender="male",
        sexual_orientation="straight",
        sexual_orientation_consent=True,
        city="Pune",
        era="millennial",
        profession="computer / hardware / software",
        education="college/university",
        relationship_intentions="serious",
        interests=["ai"],
        photos=[],
    )

    call_count = 0
    original_recommend = adapter.recommendation_model.recommend

    def counting_recommend(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original_recommend(*args, **kwargs)

    adapter.recommendation_model.recommend = counting_recommend

    # First call - cache miss
    feed_1 = adapter.rank_feed(
        db=MagicMock(),
        authenticated_user=user,
        user_profile=user_profile,
        eligible_rows=[(candidate_user, candidate_profile)],
        swiped_ids=set(),
        limit=10,
        offset=0,
    )
    assert call_count == 1
    assert feed_1["total"] == 1
    assert feed_1["profiles"][0]["matching_status"] == "scored"
    assert feed_1["profiles"][0]["compatibility_score"] is not None

    # Second call - cache hit (recommend should NOT be called again)
    feed_2 = adapter.rank_feed(
        db=MagicMock(),
        authenticated_user=user,
        user_profile=user_profile,
        eligible_rows=[(candidate_user, candidate_profile)],
        swiped_ids=set(),
        limit=10,
        offset=0,
    )
    assert call_count == 1  # Still 1, served from cache!
    assert feed_2["profiles"][0]["user_id"] == candidate_user.id
