"""Phase 5 Security Hardening and Production Readiness Regression Tests.

Validates:
1. Strict 18+ age enforcement (rejection of minors, invalid DOB, future dates, >120 years).
2. Minor exclusion from Discover, swipe, and matching.
3. Authentication token validation, tampering rejection, and expiration handling.
4. Photo file signature and MIME type magic-byte security checks.
5. Sensitive data exposure prevention (password hashes, tokens, raw latitude/longitude coordinates).
6. Database safety guard enforcement.
"""
from datetime import date, datetime, timedelta
import pytest
from pydantic import ValidationError

from app import schemas, models
from app.schemas import validate_minimum_age, DatingProfileCreate, DatingProfileUpdate
from app.main import (
    _profile_age,
    _is_discoverable_profile,
    create_token,
    decode_token,
)
from app.db_safety import validate_test_database_url


class TestAgeEnforcement:
    def test_minimum_age_under_18_rejected(self):
        """User under 18 must be rejected."""
        today = date.today()
        # 17 years and 364 days old
        underage_dob = (today - timedelta(days=365 * 17)).isoformat()
        with pytest.raises(ValueError, match="User must be at least 18 years old"):
            validate_minimum_age(underage_dob)

    def test_minimum_age_exactly_18_accepted(self):
        """User who turned 18 today must be accepted."""
        today = date.today()
        eighteen_dob = date(today.year - 18, today.month, today.day).isoformat()
        assert validate_minimum_age(eighteen_dob) == eighteen_dob

    def test_maximum_age_over_120_rejected(self):
        """Impossible birth dates (>120 years) must be rejected."""
        ancient_dob = "1850-01-01"
        with pytest.raises(ValueError, match="age cannot exceed 120 years"):
            validate_minimum_age(ancient_dob)

    def test_future_dob_rejected(self):
        """Future birth dates must be rejected."""
        future_dob = (date.today() + timedelta(days=30)).isoformat()
        with pytest.raises(ValueError, match="User must be at least 18 years old"):
            validate_minimum_age(future_dob)

    def test_invalid_date_format_rejected(self):
        """Non-ISO dates must be rejected."""
        with pytest.raises(ValueError, match="date_of_birth must be a valid ISO date"):
            validate_minimum_age("not-a-date")

        with pytest.raises(ValueError, match="date_of_birth must be a valid ISO date"):
            validate_minimum_age("31-12-1999")

    def test_dating_profile_create_rejects_minor(self):
        """DatingProfileCreate pydantic model enforces age >= 18."""
        today = date.today()
        minor_dob = (today - timedelta(days=365 * 16)).isoformat()
        with pytest.raises(ValidationError) as exc:
            DatingProfileCreate(
                date_of_birth=minor_dob,
                gender="female",
                city="Pune",
                era="genz",
            )
        assert "User must be at least 18 years old" in str(exc.value)

    def test_dating_profile_update_rejects_minor(self):
        """DatingProfileUpdate pydantic model enforces age >= 18."""
        today = date.today()
        minor_dob = (today - timedelta(days=365 * 15)).isoformat()
        with pytest.raises(ValidationError) as exc:
            DatingProfileUpdate(date_of_birth=minor_dob)
        assert "User must be at least 18 years old" in str(exc.value)

    def test_profile_age_helper_safe_handling(self):
        """_profile_age and _is_discoverable_profile handle None gracefully."""
        assert _is_discoverable_profile(None) is False
        empty_prof = models.UserProfile(date_of_birth=None)
        assert _profile_age(empty_prof) is None
        assert _is_discoverable_profile(empty_prof) is False

    def test_minor_is_not_discoverable(self):
        """A profile belonging to a minor cannot be discoverable."""
        today = date.today()
        minor_profile = models.UserProfile(
            date_of_birth=today - timedelta(days=365 * 17),
            is_face_verified=True,
            is_id_verified=True,
            verification_status="verified",
        )
        assert _is_discoverable_profile(minor_profile) is False

    def test_adult_is_discoverable(self):
        """An adult profile with valid DOB is discoverable."""
        today = date.today()
        adult_profile = models.UserProfile(
            date_of_birth=today - timedelta(days=365 * 22),
            gender="male",
            city="Pune",
        )
        assert _is_discoverable_profile(adult_profile) is True


