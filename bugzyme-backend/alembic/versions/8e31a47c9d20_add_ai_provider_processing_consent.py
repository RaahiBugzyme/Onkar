"""add explicit consent for external AI provider processing

Revision ID: 8e31a47c9d20
Revises: f62a9c31e7b4
Create Date: 2026-11-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "8e31a47c9d20"
down_revision: Union[str, Sequence[str], None] = "f62a9c31e7b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("users")}
    if "ai_provider_processing_enabled" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "ai_provider_processing_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    # This is a privacy preference; preserve it and all user data on downgrade.
    pass
