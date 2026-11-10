import asyncio
from datetime import datetime
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app import services

BOOK = {"serial_number": "000123", "title": "Lalka", "author": "Bolesław Prus"}
CHECK_OUT = {"status": "checked_out", "card_number": "654321"}
RETURN = {"status": "available"}


async def create(client: AsyncClient, **overrides: str) -> dict[str, Any]:
    response = await client.post("/books", json=BOOK | overrides)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


# --- adding books ---


async def test_create_book(client: AsyncClient) -> None:
    response = await client.post("/books", json=BOOK)

    assert response.status_code == 201
    assert response.headers["location"] == "/books/000123"
    assert response.json() == BOOK | {"status": "available", "current_loan": None}


async def test_create_book_trims_whitespace(client: AsyncClient) -> None:
    book = await create(client, title="  Lalka  ")
    assert book["title"] == "Lalka"


async def test_create_book_with_taken_serial_number_conflicts(client: AsyncClient) -> None:
    await create(client)

    response = await client.post("/books", json=BOOK | {"title": "Another title"})

    assert response.status_code == 409
    assert response.json() == {"detail": "A book with serial number 000123 already exists."}


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(BOOK | {"serial_number": "12345"}, id="serial-too-short"),
        pytest.param(BOOK | {"serial_number": "1234567"}, id="serial-too-long"),
        pytest.param(BOOK | {"serial_number": "12345a"}, id="serial-not-digits"),
        pytest.param(BOOK | {"serial_number": "١٢٣٤٥٦"}, id="serial-non-ascii-digits"),
        pytest.param(BOOK | {"serial_number": 123456}, id="serial-as-integer"),
        pytest.param(BOOK | {"title": "   "}, id="blank-title"),
        pytest.param(BOOK | {"author": ""}, id="empty-author"),
        pytest.param({"serial_number": "000123", "title": "Lalka"}, id="missing-author"),
        pytest.param(BOOK | {"isbn": "978-83-01"}, id="unknown-field"),
        pytest.param(BOOK | {"title": "La\x00lka"}, id="nul-in-title"),
        pytest.param(BOOK | {"title": "Lalka\nTom 2"}, id="line-break-in-title"),
        pytest.param(BOOK | {"author": "Bolesław\tPrus"}, id="tab-in-author"),
    ],
)
async def test_create_book_rejects_invalid_input(client: AsyncClient, body: Any) -> None:
    response = await client.post("/books", json=body)
    assert response.status_code == 422


async def test_control_characters_get_a_clear_message(client: AsyncClient) -> None:
    response = await client.post("/books", json=BOOK | {"title": "La\x00lka"})

    assert response.status_code == 422
    [error] = response.json()["detail"]
    assert error["type"] == "control_characters"
    assert error["loc"] == ["body", "title"]


async def test_validation_errors_do_not_echo_the_input(client: AsyncClient) -> None:
    response = await client.post("/books", json=BOOK | {"serial_number": "12345"})

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "type": "string_pattern_mismatch",
                "loc": ["body", "serial_number"],
                "msg": "String should match pattern '^[0-9]{6}$'",
            }
        ]
    }


@pytest.mark.parametrize(
    ("method", "path", "raw_body"),
    [
        pytest.param(
            "POST",
            "/books",
            rb'{"serial_number": "000123", "title": "\ud800", "author": "x"}',
            id="lone-surrogate-in-value",
        ),
        pytest.param(
            "POST",
            "/books",
            rb'{"serial_number": "000123", "title": "x", "author": "x", "\ud800": 1}',
            id="lone-surrogate-in-key",
        ),
        pytest.param(
            "POST",
            "/books",
            b'{"serial_number": "000123", "title": 1e999, "author": "x"}',
            id="overflowing-number",
        ),
        pytest.param(
            "POST",
            "/books",
            b'{"serial_number": "000123", "title": NaN, "author": "x"}',
            id="nan",
        ),
        pytest.param(
            "POST",
            "/books",
            b'{"serial_number": "000123", "title": "x", "author": "x", "pages": 1e999}',
            id="overflowing-number-in-unknown-field",
        ),
        pytest.param(
            "PATCH",
            "/books/000123",
            b'{"status": "checked_out", "card_number": -Infinity}',
            id="infinity-in-status-change",
        ),
    ],
)
async def test_input_that_json_cannot_echo_gets_422_not_500(
    client: AsyncClient, method: str, path: str, raw_body: bytes
) -> None:
    """Python's JSON parser accepts values that strict JSON can't send back.

    A lone surrogate has no UTF-8 encoding, and NaN or infinity (1e999 overflows to
    infinity) aren't JSON. The 422 response must still render.
    """
    response = await client.request(
        method, path, content=raw_body, headers={"content-type": "application/json"}
    )

    assert response.status_code == 422
    assert response.json()["detail"]  # valid JSON, with the error listed


