"""create books and loans

Revision ID: 0001
Revises:
Create Date: 2026-11-09 11:44:02.233952
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "books",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("serial_number", sa.String(length=6), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("author <> ''", name=op.f("ck_books_author_not_empty")),
        sa.CheckConstraint(
            "serial_number ~ '^[0-9]{6}$'", name=op.f("ck_books_serial_number_six_digits")
        ),
        sa.CheckConstraint("title <> ''", name=op.f("ck_books_title_not_empty")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_books")),
        sa.UniqueConstraint("serial_number", name=op.f("uq_books_serial_number")),
    )
    op.create_table(
        "loans",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("book_id", sa.BigInteger(), nullable=False),
        sa.Column("card_number", sa.String(length=6), nullable=False),
        sa.Column(
            "checked_out_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "card_number ~ '^[0-9]{6}$'", name=op.f("ck_loans_card_number_six_digits")
        ),
        sa.CheckConstraint(
            "returned_at IS NULL OR returned_at >= checked_out_at",
            name=op.f("ck_loans_returned_after_checked_out"),
        ),
        sa.ForeignKeyConstraint(
            ["book_id"], ["books.id"], name=op.f("fk_loans_book_id_books"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_loans")),
    )
    op.create_index(
        "ix_loans_book_id_checked_out_at", "loans", ["book_id", "checked_out_at"], unique=False
    )
    op.create_index(
        "uq_loans_one_open_loan_per_book",
        "loans",
        ["book_id"],
        unique=True,
        postgresql_where=sa.text("returned_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_loans_one_open_loan_per_book",
        table_name="loans",
        postgresql_where=sa.text("returned_at IS NULL"),
    )
    op.drop_index("ix_loans_book_id_checked_out_at", table_name="loans")
    op.drop_table("loans")
    op.drop_table("books")
