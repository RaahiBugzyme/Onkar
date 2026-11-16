import asyncio
from datetime import date

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import main, models
from app.connection_manager import ConnectionManager


class Socket:
    def __init__(self):
        self.events = []
        self.closed = []

    async def send_json(self, payload):
        self.events.append(payload)

    async def close(self, **kwargs):
        self.closed.append(kwargs)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def active_pair(db):
    a = models.User(username="p0_a", email="p0_a@example.test", hashed_password="x")
    b = models.User(username="p0_b", email="p0_b@example.test", hashed_password="x")
    outsider = models.User(username="p0_c", email="p0_c@example.test", hashed_password="x")
    db.add_all([a, b, outsider]); db.flush()
    for user in (a, b, outsider):
        db.add(models.UserProfile(user_id=user.id, date_of_birth=date(1990, 1, 1),
            gender="any", city="Test", is_face_verified=True, is_id_verified=True,
            verification_status="verified"))
    chat = models.Chat(user1_id=a.id, user2_id=b.id); db.add(chat); db.flush()
    match = models.Match(user1_id=a.id, user2_id=b.id, chat_id=chat.id, is_active=True)
    message = models.Message(chat_id=chat.id, sender_id=a.id, content="hello")
    db.add_all([match, message]); db.commit()
    return a, b, outsider, chat, match, message


def test_per_user_chat_removal_filters_only_callers_list(db):
    a, b, _, chat, _, message = active_pair(db)
    assert main.list_chats(current_user=a, db=db)
    result = main.delete_chat_from_database(db, chat.id, a.id)
    assert result["user_id"] == a.id
    assert main.list_chats(current_user=a, db=db) == []
    assert len(main.list_chats(current_user=b, db=db)) == 1
    db.refresh(message)
    assert message.is_deleted is False and message.content == "hello"


def test_message_deletion_supports_global_only_and_rejects_private_mode(db):
    a, _, _, chat, _, message = active_pair(db)
    assert main.soft_delete_message(db, a.id, message.id, False) is None
    db.refresh(message)
    assert message.is_deleted is False and message.content == "hello"
    result = main.soft_delete_message(db, a.id, message.id, True)
    assert result["for_everyone"] is True
    db.refresh(message)
    assert message.is_deleted is True and message.content is None


def test_http_message_delete_rejects_unsupported_private_mode():
    user = models.User(id=12, username="delete", email="delete@example.test", hashed_password="x")
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.delete_message(1, False, user))
    assert error.value.status_code == 422


def test_block_event_is_scoped_and_chat_socket_is_revoked(monkeypatch, db):
    a, b, outsider, chat, _, _ = active_pair(db)
    manager = ConnectionManager()
    monkeypatch.setattr(main, "manager", manager)
    scoped_a, scoped_b = Socket(), Socket()
    global_stranger = Socket()
    manager.connect(a.id, scoped_a, chat.id)
    manager.connect(b.id, scoped_b, chat.id)
    manager.connect(outsider.id, global_stranger)
    asyncio.run(main.notify_chat_access_revoked(
        chat.id, {a.id, b.id},
        {"type": "user_blocked", "blocker_id": a.id, "blocked_id": b.id, "chat_id": chat.id},
    ))
    assert scoped_a.events[0]["type"] == "user_blocked"
    assert scoped_b.events[0]["type"] == "user_blocked"
    assert global_stranger.events == []
    assert scoped_a.closed and scoped_b.closed
    assert global_stranger.closed == []


def test_block_endpoint_does_not_broadcast_to_unrelated_users(monkeypatch, db):
    a, b, outsider, chat, _, _ = active_pair(db)
    manager = ConnectionManager()
    monkeypatch.setattr(main, "manager", manager)
    socket_a, socket_b, socket_outsider = Socket(), Socket(), Socket()
    manager.connect(a.id, socket_a, chat.id)
    manager.connect(b.id, socket_b, chat.id)
    manager.connect(outsider.id, socket_outsider)
    main.block_user(
        main.schemas.BlockCreate(blocked_id=b.id), current_user=a, db=db
    )
    assert [e["type"] for e in socket_a.events] == ["user_blocked"]
    assert [e["type"] for e in socket_b.events] == ["user_blocked"]
    assert socket_outsider.events == []
    assert socket_a.closed and socket_b.closed


def test_unmatch_endpoint_notifies_only_pair_and_revokes_chat_sockets(monkeypatch, db):
    a, b, outsider, chat, match, _ = active_pair(db)
    manager = ConnectionManager()
    monkeypatch.setattr(main, "manager", manager)
    socket_a, socket_b, socket_outsider = Socket(), Socket(), Socket()
    manager.connect(a.id, socket_a, chat.id)
    manager.connect(b.id, socket_b, chat.id)
    manager.connect(outsider.id, socket_outsider)
    result = main.unmatch(match.id, current_user=a, db=db)
    assert result["unmatched"] is True
    assert socket_a.events[0]["type"] == "match_unmatched"
    assert socket_b.events[0]["type"] == "match_unmatched"
    assert socket_outsider.events == []
    assert socket_a.closed and socket_b.closed
    assert main.active_chat_for_interaction(db, chat.id, a.id) is None


