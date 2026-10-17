"""Highlights a member marked on a reading device, and the KOReader import.

`models.Highlight` says what a row is and who reads it. What arrives here is a
sidecar the member's own browser read: the book's file never leaves the device
and this server never sees it, only the passages and the fingerprint the
sidecar carries.
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from enums import HighlightSource
from models import HIGHLIGHT_CHAPTER_MAX, HIGHLIGHT_NOTE_MAX, HIGHLIGHT_TEXT_MAX
from schemas.common import UtcDateTime
from schemas.digital import PartialMd5
from schemas.progress import MAX_PAGE
from schemas.user import UserOut

#: The most highlights one import of one sidecar may carry. Chosen, not
#: measured: a heavily marked book carries a few hundred, and the bound is what
#: keeps one request from writing an unbounded batch.
MAX_HIGHLIGHTS_PER_IMPORT = 5_000

#: The widest position KOReader writes, start or end. An XPointer names a path
#: through the book's markup and is a few hundred characters at most; this is
#: room for a deep one, and the bound on what is hashed into the source key.
KOREADER_POSITION_MAX = 4_096

#: KOReader's `datetime`: local wall clock, no zone, exactly this shape.
_KOREADER_DATETIME = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$"
KOREADER_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def _blank_is_none(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


class KoreaderHighlightIn(BaseModel):
    """One highlight out of a KOReader sidecar, as the browser read it.

    **Identified by the file and `highlighted_at`**, KOReader's creation time,
    which adjusting a mark does not change; by the positions too where that
    time is missing or shared (`koreader_highlights.koreader_source_key`). A reflowable
    book's positions are XPointers; a fixed layout one's are coordinate
    tables, which the browser writes as one canonical string. They are hashed,
    never stored.
    """

    pos0: str = Field(min_length=1, max_length=KOREADER_POSITION_MAX)
    pos1: str = Field(min_length=1, max_length=KOREADER_POSITION_MAX)
    text: str = Field(min_length=1, max_length=HIGHLIGHT_TEXT_MAX)
    note: str | None = Field(default=None, max_length=HIGHLIGHT_NOTE_MAX)
    chapter: str | None = Field(default=None, max_length=HIGHLIGHT_CHAPTER_MAX)
    page: int | None = Field(default=None, ge=1, le=MAX_PAGE)
    #: KOReader's `datetime` as the sidecar wrote it, `YYYY-MM-DD HH:MM:SS` on
    #: the device's wall clock. Stored as those digits with no zone, because
    #: none was recorded: `models.Highlight.highlighted_at`.
    highlighted_at: str | None = Field(default=None, pattern=_KOREADER_DATETIME)

    @field_validator("pos0", "pos1", "text", "note", "chapter")
    @classmethod
    def _no_nul(cls, value: str | None) -> str | None:
        """Refused rather than stored: PostgreSQL's text types cannot hold the
        byte, so it would surface as a 500 there, and a position is hashed into
        the key with NUL as the separator."""
        if value is not None and "\x00" in value:
            raise ValueError("A highlight may not contain a NUL character")
        return value

    @field_validator("text")
    @classmethod
    def _a_passage_is_not_whitespace(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("A highlight needs some text.")
        return cleaned

    @field_validator("note", "chapter")
    @classmethod
    def _blank_is_absent(cls, value: str | None) -> str | None:
        return _blank_is_none(value)

    @field_validator("highlighted_at")
    @classmethod
    def _a_real_date(cls, value: str | None) -> str | None:
        """The shape is the pattern's; this refuses a 31 February. Parsed
        naive because the value has no zone to parse."""
        if value is not None:
            datetime.strptime(value, KOREADER_DATETIME_FORMAT)  # noqa: DTZ007
        return value


class KoreaderImportIn(BaseModel):
    """The highlights of one sidecar, for the one Book holding its file."""

    #: The sidecar's `partial_md5_checksum`. The Book must hold a file
    #: reference carrying it, so a sidecar lands only where its fingerprint
    #: matched and never where a title merely looked right.
    partial_md5: PartialMd5
    highlights: list[KoreaderHighlightIn] = Field(
        min_length=1, max_length=MAX_HIGHLIGHTS_PER_IMPORT
    )


class HighlightImportOut(BaseModel):
    """What one import did, in four disjoint counts over the marks it named."""

    created: int
    updated: int
    unchanged: int
    #: Marks the member deleted on the book page, which the import leaves
    #: deleted.
    left_deleted: int


class HighlightSharingIn(BaseModel):
    is_shared: bool


class HighlightOut(BaseModel):
    """One highlight the caller may read: their own, or one shared with them."""

    id: int
    book_id: int
    user_id: int
    source: HighlightSource
    text: str
    note: str | None = None
    chapter: str | None = None
    page: int | None = None
    #: The device's wall clock as KOReader wrote it, `YYYY-MM-DD HH:MM:SS`.
    #: **Text, not a `date-time`**: that format requires an offset and this
    #: value has none, so a client shows the digits and converts nothing.
    #: `models.Highlight.highlighted_at` says why no zone is invented.
    highlighted_at: str | None = None
    is_shared: bool
    created_at: UtcDateTime
    updated_at: UtcDateTime
    author: UserOut | None = None
    model_config = {"from_attributes": True}

    @field_validator("highlighted_at", mode="before")
    @classmethod
    def _as_written(cls, value: object) -> object:
        """The stored naive datetime back as the text it was given as."""
        return value.strftime(KOREADER_DATETIME_FORMAT) if isinstance(value, datetime) else value
