# Library API

A REST API for library staff to manage books, checkouts and returns.

Built with FastAPI, SQLAlchemy 2.1 (async), PostgreSQL 18, and Alembic.

## Run

Requires Docker with Compose.

```sh
docker compose up
```

Starts PostgreSQL, applies migrations and serves the API on port 8000.

- [Interactive API docs](http://localhost:8000/docs)
- [OpenAPI schema](http://localhost:8000/openapi.json)

If port 8000 is taken, use another: `API_PORT=8080 docker compose up`.

## API

| Method and path | Purpose |
|---|---|
| `POST /books` | Add a book |
| `GET /books` | List books |
| `GET /books/{serial_number}` | Get one book |
| `PATCH /books/{serial_number}` | Check a book out or return it |
| `DELETE /books/{serial_number}` | Delete a book and its loan history |
| `GET /books/{serial_number}/loans` | Loan history, newest first |
| `GET /health` | Check API and database availability |

- Serial and card numbers are strings of exactly six ASCII digits, preserving leading zeros. JSON numbers are rejected.
- `GET /books` accepts `status` (`available` or `checked_out`), `limit` (default 100, maximum 1000) and `offset` (default 0). Results are ordered by serial number and returned as `items`, `total`, `limit` and `offset`.
- Checkout and return times are set by the server. A checked-out book must be returned before deletion; otherwise the API returns 409.
- Authentication is omitted as requested in the task.

## Example

```sh
# Add a book
curl -X POST localhost:8000/books -H 'content-type: application/json' \
  -d '{"serial_number": "000123", "title": "Lalka", "author": "Bolesław Prus"}'

# Check it out to library card 654321
curl -X PATCH localhost:8000/books/000123 -H 'content-type: application/json' \
  -d '{"status": "checked_out", "card_number": "654321"}'

# Return it
curl -X PATCH localhost:8000/books/000123 -H 'content-type: application/json' \
  -d '{"status": "available"}'
```

A checked-out book in a response:

```json
{
  "serial_number": "000123",
  "title": "Lalka",
  "author": "Bolesław Prus",
  "current_loan": { "card_number": "654321", "checked_out_at": "2026-11-09T10:15:00Z" },
  "status": "checked_out"
}
```

When the book is available, `current_loan` is `null` and `status` is `available`.

## Design decisions

- **`GET /books` is paginated**, although the task asks to list all books, because an unbounded list grows with the library. `total` gives the number of matching books, so a client can fetch every page.
- **Two tables, `books` and `loans`.** A loan is one checkout, and its `returned_at` stays empty until the book comes back. A book's status is derived from its open loan instead of being stored separately, so the two can't disagree, and the loan history is kept.
- **A book can't be checked out twice, even by concurrent requests.** Each change locks the book's row (`SELECT ... FOR UPDATE`), and a partial unique index on open loans makes the database reject a second one. Both are tested.
- **Deleting a book deletes its loan history.** The task asks for deletion; a real library would more likely mark books as withdrawn and keep their history.

## Development

Requires [uv](https://docs.astral.sh/uv/) and a running Docker engine.

```sh
uv sync --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```

Tests start a disposable PostgreSQL container and apply the migrations. GitHub Actions runs these checks and a Docker Compose smoke test.
