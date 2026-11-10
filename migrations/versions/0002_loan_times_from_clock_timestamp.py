"""loan times from clock_timestamp()

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-09 13:00:00.000000

now() is the time the transaction began, which can be before the book's lock was taken.
clock_timestamp() is the time the row is written.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "loans",
        "checked_out_at",
        server_default=sa.text("clock_timestamp()"),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "loans",
        "checked_out_at",
        server_default=sa.text("now()"),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
    )
