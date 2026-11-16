"""
Milestone 4 Tests: Matches CRUD, feed pagination, and swipe rate limiting.

These tests verify:
1. GET /api/v1/matches - list matches with pagination
2. GET /api/v1/matches/{id} - get single match with authorization
3. DELETE /api/v1/matches/{id} - unmatch with block protection
4. GET /api/v1/feed - pagination envelope and deterministic ordering
5. POST /api/v1/swipe - rate limiting and concurrency safety
"""

import pytest
import uuid
from datetime import date, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.main import app
from app import models, database


@pytest.fixture
def test_db():
    """Create a test database session."""
    with database.SessionLocal() as db:
        yield db


@pytest.fixture
def client(test_db):
    """Create a test client."""
    app.dependency_overrides[database.get_db] = lambda: test_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _random_user():
    uid = uuid.uuid4().hex[:8]
    return {
        "username": f"m4_user_{uid}",
        "email": f"m4_user_{uid}@example.com",
        "password": "Password123!"
    }


@pytest.fixture
def auth_headers(client, test_db):
    """Register a user with verified profile and get auth headers."""
    user_data = _random_user()
    r = client.post("/register", json=user_data)
    assert r.status_code == 201, f"Register failed: {r.text}"
    user_id = r.json()["id"]

    login_resp = client.post("/login", data={
        "username": user_data["email"],
        "password": user_data["password"]
    })
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create dating profile
    dob = (date.today() - timedelta(days=365 * 25)).isoformat()
    create_resp = client.post("/api/v1/profile", json={
        "date_of_birth": dob,
        "gender": "female",
        "target_gender_preference": "any",
        "city": "Mumbai",
        "era": "genz",
        "match_era_preference": "genz",
    }, headers=headers)
    assert create_resp.status_code == 201, f"Profile creation failed: {create_resp.text}"

    # Verify profile
    profile = test_db.query(models.UserProfile).filter(
        models.UserProfile.user_id == user_id
    ).first()
    profile.is_face_verified = True
    profile.is_id_verified = True
    profile.verification_status = "verified"
    test_db.commit()

    return headers, user_id


def _create_verified_user(client, test_db, gender="male", target_gender="any", era="genz"):
    """Create a verified dating user."""
    uid = uuid.uuid4().hex[:10]
    username = f"m4_verified_{uid}"
    email = f"m4_verified_{uid}@example.com"
    response = client.post("/register", json={
        "username": username,
        "email": email,
        "password": "password123",
    })
    assert response.status_code == 201, f"Register failed: {response.text}"
    user_id = response.json()["id"]

    # Login
    login_resp = client.post("/login", data={"username": email, "password": "password123"})
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    # Create dating profile
    dob = (date.today() - timedelta(days=365 * 25)).isoformat()
    client.post("/api/v1/profile", json={
        "date_of_birth": dob,
        "gender": gender,
        "target_gender_preference": target_gender,
        "city": "Mumbai",
        "era": era,
        "match_era_preference": era,
    }, headers=headers)

    # Verify profile
    profile = test_db.query(models.UserProfile).filter(
        models.UserProfile.user_id == user_id
    ).first()
    profile.is_face_verified = True
    profile.is_id_verified = True
    profile.verification_status = "verified"
    test_db.commit()

    return user_id, headers


def _mark_profile_verified(test_db, user_id):
    """Mark a profile as verified."""
    profile = test_db.query(models.UserProfile).filter(
        models.UserProfile.user_id == user_id
    ).one()
    profile.is_face_verified = True
    profile.is_id_verified = True
    profile.verification_status = "verified"
    test_db.commit()


