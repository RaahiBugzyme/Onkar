import uuid

import pytest

from app import models
from app.database import SessionLocal
from app.ai.memory import save_memory
from app.models import UserMemory


@pytest.fixture
def memory_user():
    with SessionLocal() as db:
        suffix = uuid.uuid4().hex
        user = models.User(
            username=f"memory_save_{suffix[:18]}",
            email=f"memory_save_{suffix}@example.test",
            hashed_password="test-only",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        yield db, user.id
        db.rollback()


def test_save_memory_prevents_duplicate_records(memory_user):
    db, user_id = memory_user
    test_text = "Testing duplicate memory prevention."

    first = save_memory(
        db=db,
        user_id=user_id,
        memory_text=test_text,
        memory_type="general",
        confidence=0.9,
    )
    second = save_memory(
        db=db,
        user_id=user_id,
        memory_text=test_text,
        memory_type="general",
        confidence=0.9,
    )
    count = db.query(UserMemory).filter(
        UserMemory.user_id == user_id,
        UserMemory.memory_text.ilike(test_text),
    ).count()

    assert first.id == second.id
    assert count == 1
