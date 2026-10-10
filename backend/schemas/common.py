from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field, PlainSerializer

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


def _as_utc(when: datetime) -> datetime:
    """A stored value, labelled UTC on the way out.

    Every `DateTime` column here is naive, and **the frame is whatever wrote the
    row rather than one rule**. Measured off the metadata: 31 such columns, of
    which **16 carry a database side default** and are written by the engine,
    `CURRENT_TIMESTAMP` on SQLite and `now()` on a server. The rest are written
    from Python, where `accounts.now()` is the spelling and `lending.py` states
    it for the loan columns. Serialised as they stand these reach a client as
    `2026-08-19T10:00:00`, and RFC 3339, which is what `format: date-time`
    names, requires an offset.

    **So this asserts the frame rather than discovering it**, and two writers are
    known not to be in it. A deadline arrived from a browser as a wall clock
    until `frontend/src/lib/date.ts::endOfDayInstant`, so rows written before
    that are in the submitter's zone; and the sixteen defaults are cast to a
    naive column using the session zone, which nothing in this tree sets, so on
    a server away from UTC they hold local wall clock. **This change does not
    cause either and it does make both louder**, because the wire now says UTC
    over a value that may not be.

    **An aware value is converted rather than refused**, which is what makes
    this safe to apply to a field a client writes: see `UtcDateTimeIn`, which
    runs the same rule inbound so that nothing aware reaches a column.
    """
    return when.replace(tzinfo=UTC) if when.tzinfo is None else when.astimezone(UTC)


def _as_stored(when: datetime) -> datetime:
    """The inbound half: whatever a client sent, as the naive UTC a column holds.

    **The live case is not hypothetical and it is not the loan door.** The
    browser sends `file_modified_at` as `toISOString()`, so that field arrives
    **aware** on every digital reference the app writes, and the route assigns it
    onto the column. Nothing is lost today only because the offset is zero and
    the SQLite formatter drops it: the formatter reads the field values and
    ignores `tzinfo`, so an offset that is not zero would store the wrong instant
    and a server dialect would store it differently again. That accident is what
    `lending.close` was written about, one door over.
    """
    return _as_utc(when).replace(tzinfo=None)


#: A `datetime` on this API's wire, carrying the offset `format: date-time` promises.
#:
#: **`return_type=datetime` is what keeps the promise it is here to honour.**
#: Returning a string instead would type the field `{"type": "string"}` with no
#: format at all, so the schema would stop declaring `date-time` and the
#: operations would go green by dropping the claim rather than by meeting it.
#: Handing pydantic a datetime back leaves the declaration where it was and
#: renders UTC as `Z`.
#:
#: **`when_used="json"` keeps the column's frame out of the python mode dump,
#: and the reason is a write rather than a rendering.** Three routes in
#: `routers/books.py` turn a request body into column values through
#: `model_dump()`, and an aware datetime written into a `DateTime` column is
#: the frame error `lending.close` records: it reaches the disk only because
#: the SQLite formatter drops the offset, and anything reading the attribute
#: before the refetch subtracts a naive datetime from an aware one and raises.
#: **None of those three bodies carries a datetime today**, so this is what
#: stops the first one that does rather than a repair of a live failure. JSON
#: is the only mode a client sees, so it is the only mode that needs an offset.
#:
#: **Applied to every `datetime` field under `schemas/`, request bodies
#: included, rather than to the response ones.** A field crosses that line the
#: day one route names its model as a `response_model`, and a policy applied by
#: direction has to be re-decided at that moment while a policy applied by
#: position does not. On a body it is inert: FastAPI never serialises a request
#: model, and python mode is excluded above.
UtcDateTime = Annotated[
    datetime, PlainSerializer(_as_utc, return_type=datetime, when_used="json")
]

#: A `datetime` a **client** writes, normalised to the frame its column holds.
#:
#: `UtcDateTime` plus the inbound half, so the two directions are one object and
#: a field cannot have the first without the second. Validation only: the schema
#: is unchanged, because an `AfterValidator` describes no shape.
#:
#: **Narrower than `UtcDateTime` on purpose.** Every other dated field is written
#: by this server in the column's own frame, so running a conversion over them
#: would be a no op dressed as a rule. This is for the two a browser fills.
UtcDateTimeIn = Annotated[UtcDateTime, AfterValidator(_as_stored)]

