"""Request and response models. Everything entering or leaving the API passes through these."""

import unicodedata
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
)
from pydantic_core import PydanticCustomError

# [0-9] rather than \d: \d also matches non-ASCII digits such as "١٢٣٤٥٦".
SIX_DIGITS = r"^[0-9]{6}$"

SerialNumber = Annotated[
    str,
    StringConstraints(pattern=SIX_DIGITS),
    Field(description="Six-digit serial number given by library staff.", examples=["000123"]),
]
CardNumber = Annotated[
    str,
    StringConstraints(pattern=SIX_DIGITS),
    Field(description="Six-digit library card number of the borrower.", examples=["654321"]),
]
# PostgreSQL's BIGINT, which is what LIMIT and OFFSET accept.
MAX_BIGINT = 2**63 - 1
Limit = Annotated[int, Field(ge=1, le=1000)]
Offset = Annotated[int, Field(ge=0, le=MAX_BIGINT)]


def _reject_control_characters(value: str) -> str:
    # PostgreSQL cannot store NUL at all, and tabs or line breaks inside a title are typos.
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise PydanticCustomError(
            "control_characters",
            "Text must not contain control characters such as NUL, tab or line breaks.",
        )
    return value


# A title or author in a request: surrounding whitespace is trimmed, then the text must be
# 1 to 500 characters with no control characters.
NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
    AfterValidator(_reject_control_characters),
]
# The same rules for a response, which must already be in that form: nothing is trimmed,
# so surrounding whitespace is an error instead.
TrimmedText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=500, pattern=r"^\S(.*\S)?$"),
    AfterValidator(_reject_control_characters),
]


class BookStatus(StrEnum):
    AVAILABLE = "available"
    CHECKED_OUT = "checked_out"


class RequestModel(BaseModel):
    """Base for request bodies: unknown fields are rejected instead of silently ignored."""

    model_config = ConfigDict(extra="forbid")


class ResponseModel(BaseModel):
    """Base for responses: built from ORM objects, listing only the fields clients may see."""

    model_config = ConfigDict(from_attributes=True)


# --- requests ---


class BookListQuery(RequestModel):
    """Query parameters of GET /books. Unknown parameters are rejected too."""

    status: BookStatus | None = Field(None, description="Only books with this status.")
    limit: Limit = Field(100, description="Maximum number of books to return.")
    offset: Offset = Field(0, description="Number of books to skip.")


class BookCreate(RequestModel):
    serial_number: SerialNumber
    title: NonEmptyText = Field(examples=["Lalka"])
    author: NonEmptyText = Field(examples=["Bolesław Prus"])


class CheckOut(RequestModel):
    status: Literal["checked_out"]
    card_number: CardNumber


class Return(RequestModel):
    status: Literal["available"]


# The "status" field picks the variant: checking out requires a card number,
# returning a book rejects one.
StatusUpdate = CheckOut | Return


# --- responses ---
# Checked with the same rules as requests, so the API only sends what it would accept.
# If the database ever held anything else, the request fails with a 500 instead.


class LoanOut(ResponseModel):
    card_number: CardNumber
    checked_out_at: AwareDatetime


class LoanHistoryOut(LoanOut):
    returned_at: AwareDatetime | None


class BookOut(ResponseModel):
    serial_number: SerialNumber
    title: TrimmedText
    author: TrimmedText
    current_loan: LoanOut | None = Field(
        description="The open loan if the book is checked out, otherwise null."
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> BookStatus:
        return BookStatus.CHECKED_OUT if self.current_loan else BookStatus.AVAILABLE


class BookPage(BaseModel):
    items: list[BookOut]
    total: int = Field(ge=0, description="Number of books matching the filter, across all pages.")
    limit: Limit
    offset: Offset


class ErrorOut(BaseModel):
    detail: str