# --- listing and reading ---


async def test_list_books_is_empty_at_first(client: AsyncClient) -> None:
    response = await client.get("/books")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 100, "offset": 0}


async def test_list_books_sorted_by_serial_number_and_filtered_by_status(
    client: AsyncClient,
) -> None:
    await create(client, serial_number="200000")
    await create(client, serial_number="100000")
    await client.patch("/books/200000", json=CHECK_OUT)

    every = (await client.get("/books")).json()
    available = (await client.get("/books", params={"status": "available"})).json()
    checked_out = (await client.get("/books", params={"status": "checked_out"})).json()

    assert [b["serial_number"] for b in every["items"]] == ["100000", "200000"]
    assert [b["serial_number"] for b in available["items"]] == ["100000"]
    assert [b["serial_number"] for b in checked_out["items"]] == ["200000"]
    assert (every["total"], available["total"], checked_out["total"]) == (2, 1, 1)
    assert checked_out["items"][0]["current_loan"]["card_number"] == "654321"


async def test_list_books_in_pages(client: AsyncClient) -> None:
    for serial_number in ["000001", "000002", "000003", "000004", "000005"]:
        await create(client, serial_number=serial_number)

    page = (await client.get("/books", params={"limit": 2, "offset": 2})).json()
    past_the_end = (await client.get("/books", params={"offset": 10})).json()

    assert [b["serial_number"] for b in page["items"]] == ["000003", "000004"]
    assert (page["total"], page["limit"], page["offset"]) == (5, 2, 2)
    assert past_the_end["items"] == []
    assert past_the_end["total"] == 5


@pytest.mark.parametrize(
    "params",
    [
        pytest.param({"status": "lost"}, id="unknown-status"),
        pytest.param({"limit": 0}, id="limit-zero"),
        pytest.param({"limit": 1001}, id="limit-too-big"),
        pytest.param({"offset": -1}, id="negative-offset"),
        pytest.param({"offset": 2**63}, id="offset-beyond-bigint"),
        pytest.param({"limit": "ten"}, id="limit-not-a-number"),
        pytest.param({"page": 2}, id="unknown-parameter"),
    ],
)
async def test_list_books_rejects_invalid_query(client: AsyncClient, params: Any) -> None:
    response = await client.get("/books", params=params)
    assert response.status_code == 422


async def test_get_book(client: AsyncClient) -> None:
    await create(client)
    response = await client.get("/books/000123")
    assert response.status_code == 200
    assert response.json()["title"] == "Lalka"


async def test_get_unknown_book(client: AsyncClient) -> None:
    response = await client.get("/books/999999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Book 999999 not found."}


async def test_malformed_serial_number_in_path(client: AsyncClient) -> None:
    response = await client.get("/books/abc")
    assert response.status_code == 422


# --- checking out and returning ---


async def test_check_out_book(client: AsyncClient) -> None:
    await create(client)

    response = await client.patch("/books/000123", json=CHECK_OUT)

    assert response.status_code == 200
    book = response.json()
    assert book["status"] == "checked_out"
    assert book["current_loan"]["card_number"] == "654321"
    assert datetime.fromisoformat(book["current_loan"]["checked_out_at"]).tzinfo is not None


async def test_check_out_already_checked_out_book_conflicts(client: AsyncClient) -> None:
    await create(client)
    await client.patch("/books/000123", json=CHECK_OUT)

    response = await client.patch("/books/000123", json=CHECK_OUT | {"card_number": "111111"})

    assert response.status_code == 409
    book = (await client.get("/books/000123")).json()
    assert book["current_loan"]["card_number"] == "654321"


async def test_return_book(client: AsyncClient) -> None:
    await create(client)
    await client.patch("/books/000123", json=CHECK_OUT)

    response = await client.patch("/books/000123", json=RETURN)

    assert response.status_code == 200
    assert response.json()["status"] == "available"
    assert response.json()["current_loan"] is None


async def test_return_available_book_conflicts(client: AsyncClient) -> None:
    await create(client)
    response = await client.patch("/books/000123", json=RETURN)
    assert response.status_code == 409


async def test_status_change_of_unknown_book(client: AsyncClient) -> None:
    response = await client.patch("/books/999999", json=CHECK_OUT)
    assert response.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"status": "checked_out"}, id="check-out-without-card"),
        pytest.param(CHECK_OUT | {"card_number": "12345"}, id="card-too-short"),
        pytest.param(CHECK_OUT | {"card_number": 654321}, id="card-as-integer"),
        pytest.param(RETURN | {"card_number": "654321"}, id="return-with-card"),
        pytest.param({"status": "lost"}, id="unknown-status"),
        pytest.param({}, id="empty-body"),
        pytest.param(CHECK_OUT | {"checked_out_at": "2020-01-01T00:00:00Z"}, id="client-time"),
    ],
)
async def test_status_change_rejects_invalid_input(client: AsyncClient, body: Any) -> None:
    await create(client)
    response = await client.patch("/books/000123", json=body)
    assert response.status_code == 422


