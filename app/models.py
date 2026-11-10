from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    MetaData,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

SIX_DIGITS_SQL = "'^[0-9]{6}$'"


class Base(DeclarativeBase):
    # Predictable constraint names, so migrations can refer to them.
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class Book(Base):
    __tablename__ = "books"
    __table_args__ = (
        CheckConstraint(f"serial_number ~ {SIX_DIGITS_SQL}", name="serial_number_six_digits"),
        CheckConstraint("title <> ''", name="title_not_empty"),
        CheckConstraint("author <> ''", name="author_not_empty"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    # Entered by library staff. Stored as text: it is an identifier, and "000123" must stay
    # "000123" rather than becoming the integer 123.
    serial_number: Mapped[str] = mapped_column(String(6), unique=True)
    title: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # The open loan, if any. Read-only and never lazy-loaded: queries must load it
    # explicitly (joinedload), which keeps every database call visible in async code.
    current_loan: Mapped[Loan | None] = relationship(
        primaryjoin="and_(Book.id == Loan.book_id, Loan.returned_at.is_(None))",
        viewonly=True,
        lazy="raise",
    )


class Loan(Base):
    """One checkout of a book. `returned_at IS NULL` means the book is still checked out."""

    __tablename__ = "loans"
    __table_args__ = (
        CheckConstraint(f"card_number ~ {SIX_DIGITS_SQL}", name="card_number_six_digits"),
        CheckConstraint(
            "returned_at IS NULL OR returned_at >= checked_out_at",
            name="returned_after_checked_out",
        ),
        # A book can have at most one open loan. Enforced by the database, so two
        # concurrent checkouts of the same book cannot both succeed.
        Index(
            "uq_loans_one_open_loan_per_book",
            "book_id",
            unique=True,
            postgresql_where=text("returned_at IS NULL"),
        ),
        Index("ix_loans_book_id_checked_out_at", "book_id", "checked_out_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    card_number: Mapped[str] = mapped_column(String(6))
    # clock_timestamp() is the time the row is written, after the book was locked. now()
    # would be the time the transaction began, possibly before a competing request got
    # the lock, so a return could be dated before the checkout it closes.
    checked_out_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
