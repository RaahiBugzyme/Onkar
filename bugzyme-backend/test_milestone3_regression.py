"""
Milestone 3 Regression Test Suite
Validates the six specific defect fixes:
1. Database connectivity to PostgreSQL 'raahi'
2. Clean SQLAlchemy index declarations (no duplicates)
3. DatingProfileResponse date_of_birth serialization (no ResponseValidationError)
4. GET /api/v1/feed query execution (no Subquery iteration TypeError)
5. SwipeResponse is_match and match detail payload
6. test_milestone3_auth_profile.py import validity
"""

import sys
import os
import unittest
import uuid
from datetime import date, timedelta
from fastapi.testclient import TestClient

from app.main import app
from app import models, database, schemas


class TestMilestone3Regression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def _random_user(self):
        uid = uuid.uuid4().hex[:8]
        return {
            "username": f"m3_reg_{uid}",
            "email": f"m3_reg_{uid}@example.com",
            "password": "Password123!"
        }

    def _auth_user(self):
        user_data = self._random_user()
        r = self.client.post("/register", json=user_data)
        self.assertEqual(r.status_code, 201, f"Register failed: {r.text}")
        user_id = r.json()["id"]

        login_resp = self.client.post("/login", data={
            "username": user_data["email"],
            "password": user_data["password"]
        })
        self.assertEqual(login_resp.status_code, 200, f"Login failed: {login_resp.text}")
        token = login_resp.json()["access_token"]
        return user_id, {"Authorization": f"Bearer {token}"}

    def _mark_profile_verified(self, user_id):
        """Represent an external trusted verification decision in test setup."""
        with database.SessionLocal() as db:
            profile = db.query(models.UserProfile).filter(
                models.UserProfile.user_id == user_id
            ).one()
            profile.is_face_verified = True
            profile.is_id_verified = True
            profile.verification_status = "verified"
            db.commit()

    def _all_feed_ids(self, headers):
        candidate_ids = []
        offset = 0
        while True:
            response = self.client.get(
                "/api/v1/feed", headers=headers,
                params={"limit": 100, "offset": offset},
            )
            self.assertEqual(response.status_code, 200, f"Feed failed: {response.text}")
            data = response.json()
            candidate_ids.extend(row["user_id"] for row in data["profiles"])
            if not data["has_more"]:
                return candidate_ids
            offset += data["limit"]

    def test_issue1_database_connectivity(self):
        """The configured, validated test database is reachable."""
        with database.engine.connect() as conn:
            self.assertIsNotNone(conn)
            from sqlalchemy import text
            row = conn.execute(text("SELECT current_database()")).fetchone()
            expected_database = database.engine.url.database
            self.assertEqual(
                row[0], expected_database,
                f"Expected configured test database '{expected_database}', got '{row[0]}'",
            )

    def test_issue2_no_duplicate_indexes(self):
        """Fix 2: No duplicate index declarations exist on SQLAlchemy models."""
        for table_name in ("user_reports", "user_verifications", "user_memories"):
            table = database.Base.metadata.tables[table_name]
            index_names = [idx.name for idx in table.indexes]
            duplicates = [name for name in index_names if index_names.count(name) > 1]
            self.assertEqual(len(duplicates), 0, f"Table {table_name} has duplicate index declarations: {duplicates}")

    def test_issue3_profile_date_of_birth_serialization(self):
        """Fix 3: DatingProfileResponse serializes date_of_birth without ResponseValidationError."""
        _, headers = self._auth_user()

        dob = (date.today() - timedelta(days=365 * 24)).isoformat()
        # 1. POST /api/v1/profile
        create_resp = self.client.post("/api/v1/profile", headers=headers, json={
            "date_of_birth": dob,
            "gender": "male",
            "city": "Bengaluru",
            "era": "millennial",
            "vibe_tag": "Tech Nomad",
            "match_era_preference": "millennial"
        })
        self.assertEqual(create_resp.status_code, 201, f"Create profile failed: {create_resp.text}")
        data = create_resp.json()
        self.assertEqual(data["date_of_birth"], dob)

        # 2. GET /api/v1/profile/me
        get_resp = self.client.get("/api/v1/profile/me", headers=headers)
        self.assertEqual(get_resp.status_code, 200, f"Get profile failed: {get_resp.text}")
        self.assertEqual(get_resp.json()["date_of_birth"], dob)

        # 3. PUT /api/v1/profile/me
        put_resp = self.client.put("/api/v1/profile/me", headers=headers, json={
            "city": "Hyderabad",
            "vibe_tag": "Foodie & Coder"
        })
        self.assertEqual(put_resp.status_code, 200, f"Update profile failed: {put_resp.text}")
        self.assertEqual(put_resp.json()["city"], "Hyderabad")
        self.assertEqual(put_resp.json()["date_of_birth"], dob)

    def test_issue4_feed_subquery_iteration(self):
        """Fix 4: GET /api/v1/feed executes without TypeError: 'Subquery' object is not iterable."""
        u1_id, h1 = self._auth_user()
        u2_id, h2 = self._auth_user()

        dob = (date.today() - timedelta(days=365 * 23)).isoformat()
        # Create profiles for both users
        self.client.post("/api/v1/profile", headers=h1, json={
            "date_of_birth": dob,
            "gender": "female",
            "city": "Delhi",
            "era": "genz",
            "vibe_tag": "Traveler",
            "match_era_preference": "genz"
        })
        self.client.post("/api/v1/profile", headers=h2, json={
            "date_of_birth": dob,
            "gender": "male",
            "city": "Delhi",
            "era": "genz",
            "vibe_tag": "Photographer",
            "match_era_preference": "genz"
        })

        self._mark_profile_verified(u1_id)
        self._mark_profile_verified(u2_id)

        candidate_ids = self._all_feed_ids(h1)
        self.assertIn(u2_id, candidate_ids, "Candidate u2 should appear in u1's feed")

        # Now swipe on u2 and verify u2 is excluded from subsequent feed
        self.client.post("/api/v1/swipe", headers=h1, json={"target_user_id": u2_id, "action": "pass"})
        candidate_ids_after = self._all_feed_ids(h1)
        self.assertNotIn(u2_id, candidate_ids_after, "Swiped candidate should be excluded from feed")

    def test_issue5_swipe_response_match_payload(self):
        """Fix 5: SwipeResponse includes is_match and match detail dictionary on mutual like."""
        u1_id, h1 = self._auth_user()
        u2_id, h2 = self._auth_user()

        dob = (date.today() - timedelta(days=365 * 25)).isoformat()
        self.client.post("/api/v1/profile", headers=h1, json={
            "date_of_birth": dob,
            "gender": "male",
            "city": "Mumbai",
            "era": "zillenial",
            "match_era_preference": "zillenial"
        })
        self.client.post("/api/v1/profile", headers=h2, json={
            "date_of_birth": dob,
            "gender": "female",
            "city": "Mumbai",
            "era": "zillenial",
            "match_era_preference": "zillenial"
        })

        self._mark_profile_verified(u1_id)
        self._mark_profile_verified(u2_id)

        # User 1 likes User 2 -> no match yet
        s1 = self.client.post("/api/v1/swipe", headers=h1, json={"target_user_id": u2_id, "action": "like"})
        self.assertEqual(s1.status_code, 200)
        self.assertFalse(s1.json().get("is_match"))
        self.assertIsNone(s1.json().get("match"))

        # User 2 likes User 1 -> mutual match!
        s2 = self.client.post("/api/v1/swipe", headers=h2, json={"target_user_id": u1_id, "action": "like"})
        self.assertEqual(s2.status_code, 200)
        s2_data = s2.json()
        self.assertTrue(s2_data.get("is_match"), f"Expected is_match True: {s2_data}")
        match = s2_data.get("match")
        self.assertIsNotNone(match, "Match object should be present in response")
        self.assertGreater(match["chat_id"], 0)
        self.assertIn("matched_user", match)
        self.assertEqual(match["matched_user"]["id"], u1_id)

    def test_issue6_test_file_imports_cleanly(self):
        """Fix 6: test_milestone3_auth_profile.py imports without syntax error."""
        import importlib
        mod = importlib.import_module("test_milestone3_auth_profile")
        self.assertTrue(hasattr(mod, "app"))
        self.assertTrue(hasattr(mod, "models"))
        self.assertTrue(hasattr(mod, "database"))


if __name__ == "__main__":
    unittest.main()
