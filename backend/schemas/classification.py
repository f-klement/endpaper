from pydantic import BaseModel, Field, field_validator

from enums import ClassificationScheme
from models import CLASSIFICATION_LABEL_MAX, CLASSIFICATION_NUMBER_MAX

#: The most headings one book may carry, full stop.
#:
#: **Two bounds, and they are not the same bound.** `max_length` on the request
#: field caps one payload; the two **capped** writers of the table count the
#: rows already on the book and stop there (`backup.restore` is the third and
#: is deliberately uncapped, for the reason given below). Only the second makes the name true. Without it
#: every caller is bounded per request while the writers are additive across
#: requests, so the per book total is unbounded: `POST /{id}/enrich/apply`
#: takes a client supplied `BookMatch`, makes no outbound call and so carries
#: no rate limiter, and eight rows per call times any number of calls is a
#: stored denial of service the whole household pays for, since
#: `books_to_out` selectin-loads this relationship onto every row of every
#: page.
#:
#: **Both capped writers, and there are exactly two of those.**
#: `_write_classifications` is the one every add and enrich path goes through,
#: and `_repoint_relations` is the merge. `backup.restore` is a third writer of
#: this table (`backup.py`, through `_TABLES`) and is deliberately uncapped: it
#: reinstates a whole database rather than adding to one, it is admin only, and
#: every other table is uncapped there for the same reason.
#:
#: The merge is the larger of the two capped ones if it is left out: it takes up
#: to 20 books in one unlimited request, so it can move 8 x 19 = 152 rows
#: onto a survivor that then becomes the next merge's baseline. It obeys the
#: ceiling rather than carrying a documented exception, because an invariant
#: stated "full stop" with one writer exempt is worse than a cap that admits it
#: is soft. A new writer of this table has to count too.
#:
#: A bound rather than a taste, by the same route `QUOTE_TEXT_MAX` closes.
#: **Re-measured on 2026-08-24, when the DNB started returning GND subject
#: headings**, which is what a record spends this budget on now.
#:
#: | population | records | mean | over eight |
#: |---|---|---|---|
#: | ISBN lookups at the DNB | 85 | 3.07 | 1 |
#: | four `WOE=` searches at the DNB | 189 | 2.9 | 8, worst query 6 of 50 |
#:
#: **Both figures are one catalogue's**, and this bounds a book that up to four
#: catalogues feed, so neither is headroom for the merged total. The overflow is
#: dropped rather than the number raised, because every stored row is
#: selectin-loaded onto every listing row.
#:
#: **What survives the overflow is decided by order, not by luck**, and the
#: ordering is applied in `routers/books._headings`, which is the only place it
#: can be: a parser can order the record in front of it, and by then `_merge`
#: has concatenated several. See `_SCHEME_ORDER` for which scheme wins and why.
MAX_CLASSIFICATIONS_PER_BOOK = 8


class ClassificationIn(BaseModel):
    """One heading, as a client posts it back after a lookup.

    Accepted from the client rather than re-fetched, because the lookup that
    produced it is the expensive part and the member may sit on the confirm
    screen for a while. Nothing here is trusted beyond its own bounds: the
    scheme is a closed enum, and both strings are bounded and stripped.
    """

    scheme: ClassificationScheme
    number: str = Field(min_length=1, max_length=CLASSIFICATION_NUMBER_MAX)
    label: str | None = Field(default=None, max_length=CLASSIFICATION_LABEL_MAX)

    @field_validator("number")
    @classmethod
    def tidy_number(cls, value: str) -> str:
        """Collapse the whitespace a catalogue's own formatting leaves in.

        MARC pads subfields, so `"QA76.73.P98  V53 2021"` and
        `"QA76.73.P98 V53 2021"` arrive as two spellings of one call number and
        would each earn a row past
        `uq_classifications_book_scheme_number`. A number of only spaces passes
        `min_length=1` and is not a heading.
        """
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("A classification needs a number.")
        return cleaned

    @field_validator("label")
    @classmethod
    def tidy_label(cls, value: str | None) -> str | None:
        """Same collapse, and an empty caption is stored as absent.

        Otherwise `null` and `""` are two spellings of "no caption" and every
        client has to test for both.
        """
        if value is None:
            return None
        return " ".join(value.split()) or None


class ClassificationOut(BaseModel):
    scheme: ClassificationScheme
    number: str
    #: Absent where the source carried the number alone, which is every MARC
    #: 082. A client showing a heading has to be ready for the number by itself.
    label: str | None = None
    model_config = {"from_attributes": True}