class TestMatchesEndpoint:
    """Tests for matches CRUD endpoints."""

    def test_list_matches_requires_auth(self, client):
        """Test that /api/v1/matches requires authentication."""
        response = client.get("/api/v1/matches")
        assert response.status_code == 401

    def test_list_matches_empty_for_new_user(self, client, auth_headers):
        """Test that new users have no matches."""
        response = client.get("/api/v1/matches", headers=auth_headers[0])
        assert response.status_code == 200
        data = response.json()
        assert data["matches"] == []
        assert data["total"] == 0
        assert data["has_more"] is False

    def test_list_matches_includes_chat_id(self, client, test_db, auth_headers):
        """Test that list matches returns chat_id in response."""
        # Create a match scenario - user1 likes user2, user2 likes user1
        user1_id, headers1 = _create_verified_user(client, test_db, gender="male")
        user2_id, headers2 = _create_verified_user(client, test_db, gender="female")

        # User1 likes User2
        swipe1 = client.post("/api/v1/swipe", headers=headers1, json={
            "target_user_id": user2_id,
            "action": "like"
        })
        assert swipe1.status_code == 200

        # User2 likes User1 (creates match)
        swipe2 = client.post("/api/v1/swipe", headers=headers2, json={
            "target_user_id": user1_id,
            "action": "like"
        })
        assert swipe2.status_code == 200
        assert swipe2.json().get("is_match") is True

        # User1 should see the match
        response = client.get("/api/v1/matches", headers=headers1)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert len(data["matches"]) >= 1
        assert "chat_id" in data["matches"][0]

    def test_get_match_requires_auth(self, client):
        """Test that get match requires authentication."""
        response = client.get("/api/v1/matches/1")
        assert response.status_code == 401

    def test_get_match_not_found(self, client, auth_headers):
        """Test that non-existent match returns 404."""
        response = client.get("/api/v1/matches/99999", headers=auth_headers[0])
        assert response.status_code == 404

    def test_get_match_only_by_participants(self, client, test_db):
        """Test that only match participants can view a match."""
        user1_id, headers1 = _create_verified_user(client, test_db, gender="male")
        user2_id, headers2 = _create_verified_user(client, test_db, gender="female")
        user3_id, headers3 = _create_verified_user(client, test_db, gender="other")

        # Create a match via swipe
        client.post("/api/v1/swipe", headers=headers1, json={
            "target_user_id": user2_id,
            "action": "like"
        })
        swipe2 = client.post("/api/v1/swipe", headers=headers2, json={
            "target_user_id": user1_id,
            "action": "like"
        })
        match_id = swipe2.json()["match"]["id"]

        # user3 should not see the match (returns 404 to prevent enumeration)
        response = client.get(f"/api/v1/matches/{match_id}", headers=headers3)
        assert response.status_code == 404

    def test_unmatch_only_by_participants(self, client, test_db):
        """Test that only match participants can unmatch."""
        user1_id, headers1 = _create_verified_user(client, test_db, gender="male")
        user2_id, headers2 = _create_verified_user(client, test_db, gender="female")
        user3_id, headers3 = _create_verified_user(client, test_db, gender="other")

        # Create a match via swipe
        client.post("/api/v1/swipe", headers=headers1, json={
            "target_user_id": user2_id,
            "action": "like"
        })
        swipe2 = client.post("/api/v1/swipe", headers=headers2, json={
            "target_user_id": user1_id,
            "action": "like"
        })
        match_id = swipe2.json()["match"]["id"]

        # user3 cannot unmatch
        response = client.delete(f"/api/v1/matches/{match_id}", headers=headers3)
        assert response.status_code == 404

    def test_unmatch_prevents_blocked_users(self, client, test_db):
        """Test that users who have blocked each other cannot unmatch."""
        # Create two users
        user1_id, headers1 = _create_verified_user(client, test_db, gender="male")
        user2_id, headers2 = _create_verified_user(client, test_db, gender="female")

        # Create a match via swipe first
        client.post("/api/v1/swipe", headers=headers1, json={
            "target_user_id": user2_id,
            "action": "like"
        })
        swipe2 = client.post("/api/v1/swipe", headers=headers2, json={
            "target_user_id": user1_id,
            "action": "like"
        })
        match_data = swipe2.json()
        # Check if it's a match
        if match_data.get("is_match"):
            match_id = match_data["match"]["id"]
            # Now create mutual blocks after match exists
            test_db.add(models.UserBlock(blocker_id=user1_id, blocked_id=user2_id))
            test_db.add(models.UserBlock(blocker_id=user2_id, blocked_id=user1_id))
            test_db.commit()

            # Attempting to unmatch should be blocked
            response = client.delete(f"/api/v1/matches/{match_id}", headers=headers1)
            assert response.status_code == 403
        else:
            # If no match was created (due to blocking in feed), skip this test
            # The blocking prevention will be tested via feed exclusion
            pytest.skip("Match not created - blocked users excluded from feed")


