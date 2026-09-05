"""What an outside catalogue asserted about one book, as a type rather than a dict.

Every source used to hand its answer across this seam as a `dict[str, Any]`: six
adapters inventing their own keys, three consumers guessing which were present,
and nothing distinguishing an assertion somebody else's institution made from a
fact this library holds. ADR 0004 says those are different things.

**It replaces two dialects, not one.** A lookup record carried `isbn` and a list
of `subjects`; a search match carried `isbn13`, a `source`, a `google_books_id`
and those subjects joined into one string, with two translators existing only to
cross between them, one of them inside a route handler. `as_lookup()` and
`as_match()` are the two schemas one `Record` fills.

**What a caller stops having to know:**

* That a heading may repeat inside one record. One live record's `082 $a` read
  `['100', '610', '610']`, and a duplicate spends one of a book's eight heading
  slots saying nothing. The union runs at construction.
* That a caption is filled from wherever it exists and never overwritten by a
  later source: the number decides identity, the caption is what most sources
  omit.
* That an **empty list means absent** when one record fills another's gaps. That
  was a live defect rather than a hypothetical.

**What is deliberately not here.** No wire schema, so this returns plain
dictionaries keyed to the schemas rather than importing them. No headings inside
`as_lookup()` or `as_match()`, which return scalars only. **No `visible_to`, no
session, no `Book`**: a Record is evidence about a book and never a book, which
is what keeps this module outside the privacy rule rather than exempt from it.
"""

import dataclasses
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Final

import covers
import google_books
from enums import AuthorityScheme, ClassificationScheme
from models import (
    AUTHOR_LINE_MAX,
    COVER_URL_MAX,
    DESCRIPTION_MAX,
    GOOGLE_BOOKS_ID_MAX,
    ISBN_MAX,
    LANGUAGE_MAX,
    MAX_PAGE_NUMBER_IN_A_BOOK,
    MAX_SERIES_INDEX,
    PUBLISHER_MAX,
    SERIES_NAME_MAX,
    SUBTITLE_MAX,
    TITLE_MAX,
)
from schemas.book import MAX_YEAR, MIN_YEAR
from schemas.classification import MAX_CLASSIFICATIONS_PER_BOOK

logger = logging.getLogger("endpaper.catalogue")

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


@dataclass(frozen=True, slots=True)
class Subject:
    """One subject heading a catalogue asserted, with the stamp it came with.

    Three fields, and only the first is always there: the words, the vocabulary
    the record said they came from, and the identifier that vocabulary gives
    them. A record declaring neither produces `Subject("Fantasy")`, which is what
    every uncontrolled supplier here produces, and a null is the ordinary state
    rather than a parser that forgot: 199 of 453 live DNB subject fields declare
    no vocabulary and both Dublin Core dialects have nowhere to declare one.

    **Not a `Heading`, and the difference is the closed set.**
    `ClassificationScheme` has four members and everything that sorts, filters
    or orders headings reads it. A `$2` is an open set: **twelve** distinct
    codes turned up in one day's sampling of four catalogues, counted rather
    than listed from memory on 2026-08-31 (`bellobv`, `bisacsh`, `DLC`, `fhv`,
    `gatbeg`, `gnd`, `gnd-carrier`, `gnd-content`, `local`, `nlgaf`, `nlggf`,
    `VLK`), against a MARC source code list holding hundreds. Mapping one onto
    the other is a crosswalk, which #134 refuses outright, so the code is
    carried as the record wrote it and nothing here reads it as a scheme.

    **`vocabulary` is lower cased and `identifier` is not.** The folding is
    `metadata._subject_vocabulary`'s, and the reason is in this repository
    rather than in the catalogues: `marc._extra_headings` decides an LCSH
    heading by `== "lcsh"`, so an uploaded file writing `$2 LCSH` would lose
    every one of them silently. **No served record motivates it**, which is
    worth saying because the first version of this paragraph said one did: 0 of
    the twelve codes measured appeared in two cases, and the two upper case ones
    are each written by a single catalogue, `VLK` by the OENB and `DLC` by
    K10plus. An identifier is a value in somebody else's file and case may be
    part of it (`urn:nbn:gr:nlg:01-A273635`), so it is left alone.

    **`identifier` keeps its prefix, where `Classification.number` drops it.**
    That is the opposite rule and it is deliberate. There the `(DE-588)` names
    a scheme the row already has a column for, so keeping it would spell one
    heading two ways. Here there is no scheme column and the prefix is the only
    thing saying which file the number is in: `$2 gatbeg` arrives with
    `$0 (DE-101)1010008188`, so the vocabulary and the identifier's namespace
    are two different answers and neither derives the other.

    **Never a Classification.** Nothing writes a `classifications` row from one
    of these. What a subject is worth is argued in `models.Classification`: a
    row there is an assertion from a published scheme this app has a reading
    for, and a `$2` this app has never heard of is not that. Storing these is
    #143 and #140, and this type is the half those need in hand first.
    """

    label: str
    vocabulary: str | None = None
    identifier: str | None = None


