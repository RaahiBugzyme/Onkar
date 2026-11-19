"""add extended dating profile fields (profession, education, relationship_intentions, interests)

Revision ID: b1e2c3d4f5a6
Revises: ca7f31d2b904
Create Date: 2026-11-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "b1e2c3d4f5a6"
down_revision: Union[str, Sequence[str], None] = "ca7f31d2b904"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("user_profiles")}
    additions = (
        sa.Column("profession", sa.String(length=100), nullable=True),
        sa.Column("education", sa.String(length=100), nullable=True),
        sa.Column("relationship_intentions", sa.String(length=60), nullable=True),
        sa.Column("interests", sa.JSON(), nullable=True),
    )
    for column in additions:
        if column.name not in columns:
            op.add_column("user_profiles", column)


def downgrade() -> None:
    # Retain stored dating profile fields on downgrade; removal is non-destructive.
    pass
