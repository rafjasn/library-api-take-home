from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import ErrorOut

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    summary="Health check",
    responses={503: {"model": ErrorOut, "description": "The database is unreachable."}},
)
async def health(session: Annotated[AsyncSession, Depends(get_session)]) -> dict[str, str]:
    """Returns 200 when the API is up and can reach the database."""
    try:
        await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Database unavailable.") from exc
    return {"status": "ok"}
