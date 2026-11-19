"""add auth verification codes table and user phone/auth_provider fields

Revision ID: c2f3a4e5b6c7
Revises: b1e2c3d4f5a6
Create Date: 2026-11-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "c2f3a4e5b6c7"
down_revision: Union[str, Sequence[str], None] = "b1e2c3d4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    # 1. Update users table if columns do not exist
    if "users" in tables:
        user_columns = {col["name"] for col in inspector.get_columns("users")}
        if "phone_number" not in user_columns:
            op.add_column("users", sa.Column("phone_number", sa.String(length=30), nullable=True))
            op.create_index("ix_users_phone_number", "users", ["phone_number"], unique=True)
        if "auth_provider" not in user_columns:
            op.add_column(
                "users",
                sa.Column("auth_provider", sa.String(length=30), nullable=False, server_default="local"),
            )

    # 2. Create auth_verification_codes table if it does not exist
    if "auth_verification_codes" not in tables:
        op.create_table(
            "auth_verification_codes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("identifier", sa.String(length=254), nullable=False),
            sa.Column("purpose", sa.String(length=50), nullable=False),
            sa.Column("code_hash", sa.String(length=128), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_auth_verification_codes_id", "auth_verification_codes", ["id"])
        op.create_index("ix_auth_verification_codes_identifier", "auth_verification_codes", ["identifier"])
        op.create_index(
            "ix_auth_codes_identifier_purpose",
            "auth_verification_codes",
            ["identifier", "purpose"],
        )


def downgrade() -> None:
    pass
