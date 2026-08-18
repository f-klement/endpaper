from pydantic import BaseModel, Field

# Bounds for every paginated endpoint. The ceiling is what stops a caller
# asking for the whole library in one request and undoing the point of paging.
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


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
