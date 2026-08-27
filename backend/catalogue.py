"""What an outside catalogue asserted about one book, as a type rather than a dict.

Every source in `metadata.py` used to hand its answer across this seam as a
`dict[str, Any]`. Six adapters invented their own keys, three consumers guessed
which of them were present, and nothing in the type system told an assertion
somebody else's institution made from a fact this Library holds. ADR 0004 says
those are different things; the code said `dict`.

## The two dialects this replaces

There were **two** shapes, not one, and telling them apart was left to whoever
was reading. A lookup record carried `isbn` and a list of `subjects`; a search
match carried `isbn13`, a `source`, a `google_books_id` and `categories`, the
same subjects joined into one string. Two translators existed only to cross
between them: `metadata._as_match` in one direction and
`routers/books._enrichment_fields` in the other, the second of which was in a
route handler. Both are gone. One `Record` carries the facts, and `as_lookup()`
and `as_match()` name the two schemas it fills.

## What a caller stops having to know

* That a heading may repeat inside one record. One live K10plus record's 082
  `$a` values read `['100', '610', '610']` (measured 2026-08-23), and a
  duplicate spends one of a Book's eight heading slots saying nothing. The
  union runs at construction, so a parser that repeats itself costs nothing and
  no parser has to remember.
* That a caption is filled in from wherever it exists and never overwritten by
  a later source. The number decides identity; the caption is the half most
  sources omit.
* That an **empty list means absent** when one record fills another's gaps.
  This was a live defect rather than a hypothetical: `classifications` was the
  one list valued key in the old match dictionaries, a source that found no
  heading wrote `[]`, `[]` is not `None`, so it beat a populated list from the
  next source. Measured over 30 live title searches, 6 of 10 merged rows whose
  Library of Congress half carried LCSH lost every heading. Here the scalars
  and the two collections are separate fields with separate rules, so the trap
  cannot be written.
* Which fields make a record worth preferring (`completeness`).
* That several catalogues answering for one book are recorded as one row naming
  all of them (`sources`).

## Two ways to fold two records together, and they are two rules

`merged_with` is the **lookup** path. Every record it folds describes the same
printing, because they were all found by the same verified ISBN, so their
subjects and their headings are several catalogues' assertions about one book
and unioning them is right.

`filled_from` is the **search** path. Two rows meet there because they share a
title, an author and a year, which is a guess rather than proof, so the leading
catalogue's own lists are taken whole and the other's fill only what is
missing. There is a second reason it must not union: a search row is bounded at
`MAX_CLASSIFICATIONS_PER_BOOK` before it becomes a `BookMatch`, and `BookMatch`
refuses a ninth entry, so unioning two full rows would cost the row rather than
the heading.

They are named separately instead of one function with a flag, so that reading
a call site tells you which rule ran.

## What is deliberately not here

**No wire schema.** This module returns plain dictionaries keyed to
`BookLookup` and `BookMatch` rather than building them, because those are
request bodies as much as responses: the bounds a client's own payload has to
pass belong to the schema, and `routers/books._headings` is where an unusable
heading is dropped rather than allowed to 422 a member's request.

**No headings inside `as_lookup()` or `as_match()`.** Both return the scalar
facts and nothing else, and the omission is ADR 0006 expressed as a type.
Automatic enrichment and Refresh Metadata write from those dictionaries, and
neither may add a Classification: a heading reaches a Book only when a Member
picks a record and confirms the whole of it. Because the dictionaries carry
none, an unattended writer has nothing to write even by mistake.

**No `visible_to`, no session, no Book.** A Record is evidence about a book,
never a Book. Nothing here touches the database.
"""

import dataclasses
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final

import google_books
from enums import ClassificationScheme
from schemas.classification import MAX_CLASSIFICATIONS_PER_BOOK

#: How several catalogues answering for one book are spelled in `source`.
#:
#: A separator rather than a list, because `BookMatch.source` is a string on the
#: wire and the picker prints it. `sources` is the only reader of it here, so a
#: caller asking which catalogues found a row never sees the punctuation.
_SOURCE_JOIN: Final = "+"


@dataclass(frozen=True, slots=True)
class Heading:
    """One Classification a catalogue asserted, before anything bounds it.

    Not `ClassificationIn`, and the difference is the point. That model is what
    a client may post, so its strings are bounded and a value the column cannot
    hold raises. This is what a catalogue said, which is unbounded by nature: a
    400 character LCSH chain is a real thing to have parsed and a bad thing to
    have raised on halfway through a record. Dropping it is
    `routers/books._headings`, one layer later, where there is a whole record in
    hand and losing one entry costs one entry.

    `number` is the half that identifies the heading and `label` is the caption,
    which most sources omit: MARC 082 carries the notation alone everywhere, and
    the printed Dewey schedule carries the words.
    """

    scheme: ClassificationScheme
    number: str
    label: str | None = None