#: Every control character: C0 (0x00 to 0x1F), DEL, and C1 (0x80 to 0x9F).
#:
#: **`str.split()` reaches ten of them and no more**, which is why these two
#: sets exist at all. It splits on whitespace, and NUL is not whitespace:
#: measured 2026-08-27, `"a\x00b"` survived unchanged through both custom field
#: columns, as did `\x01`, `\x07`, `\x08`, `\x1b` and `\x7f`. A NUL is stored
#: by SQLite, serialised by JSON as `\u0000`, and invisible everywhere a person
#: could notice it.
#:
#: **`Cf` is deliberately absent, and that is the line between removing a
#: character and refusing the value.** SOFT HYPHEN, ZERO WIDTH SPACE and the
#: joiners are invisible too. `ClassificationIn.tidy_number` and
#: `BookIdentifierIn` refuse both categories, and each bought that width from
#: what its own column holds: a notation and a store identifier carry no
#: joiner. A name does, in Arabic and Indic scripts, so a rule that removed one
#: here would change what somebody's name says. The refusals therefore stay at
#: their own two sites: folding them in would let a width argued for a notation
#: reach a person's name with nothing red.
#: `range(0x00, 0x20)` and not `range(0x20)`, which is PIE808's fix and is why
#: the directive is here: the three terms are C0, DEL and C1, and dropping the
#: first bound stops the line reading as two blocks and a character. The rule
#: is right that the argument is redundant and wrong that it is unnecessary.
_CONTROL_CHARACTERS = dict.fromkeys([*range(0x00, 0x20), 0x7F, *range(0x80, 0xA0)])  # noqa: PIE808

#: The control characters that are **not** whitespace: 55 of the 65.
#:
#: Derived with the predicate that decides the other half rather than listed,
#: so the two cannot overlap or leave a gap. `str.split()` breaks on exactly
#: the ten this excludes, tab and the line breaks among them, so a character
#: here is one the collapse would otherwise carry through untouched and a
#: character not here is one the collapse already turns into a space.
#:
#: **Deleting a tab is therefore a decision, not a tidying.** It welds the two
#: words either side of it together, which is right for a value that may be a
#: URL and wrong for a name somebody pasted out of a two line cell.
_INVISIBLE_CHARACTERS = {
    point: None for point in _CONTROL_CHARACTERS if not chr(point).isspace()
}


def one_line(value: str) -> str:
    r"""Whatever somebody pasted in, as the one line the field is.

    Every run of whitespace becomes one space and the ends are trimmed. Two
    things rest on it and neither is cosmetic: a value of only spaces passes
    `min_length` and then renders as a row nobody can select or find again, and
    two spellings of one padded value each earn a row where the column is
    unique.

    **A control character that is not whitespace survives this**, `\x00`
    included, and that is what the two functions below exist for: a caller
    whose value is a name, a key or a URL wants one of them instead.

    `str.split()` with no argument splits on every run of whitespace, which is a
    **superset** of what a reader breaks a line on. `routers/books.py::_one_line`
    is the caller that rests on the superset, and carries why.
    """
    return " ".join(value.split())


def one_line_without_invisible_characters(value: str) -> str:
    r"""`one_line`, with the characters that have no width removed first.

    For a value a person reads back and has to be able to type again: a name, a
    label, an identifier. A NUL or an ESC is gone; a tab or a newline is still a
    word break, so `"Holiday\nreads"` is two words here and not one.

    **Removed rather than refused.** The two validators that refuse an invisible
    character instead are answering for a catalogue's own assertion: see
    `_CONTROL_CHARACTERS`.
    """
    return one_line(value.translate(_INVISIBLE_CHARACTERS))


def one_line_without_any_control_character(value: str) -> str:
    """`one_line`, with **every** control character removed first, tab included.

    The ordering is the difference from the pair above and it is load bearing:
    a tab vanishes rather than becoming a space. `CustomFieldValueUpdate.tidy`
    is the one caller and carries what the space cost, which was a 200 with an
    href no browser can follow.

    A value that may be rendered as a link is the only thing that wants this.
    For anything else the weld is a cost with nothing behind it, which is what
    `one_line_without_invisible_characters` exists to avoid.
    """
    return one_line(value.translate(_CONTROL_CHARACTERS))


class Refusal(BaseModel):
    """A refusal: the sentence saying why, in `detail`."""

    # A string: this is declared only for `refusals.DECLARED`, and the object
    # `detail` this backend also sends rides on a 409, which is not among them.
    # `tests/test_refusals.py` refuses one of the three built with a mapping or
    # a list. The mutator reads either shape (`errorDetail` in `frontend/src/api`).
    detail: str


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
