"""
Milestone 3 Tests: Authentication integration, onboarding and dating profiles.

These tests verify:
- Registration and login integration
- Protected routes
- Profile creation
- Profile updates
- Minimum-age validation
- Profile-photo ownership
- Invalid uploads
- Verification status
- Swipe and match functionality
"""

import pytest
import uuid
import json
from datetime import datetime, timedelta, date
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.main import app
from app import models, database
from unittest.mock import patch, MagicMock
import io
from PIL import Image
import tempfile
from cryptography.fernet import Fernet


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


@pytest.fixture
def auth_headers(client):
    """Register a user and get auth headers."""
    uid = uuid.uuid4().hex[:8]
    username = f"tu_{uid}"
    email = f"tu_{uid}@example.com"
    password = "password123"
    # Register
    response = client.post("/register", json={
        "username": username,
        "email": email,
        "password": password
    })
    assert response.status_code == 201

    # Login
    response = client.post("/login", data={
        "username": email,
        "password": password
    })
    assert response.status_code == 200

    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_dating_user(client, *, gender="male", target_gender="any", era="genz", match_era="any"):
    uid = uuid.uuid4().hex[:10]
    username = f"dating_{uid}"
    email = f"dating_{uid}@example.com"
    response = client.post("/register", json={
        "username": username,
        "email": email,
        "password": "password123",
    })
    assert response.status_code == 201
    user_id = response.json()["id"]
    token_response = client.post("/login", data={
        "username": email,
        "password": "password123",
    })
    assert token_response.status_code == 200
    headers = {"Authorization": f"Bearer {token_response.json()['access_token']}"}
    profile_response = client.post("/api/v1/profile", json={
        "date_of_birth": "1995-05-15",
        "gender": gender,
        "target_gender_preference": target_gender,
        "city": "Mumbai",
        "era": era,
        "match_era_preference": match_era,
    }, headers=headers)
    assert profile_response.status_code == 201
    return user_id, headers


def mark_profile_verified(test_db, user_id):
    profile = test_db.query(models.UserProfile).filter(
        models.UserProfile.user_id == user_id
    ).first()
    assert profile is not None
    profile.is_face_verified = True
    profile.is_id_verified = True
    profile.verification_status = "verified"
    test_db.commit()
    return profile


