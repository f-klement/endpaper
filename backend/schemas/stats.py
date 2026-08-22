from pydantic import BaseModel, Field

from enums import TagCategory


class PerUserStat(BaseModel):
    username: str
    count: int = Field(ge=0)


class TagStat(BaseModel):
    name: str
    category: TagCategory
    count: int = Field(ge=0)


class MonthStat(BaseModel):
    # A "YYYY-MM" bucket key, produced by SQLite's strftime.
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    count: int = Field(ge=0)


class StatsOut(BaseModel):
    """Collection statistics, scoped to what the requesting member may see.

    Previously this endpoint returned a bare dict, so the generated client had
    no idea of its shape. Every aggregation applies the privacy predicate
    independently, so a member never sees another member's private books
    reflected in any of these counts.
    """

    total: int = Field(ge=0)
    per_user: list[PerUserStat]
    by_tag: list[TagStat]
    by_month: list[MonthStat]
    # Books the *requesting member* finished, by month. Personal rather than
    # shared, unlike every other series here: "we added 12 books in March" is a
    # fact about the shelf, "I finished 3" is a fact about a reader.
    finished_by_month: list[MonthStat] = []
    # Pages the *requesting member* read, by month, from the recorded positions
    # in `reading_progress`. Personal like `finished_by_month`, and **page
    # tracked books only**: an audiobook records a percent, and turning 40% of
    # something with no page count into a page number would produce a figure
    # that adds up with the others while meaning something else.
    pages_by_month: list[MonthStat] = []
    average_rating: float | None = None
    rated_count: int = Field(default=0, ge=0)
