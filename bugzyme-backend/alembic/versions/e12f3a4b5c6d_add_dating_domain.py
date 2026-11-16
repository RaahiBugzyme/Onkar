"""add dating domain tables (user_profiles, profile_photos, swipes, matches, user_blocks, user_reports, user_verifications)

Revision ID: e12f3a4b5c6d
Revises: d9f4b2c81a67
Create Date: 2026-11-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = 'e12f3a4b5c6d'
down_revision = 'd9f4b2c81a67'

def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(inspect(bind).get_table_names())

    # 1. user_profiles — extended dating profile data
    if "user_profiles" not in existing_tables:
        op.create_table(
            "user_profiles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
            sa.Column("date_of_birth", sa.Date(), nullable=False),
            sa.Column("gender", sa.String(length=30), nullable=False),
            sa.Column("target_gender_preference", sa.String(length=30), nullable=False, server_default="any"),
            sa.Column("city", sa.String(length=60), nullable=False),
            sa.Column("era", sa.String(length=20), nullable=False, server_default="genz"),
            sa.Column("vibe_tag", sa.String(length=60), nullable=True),
            sa.Column("match_era_preference", sa.String(length=20), nullable=False, server_default="any"),
            # Verification Gate Status
            sa.Column("is_face_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_id_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("verification_status", sa.String(length=20), nullable=False, server_default="unverified"), # 'unverified', 'pending', 'verified', 'rejected'
            # Verification History (references user_verifications)
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    # 2. profile_photos — ordered profile pictures for swipe cards
    if "profile_photos" not in existing_tables:
        op.create_table(
            "profile_photos",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("profile_id", sa.Integer(), sa.ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("storage_key", sa.String(length=64), nullable=False),
            sa.Column("photo_url", sa.String(length=255), nullable=False),
            sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    # 3. swipes — user swipe actions (like, pass, superlike)
    if "swipes" not in existing_tables:
        op.create_table(
            "swipes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("target_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("action", sa.String(length=20), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("user_id", "target_user_id", name="uq_user_target_swipe"),
            sa.CheckConstraint("action IN ('like', 'pass', 'superlike')", name="ck_swipe_action_valid"),
        )

    # 4. matches — mutual match records linked to a chat room
    if "matches" not in existing_tables:
        op.create_table(
            "matches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user1_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("user2_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("chat_id", sa.Integer(), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, unique=True),
            sa.Column("compatibility_score", sa.Integer(), nullable=False, server_default="85"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("unmatched_at", sa.DateTime(), nullable=True),
            sa.Column("unmatch_reason", sa.String(100), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("user1_id", "user2_id", name="uq_match_user_pair"),
        )

    # 5. user_blocks — block lists and safety
    if "user_blocks" not in existing_tables:
        op.create_table(
            "user_blocks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("blocker_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("blocked_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("blocker_id", "blocked_id", name="uq_blocker_blocked_pair"),
        )

    # 6. user_reports — moderation reports
    if "user_reports" not in existing_tables:
        op.create_table(
            "user_reports",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("reporter_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("reported_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("reason", sa.String(length=100), nullable=False),
            sa.Column("details", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"), # 'pending', 'reviewed', 'actioned'
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    # 7. user_verifications — verification history and logs
    if "user_verifications" not in existing_tables:
        op.create_table(
            "user_verifications",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("verification_type", sa.String(30), nullable=False), # 'face', 'id_college', 'id_work', 'id_govt'
            sa.Column("status", sa.String(20), nullable=False), # 'passed', 'failed'
            sa.Column("details_json", sa.Text(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

def downgrade() -> None:
    # Safe downgrade sequence dropping dating tables in reverse dependency order
    op.drop_table("user_verifications")
    op.drop_table("user_reports")
    op.drop_table("user_blocks")
    op.drop_table("matches")
    op.drop_table("swipes")
    op.drop_table("profile_photos")
    op.drop_table("user_profiles")