class TestRegistrationAndLogin:
    """Tests for registration and login integration."""

    def test_register_success(self, client):
        """Test successful user registration."""
        uid = uuid.uuid4().hex[:8]
        response = client.post("/register", json={
            "username": f"newuser_{uid}",
            "email": f"newuser_{uid}@example.com",
            "password": "securepassword"
        })
        assert response.status_code == 201
        data = response.json()
        assert data["username"] == f"newuser_{uid}"
        assert data["email"] == f"newuser_{uid}@example.com"

    def test_register_duplicate_email(self, client):
        """Test that duplicate email registration fails."""
        client.post("/register", json={
            "username": "user1",
            "email": "same@example.com",
            "password": "password123"
        })

        response = client.post("/register", json={
            "username": "user2",
            "email": "same@example.com",
            "password": "password123"
        })
        assert response.status_code == 409

    def test_register_duplicate_username(self, client):
        """Test that duplicate username registration fails."""
        client.post("/register", json={
            "username": "duplicate",
            "email": "user1@example.com",
            "password": "password123"
        })

        response = client.post("/register", json={
            "username": "duplicate",
            "email": "user2@example.com",
            "password": "password123"
        })
        assert response.status_code == 409

    def test_login_success(self, client):
        """Test successful login."""
        client.post("/register", json={
            "username": "loginuser",
            "email": "login@example.com",
            "password": "password123"
        })

        response = client.post("/login", data={
            "username": "login@example.com",
            "password": "password123"
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_invalid_password(self, client):
        """Test login with wrong password fails."""
        client.post("/register", json={
            "username": "wrongpass",
            "email": "wrongpass@example.com",
            "password": "correctpassword"
        })

        response = client.post("/login", data={
            "username": "wrongpass@example.com",
            "password": "wrongpassword"
        })
        assert response.status_code == 401


class TestProtectedRoutes:
    """Tests for protected routes."""

    def test_me_requires_auth(self, client):
        """Test that /me endpoint requires authentication."""
        response = client.get("/me")
        assert response.status_code == 401

    def test_me_with_auth(self, client, auth_headers):
        """Test /me endpoint with valid auth."""
        response = client.get("/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "username" in data and len(data["username"]) > 0
        assert "@" in data["email"]


class TestDatingProfileCreation:
    """Tests for dating profile creation."""

    def test_create_profile_success(self, client, auth_headers):
        """Test successful profile creation."""
        response = client.post("/api/v1/profile", json={
            "date_of_birth": "1995-05-15",
            "gender": "female",
            "city": "Mumbai",
            "era": "genz",
            "target_gender_preference": "any",
            "match_era_preference": "any",
            "vibe_tag": "Talking stage"
        }, headers=auth_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["city"] == "Mumbai"
        assert data["gender"] == "female"
        assert data["era"] == "genz"
        assert data["verification_status"] == "unverified"

    def test_create_profile_duplicate(self, client, auth_headers):
        """Test that creating duplicate profile fails."""
        # First profile
        client.post("/api/v1/profile", json={
            "date_of_birth": "1995-05-15",
            "gender": "female",
            "city": "Mumbai",
            "era": "genz"
        }, headers=auth_headers)

        # Second attempt
        response = client.post("/api/v1/profile", json={
            "date_of_birth": "1995-05-15",
            "gender": "male",
            "city": "Delhi",
            "era": "millennial"
        }, headers=auth_headers)

        assert response.status_code == 409

    def test_get_profile_me(self, client, auth_headers):
        """Test getting current user's profile."""
        # Create profile first
        client.post("/api/v1/profile", json={
            "date_of_birth": "1995-05-15",
            "gender": "female",
            "city": "Mumbai",
            "era": "genz"
        }, headers=auth_headers)

        response = client.get("/api/v1/profile/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["city"] == "Mumbai"

    def test_get_profile_not_found(self, client, auth_headers):
        """Test getting profile when none exists."""
        response = client.get("/api/v1/profile/me", headers=auth_headers)
        assert response.status_code == 404


class TestMinimumAgeValidation:
    """Tests for minimum age validation (18+)."""

    def test_profile_too_young(self, client, auth_headers):
        """Test that users under 18 cannot create profile."""
        # 17 years old
        response = client.post("/api/v1/profile", json={
            "date_of_birth": "2009-05-15",  # Under 18
            "gender": "female",
            "city": "Mumbai",
            "era": "genz"
        }, headers=auth_headers)

        assert response.status_code == 422

    def test_profile_18_years_old(self, client, auth_headers):
        """Test that 18-year-olds can create profile."""
        today = date.today()
        dob = today.replace(year=today.year - 18)

        response = client.post("/api/v1/profile", json={
            "date_of_birth": dob.strftime("%Y-%m-%d"),
            "gender": "female",
            "city": "Mumbai",
            "era": "genz"
        }, headers=auth_headers)

        assert response.status_code == 201

    def test_invalid_date_format(self, client, auth_headers):
        """Test that invalid date format is rejected."""
        response = client.post("/api/v1/profile", json={
            "date_of_birth": "05/15/1995",  # Wrong format
            "gender": "female",
            "city": "Mumbai",
            "era": "genz"
        }, headers=auth_headers)

        assert response.status_code == 422


class TestProfileUpdates:
    """Tests for profile updates."""

    def test_update_profile_city(self, client, auth_headers):
        """Test updating profile city."""
        # Create profile
        client.post("/api/v1/profile", json={
            "date_of_birth": "1995-05-15",
            "gender": "female",
            "city": "Mumbai",
            "era": "genz"
        }, headers=auth_headers)

        # Update
        response = client.put("/api/v1/profile/me", json={
            "city": "Delhi"
        }, headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["city"] == "Delhi"

    def test_update_profile_vibe(self, client, auth_headers):
        """Test updating profile vibe_tag."""
        # Create profile
        client.post("/api/v1/profile", json={
            "date_of_birth": "1995-05-15",
            "gender": "female",
            "city": "Mumbai",
            "era": "genz"
        }, headers=auth_headers)

        # Update vibe
        response = client.put("/api/v1/profile/me", json={
            "vibe_tag": "Main character energy"
        }, headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["vibe_tag"] == "Main character energy"


class TestProfilePhotoUpload:
    """Tests for profile photo upload."""

    def test_upload_valid_image(self, client, auth_headers):
        """Test uploading a valid image."""
        # Create profile first
        client.post("/api/v1/profile", json={
            "date_of_birth": "1995-05-15",
            "gender": "female",
            "city": "Mumbai",
            "era": "genz"
        }, headers=auth_headers)

        # Create a valid PNG image in memory
        img = Image.new('RGB', (100, 100), color='red')
        img_io = io.BytesIO()
        img.save(img_io, 'PNG')
        img_io.seek(0)

        response = client.post(
            "/api/v1/profile/photos",
            files={"file": ("test.png", img_io.getvalue(), "image/png")},
            headers=auth_headers
        )

        assert response.status_code == 201
        data = response.json()
        assert "photo_url" in data
        assert "id" in data

    def test_upload_invalid_file_type(self, client, auth_headers):
        """Test that non-image files are rejected."""
        # Create profile first
        client.post("/api/v1/profile", json={
            "date_of_birth": "1995-05-15",
            "gender": "female",
            "city": "Mumbai",
            "era": "genz"
        }, headers=auth_headers)

        # Try to upload a text file
        response = client.post(
            "/api/v1/profile/photos",
            files={"file": ("test.txt", b"not an image", "text/plain")},
            headers=auth_headers
        )

        assert response.status_code == 400

    def test_upload_too_large_file(self, client, auth_headers):
        """Test that large files are rejected."""
        # Create profile first
        client.post("/api/v1/profile", json={
            "date_of_birth": "1995-05-15",
            "gender": "female",
            "city": "Mumbai",
            "era": "genz"
        }, headers=auth_headers)

        # Create a fake large file (> 10MB)
        large_content = b"x" * (11 * 1024 * 1024)

        response = client.post(
            "/api/v1/profile/photos",
            files={"file": ("large.png", large_content, "image/png")},
            headers=auth_headers
        )

        assert response.status_code == 400


class TestVerificationStatus:
    """Tests for verification status handling."""

    def test_verification_not_falsely_marked(self, client, auth_headers):
        """Test that verification status is NOT automatically set to verified."""
        # Create profile
        client.post("/api/v1/profile", json={
            "date_of_birth": "1995-05-15",
            "gender": "female",
            "city": "Mumbai",
            "era": "genz"
        }, headers=auth_headers)

        # Get profile
        response = client.get("/api/v1/profile/me", headers=auth_headers)
        data = response.json()

        # Should be unverified, NOT verified
        assert data["verification_status"] == "unverified"
        assert data["is_face_verified"] == False
        assert data["is_id_verified"] == False

    def test_face_verification_submission(self, client, auth_headers, test_db, monkeypatch, tmp_path):
        """Test a private encrypted face evidence request without auto-approval."""
        # Create profile
        client.post("/api/v1/profile", json={
            "date_of_birth": "1995-05-15",
            "gender": "female",
            "city": "Mumbai",
            "era": "genz"
        }, headers=auth_headers)

        applicant_id = client.get("/me", headers=auth_headers).json()["id"]
        monkeypatch.setenv("RAAHI_VERIFICATION_REVIEWER_IDS", str(applicant_id))
        monkeypatch.setenv("RAAHI_VERIFICATION_FERNET_KEY", Fernet.generate_key().decode())
        monkeypatch.setenv("RAAHI_VERIFICATION_STORAGE_DIR", str(tmp_path))

        # Create a valid image
        img = Image.new('RGB', (100, 100), color='blue')
        img_io = io.BytesIO()
        img.save(img_io, 'PNG')
        img_io.seek(0)

        response = client.post(
            "/api/v1/verification/face",
            files={"file": ("face.png", img_io.getvalue(), "image/png")},
            headers=auth_headers
        )

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "pending"
        assert data["verification_type"] == "face"

        verification = test_db.query(models.UserVerification).filter_by(
            id=data["verification_id"]
        ).one()
        evidence_key = json.loads(verification.details_json)["evidence_key"]
        encrypted_path = tmp_path / evidence_key
        assert encrypted_path.exists()
        assert not encrypted_path.read_bytes().startswith(b"\x89PNG")
        assert verification.status == "pending"

        status_response = client.get("/api/v1/verification/status", headers=auth_headers)
        assert status_response.json()["current_status"] == "pending"
        assert status_response.json()["is_face_verified"] is False
        assert status_response.json()["verification_available"] is True

    def test_reviewer_workflow_is_private_authorized_and_audited(
        self, client, test_db, monkeypatch, tmp_path
    ):
        applicant_id, applicant_headers = create_dating_user(client)
        reviewer_id, reviewer_headers = create_dating_user(client)
        monkeypatch.setenv("RAAHI_VERIFICATION_REVIEWER_IDS", str(reviewer_id))
        monkeypatch.setenv("RAAHI_VERIFICATION_FERNET_KEY", Fernet.generate_key().decode())
        monkeypatch.setenv("RAAHI_VERIFICATION_STORAGE_DIR", str(tmp_path))

        image = Image.new("RGB", (32, 32), color="purple")
        image_io = io.BytesIO()
        image.save(image_io, format="PNG")
        evidence = image_io.getvalue()

        submission = client.post(
            "/api/v1/verification/face",
            files={"file": ("selfie.png", evidence, "image/png")},
            headers=applicant_headers,
        )
        assert submission.status_code == 201
        verification_id = submission.json()["verification_id"]
        record = test_db.query(models.UserVerification).filter_by(id=verification_id).one()
        evidence_key = json.loads(record.details_json)["evidence_key"]
        assert (tmp_path / evidence_key).read_bytes() != evidence

        # An ordinary user cannot access review routes, even with a valid session.
        assert client.get("/api/v1/reviewer/verifications", headers=applicant_headers).status_code == 403
        assert client.post(
            f"/api/v1/reviewer/verifications/{verification_id}/decision",
            json={"decision": "approve", "reason": "self approval attempt"},
            headers=applicant_headers,
        ).status_code == 403
        # Evidence is not reachable through the public upload mount.
        assert client.get(f"/uploads/{evidence_key}").status_code == 404

        queue = client.get("/api/v1/reviewer/verifications", headers=reviewer_headers)
        assert queue.status_code == 200
        assert any(item["verification_id"] == verification_id for item in queue.json()["items"])
        evidence_response = client.get(
            f"/api/v1/reviewer/verifications/{verification_id}/evidence",
            headers=reviewer_headers,
        )
        assert evidence_response.status_code == 200
        assert evidence_response.content == evidence
        assert evidence_response.headers["cache-control"] == "private, no-store"

        # Even an allowlisted reviewer cannot decide their own submission.
        monkeypatch.setenv("RAAHI_VERIFICATION_REVIEWER_IDS", f"{reviewer_id},{applicant_id}")
        assert client.post(
            f"/api/v1/reviewer/verifications/{verification_id}/decision",
            json={"decision": "approve", "reason": "self approval attempt"},
            headers=applicant_headers,
        ).status_code == 403
        monkeypatch.setenv("RAAHI_VERIFICATION_REVIEWER_IDS", str(reviewer_id))

        decision = client.post(
            f"/api/v1/reviewer/verifications/{verification_id}/decision",
            json={"decision": "approve", "reason": "Face image reviewed"},
            headers=reviewer_headers,
        )
        assert decision.status_code == 200
        assert decision.json()["status"] == "passed"
        assert not (tmp_path / evidence_key).exists()
        audit = json.loads(record.details_json)["review"]
        assert audit["reviewer_user_id"] == reviewer_id
        assert audit["decision"] == "approve"
        assert audit["reason"] == "Face image reviewed"
        assert audit["evidence_sha256"]
        assert json.loads(record.details_json)["evidence_key"] is None
        profile = test_db.query(models.UserProfile).filter_by(user_id=applicant_id).one()
        assert profile.is_face_verified is True
        assert profile.is_id_verified is False

    def test_rejected_request_can_resubmit_and_pending_cannot_duplicate(
        self, client, test_db, monkeypatch, tmp_path
    ):
        applicant_id, applicant_headers = create_dating_user(client)
        reviewer_id, reviewer_headers = create_dating_user(client)
        monkeypatch.setenv("RAAHI_VERIFICATION_REVIEWER_IDS", str(reviewer_id))
        monkeypatch.setenv("RAAHI_VERIFICATION_FERNET_KEY", Fernet.generate_key().decode())
        monkeypatch.setenv("RAAHI_VERIFICATION_STORAGE_DIR", str(tmp_path))

        image_io = io.BytesIO()
        Image.new("RGB", (16, 16), color="teal").save(image_io, format="PNG")
        file = ("id.png", image_io.getvalue(), "image/png")
        submitted = client.post(
            "/api/v1/verification/id",
            data={"id_type": "id_govt"}, files={"file": file}, headers=applicant_headers,
        )
        assert submitted.status_code == 201
        verification_id = submitted.json()["verification_id"]
        assert client.post(
            "/api/v1/verification/id",
            data={"id_type": "id_govt"}, files={"file": file}, headers=applicant_headers,
        ).status_code == 409

        rejected = client.post(
            f"/api/v1/reviewer/verifications/{verification_id}/decision",
            json={"decision": "reject", "reason": "Document image is not readable"},
            headers=reviewer_headers,
        )
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "failed"
        record = test_db.query(models.UserVerification).filter_by(id=verification_id).one()
        rejected_details = json.loads(record.details_json)
        assert rejected_details["review"]["decision"] == "reject"
        assert rejected_details["evidence_key"] is None
        profile = test_db.query(models.UserProfile).filter_by(user_id=applicant_id).one()
        assert profile.is_id_verified is False
        assert profile.verification_status == "rejected"

        resubmitted = client.post(
            "/api/v1/verification/id",
            data={"id_type": "id_govt"}, files={"file": file}, headers=applicant_headers,
        )
        assert resubmitted.status_code == 201
        assert resubmitted.json()["status"] == "pending"

    def test_verification_status_endpoint(self, client, auth_headers, monkeypatch):
        """Test getting verification status."""
        # Create profile
        client.post("/api/v1/profile", json={
            "date_of_birth": "1995-05-15",
            "gender": "female",
            "city": "Mumbai",
            "era": "genz"
        }, headers=auth_headers)

        monkeypatch.delenv("RAAHI_VERIFICATION_REVIEWER_IDS", raising=False)
        monkeypatch.delenv("RAAHI_VERIFICATION_FERNET_KEY", raising=False)
        monkeypatch.delenv("RAAHI_VERIFICATION_STORAGE_DIR", raising=False)
        response = client.get("/api/v1/verification/status", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["current_status"] == "unverified"
        assert data["verification_available"] == False


class TestSwipeAndMatch:
    """Tests for swipe and match functionality."""

    def test_swipe_requires_verification(self, client, auth_headers, test_db):
        """Test that swipe requires both face and ID verification to be approved."""
        # Create profile
        client.post("/api/v1/profile", json={
            "date_of_birth": "1995-05-15",
            "gender": "female",
            "city": "Mumbai",
            "era": "genz"
        }, headers=auth_headers)

        # Try to swipe without verification - should be blocked
        response = client.post("/api/v1/swipe", json={
            "target_user_id": 999,
            "action": "like"
        }, headers=auth_headers)

        assert response.status_code == 403
        assert "Verification required" in response.json()["detail"]

    def test_swipe_like(self, client, auth_headers, test_db):
        """Test swiping like on another user when verified."""
        # Create profile
        client.post("/api/v1/profile", json={
            "date_of_birth": "1995-05-15",
            "gender": "female",
            "city": "Mumbai",
            "era": "genz"
        }, headers=auth_headers)

        # Get the user ID and mark as verified
        response = client.get("/me", headers=auth_headers)
        user_id = response.json()["id"]

        profile = test_db.query(models.UserProfile).filter(
            models.UserProfile.user_id == user_id
        ).first()
        if profile:
            profile.is_face_verified = True
            profile.is_id_verified = True
            profile.verification_status = "verified"
            test_db.commit()

        # Create a second eligible account; verification state is set directly
        # in the test database to represent a trusted reviewer decision.
        target_user_id, _ = create_dating_user(client, gender="male")
        mark_profile_verified(test_db, target_user_id)

        # Swipe on target
        response = client.post("/api/v1/swipe", json={
            "target_user_id": target_user_id,
            "action": "like"
        }, headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["is_match"] == False
        assert response.json()["action"] == "like"

    def test_self_swipe_blocked(self, client, auth_headers, test_db):
        """Test that users cannot swipe on themselves."""
        # Create profile
        client.post("/api/v1/profile", json={
            "date_of_birth": "1995-05-15",
            "gender": "female",
            "city": "Mumbai",
            "era": "genz"
        }, headers=auth_headers)

        # Get own user ID and mark as verified
        response = client.get("/me", headers=auth_headers)
        user_id = response.json()["id"]

        profile = test_db.query(models.UserProfile).filter(
            models.UserProfile.user_id == user_id
        ).first()
        if profile:
            profile.is_face_verified = True
            profile.is_id_verified = True
            profile.verification_status = "verified"
            test_db.commit()

        # Try to swipe on self
        response = client.post("/api/v1/swipe", json={
            "target_user_id": user_id,
            "action": "like"
        }, headers=auth_headers)

        assert response.status_code == 400


class TestBlockAndReport:
    """Tests for block and report functionality."""

    def test_block_user(self, client, auth_headers, test_db):
        """Test blocking a user."""
        # Create profile
        client.post("/api/v1/profile", json={
            "date_of_birth": "1995-05-15",
            "gender": "female",
            "city": "Mumbai",
            "era": "genz"
        }, headers=auth_headers)

        # Create another user
        client.post("/register", json={
            "username": "targetuser2",
            "email": "target2@example.com",
            "password": "password123"
        })

        target_user = test_db.query(models.User).filter(models.User.username == "targetuser2").first()

        response = client.post("/api/v1/blocks", json={
            "blocked_id": target_user.id
        }, headers=auth_headers)

        assert response.status_code in (200, 201)
        assert "blocker_id" in response.json()

    def test_self_block_blocked(self, client, auth_headers):
        """Test that users cannot block themselves."""
        response = client.get("/me", headers=auth_headers)
        user_id = response.json()["id"]

        response = client.post("/api/v1/blocks", json={
            "blocked_id": user_id
        }, headers=auth_headers)

        assert response.status_code == 400


class TestFeedEndpoint:
    """Tests for the feed endpoint."""

    def test_feed_requires_profile(self, client, auth_headers):
        """Test that feed requires a dating profile."""
        response = client.get("/api/v1/feed", headers=auth_headers)
        assert response.status_code == 404

    def test_feed_requires_verification(self, client, auth_headers):
        """Test that feed requires both face and ID verification to be approved."""
        # Create profile
        client.post("/api/v1/profile", json={
            "date_of_birth": "1995-05-15",
            "gender": "female",
            "city": "Mumbai",
            "era": "genz"
        }, headers=auth_headers)

        # Create another user with profile
        response = client.post("/register", json={
            "username": "feedtarget",
            "email": "feedtarget@example.com",
            "password": "password123"
        })

        # Get token for target user
        token_response = client.post("/login", data={
            "username": "feedtarget@example.com",
            "password": "password123"
        })
        token = token_response.json()["access_token"]

        client.post("/api/v1/profile", json={
            "date_of_birth": "1996-06-15",
            "gender": "male",
            "city": "Delhi",
            "era": "genz"
        }, headers={"Authorization": f"Bearer {token}"})

        # Get feed while unverified - should be blocked
        response = client.get("/api/v1/feed", headers=auth_headers)
        assert response.status_code == 403
        assert "Verification required" in response.json()["detail"]

    def test_feed_returns_profiles_when_verified(self, client, auth_headers, test_db):
        """Test that feed returns profiles for verified users."""
        # Create profile
        client.post("/api/v1/profile", json={
            "date_of_birth": "1995-05-15",
            "gender": "female",
            "city": "Mumbai",
            "era": "genz"
        }, headers=auth_headers)

        # Get the user ID and mark as verified
        response = client.get("/me", headers=auth_headers)
        user_id = response.json()["id"]

        profile = test_db.query(models.UserProfile).filter(
            models.UserProfile.user_id == user_id
        ).first()
        if profile:
            profile.is_face_verified = True
            profile.is_id_verified = True
            profile.verification_status = "verified"
            test_db.commit()

        # Create another user with profile
        response = client.post("/register", json={
            "username": "feedtarget_verified",
            "email": "feedtarget_verified@example.com",
            "password": "password123"
        })

        # Get token for target user
        token_response = client.post("/login", data={
            "username": "feedtarget_verified@example.com",
            "password": "password123"
        })
        token = token_response.json()["access_token"]

        client.post("/api/v1/profile", json={
            "date_of_birth": "1996-06-15",
            "gender": "male",
            "city": "Delhi",
            "era": "genz"
        }, headers={"Authorization": f"Bearer {token}"})

        # Get feed
        response = client.get("/api/v1/feed", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        # Feed returns pagination envelope: {profiles, total, limit, offset, has_more}
        assert "profiles" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert "has_more" in data
        assert isinstance(data["profiles"], list)


class TestDatingApiSecurityRegressions:
    def test_profile_updates_cannot_set_verification_fields(self, client, auth_headers):
        created = client.post("/api/v1/profile", json={
            "date_of_birth": "1995-05-15",
            "gender": "female",
            "city": "Mumbai",
            "era": "genz",
        }, headers=auth_headers)
        assert created.status_code == 201

        for protected_values in (
            {"is_face_verified": True, "is_id_verified": True},
            {"is_face_verified": False, "is_id_verified": False},
            {"verification_status": "verified"},
        ):
            response = client.put(
                "/api/v1/profile/me",
                json={"city": "Pune", **protected_values},
                headers=auth_headers,
            )
            assert response.status_code == 422

        normal_update = client.put(
            "/api/v1/profile/me",
            json={"city": "Pune", "vibe_tag": "Reader"},
            headers=auth_headers,
        )
        assert normal_update.status_code == 200
        assert normal_update.json()["city"] == "Pune"
        assert normal_update.json()["vibe_tag"] == "Reader"
        assert normal_update.json()["is_face_verified"] is False
        assert normal_update.json()["is_id_verified"] is False
        assert normal_update.json()["verification_status"] == "unverified"

    def test_unverified_requester_cannot_access_feed_swipe_or_other_profile(
        self, client, auth_headers, test_db
    ):
        own_profile = client.post("/api/v1/profile", json={
            "date_of_birth": "1995-05-15",
            "gender": "female",
            "city": "Mumbai",
            "era": "genz",
        }, headers=auth_headers)
        assert own_profile.status_code == 201
        target_id, _ = create_dating_user(client, gender="male")
        mark_profile_verified(test_db, target_id)

        assert client.get("/api/v1/feed", headers=auth_headers).status_code == 403
        assert client.post("/api/v1/swipe", json={
            "target_user_id": target_id,
            "action": "like",
        }, headers=auth_headers).status_code == 403
        assert client.get(
            f"/api/v1/profile/{target_id}", headers=auth_headers
        ).status_code == 403

    def test_public_profile_requires_mutual_discoverability_and_is_minimal(
        self, client, test_db
    ):
        requester_id, requester_headers = create_dating_user(client, gender="female")
        eligible_id, _ = create_dating_user(client, gender="male")
        blocked_by_requester_id, _ = create_dating_user(client, gender="male")
        blocked_requester_id, _ = create_dating_user(client, gender="male")
        for user_id in (
            requester_id,
            eligible_id,
            blocked_by_requester_id,
            blocked_requester_id,
        ):
            mark_profile_verified(test_db, user_id)

        test_db.add(models.UserBlock(
            blocker_id=requester_id,
            blocked_id=blocked_by_requester_id,
        ))
        test_db.add(models.UserBlock(
            blocker_id=blocked_requester_id,
            blocked_id=requester_id,
        ))
        test_db.commit()

        assert client.get(
            f"/api/v1/profile/{blocked_by_requester_id}", headers=requester_headers
        ).status_code == 404
        assert client.get(
            f"/api/v1/profile/{blocked_requester_id}", headers=requester_headers
        ).status_code == 404

        response = client.get(
            f"/api/v1/profile/{eligible_id}", headers=requester_headers
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["user_id"] == eligible_id
        assert payload["age"] is not None
        assert set(payload) == {
            "user_id", "username", "full_name", "age", "city", "era",
            "vibe_tag", "bio", "compatibility_score",
        }
        assert not {
            "date_of_birth", "gender", "target_gender_preference",
            "match_era_preference", "is_face_verified", "is_id_verified",
            "verification_status", "created_at", "updated_at", "email",
        }.intersection(payload)

    def test_profile_endpoint_rejects_unverified_target(self, client, test_db):
        requester_id, requester_headers = create_dating_user(client, gender="female")
        target_id, _ = create_dating_user(client, gender="male")
        mark_profile_verified(test_db, requester_id)

        response = client.get(
            f"/api/v1/profile/{target_id}", headers=requester_headers
        )
        assert response.status_code == 404

    def test_feed_excludes_unverified_minor_blocked_and_preference_mismatches(
        self, client, test_db
    ):
        requester_id, requester_headers = create_dating_user(
            client, gender="female", target_gender="male", era="genz", match_era="genz"
        )
        eligible_id, _ = create_dating_user(client, gender="male", era="genz")
        unverified_id, _ = create_dating_user(client, gender="male", era="genz")
        minor_id, _ = create_dating_user(client, gender="male", era="genz")
        blocked_by_requester_id, _ = create_dating_user(client, gender="male", era="genz")
        blocked_requester_id, _ = create_dating_user(client, gender="male", era="genz")
        gender_mismatch_id, _ = create_dating_user(
            client, gender="male", target_gender="male", era="genz"
        )
        era_mismatch_id, _ = create_dating_user(client, gender="male", era="millennial")

        mark_profile_verified(test_db, requester_id)
        for user_id in (
            eligible_id,
            minor_id,
            blocked_by_requester_id,
            blocked_requester_id,
            gender_mismatch_id,
            era_mismatch_id,
        ):
            mark_profile_verified(test_db, user_id)

        minor_profile = test_db.query(models.UserProfile).filter_by(user_id=minor_id).one()
        minor_profile.date_of_birth = date.today().replace(year=date.today().year - 17)
        test_db.add(models.UserBlock(blocker_id=requester_id, blocked_id=blocked_by_requester_id))
        test_db.add(models.UserBlock(blocker_id=blocked_requester_id, blocked_id=requester_id))
        test_db.commit()

        returned_ids = set()
        offset = 0
        while True:
            response = client.get(
                "/api/v1/feed", headers=requester_headers,
                params={"limit": 100, "offset": offset},
            )
            assert response.status_code == 200
            feed_data = response.json()
            returned_ids.update(candidate["user_id"] for candidate in feed_data["profiles"])
            if not feed_data["has_more"]:
                break
            offset += feed_data["limit"]
        assert eligible_id in returned_ids
        assert unverified_id not in returned_ids
        assert minor_id not in returned_ids
        assert blocked_by_requester_id not in returned_ids
        assert blocked_requester_id not in returned_ids
        assert gender_mismatch_id not in returned_ids
        assert era_mismatch_id not in returned_ids

    def test_swipe_rejects_ineligible_and_reciprocally_blocked_targets(
        self, client, test_db
    ):
        requester_id, requester_headers = create_dating_user(client, gender="female")
        unverified_id, _ = create_dating_user(client, gender="male")
        blocked_requester_id, _ = create_dating_user(client, gender="male")
        eligible_id, _ = create_dating_user(client, gender="male")
        for user_id in (requester_id, blocked_requester_id, eligible_id):
            mark_profile_verified(test_db, user_id)
        test_db.add(models.UserBlock(
            blocker_id=blocked_requester_id,
            blocked_id=requester_id,
        ))
        test_db.commit()

        unverified_response = client.post("/api/v1/swipe", json={
            "target_user_id": unverified_id,
            "action": "like",
        }, headers=requester_headers)
        blocked_response = client.post("/api/v1/swipe", json={
            "target_user_id": blocked_requester_id,
            "action": "like",
        }, headers=requester_headers)
        assert unverified_response.status_code == 404
        assert blocked_response.status_code == 404
        assert test_db.query(models.Swipe).filter_by(user_id=requester_id).count() == 0

        valid_response = client.post("/api/v1/swipe", json={
            "target_user_id": eligible_id,
            "action": "like",
        }, headers=requester_headers)
        assert valid_response.status_code == 200
        assert valid_response.json()["target_user_id"] == eligible_id


class TestPhaseOneVerificationExpiryAndChatAuthorization:
    def _configured_reviewer(self, client, monkeypatch, tmp_path):
        reviewer_id, reviewer_headers = create_dating_user(client, gender="female")
        monkeypatch.setenv("RAAHI_VERIFICATION_REVIEWER_IDS", str(reviewer_id))
        monkeypatch.setenv("RAAHI_VERIFICATION_FERNET_KEY", Fernet.generate_key().decode())
        monkeypatch.setenv("RAAHI_VERIFICATION_STORAGE_DIR", str(tmp_path))
        return reviewer_id, reviewer_headers

    def _png(self):
        image_io = io.BytesIO()
        Image.new("RGB", (16, 16), color="navy").save(image_io, format="PNG")
        return image_io.getvalue()

    def _matched_pair(self, client, test_db):
        first_id, first_headers = create_dating_user(client, gender="female")
        second_id, second_headers = create_dating_user(client, gender="male")
        mark_profile_verified(test_db, first_id)
        mark_profile_verified(test_db, second_id)
        assert client.post("/api/v1/swipe", headers=first_headers, json={
            "target_user_id": second_id, "action": "like",
        }).status_code == 200
        matched = client.post("/api/v1/swipe", headers=second_headers, json={
            "target_user_id": first_id, "action": "like",
        })
        assert matched.status_code == 200 and matched.json()["is_match"]
        return first_id, first_headers, second_id, second_headers, matched.json()["match"]["chat_id"]

    def test_expired_evidence_cannot_be_downloaded_or_approved(
        self, client, test_db, monkeypatch, tmp_path
    ):
        applicant_id, applicant_headers = create_dating_user(client)
        _, reviewer_headers = self._configured_reviewer(client, monkeypatch, tmp_path)
        submitted = client.post(
            "/api/v1/verification/face",
            files={"file": ("face.png", self._png(), "image/png")},
            headers=applicant_headers,
        )
        assert submitted.status_code == 201
        record = test_db.get(models.UserVerification, submitted.json()["verification_id"])
        record.reviewed_at = datetime.utcnow() - timedelta(days=31)
        test_db.commit()

        evidence = client.get(
            f"/api/v1/reviewer/verifications/{record.id}/evidence",
            headers=reviewer_headers,
        )
        assert evidence.status_code == 410
        decision = client.post(
            f"/api/v1/reviewer/verifications/{record.id}/decision",
            headers=reviewer_headers,
            json={"decision": "approve", "reason": "Evidence is no longer current"},
        )
        assert decision.status_code == 410
        test_db.refresh(record)
        assert record.status == "failed"
        assert json.loads(record.details_json)["retention"]["action"] == "expired"
        assert json.loads(record.details_json)["audit_events"][-1]["event"] == "expired"
        assert test_db.query(models.UserProfile).filter_by(user_id=applicant_id).one().is_face_verified is False

    def test_scheduled_retention_expires_only_pending_evidence_older_than_30_days(
        self, client, test_db, monkeypatch
    ):
        applicant_id, _ = create_dating_user(client)
        old_request = models.UserVerification(
            user_id=applicant_id,
            verification_type="face",
            status="pending",
            details_json=json.dumps({"evidence_key": "expired-evidence"}),
            reviewed_at=datetime.utcnow() - timedelta(days=31),
        )
        active_request = models.UserVerification(
            user_id=applicant_id,
            verification_type="id_govt",
            status="pending",
            details_json=json.dumps({"evidence_key": "active-evidence"}),
            reviewed_at=datetime.utcnow() - timedelta(days=5),
        )
        test_db.add_all([old_request, active_request])
        test_db.commit()

        deleted = []
        monkeypatch.setattr(
            "app.main.verification_storage.delete_evidence",
            lambda key: deleted.append(key) is None,
        )

        from app.main import _run_verification_retention_maintenance
        assert _run_verification_retention_maintenance(test_db) is True
        test_db.refresh(old_request)
        test_db.refresh(active_request)

        assert old_request.status == "failed"
        assert json.loads(old_request.details_json)["retention"]["action"] == "expired"
        assert json.loads(old_request.details_json)["evidence_key"] is None
        assert active_request.status == "pending"
        assert json.loads(active_request.details_json)["evidence_key"] == "active-evidence"
        assert deleted == ["expired-evidence"]

    def test_scheduled_retention_retries_finalized_evidence_cleanup(
        self, client, test_db, monkeypatch
    ):
        applicant_id, _ = create_dating_user(client)
        finalized = models.UserVerification(
            user_id=applicant_id,
            verification_type="face",
            status="failed",
            details_json=json.dumps({"evidence_key": "retry-evidence"}),
            reviewed_at=datetime.utcnow(),
        )
        test_db.add(finalized)
        test_db.commit()

        calls = {"count": 0}

        def fail_once_then_delete(key):
            calls["count"] += 1
            return calls["count"] > 1

        monkeypatch.setattr(
            "app.main.verification_storage.delete_evidence", fail_once_then_delete
        )
        from app.main import _run_verification_retention_maintenance

        assert _run_verification_retention_maintenance(test_db) is True
        test_db.refresh(finalized)
        first = json.loads(finalized.details_json)
        assert first["evidence_cleanup"]["status"] == "retry_pending"
        assert first["evidence_cleanup"]["attempts"] == 1
        assert first["evidence_key"] == "retry-evidence"

        assert _run_verification_retention_maintenance(test_db) is True
        test_db.refresh(finalized)
        second = json.loads(finalized.details_json)
        assert second["evidence_cleanup"]["status"] == "deleted"
        assert second["evidence_cleanup"]["attempts"] == 2
        assert second["evidence_key"] is None

    def test_scheduled_retention_skips_when_another_scheduler_holds_lock(
        self, client, test_db
    ):
        from sqlalchemy.orm import sessionmaker
        from app.main import (
            VERIFICATION_RETENTION_LOCK_ID,
            _run_verification_retention_maintenance,
        )

        holder = database.engine.connect()
        try:
            assert holder.execute(
                __import__("sqlalchemy").text("SELECT pg_try_advisory_lock(:lock_id)"),
                {"lock_id": VERIFICATION_RETENTION_LOCK_ID},
            ).scalar_one() is True
            holder.commit()

            independent_session_factory = sessionmaker(bind=database.engine)
            with independent_session_factory() as competing_db:
                assert _run_verification_retention_maintenance(competing_db) is False
        finally:
            holder.execute(
                __import__("sqlalchemy").text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": VERIFICATION_RETENTION_LOCK_ID},
            )
            holder.commit()
            holder.close()

    def test_legacy_pending_without_evidence_expires_and_can_resubmit(
        self, client, test_db, monkeypatch, tmp_path
    ):
        applicant_id, applicant_headers = create_dating_user(client)
        self._configured_reviewer(client, monkeypatch, tmp_path)
        legacy = models.UserVerification(
            user_id=applicant_id,
            verification_type="face",
            status="pending",
            details_json=None,
            reviewed_at=datetime.utcnow(),
        )
        test_db.add(legacy)
        test_db.commit()
        test_db.refresh(legacy)

        status = client.get("/api/v1/verification/status", headers=applicant_headers)
        assert status.status_code == 200
        test_db.refresh(legacy)
        assert legacy.status == "failed"
        assert json.loads(legacy.details_json)["retention"]["action"] == "legacy_missing_evidence"
        resubmitted = client.post(
            "/api/v1/verification/face",
            files={"file": ("face.png", self._png(), "image/png")},
            headers=applicant_headers,
        )
        assert resubmitted.status_code == 201

    def test_evidence_deletion_failure_is_audited_logged_and_retried(
        self, client, test_db, monkeypatch, tmp_path, caplog
    ):
        applicant_id, applicant_headers = create_dating_user(client)
        _, reviewer_headers = self._configured_reviewer(client, monkeypatch, tmp_path)
        submitted = client.post(
            "/api/v1/verification/face",
            files={"file": ("face.png", self._png(), "image/png")},
            headers=applicant_headers,
        )
        record = test_db.get(models.UserVerification, submitted.json()["verification_id"])
        original_delete = __import__("app.main", fromlist=["verification_storage"]).verification_storage.delete_evidence
        calls = {"count": 0}

        def fail_once(key):
            calls["count"] += 1
            if calls["count"] == 1:
                return False
            return original_delete(key)

        monkeypatch.setattr("app.main.verification_storage.delete_evidence", fail_once)
        decision = client.post(
            f"/api/v1/reviewer/verifications/{record.id}/decision",
            headers=reviewer_headers,
            json={"decision": "reject", "reason": "Image is not sufficiently clear"},
        )
        assert decision.status_code == 200
        assert decision.json()["evidence_deletion_pending"] is True
        test_db.refresh(record)
        details = json.loads(record.details_json)
        assert details["evidence_cleanup"]["status"] == "retry_pending"
        assert details["evidence_cleanup"]["attempts"] == 1
        assert "Verification evidence deletion failed" in caplog.text

        assert client.get("/api/v1/verification/status", headers=applicant_headers).status_code == 200
        test_db.refresh(record)
        assert json.loads(record.details_json)["evidence_key"] is None
        assert json.loads(record.details_json)["evidence_cleanup"]["status"] == "deleted"

    def test_cancellation_deletion_failure_is_retryable(
        self, client, test_db, monkeypatch, tmp_path
    ):
        self._configured_reviewer(client, monkeypatch, tmp_path)
        _, applicant_headers = create_dating_user(client)
        submitted = client.post(
            "/api/v1/verification/face",
            files={"file": ("face.png", self._png(), "image/png")},
            headers=applicant_headers,
        )
        record = test_db.get(models.UserVerification, submitted.json()["verification_id"])
        original_delete = __import__("app.main", fromlist=["verification_storage"]).verification_storage.delete_evidence
        calls = {"count": 0}

        def fail_once(key):
            calls["count"] += 1
            if calls["count"] == 1:
                return False
            return original_delete(key)

        monkeypatch.setattr("app.main.verification_storage.delete_evidence", fail_once)
        cancelled = client.delete(f"/api/v1/verification/{record.id}", headers=applicant_headers)
        assert cancelled.status_code == 200
        assert cancelled.json()["evidence_deletion_pending"] is True
        test_db.refresh(record)
        assert record.status == "cancelled"
        assert json.loads(record.details_json)["evidence_cleanup"]["status"] == "retry_pending"

        client.get("/api/v1/verification/status", headers=applicant_headers)
        test_db.refresh(record)
        assert json.loads(record.details_json)["evidence_key"] is None

    def test_reviewer_cannot_see_own_request_in_queue_or_download_it(
        self, client, monkeypatch, tmp_path
    ):
        applicant_id, applicant_headers = create_dating_user(client)
        reviewer_id, reviewer_headers = self._configured_reviewer(client, monkeypatch, tmp_path)
        monkeypatch.setenv("RAAHI_VERIFICATION_REVIEWER_IDS", f"{applicant_id},{reviewer_id}")
        applicant_request = client.post(
            "/api/v1/verification/face",
            files={"file": ("face.png", self._png(), "image/png")},
            headers=applicant_headers,
        )
        reviewer_request = client.post(
            "/api/v1/verification/face",
            files={"file": ("face.png", self._png(), "image/png")},
            headers=reviewer_headers,
        )
        assert applicant_request.status_code == reviewer_request.status_code == 201
        reviewer_verification_id = reviewer_request.json()["verification_id"]
        queue = client.get("/api/v1/reviewer/verifications", headers=reviewer_headers)
        queue_ids = {item["verification_id"] for item in queue.json()["items"]}
        assert applicant_request.json()["verification_id"] in queue_ids
        assert reviewer_verification_id not in queue_ids
        assert client.get(
            f"/api/v1/reviewer/verifications/{reviewer_verification_id}/evidence",
            headers=reviewer_headers,
        ).status_code == 404

    def test_matches_envelope_and_participant_authorization(self, client, test_db):
        first_id, first_headers, second_id, _, _ = self._matched_pair(client, test_db)
        listing = client.get("/api/v1/matches", headers=first_headers)
        assert listing.status_code == 200
        payload = listing.json()
        assert set(payload) == {"matches", "total", "limit", "offset", "has_more"}
        assert payload["total"] >= 1
        assert any(row["matched_user"]["id"] == second_id for row in payload["matches"])

        match_id = next(row["id"] for row in payload["matches"] if row["matched_user"]["id"] == second_id)
        assert client.get(f"/api/v1/matches/{match_id}", headers=first_headers).status_code == 200
        intruder_id, intruder_headers = create_dating_user(client)
        mark_profile_verified(test_db, intruder_id)
        assert client.get(f"/api/v1/matches/{match_id}", headers=intruder_headers).status_code == 404
        assert client.post("/chats", headers=intruder_headers, json={"user2_id": first_id}).status_code == 403

    def test_chat_writes_require_active_match_but_historical_reads_remain_available(
        self, client, test_db
    ):
        _, first_headers, _, second_headers, chat_id = self._matched_pair(client, test_db)
        sent = client.post("/messages", headers=first_headers, json={
            "chat_id": chat_id, "content": "Existing conversation history",
        })
        assert sent.status_code == 201
        message_id = sent.json()["id"]

        image_io = io.BytesIO()
        Image.new("RGB", (8, 8), color="orange").save(image_io, format="PNG")
        attachment = client.post(
            f"/chats/{chat_id}/attachments",
            headers=first_headers,
            files={"file": ("private.png", image_io.getvalue(), "image/png")},
        )
        assert attachment.status_code == 201
        attachment_id = attachment.json()["id"]
        key = test_db.get(models.Message, attachment_id).attachment_storage_key
        assert client.get(f"/uploads/{key}").status_code == 404

        match = client.get("/api/v1/matches", headers=first_headers).json()["matches"][0]
        unmatch = client.delete(f"/api/v1/matches/{match['id']}", headers=first_headers)
        assert unmatch.status_code == 200
        assert client.get(f"/messages/{chat_id}", headers=first_headers).status_code == 200
        assert client.get(f"/attachments/{attachment_id}/content", headers=second_headers).status_code == 200
        assert client.get(f"/attachments/{attachment_id}/content", headers=create_dating_user(client)[1]).status_code == 404
        assert client.post("/messages", headers=first_headers, json={
            "chat_id": chat_id, "content": "Should be denied after unmatch",
        }).status_code == 403
        assert client.post(
            f"/chats/{chat_id}/attachments",
            headers=first_headers,
            files={"file": ("private.png", b"\x89PNG\r\n\x1a\n" + b"x", "image/png")},
        ).status_code == 403
        assert message_id > 0

        token = first_headers["Authorization"].split()[1]
        from starlette.websockets import WebSocketDisconnect
        with client.websocket_connect(f"/ws/{chat_id}?token={token}") as socket:
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()

    def test_block_prevents_new_chat_writes(self, client, test_db):
        first_id, first_headers, second_id, _, chat_id = self._matched_pair(client, test_db)
        blocked = client.post("/api/v1/blocks", headers=first_headers, json={"blocked_id": second_id})
        assert blocked.status_code == 200
        assert client.post("/messages", headers=first_headers, json={
            "chat_id": chat_id, "content": "Blocked interaction",
        }).status_code == 403
        assert client.post(f"/chats/{chat_id}/suggestions", headers=first_headers, json={}).status_code == 403

    def test_voice_uploads_are_private_and_require_active_match(self, client, test_db):
        _, first_headers, _, second_headers, chat_id = self._matched_pair(client, test_db)
        voice = client.post(
            f"/upload-voice?chat_id={chat_id}",
            headers=first_headers,
            files={"file": ("voice.webm", b"\x1aE\xdf\xa3" + b"private audio", "audio/webm")},
        )
        assert voice.status_code == 200, voice.text
        payload = voice.json()["message"]
        assert payload["audio_url"].startswith("/attachments/")
        message_id = payload["id"]
        assert client.get(payload["audio_url"], headers=second_headers).status_code == 200
        assert client.get(payload["audio_url"], headers=create_dating_user(client)[1]).status_code == 404

        match = client.get("/api/v1/matches", headers=first_headers).json()["matches"][0]
        assert client.delete(f"/api/v1/matches/{match['id']}", headers=first_headers).status_code == 200
        assert client.get(payload["audio_url"], headers=second_headers).status_code == 200
        assert test_db.get(models.Message, message_id).attachment_storage_key


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
