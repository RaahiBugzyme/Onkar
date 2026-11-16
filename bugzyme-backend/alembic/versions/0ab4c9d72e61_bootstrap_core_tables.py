"""bootstrap core Raahi tables and pgvector dependency

Revision ID: 0ab4c9d72e61
Revises:
Create Date: 2026-11-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from pgvector.sqlalchemy import Vector


revision: str = "0ab4c9d72e61"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CORE_TABLES = {
    "users": (
        ("id", "INTEGER", False),
        ("username", "VARCHAR(30)", False),
        ("email", "VARCHAR(254)", False),
        ("hashed_password", "VARCHAR", False),
        ("is_online", "BOOLEAN", False),
        ("last_seen", "TIMESTAMP WITHOUT TIME ZONE", True),
    ),
    "chats": (
        ("id", "INTEGER", False),
        ("user1_id", "INTEGER", False),
        ("user2_id", "INTEGER", False),
        ("deleted_by_user1", "BOOLEAN", False),
        ("deleted_by_user2", "BOOLEAN", False),
    ),
    "messages": (
        ("id", "INTEGER", False),
        ("chat_id", "INTEGER", False),
        ("sender_id", "INTEGER", False),
        ("content", "VARCHAR(2000)", True),
        ("created_at", "TIMESTAMP WITHOUT TIME ZONE", False),
        ("is_delivered", "BOOLEAN", False),
        ("is_read", "BOOLEAN", False),
        ("is_deleted", "BOOLEAN", False),
        ("deleted_at", "TIMESTAMP WITHOUT TIME ZONE", True),
        ("reply_to_id", "INTEGER", True),
        ("message_type", "VARCHAR(20)", False),
        ("audio_url", "VARCHAR(500)", True),
        ("audio_duration", "INTEGER", True),
        ("audio_mime_type", "VARCHAR(100)", True),
    ),
    "user_memories": (
        ("id", "INTEGER", False),
        ("user_id", "INTEGER", False),
        ("memory_text", "TEXT", False),
        ("memory_type", "VARCHAR(30)", False),
        ("confidence", "DOUBLE PRECISION", False),
        ("source_message_id", "INTEGER", True),
        ("embedding", "VECTOR(384)", True),
        ("created_at", "TIMESTAMP WITHOUT TIME ZONE", False),
    ),
}

_CORE_INDEXES = (
    ("users", "ix_users_id", ["id"], False),
    ("users", "ix_users_username", ["username"], True),
    ("users", "ix_users_email", ["email"], True),
    ("chats", "ix_chats_id", ["id"], False),
    ("chats", "ix_chats_user1", ["user1_id"], False),
    ("chats", "ix_chats_user2", ["user2_id"], False),
    ("messages", "ix_messages_id", ["id"], False),
    ("messages", "ix_messages_chat_id", ["chat_id"], False),
    ("messages", "ix_messages_sender_id", ["sender_id"], False),
    ("messages", "ix_messages_reply_to_id", ["reply_to_id"], False),
    ("messages", "ix_messages_chat_id_id", ["chat_id", "id"], False),
    ("messages", "ix_messages_unread", ["chat_id", "sender_id", "is_read"], False),
    ("messages", "ix_messages_undelivered", ["chat_id", "sender_id", "is_delivered"], False),
    ("user_memories", "ix_user_memories_id", ["id"], False),
    ("user_memories", "ix_user_memories_user_id", ["user_id"], False),
    ("user_memories", "ix_user_memories_user_type", ["user_id", "memory_type"], False),
)


def _validate_existing_table(bind, table: str) -> None:
    inspector = inspect(bind)
    actual_columns = {column["name"]: column for column in inspector.get_columns(table)}
    missing = {name for name, _, _ in _CORE_TABLES[table]} - set(actual_columns)
    if missing:
        raise RuntimeError(f"Existing {table} table is incomplete; missing columns: {sorted(missing)}")
    for name, expected_type, nullable in _CORE_TABLES[table]:
        column = actual_columns[name]
        actual_type = column["type"].compile(dialect=bind.dialect).upper()
        compatible_types = {expected_type}
        if expected_type == "FLOAT":
            compatible_types.add("DOUBLE PRECISION")
        if expected_type == "DOUBLE PRECISION":
            compatible_types.add("FLOAT")
        if actual_type not in compatible_types or column["nullable"] != nullable:
            raise RuntimeError(
                f"Existing {table}.{name} is incompatible: expected "
                f"{expected_type} nullable={nullable}; got {actual_type} "
                f"nullable={column['nullable']}"
            )

    expected_primary_key = {"id"} if table != "user_memories" else {"id"}
    actual_primary_key = set((inspector.get_pk_constraint(table).get("constrained_columns") or []))
    if actual_primary_key != expected_primary_key:
        raise RuntimeError(f"Existing {table} primary key is incompatible: {sorted(actual_primary_key)}")

    expected_fks = {
        "chats": {("user1_id", "users", "id", None), ("user2_id", "users", "id", None)},
        "messages": {
            ("chat_id", "chats", "id", None),
            ("sender_id", "users", "id", None),
            ("reply_to_id", "messages", "id", None),
        },
        "user_memories": {
            ("user_id", "users", "id", "CASCADE"),
            ("source_message_id", "messages", "id", "SET NULL"),
        },
    }.get(table, set())
    actual_fks = {
        (
            (fk.get("constrained_columns") or [None])[0],
            fk.get("referred_table"),
            (fk.get("referred_columns") or [None])[0],
            (fk.get("options") or {}).get("ondelete"),
        )
        for fk in inspector.get_foreign_keys(table)
    }
    if not expected_fks.issubset(actual_fks):
        raise RuntimeError(f"Existing {table} table is missing expected foreign keys")

    if table == "chats" and not any(
        constraint.get("name") == "uq_chat_users"
        and constraint.get("column_names") == ["user1_id", "user2_id"]
        for constraint in inspector.get_unique_constraints(table)
    ):
        raise RuntimeError("Existing chats table is missing uq_chat_users")


def _create_tables() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(30), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("is_online", sa.Boolean(), nullable=False),
        sa.Column("last_seen", sa.DateTime(), nullable=True),
        if_not_exists=True,
    )
    op.create_table(
        "chats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user1_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("user2_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("deleted_by_user1", sa.Boolean(), nullable=False),
        sa.Column("deleted_by_user2", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("user1_id", "user2_id", name="uq_chat_users"),
        if_not_exists=True,
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.Integer(), sa.ForeignKey("chats.id"), nullable=False),
        sa.Column("sender_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("content", sa.String(2000), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("is_delivered", sa.Boolean(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("reply_to_id", sa.Integer(), sa.ForeignKey("messages.id"), nullable=True),
        sa.Column("message_type", sa.String(20), nullable=False),
        sa.Column("audio_url", sa.String(500), nullable=True),
        sa.Column("audio_duration", sa.Integer(), nullable=True),
        sa.Column("audio_mime_type", sa.String(100), nullable=True),
        if_not_exists=True,
    )
    op.create_table(
        "user_memories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("memory_text", sa.Text(), nullable=False),
        sa.Column("memory_type", sa.String(30), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_message_id", sa.Integer(), sa.ForeignKey("messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("embedding", Vector(384), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        if_not_exists=True,
    )


def _ensure_index(table: str, name: str, columns: list[str], unique: bool) -> None:
    context = op.get_context()
    if context.as_sql:
        op.create_index(name, table, columns, unique=unique, if_not_exists=True)
        return
    bind = op.get_bind()
    indexes = inspect(bind).get_indexes(table)
    named = next((index for index in indexes if index["name"] == name), None)
    if named is not None:
        if (
            named.get("column_names") != columns
            or bool(named.get("unique")) != unique
            or named.get("expressions")
            or (named.get("dialect_options") or {}).get("postgresql_where")
        ):
            raise RuntimeError(f"Existing {table}.{name} index is incompatible")
        return
    if any(
        index.get("column_names") == columns
        and bool(index.get("unique")) == unique
        and not index.get("expressions")
        and not (index.get("dialect_options") or {}).get("postgresql_where")
        for index in indexes
    ):
        return
    op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    # vector is a database-level prerequisite for the persisted 384D memory embedding.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    bind = op.get_bind()
    existing_tables = set(inspect(bind).get_table_names())
    for table in _CORE_TABLES:
        if table in existing_tables:
            _validate_existing_table(bind, table)
    _create_tables()
    for table in _CORE_TABLES:
        _validate_existing_table(bind, table)
    for table, name, columns, unique in _CORE_INDEXES:
        _ensure_index(table, name, columns, unique)


def downgrade() -> None:
    # Core identity, chat, message and memory data is never removed by downgrade.
    pass
