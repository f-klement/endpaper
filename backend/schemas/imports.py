from pydantic import BaseModel, Field


class ImportResultOut(BaseModel):
    """What an import actually did.

    Reported field by field rather than as a single count, because the useful
    question afterwards is "why did it not pick up book X?" and the answer is
    almost always one of: the book is not in the catalogue, the status was
    already correct, or the row could not be acted on at all.
    """

    rows_read: int = Field(ge=0, description="Rows with a title")
    matched: int = Field(ge=0, description="Rows matched to a book already here")
    created: int = Field(ge=0, description="Books added from the file")
    statuses_updated: int = Field(ge=0, description="Statuses actually changed")
    skipped: int = Field(
        ge=0,
        description=(
            "Rows this import could not act on: no title, or an ISBN held by a "
            "book the caller cannot see"
        ),
    )
    # Capped by the router: a large export with nothing matching would
    # otherwise return more than it was given.
    unmatched_titles: list[str] = []


class ImportPreviewRow(BaseModel):
    """One row as the parser read it, for the confirmation step."""

    title: str
    author: str | None = None
    isbn: str | None = None
    status: str | None = None


class ImportPreviewOut(BaseModel):
    """What the file turned out to be, before anything is written.

    Exists because a column guessed wrong is invisible until after the import,
    and after the import is too late: the fix is deleting a few hundred books.
    The reader sees which header filled which field, and the first few rows as
    the parser actually read them.
    """

    #: Every header in the file, so a wrong guess can be corrected against the
    #: real list rather than from memory.
    headers: list[str]
    #: Field name to the header it was taken from, or null where nothing
    #: matched. The keys are what `overrides` accepts.
    mapping: dict[str, str | None]
    #: What separated the columns. Worth showing: a tab-separated file read as
    #: CSV is the failure that looks like corrupt data.
    delimiter: str
    total_rows: int = Field(ge=0)
    skipped: int = Field(ge=0, description="Rows with no title")
    #: How many different tags this file carries. Shown next to the "bring the
    #: tags across" switch, because a count of this file beats a warning that
    #: says "often hundreds".
    distinct_tags: int = Field(default=0, ge=0)
    rows: list[ImportPreviewRow] = []