@dataclass(frozen=True, slots=True)
class AuthorityAssertion:
    """One catalogue saying which record in an authority file an author is.

    **Not a `Heading`, though the DNB writes both in the same MARC `$0`.** A
    heading says what the book is about and belongs to the book; this says who
    wrote it and belongs to a *name*, which outlives every book carrying it. One
    type for both would put a subject heading and a person in the same store and
    make `4203576-4` and `118181505` the same kind of row.

    `name` is the spelling the record used, already in reading order: the key it
    is filed under is derived from it by `authors.author_key`, and deriving it
    here would put a normalisation rule in a parser. Unbounded, like
    `Heading.number`, because this is what a catalogue said rather than what a
    client may post: `authorship.Authorship` drops what the column cannot hold,
    one layer later, with the whole record in hand.

    **Certainty is not a field**, and its absence is the design. Whether an
    assertion is trustworthy is a property of the path that fetched it, not of
    the record: `100 $0` on a record found by this book's verified ISBN is a
    cataloguer's claim about this book, and the identical subfield on a record
    found by a title and author search is a guess about somebody with a similar
    name. The parser cannot tell them apart because it is the same parser. So
    the call site decides, by calling `Authorship.record_catalogue_assertions`
    or by not calling it, which is the same reason `merged_with` and
    `filled_from` are two names rather than one function with a flag.
    """

    name: str
    scheme: AuthorityScheme
    identifier: str


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
#: `subjects`, `headings` and `author_identifiers` are absent for the opposite
#: reason: they are collections with two rules of their own, above.
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


#: How wide a scalar fact may be before the column that stores it cannot hold it.
#:
#: Every ceiling is imported from `models`, which is where the column declares
#: it, so this table cannot drift from the schema and there is no second literal
#: to keep in step. `tests/test_catalogue.py::TestARecordAgreesWithTheColumnsItFeeds`
#: recomputes each one from `Book.__table__` rather than restating it.
#:
#: `description` is the one whose column is `Text` and therefore declares
#: nothing. `DESCRIPTION_MAX` is the ceiling `BookCreate`, `BookMatch` and
#: `BookLookup` already hold it to, and it is imported from the same module for
#: the same reason.
_TEXT_CEILINGS: Final[dict[str, int]] = {
    "title": TITLE_MAX,
    "subtitle": SUBTITLE_MAX,
    "author": AUTHOR_LINE_MAX,
    "publisher": PUBLISHER_MAX,
    "description": DESCRIPTION_MAX,
    "language": LANGUAGE_MAX,
    "cover_url": COVER_URL_MAX,
    "series_name": SERIES_NAME_MAX,
    "google_books_id": GOOGLE_BOOKS_ID_MAX,
    # Bounding this can clear the field, and `as_lookup` hands `None` to a
    # required `BookLookup.isbn`, which is a 500 on a member's scan. Safe only
    # while every lookup producer parses its own identifier: `as_lookup` carries
    # the risk and the trigger, `docs/decisions.md` the measurement.
    "isbn": ISBN_MAX,
}

