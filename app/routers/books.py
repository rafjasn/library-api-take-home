from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app import services
from app.db import get_session
from app.schemas import (
    SIX_DIGITS,
    BookCreate,
    BookListQuery,
    BookOut,
    BookPage,
    CheckOut,
    ErrorOut,
    LoanHistoryOut,
    StatusUpdate,
)

router = APIRouter(prefix="/books", tags=["books"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SerialNumberPath = Annotated[
    str, Path(pattern=SIX_DIGITS, description="Six-digit serial number.", examples=["000123"])
]

NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorOut, "description": "No book with this serial number."}
}


def _conflict(description: str) -> dict[int | str, dict[str, Any]]:
    return {409: {"model": ErrorOut, "description": description}}


CREATED_LOCATION: dict[int | str, dict[str, Any]] = {
    201: {
        "headers": {
            "Location": {
                "description": "Path of the new book.",
                "schema": {"type": "string", "examples": ["/books/000123"]},
            }
        }
    }
}

STATUS_UPDATE_EXAMPLES: dict[str, Any] = {
    "check_out": {
        "summary": "Check the book out",
        "value": {"status": "checked_out", "card_number": "654321"},
    },
    "return": {"summary": "Return the book", "value": {"status": "available"}},
}


@router.get("", summary="List books")
async def list_books(session: SessionDep, query: Annotated[BookListQuery, Query()]) -> BookPage:
    """Books ordered by serial number, one page at a time. Optionally filter by `status`."""
    books, total = await services.list_books(session, query.status, query.limit, query.offset)
    return BookPage(
        items=[BookOut.model_validate(book) for book in books],
        total=total,
        limit=query.limit,
        offset=query.offset,
    )


@router.post(
    "",
    status_code=201,
    summary="Add a book",
    responses=CREATED_LOCATION | _conflict("A book with this serial number already exists."),
)
async def create_book(
    body: BookCreate, session: SessionDep, request: Request, response: Response
) -> BookOut:
    book = await services.create_book(session, body)
    response.headers["Location"] = request.app.url_path_for(
        "get_book", serial_number=book.serial_number
    )
    return BookOut.model_validate(book)


@router.get("/{serial_number}", summary="Get a book", responses=NOT_FOUND)
async def get_book(serial_number: SerialNumberPath, session: SessionDep) -> BookOut:
    return BookOut.model_validate(await services.get_book(session, serial_number))


@router.patch(
    "/{serial_number}",
    summary="Check a book out or return it",
    responses=NOT_FOUND | _conflict("The book is already checked out, or is not checked out."),
)
async def update_book_status(
    serial_number: SerialNumberPath,
    body: Annotated[
        StatusUpdate,
        Body(discriminator="status", title="StatusUpdate", openapi_examples=STATUS_UPDATE_EXAMPLES),
    ],
    session: SessionDep,
) -> BookOut:
    """
    - `{"status": "checked_out", "card_number": "654321"}` checks the book out.
    - `{"status": "available"}` marks it as returned.

    The checkout and return times are set by the server.
    """
    if isinstance(body, CheckOut):
        book = await services.check_out(session, serial_number, body.card_number)
    else:
        book = await services.return_book(session, serial_number)
    return BookOut.model_validate(book)


@router.delete(
    "/{serial_number}",
    status_code=204,
    summary="Delete a book",
    responses=NOT_FOUND | _conflict("The book is checked out."),
)
async def delete_book(serial_number: SerialNumberPath, session: SessionDep) -> None:
    """Deletes the book and its loan history. A checked-out book must be returned first."""
    await services.delete_book(session, serial_number)


@router.get("/{serial_number}/loans", summary="Loan history of a book", responses=NOT_FOUND)
async def list_loans(serial_number: SerialNumberPath, session: SessionDep) -> list[LoanHistoryOut]:
    """Every checkout of the book, newest first."""
    loans = await services.list_loans(session, serial_number)
    return [LoanHistoryOut.model_validate(loan) for loan in loans]
