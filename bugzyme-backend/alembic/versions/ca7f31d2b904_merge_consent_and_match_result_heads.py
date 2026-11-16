"""merge AI consent and match result migration branches

Revision ID: ca7f31d2b904
Revises: 8e31a47c9d20, 93b7e4c18a62
Create Date: 2026-11-13
"""
from typing import Sequence, Union


revision: str = "ca7f31d2b904"
down_revision: Union[str, Sequence[str], None] = (
    "8e31a47c9d20",
    "93b7e4c18a62",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge the existing branches; both schema changes are in parent revisions."""
    pass


def downgrade() -> None:
    """Keep both parent branches applied; merge revisions have no inverse DDL."""
    pass