async def test_concurrent_checkouts_let_exactly_one_through(client: AsyncClient) -> None:
    await create(client)

    responses = await asyncio.gather(
        *(
            client.patch("/books/000123", json=CHECK_OUT | {"card_number": f"00000{i}"})
            for i in range(5)
        )
    )

    assert sorted(r.status_code for r in responses) == [200, 409, 409, 409, 409]


async def test_response_shows_the_state_this_request_committed(
    client: AsyncClient, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another request returns the book right after our checkout commits.

    The checkout's response must still say "checked_out": it describes what this
    request did, not whatever happened afterwards.
    """
    await create(client)
    real_commit = AsyncSession.commit

    async def commit_then_someone_returns_the_book(session: AsyncSession) -> None:
        await real_commit(session)
        async with engine.begin() as other_connection:
            await other_connection.execute(
                text("UPDATE loans SET returned_at = now() WHERE returned_at IS NULL")
            )

    monkeypatch.setattr(AsyncSession, "commit", commit_then_someone_returns_the_book)
    response = await client.patch("/books/000123", json=CHECK_OUT)

    assert response.status_code == 200
    assert response.json()["status"] == "checked_out"


async def test_return_is_timestamped_after_the_checkout_it_closes(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    """A return whose transaction began before a competing checkout got the book's lock.

    Two requests can begin their transactions in one order and lock the book in the other.
    PostgreSQL's now() is the time the transaction began, so it would date the return
    before the checkout it closes, which the database rejects.
    """
    await create(client)
    async with AsyncSession(engine, expire_on_commit=False) as returning:
        await returning.execute(text("SELECT 1"))  # the return's transaction begins
        checkout = await client.patch("/books/000123", json=CHECK_OUT)  # a checkout overtakes it
        await services.return_book(returning, "000123")

    assert checkout.status_code == 200
    [loan] = (await client.get("/books/000123/loans")).json()
    returned_at = datetime.fromisoformat(loan["returned_at"])
    assert returned_at > datetime.fromisoformat(loan["checked_out_at"])


async def test_database_allows_only_one_open_loan_per_book(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    """The partial unique index holds even if application checks are bypassed."""
    await create(client)
    await client.patch("/books/000123", json=CHECK_OUT)

    with pytest.raises(IntegrityError, match="uq_loans_one_open_loan_per_book"):
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO loans (book_id, card_number) "
                    "SELECT id, '111111' FROM books WHERE serial_number = '000123'"
                )
            )


async def test_invalid_data_in_the_database_is_never_sent(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    """Responses are validated too. The database allows a tab in a title; the API doesn't.

    A real server answers this with the generic 500 (see test_infrastructure.py).
    """
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO books (serial_number, title, author) "
                "VALUES ('000123', E'La\\tlka', 'Prus')"
            )
        )

    with pytest.raises(ValidationError, match="title"):
        await client.get("/books/000123")


# --- loan history ---


async def test_loan_history_newest_first(client: AsyncClient) -> None:
    await create(client)
    await client.patch("/books/000123", json=CHECK_OUT | {"card_number": "111111"})
    await client.patch("/books/000123", json=RETURN)
    await client.patch("/books/000123", json=CHECK_OUT | {"card_number": "222222"})

    response = await client.get("/books/000123/loans")

    assert response.status_code == 200
    loans = response.json()
    assert [loan["card_number"] for loan in loans] == ["222222", "111111"]
    assert loans[0]["returned_at"] is None
    assert loans[1]["returned_at"] is not None


async def test_loan_history_of_unknown_book(client: AsyncClient) -> None:
    response = await client.get("/books/999999/loans")
    assert response.status_code == 404


# --- deleting ---


async def test_delete_book_with_its_history(client: AsyncClient, engine: AsyncEngine) -> None:
    await create(client)
    await client.patch("/books/000123", json=CHECK_OUT)
    await client.patch("/books/000123", json=RETURN)

    response = await client.delete("/books/000123")

    assert response.status_code == 204
    assert response.content == b""
    assert (await client.get("/books/000123")).status_code == 404
    async with engine.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM loans")) == 0


async def test_delete_checked_out_book_conflicts(client: AsyncClient) -> None:
    await create(client)
    await client.patch("/books/000123", json=CHECK_OUT)

    response = await client.delete("/books/000123")

    assert response.status_code == 409
    assert (await client.get("/books/000123")).status_code == 200


async def test_delete_unknown_book(client: AsyncClient) -> None:
    response = await client.delete("/books/999999")
    assert response.status_code == 404


async def test_serial_number_can_be_reused_after_delete(client: AsyncClient) -> None:
    await create(client)
    await client.delete("/books/000123")
    await create(client, title="Quo vadis")
