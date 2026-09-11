"""What a store calls a Book, as a request carries it and as a response does.

**A Book's identifiers, not a person's.** `schemas/author.py` holds the other
family, and the two are separate stores because they are keyed differently: an
author's identifier hangs off a spelling of a name and a Book's hangs off the
row. `models.BookIdentifier` carries the rest of the reasoning.

Bounded here and again by `ck_book_identifiers_bounds` on the column, because
`backup.restore` inserts through Core and sees no Pydantic model: the same
arrangement `schemas/digital.py` states for the file references.
"""

import unicodedata

from pydantic import BaseModel, Field, field_validator

from enums import BookIdentifierScheme
from models import BOOK_IDENTIFIER_MAX

#: The most identifiers one Book may carry, full stop.
#:
#: **Two bounds, and they are not the same bound**, which is
#: `MAX_CLASSIFICATIONS_PER_BOOK`'s distinction and its reason: `max_length` on
#: the request field caps one payload, and the capped writers count what the
#: Book already carries and stop there, which is the half that makes the name
#: true. Without the second, every caller is bounded per request while the
#: writers are additive across them, so the per Book total is unbounded and
#: `books_to_out` selectin-loads this relationship onto every row of every page.
#:
#: **The two capped writers are `identifiers.add_identifiers` and
#: `_repoint_relations`**, exactly as for the headings. `backup.restore` is the
#: third and is deliberately uncapped: it reinstates a whole database rather
#: than adding to one, and every other table is uncapped there for that reason.
#:
#: **The number is not a measurement, because the population is not a
#: catalogue's output.** A heading budget is what a record supplies and was
#: measured over live records; this one is the number of stores a household
#: imported one Book from. Four are wired and two of them carry an identifier,
#: so eight is that roster doubled and has room for the roster doubling.
#:
#: **The exclusion, because a merge can exceed it**: `POST /api/books/merge`
#: takes up to 20 Books in one unlimited request, so it can offer more rows than
#: this admits. The overflow is dropped with a log line rather than the ceiling
#: raised, which is the same bargain `MAX_CLASSIFICATIONS_PER_BOOK` records: a
#: cap that admits it is soft beats an invariant with one writer exempt.
MAX_IDENTIFIERS_PER_BOOK = 8

#: Unicode categories an identifier may hold no character from.
#:
#: `Cc` is the control characters and `Cf` the formatting ones. `an_opaque_token`
#: says what each costs and why whitespace is refused beside them.
_INVISIBLE = frozenset({"Cc", "Cf"})


class BookIdentifierIn(BaseModel):
    """One identifier, as a client posts it after reading its own library.

    Nothing here is trusted beyond its own bounds: the scheme is a closed enum,
    so a client cannot invent one, and the value is bounded and checked. The
    producer is a member's own browser, which `lib/bookBounds.ts` and
    `models.DigitalReference` both state is not a trusted producer.
    """

    scheme: BookIdentifierScheme
    value: str = Field(min_length=1, max_length=BOOK_IDENTIFIER_MAX)

    @field_validator("value")
    @classmethod
    def an_opaque_token(cls, value: str) -> str:
        """Trim the file's own padding, and refuse anything invisible in it.

        **Trimmed, because padding is not part of the value.** A store's XML
        indents its elements, so a reader that took the text node whole would
        write `\\n      B00J4YQKHY\\n    ` and the unique index would hold that
        as a different identifier from the same one read tidily.

        **The padding still counts against `max_length`**, which runs before
        this and bounds what arrived rather than what is stored. That is the
        order worth keeping, because it is what stops an unbounded string
        reaching the scan below, and `ClassificationIn.tidy_number` is arranged
        the same way. What it costs is small and measured: the widest identifier
        any reader here produces is 12 characters, so a payload would have to
        carry 48 characters of whitespace around one before the trim would have
        saved it.

        **Refused rather than collapsed, and that is where this parts company
        with `ClassificationIn.tidy_number` beside it.** A call number
        legitimately contains spaces, so that validator collapses runs of them
        and stores what is left. An identifier here is an opaque token: nothing
        inside it is whitespace, so whitespace inside one means the reader picked
        up something that is not the identifier, and collapsing it would store a
        value this app invented. A stored row is an assertion, and one quietly
        rewritten is worse than one declined.

        **Both invisible categories as well as whitespace**, because the failure
        is the unique index rather than the display: `uq_book_identifiers_book_
        scheme_value` is on the exact characters, so a SOFT HYPHEN inside an
        ASIN earns a second row for one identifier and nothing on any screen
        shows the two apart. That is the case `ClassificationIn.tidy_number`
        closed the same way after a narrower rule reached the 24 ASCII controls
        and admitted the 41 C1 controls, SOFT HYPHEN, ZERO WIDTH SPACE and BOM.

        **A NUL is one of the `Cc` characters, and this is where it is refused
        for a request.** `ck_book_identifiers_bounds` refuses it again on the
        column, which is what covers `backup.restore`: that path runs no
        Pydantic model, and without the NUL arm SQLite's `length()` stops
        counting at one and the character ceiling binds on nothing.
        """
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("An identifier needs a value.")
        if any(
            character.isspace()
            or unicodedata.category(character) in _INVISIBLE
            for character in trimmed
        ):
            raise ValueError(
                "An identifier holds no whitespace, control or formatting "
                "characters."
            )
        return trimmed


class BookIdentifierOut(BaseModel):
    """One identifier a Book carries, as a response gives it.

    The scheme and the value and nothing else. `created_at` is on the row and is
    deliberately not here: it says when this library was told, never when the
    store issued the number, which is the distinction
    `models.DigitalReference.confirmed_at` draws at length, and a client showing
    it would be showing an import's timestamp under an identifier's name.
    """

    scheme: BookIdentifierScheme
    value: str
    model_config = {"from_attributes": True}
