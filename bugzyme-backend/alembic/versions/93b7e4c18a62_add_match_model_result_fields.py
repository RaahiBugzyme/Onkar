"""add nullable model result provenance to matches

Revision ID: 93b7e4c18a62
Revises: f62a9c31e7b4
Create Date: 2026-11-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision: str = "93b7e4c18a62"
down_revision: Union[str, Sequence[str], None] = "f62a9c31e7b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("matches")}
    additions = (
        sa.Column("raw_compatibility_score", sa.Numeric(7, 4), nullable=True),
        sa.Column("confidence_score", sa.Numeric(7, 4), nullable=True),
        sa.Column("adjusted_score", sa.Numeric(7, 4), nullable=True),
        sa.Column("model_version", sa.String(length=80), nullable=True),
        sa.Column("eligibility_status", sa.Boolean(), nullable=True),
        sa.Column("eligibility_reason", sa.Text(), nullable=True),
        sa.Column("explanation", sa.JSON(), nullable=True),
        sa.Column("component_scores", sa.JSON(), nullable=True),
        sa.Column("prediction_provenance", sa.String(length=40), nullable=True, server_default="legacy"),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in additions:
        if column.name not in columns:
            op.add_column("matches", column)
    # Existing 85 values are retained byte-for-byte, while the new metadata
    # makes clear that those rows predate genuine model predictions.
    bind.execute(text("UPDATE matches SET prediction_provenance = 'legacy' WHERE prediction_provenance IS NULL"))


def downgrade() -> None:
    # Prediction metadata must not be discarded by a downgrade.
    pass
