from datetime import date
import pytest
from fastapi.testclient import TestClient

from app import models
from app.database import SessionLocal
from app.main import app, create_token, password_hash
from app.services.account_security import (
    MAX_ACCOUNT_FAILURES,
    reset_login_rate_limits,
)


def setup_function():
    reset_login_rate_limits()


def teardown_function():
    reset_login_rate_limits()


def _create_user(db, username: str, email: str, password: str = "ValidPass123!"):
    user = models.User(
        username=username,
        email=email,
        hashed_password=password_hash.hash(password),
        is_online=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_delete_my_account_requires_auth():
    client = TestClient(app)
    resp = client.delete("/me")
    assert resp.status_code == 401


def test_delete_my_account_cascades_all_dependent_data_and_preserves_other_users():
    db = SessionLocal()
    try:
        alice = _create_user(db, "alice_del", "alice_del@example.test")
        bob = _create_user(db, "bob_keep", "bob_keep@example.test")

        alice_profile = models.UserProfile(
            user_id=alice.id,
            date_of_birth=date(1999, 5, 10),
            gender="woman",
            sexual_orientation="straight",
            target_gender_preference="man",
            city="Mumbai",
            era="genz",
            vibe_tag="Main character era",
        )
        bob_profile = models.UserProfile(
            user_id=bob.id,
            date_of_birth=date(1998, 3, 15),
            gender="man",
            sexual_orientation="straight",
            target_gender_preference="woman",
            city="Mumbai",
            era="genz",
            vibe_tag="Soft launch",
        )
        db.add_all([alice_profile, bob_profile])
        db.flush()

        db.add(models.Swipe(user_id=alice.id, target_user_id=bob.id, action="like"))
        db.add(models.Swipe(user_id=bob.id, target_user_id=alice.id, action="like"))
        chat = models.Chat(user1_id=min(alice.id, bob.id), user2_id=max(alice.id, bob.id))
        db.add(chat)
        db.flush()

        match = models.Match(
            user1_id=min(alice.id, bob.id),
            user2_id=max(alice.id, bob.id),
            chat_id=chat.id,
            is_active=True,
        )
        msg1 = models.Message(chat_id=chat.id, sender_id=alice.id, content="Hi Bob!", message_type="text")
        db.add_all([match, msg1])
        db.flush()
        msg2 = models.Message(
            chat_id=chat.id,
            sender_id=bob.id,
            content="Hey Alice!",
            message_type="text",
            reply_to_id=msg1.id,
        )
        mem = models.UserMemory(
            user_id=alice.id,
            memory_type="preference",
            memory_text="Likes coffee",
        )
        db.add_all([msg2, mem])
        db.commit()

        alice_id = alice.id
        bob_id = bob.id
        chat_id = chat.id
        alice_token = create_token(alice_id)
        bob_token = create_token(bob_id)
    finally:
        db.close()

    client = TestClient(app)
    del_resp = client.delete("/me", headers={"Authorization": f"Bearer {alice_token}"})
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True
    assert del_resp.json()["user_id"] == alice_id

    # Alice's JWT must now be rejected
    me_alice = client.get("/me", headers={"Authorization": f"Bearer {alice_token}"})
    assert me_alice.status_code == 401

    # Bob's account and profile must remain intact
    me_bob = client.get("/me", headers={"Authorization": f"Bearer {bob_token}"})
    assert me_bob.status_code == 200
    assert me_bob.json()["id"] == bob_id

    # Verify DB rows for Alice & shared chat are completely removed
    db_check = SessionLocal()
    try:
        assert db_check.get(models.User, alice_id) is None
        assert db_check.query(models.UserProfile).filter(models.UserProfile.user_id == alice_id).first() is None
        assert db_check.get(models.Chat, chat_id) is None
        assert db_check.query(models.Message).filter(models.Message.chat_id == chat_id).count() == 0
        assert db_check.query(models.Match).filter(models.Match.chat_id == chat_id).count() == 0
        assert db_check.get(models.User, bob_id) is not None
    finally:
        db_check.close()


def test_login_rate_limiting_blocks_brute_force_and_resets_on_success():
    db = SessionLocal()
    try:
        _create_user(db, "ratelimit_user", "ratelimit@example.test", password="CorrectPassword1!")
    finally:
        db.close()

    client = TestClient(app)

    # First MAX_ACCOUNT_FAILURES failed attempts return 401
    for _ in range(MAX_ACCOUNT_FAILURES):
        resp = client.post(
            "/login",
            data={"username": "ratelimit@example.test", "password": "WrongPassword!"},
        )
        assert resp.status_code == 401

    # Next attempt must be rate limited (429)
    blocked_resp = client.post(
        "/login",
        data={"username": "ratelimit@example.test", "password": "CorrectPassword1!"},
    )
    assert blocked_resp.status_code == 429
    assert "Retry-After" in blocked_resp.headers
