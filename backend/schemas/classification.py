from pydantic import BaseModel, Field, field_validator, model_validator

import ddc
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
#: stored denial of service everyone here pays for, since
#: `books_to_out` selectin-loads this relationship onto every row of every
#: page.
#:
#: **Both capped writers, and there are exactly two of those.**
#: `classifications.add_headings` serves the create and selected enrichment paths.
#: `_repoint_relations` serves a merge. `backup.restore` is a third writer of
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
#: ordering is applied in `classifications.bounded_headings`, which is the only place it
#: can be: a parser can order the record in front of it, and by then `_merge`
#: has concatenated several. See `classifications.SCHEME_ORDER` for which scheme wins and why.
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

    @model_validator(mode="after")
    def dewey_numbers_are_notations(self) -> ClassificationIn:
        """A `ddc` row holds a Dewey notation, refused here rather than assumed.

        **Two things read this column as a notation and both were assuming.**
        `ddc.division` projects it onto a division for the browse facet, and
        `shelf._division_key` does the same projection in SQL for the filter.
        Both carried a comment saying every write path goes through
        `ddc.notation`. Neither did: `ddc.notation` is called from nowhere
        outside `ddc.py`, and `POST /api/books` with
        `{"scheme": "ddc", "number": "Hello world"}` answered 201 and stored it.

        What that cost was not a stored oddity, it was a **fail open filter fed
        by the app's own output**: the facet then published a division `He0`,
        and the chip linking to `?ddc=He0` dropped the unparseable token, applied
        no clause, and returned the whole library. Both critic seats found it
        independently.

        Refused rather than dropped, which is the opposite of the query
        parameter rule twelve modules away and is deliberate. A filter value
        that means nothing is a link somebody typed and there is nobody to tell.
        A stored row is a catalogue assertion, and one that cannot be read as
        the scheme it claims is worth a 422 naming the field.

        Only `ddc`. LCC has no canonical form this app parses, and for GND and
        LCSH the number is an identifier or a phrase, so there is nothing to
        check against.
        """
        if self.scheme is ClassificationScheme.DDC and ddc.notation(self.number) is None:
            raise ValueError(
                f"{self.number!r} is not a Dewey number: three digits, "
                "optionally a decimal fraction."
            )
        return self

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


class HeadingFacetOut(BaseModel):
    """One distinct heading in the library, with how many Books carry it.

    The facet a reader picks from, and the same shape a Book's own heading has
    plus the count, so a client can render both with one component.
    """

    scheme: ClassificationScheme
    number: str
    label: str | None = None
    book_count: int


class DivisionFacetOut(BaseModel):
    """One Dewey division in the library, with how many Books fall in it."""

    #: Three digits ending in zero, as `ddc.division` produces.
    division: str
    #: **This library's own word for the division, not Dewey's caption.**
    #:
    #: The distinction is worth the sentence, because the two look alike and
    #: are not the same claim. Dewey's published captions are the schedule,
    #: which is OCLC's and is not ours to redistribute; what this carries is
    #: the entry from `ddc.DIVISION_TAGS`, the map from a division onto the
    #: seeded tag it is closest to, which this app already computes and already
    #: shows people as a tag suggestion. So `010` reads as `Reference` here
    #: where Dewey says Bibliography: a coarser word, chosen from a vocabulary
    #: the library curated, and correct as far as it goes.
    #:
    #: Absent where the division maps to no tag, which is a real answer rather
    #: than a gap: 040 is unassigned in the schedule, 080 is quotations and 310
    #: is general statistics, and inventing a word for those is the failure
    #: `DIVISION_TAGS` exists to avoid. A client shows the number alone.
    label: str | None = None
    book_count: int


class ClassificationFacets(BaseModel):
    """Everything the classification filter panel needs, in one response.

    Two lists rather than two endpoints, because they are drawn in one panel
    and a caller that wants one always wants the other. A division count is not
    derivable from the heading counts, so this is genuinely two questions with
    one answer rather than one padded out.
    """

    headings: list[HeadingFacetOut]
    divisions: list[DivisionFacetOut]
