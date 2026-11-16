import os
from datetime import date, timedelta

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-read-receipt-tests-32chars")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.main import mark_read


def make_db():
    engine = create_engine("sqlite://")
    tables = [
        models.User.__table__,
        models.UserProfile.__table__,
        models.UserBlock.__table__,
        models.Chat.__table__,
        models.Match.__table__,
        models.Message.__table__,
    ]
    models.Base.metadata.create_all(engine, tables=tables)
    return sessionmaker(bind=engine)()


def add_user(db, username):
    user = models.User(username=username, email=f"{username}@example.test", hashed_password="x")
    db.add(user)
    db.flush()
    return user


def test_read_receipt_persists_once_and_only_for_chat_recipient():
    db = make_db()
    sender = add_user(db, "sender")
    recipient = add_user(db, "recipient")
    outsider = add_user(db, "outsider")
    birth_date = date.today() - timedelta(days=365 * 25)
    for user in (sender, recipient):
        db.add(models.UserProfile(
            user_id=user.id,
            date_of_birth=birth_date,
            gender="any",
            city="Test",
            is_face_verified=True,
            is_id_verified=True,
            verification_status="verified",
        ))
    chat = models.Chat(user1_id=sender.id, user2_id=recipient.id)
    db.add(chat)
    db.flush()
    db.add(models.Match(
        user1_id=min(sender.id, recipient.id),
        user2_id=max(sender.id, recipient.id),
        chat_id=chat.id,
    ))
    message = models.Message(chat_id=chat.id, sender_id=sender.id, content="Hello")
    db.add(message)
    db.commit()

    assert mark_read(db, outsider.id, chat.id, None) is None
    db.refresh(message)
    assert message.is_read is False
    assert message.read_at is None

    event = mark_read(db, recipient.id, chat.id, None)
    db.refresh(message)
    first_read_at = message.read_at
    assert event["sender"] == sender.id
    assert event["ids"] == [message.id]
    assert event["read_at"][message.id]
    assert message.is_read is True
    assert message.is_delivered is True
    assert first_read_at is not None

    assert mark_read(db, recipient.id, chat.id, None)["ids"] == []
    db.refresh(message)
    assert message.read_at == first_read_at
    db.close()
