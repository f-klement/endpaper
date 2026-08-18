from pydantic import BaseModel, Field


class GoodreadsImportOut(BaseModel):
    """What an import actually did.

    Reported field by field rather than as a single count, because the useful
    question after an import is usually "why did it not pick up book X?" and
    the answer is almost always one of: the shelf was not one we map, the book
    is not in the catalogue, or the status was already correct.
    """

    rows_read: int = Field(ge=0, description="Rows with a shelf we understand")
    matched: int = Field(ge=0, description="Rows matched to a book already here")
    created: int = Field(ge=0, description="Books added from the export")
    statuses_updated: int = Field(ge=0, description="Statuses actually changed")
    skipped: int = Field(ge=0, description="Rows on a shelf we do not map")
    # Capped by the router: a large export with nothing matching would
    # otherwise return more than it was given.
    unmatched_titles: list[str] = []
