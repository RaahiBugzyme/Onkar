"""
Standalone verification script for real user experience and search.
Runs all assertions directly against the FastAPI app and local database.
"""
import os
import sys

# Ensure local dev DB is set if not already present
if not os.getenv("DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.getenv(
        "RAAHI_LOCAL_DEV_MIGRATION_URL",
        "postgresql://postgres:password@localhost/raahi"
    )

from datetime import date, timedelta
from uuid import uuid4
from fastapi.testclient import TestClient

from app import database, models, schemas
from app.main import app, get_current_user


def run_verification():
    print("=" * 60)
    print("RAAHI — REAL USER EXPERIENCE & SEARCH VERIFICATION")
    print("=" * 60)

    db = database.SessionLocal()
    tag = uuid4().hex[:8]

    try:
        # 1. Create two real test users
        print("\n[1] Creating real user accounts...")
        u1 = models.User(
            username=f"aarav_{tag}",
            email=f"aarav_{tag}@raahi.in",
            hashed_password="pw_hash_test_1",
            full_name="Aarav Sharma",
            bio="Designer exploring indie coffee and street photography"
        )
        u2 = models.User(
            username=f"diya_{tag}",
            email=f"diya_{tag}@raahi.in",
            hashed_password="pw_hash_test_2",
            full_name="Diya Patel",
            bio="Engineer into coffee, road trips and indie music"
        )
        u3 = models.User(
            username=f"kabir_{tag}",
            email=f"kabir_{tag}@raahi.in",
            hashed_password="pw_hash_test_3",
            full_name="Kabir Khan",
            bio="Architect passionate about heritage structures"
        )
        db.add_all([u1, u2, u3])
        db.flush()

        # 2. Add full dating profiles with new fields
        print("[2] Adding dating profiles with extended fields (profession, education, intentions, interests)...")
        p1 = models.UserProfile(
            user_id=u1.id,
            date_of_birth=date.today() - timedelta(days=365 * 24),
            gender="male",
            city="Mumbai",
            era="genz",
            vibe_tag="Creative",
            profession="UX Designer",
            education="IIT Bombay",
            relationship_intentions="Long-term relationship",
            interests=["Coffee", "Travel", "Photography"],
            is_face_verified=True,
            is_id_verified=True,
            verification_status="verified",
            target_gender_preference="any",
            match_era_preference="any",
        )
        p2 = models.UserProfile(
            user_id=u2.id,
            date_of_birth=date.today() - timedelta(days=365 * 23),
            gender="female",
            city="Mumbai",
            era="genz",
            vibe_tag="Adventurous",
            profession="Software Engineer",
            education="BITS Pilani",
            relationship_intentions="Long-term relationship",
            interests=["Coffee", "Travel", "Music"],
            is_face_verified=True,
            is_id_verified=True,
            verification_status="verified",
            target_gender_preference="any",
            match_era_preference="any",
        )
        p3 = models.UserProfile(
            user_id=u3.id,
            date_of_birth=date.today() - timedelta(days=365 * 29),
            gender="male",
            city="Delhi",
            era="millennial",
            vibe_tag="Architecture",
            profession="Architect",
            education="SPA Delhi",
            relationship_intentions="Casual dating",
            interests=["Architecture", "Cricket"],
            is_face_verified=True,
            is_id_verified=True,
            verification_status="verified",
            target_gender_preference="any",
            match_era_preference="any",
        )
        db.add_all([p1, p2, p3])
        db.flush()

        # Add profile photos
        ph1 = models.ProfilePhoto(profile_id=p1.id, storage_key=f"k1_{tag}", photo_url=f"/uploads/profiles/u1_{tag}.jpg", display_order=1, is_primary=True)
        ph2 = models.ProfilePhoto(profile_id=p2.id, storage_key=f"k2_{tag}", photo_url=f"/uploads/profiles/u2_{tag}.jpg", display_order=1, is_primary=True)
        ph3 = models.ProfilePhoto(profile_id=p3.id, storage_key=f"k3_{tag}", photo_url=f"/uploads/profiles/u3_{tag}.jpg", display_order=1, is_primary=True)
        db.add_all([ph1, ph2, ph3])
        db.commit()

        print("  ✓ Created 3 users, profiles and photos successfully.")

        # Test with TestClient as u1
        app.dependency_overrides[database.get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: u1

        client = TestClient(app)

        # 3. Test Search Endpoint
        print("\n[3] Testing GET /api/v1/search...")
        search_res = client.get("/api/v1/search")
        assert search_res.status_code == 200, f"Expected 200, got {search_res.status_code}: {search_res.text}"
        data = search_res.json()
        assert data["total"] == 2, f"Expected 2 results (u2, u3), got {data['total']}"
        top_result = data["results"][0]
        assert top_result["user_id"] == u2.id, f"Expected top result to be u2 (Diya), got {top_result['user_id']}"
        assert top_result["shared_interests_count"] == 2, f"Expected 2 shared interests, got {top_result['shared_interests_count']}"
        print(f"  ✓ Search returned 2 candidates. Top ranked: {top_result['full_name']} (score: {top_result['relevance_score']}, shared: {top_result['shared_interests']})")

        # Test Search Filters
        print("\n[4] Testing Search filters...")
        # City filter
        res_mumbai = client.get("/api/v1/search?city=Mumbai").json()
        assert res_mumbai["total"] == 1 and res_mumbai["results"][0]["user_id"] == u2.id
        print("  ✓ City filter 'Mumbai' correctly isolated u2.")

        # Profession filter
        res_prof = client.get("/api/v1/search?profession=Architect").json()
        assert res_prof["total"] == 1 and res_prof["results"][0]["user_id"] == u3.id
        print("  ✓ Profession filter 'Architect' correctly isolated u3.")

        # Multi-interest filter
        res_music = client.get("/api/v1/search?interests=Music").json()
        assert res_music["total"] == 1 and res_music["results"][0]["user_id"] == u2.id
        print("  ✓ Interest filter 'Music' correctly matched u2.")

        # Query text search
        res_q = client.get("/api/v1/search?q=coffee").json()
        assert res_q["total"] == 1 and res_q["results"][0]["user_id"] == u2.id
        print("  ✓ Free text query 'coffee' correctly matched u2.")

        # 4. Mutual Like & Match Formation
        print("\n[5] Testing mutual swipe and match creation...")
        # u1 likes u2
        s1 = client.post("/api/v1/swipe", json={"target_user_id": u2.id, "action": "like"}).json()
        assert s1["is_match"] is False, "First swipe should not immediately match"
        print(f"  ✓ User 1 swiped like on User 2 (is_match = {s1['is_match']})")

        # Switch to u2
        app.dependency_overrides[get_current_user] = lambda: u2
        s2 = client.post("/api/v1/swipe", json={"target_user_id": u1.id, "action": "like"}).json()
        assert s2["is_match"] is True, "Second reciprocal swipe must produce is_match = True"
        chat_id = s2["match"]["chat_id"]
        assert chat_id is not None, "Match must have a valid chat_id"
        print(f"  ✓ User 2 swiped like on User 1 -> Mutual Match created! Chat ID: {chat_id}")

        # Check matches list for u2
        matches_res = client.get("/api/v1/matches").json()
        assert any(m["chat_id"] == chat_id for m in matches_res["matches"])
        print(f"  ✓ User 2's /api/v1/matches contains the new mutual match.")

        # 5. Real Chat Messaging (No Demo Responses)
        print("\n[6] Testing real messaging exchange...")
        # u2 sends a message
        msg1_res = client.post(
            "/messages",
            json={"chat_id": chat_id, "content": "Hey Aarav! Loved your design vibe ✦", "message_type": "text"}
        )
        assert msg1_res.status_code == 201, f"Send failed: {msg1_res.text}"
        msg1 = msg1_res.json()
        assert msg1["sender_id"] == u2.id
        print(f"  ✓ User 2 sent real message: '{msg1['content']}'")

        # Switch to u1 and read messages
        app.dependency_overrides[get_current_user] = lambda: u1
        history_res = client.get(f"/messages/{chat_id}").json()
        assert len(history_res) == 1
        assert history_res[0]["content"] == "Hey Aarav! Loved your design vibe ✦"
        print(f"  ✓ User 1 retrieved chat history: 1 real message found.")

        # u1 replies
        msg2_res = client.post(
            "/messages",
            json={"chat_id": chat_id, "content": "Hey Diya! Thanks! Let's grab coffee this weekend ☕", "message_type": "text"}
        )
        assert msg2_res.status_code == 201
        print(f"  ✓ User 1 replied: '{msg2_res.json()['content']}'")

        # Verify chat history has exactly 2 messages (zero simulated/fake responses)
        final_history = client.get(f"/messages/{chat_id}").json()
        assert len(final_history) == 2, f"Expected exactly 2 real messages, found {len(final_history)}"
        assert final_history[0]["sender_id"] == u2.id
        assert final_history[1]["sender_id"] == u1.id
        print(f"  ✓ Final history contains exactly {len(final_history)} messages sent by real users. Zero fake automated replies.")

        # 6. Verify User Block removes profile from search
        print("\n[7] Testing search privacy & block exclusion...")
        block = models.UserBlock(blocker_id=u1.id, blocked_id=u3.id)
        db.add(block)
        db.commit()

        search_blocked = client.get("/api/v1/search").json()
        found_ids = [r["user_id"] for r in search_blocked["results"]]
        assert u3.id not in found_ids, "Blocked user must not appear in search results"
        print("  ✓ Blocked user was correctly excluded from search results.")

        print("\n" + "=" * 60)
        print("ALL VERIFICATION CHECKS PASSED SUCCESSFULLY! ✓")
        print("=" * 60)

    finally:
        app.dependency_overrides.clear()
        # Clean up test rows
        try:
            db.query(models.Message).filter(models.Message.sender_id.in_([u1.id, u2.id, u3.id])).delete(synchronize_session=False)
            db.query(models.Chat).filter(models.Chat.user1_id.in_([u1.id, u2.id, u3.id])).delete(synchronize_session=False)
            db.query(models.Match).filter(models.Match.user1_id.in_([u1.id, u2.id, u3.id])).delete(synchronize_session=False)
            db.query(models.Swipe).filter(models.Swipe.user_id.in_([u1.id, u2.id, u3.id])).delete(synchronize_session=False)
            db.query(models.UserBlock).filter(models.UserBlock.blocker_id.in_([u1.id, u2.id, u3.id])).delete(synchronize_session=False)
            db.query(models.ProfilePhoto).filter(models.ProfilePhoto.profile_id.in_([p1.id, p2.id, p3.id])).delete(synchronize_session=False)
            db.query(models.UserProfile).filter(models.UserProfile.id.in_([p1.id, p2.id, p3.id])).delete(synchronize_session=False)
            db.query(models.User).filter(models.User.id.in_([u1.id, u2.id, u3.id])).delete(synchronize_session=False)
            db.commit()
        except Exception as e:
            print("Cleanup notice:", e)
        finally:
            db.close()


if __name__ == "__main__":
    run_verification()
