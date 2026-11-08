from pydantic import BaseModel, Field

from enums import TagCategory
from schemas.tag import KnownTagKey


class PerUserStat(BaseModel):
    username: str
    count: int = Field(ge=0)


class TagStat(BaseModel):
    name: str
    category: TagCategory
    count: int = Field(ge=0)
    #: Carried for the same reason `TagOut` carries it: the stats page prints
    #: these names, and without the key it would print the English ones into a
    #: German page while every other tag on screen was translated. The same
    #: `KnownTagKey`, so the two models cannot disagree about an unknown one.
    key: KnownTagKey = None


class CollectionStat(BaseModel):
    """One named collection and how much of it the caller can see.

    Named collections only. Unfiled books are not a bucket here, because they
    are not a collection: `total` minus the sum of these is how many there are,
    and the library's own unfiled filter is where somebody goes to look at
    them.
    """

    name: str
    count: int = Field(ge=0)


class CurrencyTotal(BaseModel):
    """What the visible copies priced in one currency cost, summed.

    One row per currency and never converted: no exchange rate is consulted,
    so a library that bought in two currencies gets two totals.
    """

    #: As stored on the copy: three characters, upper cased on write, and not
    #: checked against ISO 4217, so a client formatting it must expect a code
    #: its formatter does not know.
    currency: str
    #: Hundredths of the currency, the unit `purchase_price_minor` is stored
    #: in whatever the currency: the client divides by 100 for every code, so
    #: a yen total arrives as a hundred times the yen.
    #:
    #: No lower bound, unlike every count here. A write refuses a negative
    #: price, but a restored archive bypasses that check, and a lower bound
    #: would fail response validation on one such row and answer the whole
    #: route with a 500. Clamping was refused too: it would print a total that
    #: no set of the recorded prices adds up to, and hide the bad row besides.
    total_minor: int
    copies: int = Field(ge=1)


class MonthStat(BaseModel):
    # A "YYYY-MM" bucket key, produced by `database.MonthBucket`.
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
    # Named collections, largest first. A shelf split into physical and ebook
    # wants the split counted; a library that never made one gets an empty
    # list and the section is not drawn.
    by_collection: list[CollectionStat] = []
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
    # What the visible copies cost, one total per currency, by currency code.
    # Shared like `total`: a fact about the shelf, not about a reader.
    purchase_totals: list[CurrencyTotal] = []
    # Copies with a price and no currency. Counted rather than summed: adding
    # them to any one total would be guessing the currency, and summing them
    # together could add yen to pounds.
    priced_without_currency: int = Field(default=0, ge=0)
