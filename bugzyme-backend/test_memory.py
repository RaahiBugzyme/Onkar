import uuid

import pytest

from app import models
from app.database import SessionLocal
from app.ai.memory import save_memory, search_memories


@pytest.fixture
def memory_user():
    with SessionLocal() as db:
        suffix = uuid.uuid4().hex
        user = models.User(
            username=f"memory_{suffix[:20]}",
            email=f"memory_{suffix}@example.test",
            hashed_password="test-only",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        yield db, user.id
        db.rollback()


def test_memory_save_and_search_for_created_user(memory_user):
    db, user_id = memory_user
    memory_text = "Prefers casual conversations and simple questions."

    memory = save_memory(
        db=db,
        user_id=user_id,
        memory_text=memory_text,
        memory_type="preference",
    )
    assert memory.user_id == user_id
    assert memory.memory_text == memory_text

    results = search_memories(
        db=db,
        user_id=user_id,
        query="What communication style does this person prefer?",
    )
    assert any(result.get("memory_text") == memory_text for result in results)