#: Fields worth having, and therefore worth scoring a record on.
#:
#: Used twice, and the two uses are why this is a property rather than a rule at
#: either call site: choosing between several printings of one ISBN inside a
#: single catalogue, and choosing which catalogue leads the merge when both
#: answer.
_SCORED: Final = (
    "author",
    "year",
    "publisher",
    "page_count",
    "language",
    "description",
    "series_name",
)

#: The scalar facts, which are the fields one record fills in for another.
#:
#: `source` is absent on purpose: it is unioned rather than filled, because two
#: catalogues answering for one book is not one of them being missing.
#: `subjects` and `headings` are absent for the opposite reason: they are
#: collections with two rules of their own, above.
_FILLED: Final = (
    "isbn",
    "title",
    "subtitle",
    "author",
    "publisher",
    "year",
    "description",
    "language",
    "page_count",
    "cover_url",
    "series_name",
    "series_index",
    "google_books_id",
)


@dataclass(frozen=True, slots=True)
class Record:
    """One catalogue's answer about one book. Evidence, never a Book.

    Frozen, because a record is something an institution said at a moment and
    folding two of them produces a third rather than editing either. The old
    dictionaries were rewritten in place, which is how the search merge came to
    `clear()` and `update()` a row to keep its slot in a list.

    Every field defaults to absent, so an adapter names only what its catalogue
    carries and a source that has no notion of a series says nothing rather than
    saying `None` in a dictionary literal.
    """

    #: Which catalogue said it. Several, joined, once a merge has run: see
    #: `sources`.
    source: str = ""
    isbn: str | None = None
    title: str | None = None
    subtitle: str | None = None
    author: str | None = None
    publisher: str | None = None
    year: int | None = None
    description: str | None = None
    language: str | None = None
    page_count: int | None = None
    cover_url: str | None = None
    series_name: str | None = None
    series_index: float | None = None
    #: Google's own volume id, which only Google supplies and only
    #: `google_books.merge_into` stores.
    google_books_id: str | None = None
    #: The publisher's and the catalogue's uncontrolled words for what this book
    #: is about. Feed the tag suggestion, never stored as headings: an Open
    #: Library subject list carries `open_syllabus_project` and
    #: `fiction classics`, which are somebody's words rather than an assertion
    #: from a published scheme.
    subjects: tuple[str, ...] = ()
    #: Assertions from a published scheme, which is what §30i's table holds.
    headings: tuple[Heading, ...] = ()
    #: Whether the two collections above have already been folded.
    #:
    #: **Not a cache and not an optimisation to be tidied away.** Every `replace`
    #: re-runs `__post_init__`, and `_merge_matches` folds every row sharing a
    #: title, an author and a year onto one slot, so a fat record met by N thin
    #: ones re-inspected its whole subject and heading lists N times.
    #:
    #: **The cost is the product of the row count and the surviving record's
    #: width, not either alone**, which is what makes it worth attacking: a
    #: hostile body spends its bytes on one fat record and pads the rest with
    #: minimal rows that share its slot. Both figures below are measured, one
    #: process, one four core worker, CPython 3.14.7:
    #:
    #: | rows | width | body | of the cap | with this field | without |
    #: |---|---|---|---|---|---|
    #: | 5,000 | 7,000 | 1,242,876 | 59% | 0.127 | 42.564 |
    #: | 8,176 | 11,392 | 2,027,588 | **97%** | 0.227 | **125.970** |
    #:
    #: **The second row is the worst shape that fits**, and the budget is worth
    #: writing down because it is not obvious: against `_loc_record`, a thin
    #: `<mods>` row that still parses and still folds onto the same slot costs
    #: 124 bytes, one `<subject authority="lcsh"><topic>` costs 53 and yields a
    #: subject **and** a heading, and one plain `<subject><topic>` costs 36 and
    #: yields a subject. So a width of W costs 89W bytes and 3W inspections per
    #: merge, and the optimum spends half the budget on each side.
    #:
    #: **The column that matters is the fifth**: with the field, the time is
    #: flat in width, so no choice of shape buys the attacker anything.
    #:
    #: `_merge_matches` is synchronous inside `async def search`, so that is the
    #: event loop stopped for every Member at once. `SEARCH_DEADLINE_SECONDS`
    #: does **not** bound it: that bounds `_within_deadline`, and this runs
    #: after it returns.
    #:
    #: **This comment has been wrong twice, in opposite directions, and both are
    #: worth keeping.** It first recorded "over 120 seconds" against a shape of
    #: 8,001 rows and 1,913,056 wire bytes. Re-measured, that shape is 0.854s,
    #: so the recorded shape was wrong, and the comment was then corrected to
    #: say the figure did not reproduce. **That correction was also wrong**: at
    #: the shape above it reproduces at 125.970s. The original timing was real
    #: and taken at a shape nobody wrote down. A number is only checkable if it
    #: says what it was measured against, and a retraction is a number too.
    #:
    #: **The one rule: a `replace` that changes `subjects` or `headings` passes
    #: `_folded=False`.** `merged_with` is the only one that does, because it is
    #: the only one that concatenates. Everything else copies tuples this record
    #: has already folded, and re-folding them cannot find anything.
    #:
    #: `compare=False` so two records are equal on what a catalogue said rather
    #: than on how they were built, and `repr=False` so it stays out of the log
    #: line a failed parse writes.
    _folded: bool = dataclasses.field(default=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Deduplicate both collections, in place, once per record.

        **Here rather than in each parser, and that is a rule moving rather than
        a rule added.** `metadata._dnb_subjects` deduplicated its own subjects
        because 689 restates the 600, 650 and 651 headings it was built from, so
        the reference record 9783446249974 named Stevenson, Samoainseln and
        Schatz twice each. The old `_as_match` deduplicated headings for the
        search path and `_merge` did it again for the lookup path. Three sites,
        one rule, and the next source added would have had to know about all
        three.

        `object.__setattr__` because the class is frozen: this is construction,
        not mutation. It runs **once** per set of collections: see `_folded` for
        the measurement that makes that a requirement rather than a saving.
        """
        if self._folded:
            return
        object.__setattr__(self, "subjects", _unique(self.subjects))
        object.__setattr__(self, "headings", _union(self.headings))
        object.__setattr__(self, "_folded", True)

    @property
    def completeness(self) -> int:
        """How much of this record is actually filled in.

        A count rather than a weighting: the question it answers is "is this a
        record somebody could recognise their copy from", and every field in
        `_SCORED` answers it once.
        """
        return sum(1 for name in _SCORED if getattr(self, name)) + bool(self.subjects)

    @property
    def sources(self) -> frozenset[str]:
        """Every catalogue that answered for this book."""
        return frozenset(part for part in self.source.split(_SOURCE_JOIN) if part)

    def filled_from(self, other: Record) -> Record:
        """This record, with its gaps filled from another. The search path rule.

        Nothing is overwritten: the leading catalogue stays the one describing
        the book, and the other supplies only what it left out. A Google blurb
        and a K10plus page count end up on one row that way.

        **Absent means `None` for a scalar and empty for a collection**, and
        they are two tests because they are two kinds of field. Falsiness would
        be one test and would be wrong: a `page_count` of 0, a `year` of 0, a
        `series_index` of 0.0 and any `""` are values a catalogue supplied, and
        treating them as missing lets a later source overwrite them. Measured
        over 1,629 live rows, 1,216 carry an int and 2 a float.
        """
        changes: dict[str, Any] = {
            name: getattr(other, name)
            for name in _FILLED
            if getattr(self, name) is None and getattr(other, name) is not None
        }
        if not self.subjects:
            changes["subjects"] = other.subjects
        if not self.headings:
            changes["headings"] = other.headings
        changes["source"] = _SOURCE_JOIN.join(sorted(self.sources | other.sources))
        return dataclasses.replace(self, **changes)

    def merged_with(self, other: Record) -> Record:
        """`filled_from`, and both catalogues' subjects and headings. The lookup path.

        Safe here and not on the search path because every record folded here
        was found by the same ISBN, already canonicalised and already checked
        against the record's own 020. They are several catalogues describing one
        printing, so a heading either of them carries is a heading this book
        has.
        """
        return dataclasses.replace(
            self.filled_from(other),
            subjects=self.subjects + other.subjects,
            headings=self.headings + other.headings,
            # The one replace in this repository that changes either collection,
            # and therefore the one that has to fold again. See `_folded`.
            _folded=False,
        )

    def match_headings(self) -> tuple[Heading, ...]:
        """The headings a Member confirms by picking this row, bounded.

        **Bounded here as well as in `routers/books._headings`, and the two are
        not the same job.** That one drops an entry the column could not hold,
        so a 400 character caption costs its own heading rather than the row.
        This one caps the count, and it belongs to the shape rather than to the
        caller: the previous round bounded it in the search handler alone, and
        `GET /{id}/enrich/candidates`, fed by the same search, answered **500
        for the whole response** because `BookMatch` refuses a ninth entry and
        nothing in `main.py` catches a `ValidationError`. Measured over four
        live DNB `WOE=` searches on 2026-08-24: 8 of 189 records carry more than
        eight headings.

        The **lookup** path deliberately does not come through here. Up to four
        catalogues have been concatenated by then, so which heading survives has
        to be decided by scheme and not by which catalogue answered first, and
        that ordering is applied where the whole merged record is in hand.
        """
        return self.headings[:MAX_CLASSIFICATIONS_PER_BOOK]

    def with_cover(self, cover_url: str | None) -> Record:
        """The same record, with the cover the image services actually answered.

        A method rather than leaving `metadata.lookup` to call
        `dataclasses.replace`, so that **no module outside this one replaces a
        field on a `Record`**. That is what keeps `_folded` a rule with one
        reader instead of a convention every caller has to know: a distant
        `replace` passing a new `headings` tuple would silently keep the flag
        and skip the fold.
        """
        return dataclasses.replace(self, cover_url=cover_url)

    def as_lookup(self) -> dict[str, Any]:
        """The scalar facts, in the keys `schemas.book.BookLookup` names.

        Headings are not here: see the module docstring.

        **That schema requires two fields, not one**, and only one of them is
        coerced. `title` is, because a catalogue may answer with an untitled
        record and a `Record`'s title is therefore optional. `isbn` is required
        there too and is passed through as it stands, so a `Record` with no ISBN
        makes `BookLookup(**record.as_lookup())` raise, and `lookup_isbn`
        catches no `ValidationError`, so the response would be a 500.

        **Left as it is, deliberately, and written down rather than fixed.** All
        four sources on the lookup path set `isbn` from the canonicalised
        argument `metadata.lookup` was given, so no live record reaches here
        without one, and coercing it to `""` would answer a member's scan with a
        book carrying an empty ISBN instead of an error. What makes it worth
        stating is that nothing checks it: the return type is `dict[str, Any]`,
        so mypy sees no requirement, and the guarantee lives in four adapters
        rather than in a type. A fifth lookup source that leaves `isbn` unset is
        the change that turns this paragraph into a defect.
        """
        return {
            "isbn": self.isbn,
            "title": self.title or "",
            "subtitle": self.subtitle,
            "author": self.author,
            "publisher": self.publisher,
            "year": self.year,
            "description": self.description,
            "cover_url": self.cover_url,
            "series_name": self.series_name,
            "series_index": self.series_index,
            "language": self.language,
            "page_count": self.page_count,
        }

    def as_match(self) -> dict[str, Any]:
        """The scalar facts, in the keys `schemas.book.BookMatch` names.

        Three keys differ from `as_lookup` and nothing else does: a match names
        the catalogue that found it, calls the ISBN `isbn13` because a search
        row is one printing among several rather than the one asked for, and
        carries the subjects joined into the single string a Book row stores.

        **The join goes through `google_books.join_categories`.** That module
        and its `split_categories` are the only two places that know the
        separator is a semicolon, because Google's own category names contain
        commas ("Fiction, general"). Calling it is not a third place that knows.
        """
        return {
            "source": self.source,
            "google_books_id": self.google_books_id,
            "title": self.title,
            "subtitle": self.subtitle,
            "author": self.author,
            "publisher": self.publisher,
            "year": self.year,
            "description": self.description,
            "page_count": self.page_count,
            "language": self.language,
            "categories": google_books.join_categories(list(self.subjects)) or None,
            "cover_url": self.cover_url,
            "isbn13": self.isbn,
            "series_name": self.series_name,
            "series_index": self.series_index,
        }


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    """The same strings, first occurrence kept, order preserved."""
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return tuple(seen)


def _union(headings: Iterable[Heading]) -> tuple[Heading, ...]:
    """One heading per scheme and number, keeping the caption if any source had one.

    The captions are what differ. **No source supplies a Dewey caption today**:
    the DNB returned `830 Deutsche Literatur` until it moved to MARC21 on
    2026-08-24, and MARC 082 carries the number alone everywhere. The rule is
    kept because it is the schemes that will, and because the same rule runs in
    `routers/books._write_classifications` against a heading already stored,
    which is the live path: the number decides identity, the caption is filled
    in from wherever it exists, and a later source never overwrites a caption
    already found.
    """
    kept: dict[tuple[ClassificationScheme, str], Heading] = {}
    for heading in headings:
        key = (heading.scheme, heading.number)
        existing = kept.get(key)
        if existing is None:
            kept[key] = heading
        elif existing.label is None and heading.label is not None:
            kept[key] = dataclasses.replace(existing, label=heading.label)
    return tuple(kept.values())
