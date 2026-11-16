import asyncio
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import main, models, schemas
from app.connection_manager import ConnectionManager


class FakeSocket:
    def __init__(self):
        self.events = []
        self.closed = []

    async def send_json(self, payload):
        self.events.append(payload)

    async def close(self, **kwargs):
        self.closed.append(kwargs)


@pytest.fixture
def presence_db(monkeypatch):
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    manager = ConnectionManager()
    monkeypatch.setattr(main, "manager", manager)
    try:
        yield db, manager
    finally:
        db.close()
        engine.dispose()


def test_presence_preference_overrides_active_sockets_and_resumes(presence_db):
    db, manager = presence_db
    user = models.User(username="presence_a", email="presence_a@example.test", hashed_password="x")
    viewer = models.User(username="presence_b", email="presence_b@example.test", hashed_password="x")
    outsider = models.User(username="presence_c", email="presence_c@example.test", hashed_password="x")
    db.add_all([user, viewer, outsider]); db.flush()
    for account in (user, viewer, outsider):
        db.add(models.UserProfile(user_id=account.id, date_of_birth=date(1990, 1, 1),
            gender="any", city="Test", is_face_verified=True, is_id_verified=True,
            verification_status="verified"))
    chat = models.Chat(user1_id=user.id, user2_id=viewer.id); db.add(chat); db.flush()
    db.add(models.Match(user1_id=user.id, user2_id=viewer.id, chat_id=chat.id, is_active=True))
    db.commit()

    user_socket_a, user_socket_b, viewer_socket, outsider_socket = FakeSocket(), FakeSocket(), FakeSocket(), FakeSocket()
    manager.connect(user.id, user_socket_a)
    manager.connect(user.id, user_socket_b)
    manager.connect(viewer.id, viewer_socket)
    manager.connect(outsider.id, outsider_socket)

    user.activity_status_enabled = True
    db.commit()
    assert user.id in main.visible_online_ids(db)
    assert next(row for row in main.get_users(viewer, db) if row.id == user.id).is_online is True

    hidden = asyncio.run(main.update_presence_preference(
        schemas.PresencePreferenceUpdate(activity_status_enabled=False), user, db
    ))
    assert hidden["activity_status_enabled"] is False
    assert hidden["is_online"] is False
    assert main.me(user).activity_status_enabled is False  # persisted state used after refresh/login
    assert main.set_online(db, user.id, True)["is_online"] is False  # reconnect/heartbeat cannot override opt-out
    assert user.id not in main.visible_online_ids(db)  # heartbeat/socket remains connected
    assert next(row for row in main.get_users(viewer, db) if row.id == user.id).is_online is False
    assert viewer_socket.events[-1]["status"] == "hidden"
    assert viewer_socket.events[-1]["last_seen"] is None
    assert outsider_socket.events == []

    visible = asyncio.run(main.update_presence_preference(
        schemas.PresencePreferenceUpdate(activity_status_enabled=True), user, db
    ))
    assert visible["activity_status_enabled"] is True
    assert visible["is_online"] is True
    assert user.id in main.visible_online_ids(db)
    assert next(row for row in main.get_users(viewer, db) if row.id == user.id).is_online is True
    assert viewer_socket.events[-1]["status"] == "online"

    # Only an active matched participant receives presence broadcasts.
    asyncio.run(main.broadcast_presence(user.id, "online", "2026-01-01T00:00:00Z", True,
        partners={chat.id: viewer.id}))
    assert viewer_socket.events[-1]["chat_id"] == chat.id
    assert outsider_socket.events == []

    # One of multiple tabs closing must not mark the account offline.
    assert manager.disconnect(user.id, user_socket_a) is False
    assert manager.is_online(user.id) is True
