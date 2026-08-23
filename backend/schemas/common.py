from typing import Annotated

from pydantic import BaseModel, Field

# Bounds for every paginated endpoint. The ceiling is what stops a caller
# asking for the whole library in one request and undoing the point of paging.
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

#: The largest value SQLite stores in an INTEGER column.
#:
#: Every caller-supplied row id is bounded by it, and that is not decoration: a
#: Python int has no ceiling, so a larger one passes validation, reaches the
#: driver and raises `OverflowError` from inside the query. That answers **500**
#: to a value the caller chose, which is the app calling its own code buggy.
#: Measured once already on `POST /api/books/covers/backfill?after_id=`; see
#: `tests/test_house_rules.py`.
MAX_ROW_ID = 2**63 - 1

#: A row id arriving in a **request body**, where there is no `Path()` or
#: `Query()` to carry the bounds.
#:
#: The same hazard by a different door, and the door the path fix did not close:
#: `{"book_ids": [2**63]}` reached the driver through `POST /api/books/bulk`,
#: `/merge` and `POST /api/loans`, and each answered 500. A body field is
#: neither a handler parameter nor a dependency, so the parameter lint cannot
#: see it; `tests/test_house_rules.py::TestEveryRequestBodyRowIdIsBounded` is
#: the one that does.
RowIdField = Annotated[int, Field(ge=1, le=MAX_ROW_ID)]


class Page[T](BaseModel):
    """A slice of a longer list, plus what the client needs to ask for more.

    `total` is the count of rows matching the filters, not the length of
    `items`. The grid needs it to show "42 books" and to know when to stop
    requesting further pages.
    """

    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=MAX_PAGE_SIZE)

    @property
    def has_more(self) -> bool:
        return self.page * self.page_size < self.total