def test_active_mutual_match_remains_available_and_revocation_invalidates_ai(db):
    a, b, _, chat, match, message = active_pair(db)
    assert main.active_chat_for_interaction(db, chat.id, a.id) is not None
    notification = models.DeathZoneNotification(
        chat_id=chat.id, user_id=a.id, event_key="p0", trigger_message_id=message.id,
        status="ready", suggestions_json='[{"message":"keep history"}]', death_zone_json="{}",
    )
    state = models.DeathZoneConversationState(chat_id=chat.id, active=True, target_user_id=a.id)
    db.add_all([notification, state]); db.commit()
    main.invalidate_chat_ai_notifications(db, chat.id)
    db.commit()
    db.refresh(notification); db.refresh(state)
    assert notification.status == "invalidated"
    assert "keep history" in notification.suggestions_json
    assert state.active is False and state.target_user_id is None
    match.is_active = False; db.commit()
    assert main.active_chat_for_interaction(db, chat.id, a.id) is None


def test_voice_duration_boundaries_and_metadata_are_validated(db):
    a, _, _, chat, _, _ = active_pair(db)
    lower = main.save_voice_message(db, a.id, chat.id, "a" * 32, "clip.webm",
        "audio/webm", 10, main.MIN_VOICE_DURATION_SECONDS)
    upper = main.save_voice_message(db, a.id, chat.id, "b" * 32, "clip.webm",
        "audio/webm", 10, main.MAX_VOICE_DURATION_SECONDS)
    assert lower["audio_duration"] == 1
    assert upper["audio_duration"] == 300
    assert main.save_voice_message(db, a.id, chat.id, "c" * 32, "clip.webm",
        "audio/webm", 10, 0) is None
    assert main.save_voice_message(db, a.id, chat.id, "d" * 32, "clip.webm",
        "audio/webm", 10, 301) is None
    assert main.save_voice_message(db, a.id, chat.id, "e" * 32, "clip.txt",
        "text/plain", 10, 30) is None
    assert main.save_voice_message(db, a.id, chat.id, "f" * 32, "clip.webm",
        "audio/webm", 0, 30) is None


def test_voice_upload_http_duration_out_of_range_is_rejected_before_storage(monkeypatch, db):
    a, _, _, chat, _, _ = active_pair(db)
    calls = []

    async def save_upload(_file):
        calls.append(True)
        return "a" * 32, "clip.webm", "audio/webm", 10, "voice"

    monkeypatch.setattr(main.attachment_storage, "save_upload", save_upload)
    main.app.dependency_overrides[main.get_current_user] = lambda: a
    main.app.dependency_overrides[main.get_db] = lambda: db
    client = TestClient(main.app)
    try:
        for duration in (0, main.MAX_VOICE_DURATION_SECONDS + 1):
            response = client.post(
                f"/upload-voice?chat_id={chat.id}&duration={duration}",
                files={"file": ("clip.webm", b"synthetic", "audio/webm")},
            )
            assert response.status_code == 422
        assert calls == []
    finally:
        main.app.dependency_overrides.pop(main.get_current_user, None)
        main.app.dependency_overrides.pop(main.get_db, None)
        client.close()


def test_message_is_persisted_and_acknowledged_when_background_ai_fails(monkeypatch, db):
    a, b, _, chat, _, _ = active_pair(db)
    manager = ConnectionManager()
    monkeypatch.setattr(main, "manager", manager)
    tasks = []
    async def guarded_db_call(function, *args):
        if function is main.save_message:
            return main.save_message(db, *args)
        if function is main.mark_delivered:
            return main.mark_delivered(db, *args)
        raise RuntimeError("synthetic background AI failure")
    monkeypatch.setattr(main, "db_call", guarded_db_call)
    monkeypatch.setattr(main, "spawn", lambda coroutine: tasks.append(asyncio.create_task(coroutine)))
    origin = Socket()

    async def run():
        result = await main.process_message(a.id, "sender-name", chat.id,
            "Persist this before optional AI processing.", client_id="client-1", origin=origin)
        await asyncio.gather(*tasks)
        return result

    result = asyncio.run(run())
    assert result["id"] is not None
    assert [event["type"] for event in origin.events] == ["message_sent"]
    stored = db.get(models.Message, result["id"])
    assert stored is not None and stored.content == "Persist this before optional AI processing."


def test_voice_upload_file_is_removed_when_database_persistence_fails(monkeypatch, db):
    a, _, _, chat, _, _ = active_pair(db)
    removed = []

    class Upload:
        async def close(self):
            return None

    async def save_upload(_file):
        return "a" * 32, "clip.webm", "audio/webm", 100, "voice"

    async def fail_db_call(*args):
        raise RuntimeError("synthetic database persistence failure")

    monkeypatch.setattr(main.attachment_storage, "save_upload", save_upload)
    monkeypatch.setattr(main.attachment_storage, "remove_attachment", removed.append)
    monkeypatch.setattr(main, "db_call", fail_db_call)
    with pytest.raises(RuntimeError):
        asyncio.run(main.upload_voice(Upload(), chat.id, 10, current_user=a, db=db))
    assert removed == ["a" * 32]