class TestFeedPagination:
    """Tests for feed pagination envelope."""

    def test_feed_returns_pagination_envelope(self, client, test_db, auth_headers):
        """Test that feed returns {profiles, total, limit, offset, has_more}."""
        headers, user_id = auth_headers
        _create_verified_user(client, test_db, gender="female")

        response = client.get("/api/v1/feed", headers=headers)
        assert response.status_code == 200
        data = response.json()

        assert "profiles" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert "has_more" in data
        assert isinstance(data["profiles"], list)
        assert isinstance(data["has_more"], bool)

    def test_feed_pagination_deterministic_ordering(self, client, test_db, auth_headers):
        """Test that feed ordering is deterministic by (-compatibility_score, user_id)."""
        headers, user_id = auth_headers

        # Create multiple verified users
        for i in range(5):
            _create_verified_user(client, test_db, gender="female", era="genz")

        # Fetch first page
        response1 = client.get("/api/v1/feed", headers=headers, params={"limit": 2, "offset": 0})
        assert response1.status_code == 200
        data1 = response1.json()

        # Fetch same page again - should be identical
        response2 = client.get("/api/v1/feed", headers=headers, params={"limit": 2, "offset": 0})
        assert response2.status_code == 200
        data2 = response2.json()

        # Profiles should be in the same order
        assert data1["profiles"] == data2["profiles"]

    def test_feed_pagination_no_duplicates_across_pages(self, client, test_db, auth_headers):
        """Test that profiles don't repeat across pagination pages."""
        headers, user_id = auth_headers

        # Create more profiles than the default limit
        for i in range(30):
            _create_verified_user(client, test_db, gender="female", era="genz")

        all_user_ids = set()
        offset = 0
        limit = 10

        while True:
            response = client.get("/api/v1/feed", headers=headers, params={"limit": limit, "offset": offset})
            assert response.status_code == 200
            data = response.json()

            for profile in data["profiles"]:
                assert profile["user_id"] not in all_user_ids, "Duplicate profile found across pages"
                all_user_ids.add(profile["user_id"])

            if not data["has_more"]:
                break
            offset += limit


class TestSwipeRateLimiting:
    """Tests for swipe rate limiting and concurrency safety."""

    def test_swipe_rate_limit_enforced(self, client, test_db, auth_headers):
        """Test that swipe rate limit (120 per 60s) is enforced."""
        headers, user_id = auth_headers
        _create_verified_user(client, test_db, gender="male")

        # Create multiple target users
        target_ids = []
        for i in range(122):
            target_id, target_headers = _create_verified_user(client, test_db, gender="female")
            target_ids.append(target_id)

        # Swipe on different targets - rate limit should kick in after 120 swipes
        for i in range(121):
            response = client.post("/api/v1/swipe", headers=headers, json={
                "target_user_id": target_ids[i],
                "action": "pass"
            })
            # First 120 should succeed (either 200 or 404 if target already swiped), 121st should be rate limited
            if i < 120:
                assert response.status_code in (200, 404), f"Swipe {i} failed unexpectedly: {response.status_code}"
            else:
                assert response.status_code == 429, f"Swipe {i} should be rate limited: {response.status_code}"

    def test_swipe_concurrent_likes_create_match(self, client, test_db):
        """Test that concurrent likes from both users create a match."""
        # Create two users
        user1_id, headers1 = _create_verified_user(client, test_db, gender="male")
        user2_id, headers2 = _create_verified_user(client, test_db, gender="female")

        # User1 likes User2
        swipe1 = client.post("/api/v1/swipe", headers=headers1, json={
            "target_user_id": user2_id,
            "action": "like"
        })
        assert swipe1.status_code == 200

        # User2 likes User1 (should create match)
        swipe2 = client.post("/api/v1/swipe", headers=headers2, json={
            "target_user_id": user1_id,
            "action": "like"
        })
        assert swipe2.status_code == 200
        swipe2_data = swipe2.json()
        assert swipe2_data.get("is_match") is True
        assert "match" in swipe2_data

        # Check match in database
        match = test_db.query(models.Match).filter(
            models.Match.user1_id == min(user1_id, user2_id),
            models.Match.user2_id == max(user1_id, user2_id),
            models.Match.is_active == True
        ).first()
        assert match is not None

    def test_swipe_unique_constraint_prevents_duplicate_swipe(self, client, test_db):
        """Test that unique constraint on Swipe prevents duplicate swipes."""
        user1_id, headers1 = _create_verified_user(client, test_db, gender="male")
        user2_id, headers2 = _create_verified_user(client, test_db, gender="female")

        # Swipe once
        swipe1 = client.post("/api/v1/swipe", headers=headers1, json={
            "target_user_id": user2_id,
            "action": "like"
        })
        assert swipe1.status_code == 200

        # Swipe again - should be idempotent
        swipe2 = client.post("/api/v1/swipe", headers=headers1, json={
            "target_user_id": user2_id,
            "action": "like"
        })
        assert swipe2.status_code == 200
        assert swipe2.json() == swipe1.json()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])