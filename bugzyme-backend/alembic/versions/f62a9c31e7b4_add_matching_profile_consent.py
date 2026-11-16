"""add private matching orientation and behavioral consent fields

Revision ID: f62a9c31e7b4
Revises: e12f3a4b5c6d
Create Date: 2026-11-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "f62a9c31e7b4"
down_revision: Union[str, Sequence[str], None] = "e12f3a4b5c6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("user_profiles")}
    additions = (
        sa.Column("sexual_orientation", sa.String(length=30), nullable=True),
        sa.Column("sexual_orientation_consent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sexual_orientation_consent_version", sa.String(length=40), nullable=True),
        sa.Column("sexual_orientation_consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sexual_orientation_consent_revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("behavioral_personalization_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("behavioral_personalization_consent_version", sa.String(length=40), nullable=True),
        sa.Column("behavioral_personalization_consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("behavioral_personalization_consent_revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in additions:
        if column.name not in columns:
            op.add_column("user_profiles", column)


def downgrade() -> None:
    # Consent and profile data must survive downgrades; removal is intentionally non-destructive.
    pass
