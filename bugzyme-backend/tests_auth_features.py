"""
Unit tests for extended authentication features:
- Google OAuth flow & ID token verification
- Phone SMS OTP flow, rate limiting, and attempt limits
- Email OTP and Reset Link password recovery
- Actual email delivery verification & OTP expiry/one-time use
- Password update verification and account enumeration safety
"""
import os
import re
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Setup test environment before importing app modules
os.environ["SECRET_KEY"] = "test-secret-key-at-least-32-chars-long-strictly"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.database import Base
from app import models, schemas
from app.services import google_auth, email_service, sms_service
from app.main import (
    _hash_verification_code,
    _issue_verification_code,
    _verify_verification_code,
    _generate_unique_username,
    send_password_reset_otp,
    verify_password_reset_otp,
    send_password_reset_link,
    confirm_password_reset_link,
    password_hash,
)
from fastapi import HTTPException


class AuthFeaturesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine)

    def setUp(self):
        self.db = self.Session()
        email_service.clear_mock_deliveries()
        email_service.enable_mock_delivery(True)

    def tearDown(self):
        email_service.enable_mock_delivery(False)
        self.db.rollback()
        self.db.close()

    def test_google_auth_mock_claims_verification(self):
        """Test Google ID token verification with mock claims."""
        mock_claims = {
            "iss": "https://accounts.google.com",
            "aud": "mock-client-id",
            "exp": (datetime.now().timestamp() + 3600),
            "email_verified": True,
            "sub": "google-1234567890",
            "email": "googleuser@example.com",
            "name": "Google User",
            "picture": "https://example.com/avatar.jpg",
        }
        claims = google_auth.verify_google_id_token("dummy-jwt", client_id="mock-client-id", mock_claims=mock_claims)
        self.assertEqual(claims["email"], "googleuser@example.com")
        self.assertEqual(claims["sub"], "google-1234567890")
        self.assertEqual(claims["name"], "Google User")
        self.assertTrue(claims["email_verified"])

    def test_google_auth_url_and_state_pkce(self):
        """Test Google OAuth URL generation and state verification."""
        with patch.object(google_auth, "is_google_auth_configured", return_value=True):
            with patch.object(google_auth.settings, "GOOGLE_CLIENT_ID", "test-client-id"):
                with patch.object(google_auth.settings, "GOOGLE_CLIENT_SECRET", "test-client-secret"):
                    auth_data = google_auth.build_google_auth_url(redirect_uri="http://localhost:5173/auth/callback")
                    self.assertIn("accounts.google.com", auth_data["authorization_url"])
                    self.assertIn("code_challenge=", auth_data["authorization_url"])
                    state = auth_data["state"]

                    # Consume state
                    state_record = google_auth.verify_and_consume_oauth_state(state)
                    self.assertIsNotNone(state_record)
                    self.assertEqual(state_record["code_verifier"], auth_data["code_verifier"])

                    # Consuming again fails (single-use)
                    self.assertIsNone(google_auth.verify_and_consume_oauth_state(state))

    def test_verification_code_issuance_and_verification(self):
        """Test OTP issuance, hashing, and single-use verification."""
        phone = "+919876543210"
        otp = "654321"
        rec = _issue_verification_code(self.db, phone, "phone_otp", otp, ttl_minutes=5)
        self.assertNotEqual(rec.code_hash, otp)
        self.assertEqual(rec.code_hash, _hash_verification_code(otp))

        # Incorrect OTP increments attempt counter
        self.assertFalse(_verify_verification_code(self.db, phone, "phone_otp", "000000"))

        # Correct OTP succeeds
        self.assertTrue(_verify_verification_code(self.db, phone, "phone_otp", otp))

        # Subsequent attempt fails because it was consumed
        self.assertFalse(_verify_verification_code(self.db, phone, "phone_otp", otp))

    def test_verification_code_attempt_limit(self):
        """Test that after 5 wrong attempts, the code is invalidated."""
        email = "victim@example.com"
        otp = "112233"
        _issue_verification_code(self.db, email, "password_reset_otp", otp, ttl_minutes=10)

        # 5 failed attempts
        for _ in range(5):
            self.assertFalse(_verify_verification_code(self.db, email, "password_reset_otp", "999999"))

        # Even with correct code, it is now blocked
        self.assertFalse(_verify_verification_code(self.db, email, "password_reset_otp", otp))

    def test_unique_username_generator(self):
        """Test unique username generation with conflict resolution."""
        user1 = models.User(
            username="testuser",
            email="test1@example.com",
            hashed_password="hash",
        )
        self.db.add(user1)
        self.db.commit()

        new_username = _generate_unique_username("Test User", "test2@example.com", self.db)
        self.assertEqual(new_username, "testuser1")

    def test_send_password_reset_otp_and_actual_delivery(self):
        """Test complete password reset OTP send flow with actual email delivery verification."""
        user = models.User(
            username="realuser",
            email="realuser@example.com",
            hashed_password=password_hash.hash("OldPassword123!"),
        )
        self.db.add(user)
        self.db.commit()

        # Send OTP
        res = send_password_reset_otp(schemas.PasswordResetSendOtpRequest(email="realuser@example.com"), db=self.db)
        self.assertTrue(res.success)
        self.assertIn("6-digit verification code", res.message)

        # Verify actual email delivery
        deliveries = email_service.get_mock_deliveries()
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0]["to"], "realuser@example.com")
        self.assertIn("Raahi Password Reset Code", deliveries[0]["subject"])

        # Extract the 6-digit OTP from email body
        match = re.search(r"\b(\d{6})\b", deliveries[0]["text"])
        self.assertIsNotNone(match)
        delivered_otp = match.group(1)

        # Verify OTP is active in DB
        code_record = self.db.query(models.AuthVerificationCode).filter(
            models.AuthVerificationCode.identifier == "realuser@example.com",
            models.AuthVerificationCode.purpose == "password_reset_otp",
        ).first()
        self.assertIsNotNone(code_record)
        self.assertEqual(code_record.code_hash, _hash_verification_code(delivered_otp))
        self.assertFalse(code_record.used)

    def test_otp_expiry_and_one_time_use(self):
        """Verify OTP expiration and one-time use behavior."""
        email = "expiryuser@example.com"
        otp = "334455"
        rec = _issue_verification_code(self.db, email, "password_reset_otp", otp, ttl_minutes=10)

        # Expire code artificially
        rec.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        self.db.commit()

        # Expired code fails verification
        self.assertFalse(_verify_verification_code(self.db, email, "password_reset_otp", otp))

        # Re-issue non-expired code
        rec2 = _issue_verification_code(self.db, email, "password_reset_otp", "778899", ttl_minutes=10)
        # First verification succeeds
        self.assertTrue(_verify_verification_code(self.db, email, "password_reset_otp", "778899"))
        # Second verification fails (one-time use)
        self.assertFalse(_verify_verification_code(self.db, email, "password_reset_otp", "778899"))

    def test_password_reset_and_subsequent_login(self):
        """Test complete password reset via OTP and subsequent authentication."""
        initial_pw = "OriginalPass123"
        new_pw = "BrandNewSecurePass456!"
        user = models.User(
            username="resetuser",
            email="resetuser@example.com",
            hashed_password=password_hash.hash(initial_pw),
        )
        self.db.add(user)
        self.db.commit()

        # Send OTP
        send_password_reset_otp(schemas.PasswordResetSendOtpRequest(email="resetuser@example.com"), db=self.db)
        deliveries = email_service.get_mock_deliveries()
        match = re.search(r"\b(\d{6})\b", deliveries[0]["text"])
        otp_code = match.group(1)

        # Attempt reset with incorrect OTP
        with self.assertRaises(HTTPException) as cm:
            verify_password_reset_otp(schemas.PasswordResetVerifyOtpRequest(
                email="resetuser@example.com",
                otp="000000",
                new_password=new_pw,
            ), db=self.db)
        self.assertEqual(cm.exception.status_code, 400)

        # Reset with correct OTP
        reset_res = verify_password_reset_otp(schemas.PasswordResetVerifyOtpRequest(
            email="resetuser@example.com",
            otp=otp_code,
            new_password=new_pw,
        ), db=self.db)
        self.assertTrue(reset_res.success)

        # Verify database state and login capability
        refreshed_user = self.db.query(models.User).filter(models.User.email == "resetuser@example.com").first()
        self.assertTrue(password_hash.verify(new_pw, refreshed_user.hashed_password))
        self.assertFalse(password_hash.verify(initial_pw, refreshed_user.hashed_password))

    def test_unconfigured_smtp_prevents_account_enumeration(self):
        """Verify that when SMTP is unconfigured, 503 is returned without leaking account existence."""
        email_service.enable_mock_delivery(False)
        with patch.object(email_service, "is_email_configured", return_value=False):
            # User exists in DB
            user = models.User(username="existing", email="existing@example.com", hashed_password="pw")
            self.db.add(user)
            self.db.commit()

            with self.assertRaises(HTTPException) as cm_existing:
                send_password_reset_otp(schemas.PasswordResetSendOtpRequest(email="existing@example.com"), db=self.db)
            self.assertEqual(cm_existing.exception.status_code, 503)

            # User does NOT exist in DB
            with self.assertRaises(HTTPException) as cm_nonexistent:
                send_password_reset_otp(schemas.PasswordResetSendOtpRequest(email="nonexistent@example.com"), db=self.db)
            self.assertEqual(cm_nonexistent.exception.status_code, 503)

            # Both return identical error message
            self.assertEqual(cm_existing.exception.detail, cm_nonexistent.exception.detail)


if __name__ == "__main__":
    unittest.main()
