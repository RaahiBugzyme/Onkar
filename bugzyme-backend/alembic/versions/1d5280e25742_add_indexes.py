"""add indexes

Revision ID: 1d5280e25742
Revises: 
Create Date: 2026-09-14 00:34:57.218899

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '1d5280e25742'
down_revision: Union[str, Sequence[str], None] = "0ab4c9d72e61"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ensure_index(table: str, name: str, columns: list[str]) -> None:
    context = op.get_context()
    if context.as_sql:
        op.create_index(name, table, columns, unique=False, if_not_exists=True)
        return

    bind = op.get_bind()
    indexes = inspect(bind).get_indexes(table)
    named = next((index for index in indexes if index["name"] == name), None)
    if named is not None:
        if (
            named.get("column_names") != columns
            or named.get("unique")
            or named.get("expressions")
            or (named.get("dialect_options") or {}).get("postgresql_where")
        ):
            raise RuntimeError(f"{table}.{name} exists with an incompatible definition")
        return
    # A prior create_all() may have made the same index under a different name.
    # Keep one equivalent index rather than adding a redundant copy.
    if any(
        index.get("column_names") == columns
        and not index.get("unique")
        and not index.get("expressions")
        and not (index.get("dialect_options") or {}).get("postgresql_where")
        for index in indexes
    ):
        return
    op.create_index(name, table, columns, unique=False)


def upgrade() -> None:
    """Ensure the core lookup indexes exist without duplicating equivalents."""
    _ensure_index("chats", "ix_chats_user1", ["user1_id"])
    _ensure_index("chats", "ix_chats_user2", ["user2_id"])
    _ensure_index("messages", "ix_messages_chat_id", ["chat_id"])
    _ensure_index("messages", "ix_messages_sender_id", ["sender_id"])


def downgrade() -> None:
    # Keep core lookup indexes; baseline-created indexes may predate this revision.
    pass
