"""Response models check what the API sends, with the same rules as requests."""

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas import BookOut, BookPage, LoanHistoryOut

NOW = datetime(2026, 11, 9, 10, 15, tzinfo=UTC)
NO_TIME_ZONE = datetime(2026, 11, 9, 10, 15)
LOAN = {"card_number": "654321", "checked_out_at": NOW, "returned_at": None}
BOOK = {
    "serial_number": "000123",
    "title": "Lalka",
    "author": "Bolesław Prus",
    "current_loan": LOAN,
}


def test_valid_data_passes() -> None:
    """The baseline for the tests below: each of them changes exactly one field."""
    assert BookOut.model_validate(BOOK).status == "checked_out"
    assert LoanHistoryOut.model_validate(LOAN | {"returned_at": NOW}).returned_at == NOW
    BookPage(items=[BookOut.model_validate(BOOK)], total=1, limit=100, offset=0)


@pytest.mark.parametrize(
    ("field", "book"),
    [
        pytest.param("serial_number", BOOK | {"serial_number": "bad"}, id="bad-serial-number"),
        pytest.param("title", BOOK | {"title": ""}, id="empty-title"),
        pytest.param("author", BOOK | {"author": ""}, id="empty-author"),
        pytest.param("title", BOOK | {"title": "  Lalka"}, id="untrimmed-title"),
        pytest.param("title", BOOK | {"title": "La\tlka"}, id="control-character-in-title"),
        pytest.param("author", BOOK | {"author": "x" * 501}, id="author-too-long"),
        pytest.param(
            "card_number",
            BOOK | {"current_loan": LOAN | {"card_number": "bad"}},
            id="bad-card-number",
        ),
        pytest.param(
            "checked_out_at",
            BOOK | {"current_loan": LOAN | {"checked_out_at": NO_TIME_ZONE}},
            id="checkout-time-without-time-zone",
        ),
    ],
)
def test_book_response_rejects_invalid_data(field: str, book: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match=field):
        BookOut.model_validate(book)


def test_loan_history_rejects_return_time_without_time_zone() -> None:
    with pytest.raises(ValidationError, match="returned_at"):
        LoanHistoryOut.model_validate(LOAN | {"returned_at": NO_TIME_ZONE})


@pytest.mark.parametrize(
    ("field", "page"),
    [
        pytest.param("total", {"total": -1, "limit": 100, "offset": 0}, id="negative-total"),
        pytest.param("limit", {"total": 0, "limit": 0, "offset": 0}, id="limit-zero"),
        pytest.param("offset", {"total": 0, "limit": 100, "offset": -1}, id="negative-offset"),
    ],
)
def test_page_rejects_invalid_numbers(field: str, page: dict[str, int]) -> None:
    with pytest.raises(ValidationError, match=field):
        BookPage(items=[], **page)