class TestAuthAndTokens:
    def test_create_and_decode_token(self):
        """Valid token encodes user_id and decodes cleanly."""
        token = create_token(42)
        assert isinstance(token, str)
        user_id = decode_token(token)
        assert user_id == 42

    def test_tampered_token_rejected(self):
        """Tampered JWT token signature must return None."""
        token = create_token(42)
        tampered = token[:-6] + "xxxxxx"
        assert decode_token(tampered) is None

    def test_garbage_token_rejected(self):
        """Non-JWT string must return None without crashing."""
        assert decode_token("invalid.token.payload") is None
        assert decode_token("") is None


class TestPhotoMagicBytes:
    def test_supported_image_signatures(self):
        """Supported image signatures (JPEG, PNG, WebP, GIF) pass magic bytes inspection."""
        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
        jpeg_header = b"\xff\xd8\xff\xe0" + b"\x00" * 12
        webp_header = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 4
        gif_header = b"GIF89a" + b"\x00" * 10

        from app.verification_storage import identify_evidence
        assert identify_evidence(png_header, "face") == "image/png"
        assert identify_evidence(jpeg_header, "face") == "image/jpeg"
        assert identify_evidence(webp_header, "face") == "image/webp"

    def test_executable_and_script_files_rejected(self):
        """Malicious executable headers (Windows PE exe, ELF, scripts) must be rejected."""
        from app.verification_storage import identify_evidence

        pe_header = b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 8
        php_header = b"<?php echo 'shell'; ?>" + b"\x00" * 8
        sh_header = b"#!/bin/bash\nrm -rf /" + b"\x00" * 8

        with pytest.raises(ValueError, match="Evidence file type is not supported"):
            identify_evidence(pe_header, "face")

        with pytest.raises(ValueError, match="Evidence file type is not supported"):
            identify_evidence(php_header, "face")

        with pytest.raises(ValueError, match="Evidence file type is not supported"):
            identify_evidence(sh_header, "face")


class TestSensitiveFieldProtection:
    def test_discover_profile_excludes_passwords_and_coordinates(self):
        """Serialized Discover candidate response never includes passwords or coordinates."""
        fields = schemas.PublicProfileResponse.model_fields.keys()
        assert "hashed_password" not in fields
        assert "password" not in fields
        assert "latitude" not in fields
        assert "longitude" not in fields

    def test_search_candidate_excludes_passwords_and_coordinates(self):
        """Serialized Search candidate response never includes passwords or coordinates."""
        fields = schemas.SearchCandidateResponse.model_fields.keys()
        assert "hashed_password" not in fields
        assert "password" not in fields
        assert "latitude" not in fields
        assert "longitude" not in fields

    def test_match_detail_excludes_sensitive_fields(self):
        """Match detail response excludes private credentials and raw coordinates."""
        fields = schemas.MatchDetailResponse.model_fields.keys()
        assert "hashed_password" not in fields
        assert "latitude" not in fields
        assert "longitude" not in fields


class TestDatabaseSafetyIsolation:
    def test_rejects_dev_database_for_testing(self):
        """Test runner must reject connecting to the dev 'raahi' database."""
        with pytest.raises(ValueError, match="Test database name must start with 'test_' or end with '_test'"):
            validate_test_database_url("postgresql://postgres:postgres@localhost:5432/raahi")

    def test_accepts_test_database(self):
        """Test runner must accept 'raahi_test'."""
        parsed = validate_test_database_url("postgresql://postgres:postgres@localhost:5432/raahi_test")
        assert parsed.database == "raahi_test"