#: How a value is rewritten between the record and the column, where anything
#: rewrites it. The ceiling is measured against the **stored** form, not the
#: parsed one.
#:
#: One entry, and it is an off by one rather than a hypothetical. `Book`'s
#: `@validates("cover_url")` runs `covers.https_url` on every write, which turns
#: `http://` into `https://` and so **lengthens the value by one character**.
#: Measured through the refresh handler's own line: a 500 character http URL was
#: stored as 501 against a `String(500)`. That is one character on SQLite, which
#: enforces nothing, and a failed flush on an engine that does. http is not an
#: edge here either: Google Books serves `imageLinks.thumbnail` over it, which is
#: the whole reason `https_url` exists.
#:
#: A table rather than a special case inside the loop, because the next column
#: that grows a validator has somewhere to go that is not another arm.
_AS_STORED: Final[dict[str, Callable[[str], str | None]]] = {
    "cover_url": covers.https_url,
}

#: What a numeric fact has to fall inside, closed at both ends.
#:
#: These are not column widths: all three columns are `Integer` or `Float` and
#: SQLite would hold anything. They are the bounds this app's own request bodies
#: already carry, and the reason they belong here is that a value outside them
#: is a row a Member cannot then edit: `BookDetailsUpdate` answers 422 for
#: exactly the values an unbounded catalogue write could store.
#:
#: `series_index` is the one with teeth beyond an untidy row. `routers/books.list_series`
#: computes `set(range(1, max(held) + 1))` over the column, so a stored `1e9` is
#: roughly 70 GB and ten minutes of work on every request by every Member. The
#: refresh handler does not write that column, which is why this ticket is not
#: that severity, but `google_books.merge_into` does and it is fed from here.
_NUMBER_RANGES: Final[dict[str, tuple[float, float]]] = {
    "year": (MIN_YEAR, MAX_YEAR),
    "page_count": (1, MAX_PAGE_NUMBER_IN_A_BOOK),
    "series_index": (0, MAX_SERIES_INDEX),
}

#: The one scalar with no ceiling, and why it needs none.
#:
#: **`source`** is this app's own word rather than a catalogue's, so there is no
#: outside value to bound: `Record.sources` joins the roster's own names.
#:
#: Pinned by `TestWhichScalarsAreBoundedAndWhichAreNamedInstead`, which asserts
#: the composition as well as the coverage: moving a name out of the ceilings
#: and into here in one gesture leaves the coverage assertion green.
_UNBOUNDED: Final = frozenset({"source"})

#: Which strings an uploaded file may have cut to fit, and which it may not.
#:
#: `Record.from_upload` truncates rather than drops, and the two sets are the
#: half of that policy nobody would think to write down: **a cut value has to
#: still be an instance of what it was.** A title cut to 500 characters is the
#: same book seen through a narrower window, which is why the importer would
#: rather have it than lose the row. A URL cut to 500 characters is a different
#: address, a Google volume id cut to 50 names a different volume, and a
#: language code cut to 10 names a different language or nothing at all. Those
#: are dropped on the upload path too, which is the answer the network path
#: gives for everything. **An ISBN is the same family and the sharpest case of
#: it**: a cut identifier fails its own checksum, so it names no book at all,
#: and `books.isbn` is the importer's primary match key. Deliberately no count
#: of them here: the set is on the next line and a number would be a second
#: thing to keep in step.
#:
#: `cover_url` and `google_books_id` are not reachable from a MARC file today:
#: `_MARC_RECORD_FIELDS` carries neither. The other two are, and neither can
#: arrive over-wide: `_marc_language` reads a three letter `041 $a`, and
#: `metadata._marc_isbn` returns `isbn.parse` output. All four are classified
#: anyway, because a set that is exhaustive by assertion cannot acquire a field
#: by default, which is the shape this repository keeps finding.
_CUT_ON_UPLOAD: Final = frozenset(
    {"title", "subtitle", "author", "publisher", "description", "series_name"}
)
_KEPT_WHOLE_ON_UPLOAD: Final = frozenset(
    {"language", "cover_url", "google_books_id", "isbn"}
)


