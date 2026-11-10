from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.db import engine
from app.errors import ConflictError, NotFoundError
from app.routers import books, health


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


app = FastAPI(
    title="Library API",
    version="0.1.0",
    description="Lets library staff add, remove and list books and check them out or in.",
    lifespan=lifespan,
)
app.include_router(books.router)
app.include_router(health.router)


# FastAPI's 422 body without the parts that echo the rejected value ("input", and "ctx",
# which repeats the message's details). An echoed value can be something JSON can't hold,
# such as the infinity that Python reads from 1e999, or a lone surrogate ("\ud800").
# Location, type and message remain; any client text in them has passed through Pydantic,
# which rejects or replaces what UTF-8 can't encode.
@app.exception_handler(RequestValidationError)
async def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {"type": error["type"], "loc": error["loc"], "msg": error["msg"]} for error in exc.errors()
    ]
    return JSONResponse({"detail": errors}, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)


def openapi() -> dict[str, Any]:
    """FastAPI's generated schema, with 422 errors described as `invalid_request` sends them."""
    if app.openapi_schema is None:
        schema = FastAPI.openapi(app)  # generated once, then cached in app.openapi_schema
        error_fields = schema["components"]["schemas"]["ValidationError"]["properties"]
        for field in ("input", "ctx"):
            error_fields.pop(field, None)
        return schema
    return app.openapi_schema


app.openapi = openapi  # type: ignore[method-assign]  # FastAPI's documented way to extend it


# Domain errors get the same {"detail": "..."} body as FastAPI's own HTTPException.
@app.exception_handler(NotFoundError)
async def not_found(_: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_404_NOT_FOUND)


@app.exception_handler(ConflictError)
async def conflict(_: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_409_CONFLICT)


# Anything unexpected: a JSON 500 instead of Starlette's plain-text one. The details stay
# out of the response; Starlette re-raises the exception so the server logs the traceback.
@app.exception_handler(Exception)
async def unexpected_error(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(
        {"detail": "Internal server error."}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
    )
