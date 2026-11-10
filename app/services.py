"""Database operations. Raises domain errors from `app.errors`; knows nothing about HTTP.

Every write locks the book row (SELECT ... FOR UPDATE) first, so concurrent requests
for the same book run one after another. The database constraints (unique serial number,
one open loan per book) still back this up.
"""

from collections.abc import Sequence

from sqlalchemy import ColumnElement, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.errors import (
    BookAlreadyCheckedOut,
    BookCheckedOut,
    BookNotCheckedOut,
    BookNotFound,
    SerialNumberTaken,
)
from app.models import Book, Loan
from app.schemas import BookCreate, BookStatus


async def list_books(
    session: AsyncSession, status: BookStatus | None, limit: int, offset: int
) -> tuple[Sequence[Book], int]:
    """One page of books ordered by serial number, and how many books match in total."""
    filters: list[ColumnElement[bool]] = []
    if status is BookStatus.AVAILABLE:
        filters.append(~Book.current_loan.has())
    elif status is BookStatus.CHECKED_OUT:
        filters.append(Book.current_loan.has())

    total = await session.scalar(select(func.count()).select_from(Book).where(*filters))
    # Books LEFT JOIN their open loan, in one query.
    books = await session.scalars(
        select(Book)
        .where(*filters)
        .options(joinedload(Book.current_loan))
        .order_by(Book.serial_number)
        .limit(limit)
        .offset(offset)
    )
    return books.all(), total or 0


async def get_book(session: AsyncSession, serial_number: str) -> Book:
    book = await session.scalar(
        select(Book)
        .where(Book.serial_number == serial_number)
        .options(joinedload(Book.current_loan))
    )
    if book is None:
        raise BookNotFound(serial_number)
    return book


async def create_book(session: AsyncSession, data: BookCreate) -> Book:
    # ON CONFLICT DO NOTHING instead of catching IntegrityError: no row returned
    # means the serial number is taken, even if another request inserted it a moment ago.
    inserted_id = await session.scalar(
        insert(Book)
        .values(**data.model_dump())
        .on_conflict_do_nothing(index_elements=[Book.serial_number])
        .returning(Book.id)
    )
    if inserted_id is None:
        raise SerialNumberTaken(data.serial_number)
    return await _get_and_commit(session, data.serial_number)


async def delete_book(session: AsyncSession, serial_number: str) -> None:
    book = await _lock_book(session, serial_number)
    open_loan = exists().where(Loan.book_id == book.id, Loan.returned_at.is_(None))
    if await session.scalar(select(open_loan)):
        raise BookCheckedOut(serial_number)
    await session.delete(book)  # its loan history goes too (ON DELETE CASCADE)
    await session.commit()


async def check_out(session: AsyncSession, serial_number: str, card_number: str) -> Book:
    book = await _lock_book(session, serial_number)
    loan_id = await session.scalar(
        insert(Loan)
        .values(book_id=book.id, card_number=card_number)
        .on_conflict_do_nothing(
            index_elements=[Loan.book_id], index_where=Loan.returned_at.is_(None)
        )
        .returning(Loan.id)
    )
    if loan_id is None:
        raise BookAlreadyCheckedOut(serial_number)
    return await _get_and_commit(session, serial_number)


async def return_book(session: AsyncSession, serial_number: str) -> Book:
    book = await _lock_book(session, serial_number)
    loan_id = await session.scalar(
        update(Loan)
        .where(Loan.book_id == book.id, Loan.returned_at.is_(None))
        # The time of this statement, after the lock (see Loan.checked_out_at).
        .values(returned_at=func.clock_timestamp())
        .returning(Loan.id)
    )
    if loan_id is None:
        raise BookNotCheckedOut(serial_number)
    return await _get_and_commit(session, serial_number)


async def list_loans(session: AsyncSession, serial_number: str) -> Sequence[Loan]:
    book_id = await session.scalar(select(Book.id).where(Book.serial_number == serial_number))
    if book_id is None:
        raise BookNotFound(serial_number)
    return (
        await session.scalars(
            select(Loan)
            .where(Loan.book_id == book_id)
            .order_by(Loan.checked_out_at.desc(), Loan.id.desc())
        )
    ).all()


async def _get_and_commit(session: AsyncSession, serial_number: str) -> Book:
    """Read the book, then commit.

    Reading first, while this transaction still holds the book's row lock, means the
    result is exactly the state this request committed. Reading after the commit could
    already show another request's change.
    """
    book = await get_book(session, serial_number)
    await session.commit()
    return book


async def _lock_book(session: AsyncSession, serial_number: str) -> Book:
    book = await session.scalar(
        select(Book).where(Book.serial_number == serial_number).with_for_update()
    )
    if book is None:
        raise BookNotFound(serial_number)
    return book