def _drop_unstorable(record: Record) -> list[str]:
    """Clear every scalar the columns could not hold, and name them.

    **The field rather than the record**, which is the rule
    `routers/books._bounded_match` settled: a catalogue value too wide loses
    that field, it does not lose the record and it never 422s a Member's own
    request. Here it is applied one layer earlier, so every consumer of a
    `Record` inherits it instead of each one remembering.

    **`None` rather than a truncation.** A record says what a catalogue
    asserted, and half a title is an assertion nobody made. Absent is a state
    every consumer already handles: `filled_from` fills it from another
    catalogue, `merge_into` skips it, and the refresh handler's `or book.title`
    keeps what the Book already had.

    This mutates through `object.__setattr__` because the class is frozen and
    this is construction rather than mutation, exactly as the fold above it.
    """
    dropped: list[str] = []
    for name, ceiling in _TEXT_CEILINGS.items():
        value = getattr(record, name)
        if value is None:
            continue
        rewrite = _AS_STORED.get(name)
        stored = rewrite(value) if rewrite is not None else value
        if stored is not None and len(stored) > ceiling:
            object.__setattr__(record, name, None)
            dropped.append(name)
    for name, (low, high) in _NUMBER_RANGES.items():
        value = getattr(record, name)
        if value is not None and not low <= value <= high:
            object.__setattr__(record, name, None)
            dropped.append(name)
    return dropped


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
    #: What this book is about, in the catalogue's own words, each carrying the
    #: vocabulary the record declared and the identifier it gave. Feeds the tag
    #: suggestion, never stored as headings: an Open Library subject list
    #: carries `open_syllabus_project` and `fiction classics`, which are
    #: somebody's words rather than an assertion from a published scheme, and a
    #: declared vocabulary does not change that. See `Subject`.
    subjects: tuple[Subject, ...] = ()
    #: Assertions from a published scheme, which is what §30i's table holds.
    headings: tuple[Heading, ...] = ()
    #: Which record in an authority file each credited person is, where the
    #: catalogue said so. Empty everywhere but the DNB: see
    #: `metadata._marc_author_identifiers`.
    author_identifiers: tuple[AuthorityAssertion, ...] = ()
    #: Whether the three collections above have already been folded.
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
    #: **The one rule: a `replace` that changes `subjects`, `headings` or
    #: `author_identifiers` passes `_folded=False`.** `merged_with` is the only
    #: one that does, because it is the only one that concatenates. Everything else copies tuples this record
    #: has already folded, and re-folding them cannot find anything.
    #:
    #: `compare=False` so two records are equal on what a catalogue said rather
    #: than on how they were built, and `repr=False` so it stays out of the log
    #: line a failed parse writes.
    _folded: bool = dataclasses.field(default=False, repr=False, compare=False)

    @classmethod
    def from_upload(cls, **fields: Any) -> Record:
        """A record read out of a file somebody handed over, its strings cut to fit.

        **The one producer whose over-wide strings are truncated rather than
        dropped, and the reason is the input rather than the type.** A catalogue
        answering over the network is asserting something about a book this
        Library already holds, and half of that assertion overwriting a good
        stored value is worse than nothing, so `_drop_unstorable` clears it. An
        uploaded MARC file is the Member's own library arriving in one batch,
        where losing a title loses the row: `books.title` is `NOT NULL`, so a
        dropped title is not a thin record, it is a 500 and a lost transfer.

        That policy is not invented here. `importing.within_bounds` has held it
        since 2026-09-03, in as many words: strings truncate because truncating
        a title keeps the record, and numbers are dropped because clamping a
        `9999` to 2200 asserts a date nobody supplied. This states the same rule
        one layer above it rather than moving it: that function is unchanged and
        still runs, and it now finds every value already inside its column. The
        point of saying it here as well is the invariant, that every `Record` in
        this application fits the columns whatever produced it, so the two
        producers differ in how they get there rather than in whether they do.

        **Numbers are not touched here**, deliberately: dropping them is already
        both policies, so `__post_init__` is the whole of that rule and a second
        statement of it would be a place for the two to disagree.

        **Nor is every string.** See `_CUT_ON_UPLOAD`: a cut title is the same
        book, and a cut URL, volume id or language code is a different thing
        rather than a shorter one, so those are dropped here as well.
        Deliberately no count of them, since the set is next to this and a
        number here would be a second thing to keep in step.

        `tests/test_catalogue.py::TestARecordFromAnUploadedFile` pins the split,
        including that no module but `marc.py` opens this door.
        """
        cut = {
            name: value[: _TEXT_CEILINGS[name]]
            for name, value in fields.items()
            if name in _CUT_ON_UPLOAD and isinstance(value, str)
        }
        return cls(**{**fields, **cut})

    def __post_init__(self) -> None:
        """Bound the scalars against their columns, then deduplicate the collections.

        **The bound runs above the `_folded` guard and the fold runs below it,
        and that split is the whole of why this is not one paragraph.** The fold
        is idempotent and expensive, so it runs once per set of collections. The
        bound is cheap and is **not** idempotent across a `replace`:
        `with_cover` puts a URL on a record the image services chose, after the
        flag is already set, so a bound below the guard would let that one field
        through unchecked. Everything else `replace` copies has been bounded
        already, so re-checking it costs the comparisons and finds nothing.

        Measured on the worst shape `_folded` records: one process on the four
        core development host, CPython 3.14, 8,176 `filled_from` calls onto a
        record carrying 22,784 subjects and 11,392 headings, costing **0.077s**
        with the bound stubbed out and **0.088s** with it, a difference of
        **0.011s** over those 8,176 constructions. Re-derived independently on
        the same host as 0.075s, 0.088s and 0.013s. Not a suite run and so not
        one of the worker nodes, which is why the machine is named by its shape
        rather than by its name.

        That is the replaces alone and **not** the 0.227s in
        `_folded`, which is `_merge_matches` end to end on the same shape: a
        different harness measuring a different thing, quoted here so the two
        are not read as one number.

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

        **The subject fold has three passes since #134 and is still linear.**
        Counted rather than carried forward: `kept`, then `by_label`, then the
        filter that calls `_restates`. This said **two** until the pass that
        calls `_restates` was added and the sentence was not recounted.

        The third is the one worth checking, because `_restates` scans a whole
        label group and so looks quadratic. It is not: `kept` is keyed on
        (label, vocabulary), so a group holds **at most one** entry whose
        vocabulary is None, and `or` short circuits, so `_restates` runs at most
        once per group and costs that group's length. The total is the sum of
        the group lengths, which is the number of kept entries. The budget in
        `_folded` counts inspections per merge and is unchanged.
        """
        dropped = _drop_unstorable(self)
        if dropped:
            # The source is named untruncated on purpose: it is one of this
            # app's own roster literals, never a catalogue's string. See
            # `_UNBOUNDED`.
            logger.info(
                "Dropped %s from a record from %r: the column cannot hold it",
                ", ".join(dropped),
                self.source,
            )

        if self._folded:
            return
        object.__setattr__(self, "subjects", _folded_subjects(self.subjects))
        object.__setattr__(self, "headings", _union(self.headings))
        object.__setattr__(
            self, "author_identifiers", _distinct(self.author_identifiers)
        )
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

    @property
    def subject_labels(self) -> list[str]:
        """The subject words, each once, in order. What a reader is shown.

        **A second deduplication, and it is not the fold repeated.**
        `_folded_subjects` keeps `Roemisches Recht` twice on purpose, once for
        `gnd` and once for `local`, because they are two catalogued assertions.
        Neither of the two consumers can use that distinction and both would be
        wrong to show it: `as_match` joins these into the one `categories`
        string a person reads, where the same word twice reads as a bug, and
        `suggested_tag_ids` matches them against tag names, where a repeat buys
        nothing. Measured over the same live sample, 15 of 765 (record, label)
        pairs are affected.

        A `list` rather than a tuple because both callers pass it straight into
        a function taking one.
        """
        seen: dict[str, None] = {}
        for subject in self.subjects:
            seen.setdefault(subject.label, None)
        return list(seen)

    def filled_from(self, other: Record) -> Record:
        """This record, with its gaps filled from another. The search path rule.

        Nothing is overwritten: the leading catalogue stays the one describing
        the book, and the other supplies only what it left out. A Google blurb
        and a K10plus page count end up on one row that way.

        **Absent means `None` for a scalar and empty for a collection**, and
        they are two tests because they are two kinds of field. Falsiness would
        be one test and would be wrong: a `series_index` of 0.0 and any `""` are
        values a catalogue supplied, and treating them as missing lets a later
        source overwrite them. Measured over 1,629 live rows, 1,216 carry an int
        and 2 a float.

        **This sentence used to name four falsy values and two of them are now
        unreachable**, which is worth saying rather than leaving a reader to
        re-derive. A `page_count` of 0 and a `year` of 0 fall outside
        `_NUMBER_RANGES`, so `__post_init__` has already cleared them to `None`
        before this runs. The rule is unchanged and still has teeth:
        `series_index` is bounded at 0 inclusive, and no ceiling makes `""`
        absent.
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
        if not self.author_identifiers:
            changes["author_identifiers"] = other.author_identifiers
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
            author_identifiers=self.author_identifiers + other.author_identifiers,
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

        **`isbn` is left uncoerced deliberately, and written down rather than
        fixed.** Every source on the lookup path sets it from the canonicalised
        argument `metadata.lookup` was given or from `isbn.parse`'s output, so a
        live record reaching here without one is a defect rather than an
        ordinary answer, and coercing it to `""` would answer a member's scan
        with a book carrying an empty ISBN instead of an error. What makes it
        worth stating is that nothing in the **type** checks it: the return is
        `dict[str, Any]`, so mypy sees no requirement, and the guarantee lives
        in the adapters and in
        `tests/test_metadata.py::TestEverySourceSetsTheIsbnItWasAskedFor`.

        **No number is put on "every", deliberately, and it is a rule rather
        than a style.** `tests/test_roster_counts.py` admits a candidate only
        when its value is a **live** cardinality, so the right number here
        creates a candidate with no verdict and fails that census, while a wrong
        one is invisible to it. **A count leaves the census's scope at the
        moment it becomes stale enough**, which is worth knowing about a guard
        whose whole subject is stale counts. This sentence read "All **five**
        sources" while the roster was larger, and a seat quoted it when deciding
        it was safe to bound this field. A sentence with no number needs no
        verdict and cannot rot.

        **The adapter that did not keep the guarantee now keeps it, and the
        field is bounded because of that.** `metadata._google_record` set
        `isbn=fields.get("isbn13") or isbn`, preferring an identifier taken out
        of Google's JSON with no parse over the canonicalised argument;
        `metadata._google_isbn13` parses it and refuses a non string first. So
        every producer reaching here sets the field from `isbn.parse` output,
        which is narrower than the column, and the ceiling `_TEXT_CEILINGS` now
        carries cannot clear it. **No width is written here**, because a number
        in prose stops being re-derived:
        `tests/test_catalogue.py::TestWhichScalarsAreBoundedAndWhichAreNamedInstead`
        recomputes it from the parser and compares it with `ISBN_MAX`.

        **The bound is safe because of that invariant and not on its own**: an
        adapter that set `isbn` from a record's own bytes again would turn the
        ceiling into the 500 this paragraph describes, which is why the trigger
        below is still written down.

        **The trigger is a shape, not a number, and that is why it worked.**
        It named the next source by ordinal once, and the OENB arrived on
        2026-08-27 and was checked because of it: it passes the canonicalised
        ISBN into `metadata._dnb_record` the way the DNB's own lookup does, so
        the guarantee held. The ordinal has since been wrong while the shape
        stayed right, so only the shape is kept. **A lookup source that leaves
        `isbn` unset, or sets it from a record's own bytes without parsing, is
        the change that turns this paragraph into a defect.** The tripwire only
        ever worked because somebody wrote the trigger down rather than the
        count.
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
            "categories": google_books.join_categories(self.subject_labels) or None,
            "cover_url": self.cover_url,
            "isbn13": self.isbn,
            "series_name": self.series_name,
            "series_index": self.series_index,
        }


def uncontrolled(labels: Iterable[str]) -> tuple[Subject, ...]:
    """Subjects from a source that declares no vocabulary and no identifier.

    Named rather than left as a comprehension at each site, so that a reader
    comparing the adapters sees which of them **cannot** supply the stamp rather
    than which of them forgot to.

    **Four catalogues**, at five call sites: the BnF, the NKP, Google Books and
    Open Library, the last of which builds a record on both the lookup path and
    the edition cluster. The reason is the format rather than the catalogue.
    Dublin Core has nowhere to put either, in both its dialects, measured
    2026-08-31 over the BnF's 153 `dc:subject` elements in 200 records, whose
    only attribute is `xml:lang`, and the NKP's 17 in 5, which carry no
    attribute at all. Google and Open Library publish uncontrolled words by
    nature.

    The Library of Congress is **not** here and is the reason this is not simply
    "the non MARC sources": MODS names the vocabulary in an `authority`
    attribute and carries no identifier, so `metadata._loc_subjects` supplies
    half and calls nothing.

    A source that stops being in that list stops calling this, which is a change
    to one line and visible in a diff.
    """
    return tuple(Subject(label) for label in labels)


def _restates(bare: Subject, entries: list[Subject]) -> bool:
    """Whether an undeclared subject only repeats something declared beside it.

    True when some entry sharing its label declares a vocabulary **and** the
    bare one adds no identifier of its own: either it carries none, or it
    carries one a declared entry already names.

    **The identifier clause is the whole of this rule and it is measured.** Over
    the 169 live (record, label) pairs that carry a declared and an undeclared
    occurrence together, the undeclared entry this function is handed carries
    the identical identifier **147** times, none at all **20** times, and a
    **different** one **2** times. **147 + 20 + 2 = 169**, which is the check,
    and stating it is the point rather than decoration: the first version of
    this paragraph read 27, 150 and 2, which sums to 179, in the same commit
    whose headline correction is that a partition must sum.

    **179 is a real number and it counts something else.** It is the undeclared
    **occurrences**, and a record may write several for one label. It cannot be
    the unit here, because `_folded_subjects` collapses every undeclared
    occurrence of a label into the one key `(label, None)` before this function
    ever runs, so what this decides is one entry per pair. Recounted per pair by
    mirroring the fold rather than by reconciling the old rows, which also moved
    the occurrence figures to 149, 27 and 3.

    The 2 are real and are the reason this is not simply "an undeclared repeat
    folds away": the OENB writes
    `650 $a Oesterreich $2 VLK $0 (AT-VLB)LA01044691` and, on the same record, a
    `689 $a Oesterreich $0 (DE-588)4043271-3`. Folding the second into the first
    throws away the GND number, which is the better identifier of the two.

    **And it is not fixed by filling the identifier across the fold**, which is
    the obvious repair and is wrong. Writing `(DE-588)4043271-3` onto the `VLK`
    entry asserts that the GND number is the identifier of a heading in the
    Vorarlberg list. That is a crosswalk between two vocabularies, which #134
    refuses outright, and it is exactly the assertion nobody made. So the two
    stay side by side, labelled differently, which is what this whole ticket is
    for.
    """
    declared = [entry for entry in entries if entry.vocabulary is not None]
    if not declared:
        return False
    return bare.identifier is None or any(
        entry.identifier == bare.identifier for entry in declared
    )


def _folded_subjects(subjects: Iterable[Subject]) -> tuple[Subject, ...]:
    """One subject per label and vocabulary, and an undeclared restatement of a
    declared label folds away.

    Measured on 2026-08-31 over 765 distinct (record, label) pairs from live
    DNB, OENB, NLG and K10plus records.

    **A label under two declared vocabularies stays two subjects**, 15 pairs of
    the 765: `Woerterbuch` is a `gnd` subject and a `gnd-content` form type on
    one record, `Roemisches Recht` is `gnd` and `local` on another. Folding
    those together asserts that one vocabulary's heading is the other's, which
    is the crosswalk #134 refuses in as many words.

    **A label some field declared and another restated undeclared is one
    subject**, 169 pairs of the 765 and the same 169 `_restates` partitions. It
    is the ordinary shape rather than an edge: the DNB's `689` restates the
    `600`, `650` and `651` headings it was built from and declares no `$2` on
    any of 199 live fields. This is not
    inference. It gives no undeclared value a vocabulary; it drops a second copy
    of something the record already wrote. **What counts as a restatement is
    `_restates`**, and the identifier is why that is a function rather than a
    label comparison.

    **A label keeps the place of its first occurrence, whichever entry
    survives.** This is the half that was wrong when the rule was written: the
    fold emitted surviving entries in key order, so dropping an undeclared entry
    that came first moved its label to wherever the declared one sat, and
    `Roman; Informatik` became `Informatik; Roman`. That is not internal.
    `as_match` joins these labels into `categories`, `categories` is **stored on
    the Book**, and a person reads it, so "nothing reads the order" was false as
    written: a human reading the order is reading the order. K10plus reaches the
    shape on its own (`650` declares nothing, `689` declares `gnd`) and a merge
    of two catalogues reaches it without either doing so.

    Grouping by label rather than sorting keeps this linear: a dict preserves
    insertion order, and a label's first key is inserted at its first
    occurrence, so the groups come out in first occurrence order for free. The
    budget in `Record._folded` counts inspections per merge and is unchanged.

    Within one label the entries keep the order the records wrote them, and an
    identifier is filled in from whichever occurrence has one and never
    overwritten, which is `_union`'s rule for a caption applied to the half a
    record more often omits.
    """
    kept: dict[tuple[str, str | None], Subject] = {}
    for subject in subjects:
        key = (subject.label, subject.vocabulary)
        existing = kept.get(key)
        if existing is None:
            kept[key] = subject
        elif existing.identifier is None and subject.identifier is not None:
            kept[key] = dataclasses.replace(existing, identifier=subject.identifier)

    by_label: dict[str, list[Subject]] = {}
    for (label, _), subject in kept.items():
        by_label.setdefault(label, []).append(subject)

    return tuple(
        subject
        for entries in by_label.values()
        for subject in entries
        if subject.vocabulary is not None or not _restates(subject, entries)
    )


def _distinct(assertions: Iterable[AuthorityAssertion]) -> tuple[AuthorityAssertion, ...]:
    """The same assertions, first occurrence kept, order preserved.

    **Deduplicated on the whole value, not on a key.** `_union` folds two
    headings that share a scheme and a number because the caption is the half
    sources omit and there is a right answer to merge towards. There is no such
    half here: two records giving one spelling two different GND numbers is a
    disagreement to carry to the store, which refuses the second rather than
    picking, and folding it here would hide the conflict behind whichever
    catalogue answered first.

    What this does remove is the ordinary repeat, which every DNB record with an
    author produces: `100` names the author and a `700` for the same person
    names them again, exactly as `_marc_authors` already has to fold.
    """
    seen: dict[AuthorityAssertion, None] = {}
    for assertion in assertions:
        seen.setdefault(assertion, None)
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
