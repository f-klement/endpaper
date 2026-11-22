"""What an admin sends and reads about a patron. `models.Patron` is the record.

**Only an admin reads who a patron is** (owner, 2026-11-20). `PatronOut` is the
whole record, served by `routers/patrons.py` alone, with the patron's open
loans on it. A loan names its patron to an admin by `LoanPatronOut`, the name
and the card and nothing to contact them by, filled per viewer by
`patrons.named_on_loans`; every other reader of a loan, and the public
catalogue, gets `LoanOut.to_patron` and no more. `LoanCreate` takes a patron's
id on the way in, from an admin alone.
"""

from datetime import date
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, Field, StringConstraints, model_validator

import patrons
from models import (
    PATRON_CARD_NUMBER_MAX,
    PATRON_CITY_MAX,
    PATRON_HOUSE_NUMBER_MAX,
    PATRON_NAME_MAX,
    PATRON_PHONE_MAX,
    PATRON_POSTCODE_MAX,
    PATRON_STREET_MAX,
)
from schemas.common import UtcDateTime, one_line_without_invisible_characters
from schemas.user import AddressField

#: What a card number may look like: letters and digits, with a dot, a slash or
#: a hyphen between them. No space, because a scanner reads none and a padded
#: number would earn a second row beside the unpadded one.
CARD_NUMBER_PATTERN = r"^[0-9A-Za-z]+(?:[./-][0-9A-Za-z]+)*$"


def _a_line(value: str) -> str:
    """One line a person can read back, refused where nothing is left."""
    cleaned = one_line_without_invisible_characters(value)
    if not cleaned:
        raise ValueError("This field may not be blank.")
    return cleaned


def _a_line_or_nothing(value: str | None) -> str | None:
    """One line, or null for nothing typed, so a cleared field clears the column."""
    if value is None:
        return None
    return one_line_without_invisible_characters(value) or None


Name = Annotated[str, Field(max_length=PATRON_NAME_MAX), AfterValidator(_a_line)]


def _upper_cased(value: str) -> str:
    """The card number as it is stored: upper case, whatever was typed."""
    return value.upper()


#: Trimmed before the pattern is asked, so a pasted space is not refused and is
#: not a second card either. **Upper cased after it**, so `a12` and `A12` are
#: one card to the unique index, the 409 and the search alike; without it a
#: desk typing by hand registers the same card twice. The pattern admits ASCII
#: letters alone, so upper casing never changes a value's length.
CardNumber = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=PATRON_CARD_NUMBER_MAX, pattern=CARD_NUMBER_PATTERN
    ),
    AfterValidator(_upper_cased),
]


Phone = Annotated[str | None, Field(max_length=PATRON_PHONE_MAX), AfterValidator(_a_line_or_nothing)]
Street = Annotated[str | None, Field(max_length=PATRON_STREET_MAX), AfterValidator(_a_line_or_nothing)]
HouseNumber = Annotated[
    str | None, Field(max_length=PATRON_HOUSE_NUMBER_MAX), AfterValidator(_a_line_or_nothing)
]
Postcode = Annotated[str | None, Field(max_length=PATRON_POSTCODE_MAX), AfterValidator(_a_line_or_nothing)]
City = Annotated[str | None, Field(max_length=PATRON_CITY_MAX), AfterValidator(_a_line_or_nothing)]


class PatronCreate(BaseModel):
    """A patron registered by an admin. A card number and a name; the rest optional."""

    card_number: CardNumber
    name: Name
    email: AddressField = None
    phone: Phone = None
    street: Street = None
    house_number: HouseNumber = None
    postcode: Postcode = None
    city: City = None
    #: When the registration lapses. None is a registration with no end.
    expires_on: date | None = None


class PatronUpdate(BaseModel):
    """The fields an admin changes. A field left out is left alone; null clears it.

    The card number and the name may be changed and never cleared: a patron
    with neither is nobody the desk can find.
    """

    card_number: CardNumber | None = None
    name: Name | None = None
    email: AddressField = None
    phone: Phone = None
    street: Street = None
    house_number: HouseNumber = None
    postcode: Postcode = None
    city: City = None
    expires_on: date | None = None

    @model_validator(mode="after")
    def _keeps_a_card_and_a_name(self) -> Self:
        """Null for either required column is a 422 naming it, never a 500."""
        cleared = sorted(
            field
            for field in ("card_number", "name")
            if field in self.model_fields_set and getattr(self, field) is None
        )
        if cleared:
            raise ValueError(
                f"A patron keeps a card number and a name: {', '.join(cleared)} may not be null."
            )
        return self


#: The longest search term, which is longer than any one column it is matched against.
SEARCH_TERM_MAX = 200
#: What a search returns when the caller names no limit.
SEARCH_LIMIT_DEFAULT = 20


def _a_term(value: str) -> str:
    """The term cleaned as a name is on write, refused where nothing is left.

    **The cleaning is the names' own**: a term cleaned differently from the
    column it matches finds nothing where a person sees a match, so `"P\\x07at"`
    would miss the `Pat` its name was stored as. The collapse also takes the
    separators `\\x1c` to `\\x1f`, which no whitespace class in a pattern names,
    so a term of only those is refused here rather than reaching the search
    blank and matching every patron. A NUL never arrives: the body's NUL check
    in `dependencies.py` refuses it first.
    """
    term = one_line_without_invisible_characters(value)
    if not term:
        raise ValueError("A search term may not be blank.")
    return term


class PatronSearch(BaseModel):
    """A search for a patron, sent as a body.

    **A body, never a query string**, because the term is a name, an email or a
    card number, and a reverse proxy or a server logs a request line with its
    query by default, where no erasure reaches it.
    """

    q: Annotated[
        str,
        Field(
            min_length=1,
            max_length=SEARCH_TERM_MAX,
            description="Matched against name, email and card number",
        ),
        AfterValidator(_a_term),
    ]
    limit: Annotated[int, Field(ge=1, le=patrons.SEARCH_LIMIT_MAX)] = SEARCH_LIMIT_DEFAULT


class LoanPatronOut(BaseModel):
    """Who holds a lent book, as an admin reads it on the loan.

    **The name and the card, and no address**, because this answers "who has
    it" and "whom to chase", and the record one click away has the rest. It
    also keeps the address rule in `tests/test_house_rules.py` from having a
    loan schema to allow.
    """

    name: str
    card_number: str
    model_config = {"from_attributes": True}


class PatronLoanOut(BaseModel):
    """One loan a patron still holds, as their record lists it."""

    id: int
    book_id: int
    title: str
    loaned_at: UtcDateTime
    due_at: UtcDateTime | None = None


class PatronOut(BaseModel):
    """A patron's whole record, as an admin reads it. Served by `routers/patrons.py` alone."""

    id: int
    card_number: str
    name: str
    email: str | None = None
    phone: str | None = None
    street: str | None = None
    house_number: str | None = None
    postcode: str | None = None
    city: str | None = None
    expires_on: date | None = None
    enrolled_at: UtcDateTime
    #: The books this patron has out, oldest loan first. Filled by the router
    #: from `Loans.seen_by` the admin, never off the row, which has no such
    #: relation: `routers/patrons.py::_records`.
    open_loans: list[PatronLoanOut] = []
    model_config = {"from_attributes": True}
