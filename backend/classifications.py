"""The classifications table: what may be written to it, and how much.

Three rules live here and they are one rule seen at three distances, plus the
log helper the first of them needs.
`bounded_headings` decides which of a record's assertions this app can hold at
all. `SCHEME_ORDER` decides which of them survive when a book runs out of room.
`add_headings` puts the survivors on a Book without ever exceeding the ceiling or
depositing a heading twice.

**A module rather than three private functions in `routers/books.py`, which is
where all three were.** They gained a second caller when MARC import arrived:
`importing.py` writes a Book's headings out of an uploaded catalogue record and
has to obey the same ceiling, the same ordering and the same drop rule. A
router is the wrong place for a rule a domain module needs, and a second copy
of a ceiling is a ceiling that has stopped being one. The lookup path and the
import path now cannot disagree about what a book may carry, because there is
one implementation and no flag on it.

**Nothing here queries.** `add_headings` takes a Book somebody else resolved and adds
rows to it; `bounded_headings` takes a parser's output and touches no session
at all. The privacy rule is `shelf.py`'s and is applied before a Book reaches
either.

**How a scheme's numbers sort is not one of the three, and lives in
`filing.py`.** `SCHEME_ORDER` below decides which heading a full Book keeps, so
it reads like the place a shelf order would go, and it is not: it ranks whole
schemes against each other and a filing rule ranks numbers within one.
"""

import logging
from collections.abc import Iterable, Sequence
from typing import Final

from pydantic import ValidationError
from sqlalchemy.orm import Session

from catalogue import Heading
from enums import ClassificationScheme, HeadingKind
from models import Book, Classification
from schemas.classification import MAX_CLASSIFICATIONS_PER_BOOK, ClassificationIn

logger = logging.getLogger("endpaper.classifications")


#: How much of a rejected third party value reaches the log.
#:
#: A catalogue response has no size cap anywhere in `metadata.py`, so an
#: untruncated `%r` of a record writes as many bytes to the log as the record
#: holds. `backup.py` already solves the identical problem the same way with
#: `cover[:120]` in its own "dropped rather than refused" line.
LOGGED_VALUE_MAX = 200


def clipped(value: object) -> str:
    """A third party value, short enough to log. See `LOGGED_VALUE_MAX`."""
    text = repr(value)
    return text if len(text) <= LOGGED_VALUE_MAX else text[:LOGGED_VALUE_MAX] + "..."


#: Which heading survives a full book, most worth keeping first.
#:
#: DDC leads because it is the only scheme a tag suggestion is projected from,
#: so losing it costs the member something visible. LCC next: a shelf
#: classification is one assertion per catalogue and the thing a MARC export
#: needs. The two subject vocabularies come after both, because a single record
#: supplies several of each (GND 2.20 per record over 85 live DNB records, LCSH
#: 2.03 per record that carries any over 900 live Library of Congress records,
#: both measured 2026-08-24) and an eighth subject heading is worth less than
#: another catalogue's Dewey number.
#:
#: **GND before LCSH, and the tie is broken on which `number` is stable.** They
#: are the same kind of assertion at nearly the same rate, so the reason has to
#: be the column: a GND row's number is an authority identifier that outlives
#: its own caption, and an LCSH row's number is the heading string itself,
#: which is precisely what moves when the Library of Congress revises a heading
#: (`Afro-Americans` became `African Americans`). The store exists to hold the
#: half that does not move, so the scheme that has one is kept first. Nothing
#: rendered a classification when this was written, so it was not a display
#: preference. That changed: a Book's headings are now shown, filtered and
#: sorted, and this order decides which of them a full Book keeps. It is
#: still a keeping rule rather than a display one, since nothing draws them
#: in this order, but it is no longer invisible when it drops one.
#:
#: A scheme missing from here sorts last rather than raising, so adding one to
#: `ClassificationScheme` cannot break the ceiling by forgetting this.
SCHEME_ORDER: Final[dict[ClassificationScheme, int]] = {
    ClassificationScheme.DDC: 0,
    ClassificationScheme.LCC: 1,
    ClassificationScheme.GND: 2,
    ClassificationScheme.LCSH: 3,
}


#: Which kind of heading survives a full book, most worth keeping first.
#:
#: A subject leads because it is what the store is for: `models.Classification`
#: opens "one published scheme's assertion about what a book is about", and the
#: other two are not that. A content type comes next because it is still about
#: the work, a genre or a form somebody would browse by. A carrier is last
#: because it describes the object in the member's hand, which they can see.
#:
#: **Only the carrier is demoted, and a content type deliberately ties with a
#: subject.** This outranks `SCHEME_ORDER`, so a rank of its own is a heading
#: dropped before every subject from every scheme. That is the right answer for
#: a disc and the wrong one for `Fiktionale Darstellung`, which is the heading
#: `#162` names as the reason not to refuse the content vocabulary at all: given
#: its own rank it would be dropped before any Library of Congress subject,
#: where `SCHEME_ORDER` alone had kept it ahead of one. So a content type ties
#: and falls through to the scheme order it had before, and the only behaviour
#: this changes is the carrier's.
#:
#: The tie is what makes that true, so it is a rank two of them share rather
#: than a comment saying they are close.
KIND_ORDER: Final[dict[HeadingKind, int]] = {
    HeadingKind.SUBJECT: 0,
    HeadingKind.CONTENT: 0,
    HeadingKind.CARRIER: 1,
}


def kind_of(kind: HeadingKind | None) -> HeadingKind:
    """What a heading asserts, reading an undeclared one as a subject.

    **The one place the null is interpreted**, so the fallback is stated once
    rather than at each of the readers. Every row written before
    `a1e7c93b60df` carries a null, as does every Dewey number and every call
    number today, and a subject is what all of those are.

    **Narrow rather than tolerant, and the first version was tolerant for a
    reason that turned out to be false.** It took `object` and degraded, citing
    `filing.sort_key_for` and the archive `backup.restore` inserts through Core.
    That analogy does not hold: `sort_key_for` **is** called on the restore
    value, at `backup._parse_row`, and this is not called on a column value
    anywhere. What guards the column is `ck_classifications_kind`, which is the
    strong side of the split `tests/test_house_rules.py` holds, so the tolerance
    guarded nothing while reading as though it did.
    """
    return kind if kind is not None else HeadingKind.SUBJECT


def bounded_headings(entries: Iterable[Heading]) -> list[ClassificationIn]:
    """The classifications in a catalogue record, through the schema a client posts.

    **An upstream catalogue is no more trusted than a browser.** The lookup
    response is a draft the client posts straight back, so a caption longer than
    the column or a number longer than `CLASSIFICATION_NUMBER_MAX` has to be
    refused here rather than accepted into a payload that then 422s on the way
    in. Nothing
    in a record is worth failing the whole lookup for, so a bad entry is
    dropped and logged and the rest of the record is answered.

    **Validated first, then truncated.** Slicing the input to
    `MAX_CLASSIFICATIONS_PER_BOOK` before the loop would let eight malformed
    entries hide a ninth good one, which is the opposite of what dropping a bad
    entry is for.

    **Ordered by kind, then by scheme, before the slice, and this is the only
    place that can be.** The kind leads: a disc the DNB wrote into a subject
    field is the first thing a full book should lose, and before this it was
    kept ahead of a Library of Congress subject heading because its number
    happened to be a GND one. A parser can only order the record in front of it,
    and by the time a list reaches here a merge has concatenated up to seven
    catalogues, which is every catalogue whose reader builds a `Heading`: the
    leading source's subject headings sit in front of the second catalogue's
    Dewey number and the Library of Congress's call number, which are then the
    first things dropped. Ordering here is what makes "the Dewey number
    survives" true of a book rather than of a record.

    **Catalogues rather than sources, because a catalogue is not the only
    thing that builds one.** `marc._record` builds headings out of an uploaded
    file and `routers/imports` hands them straight to this function, so a claim
    about every *source* was false by one. The count itself is derived rather
    than restated, by `tests/test_classifications.py`.
    """
    headings: list[ClassificationIn] = []
    for entry in entries:
        try:
            headings.append(
                ClassificationIn(
                    scheme=entry.scheme,
                    number=entry.number,
                    label=entry.label,
                    kind=entry.kind,
                )
            )
        except ValidationError:
            logger.info("Discarded an unusable classification: %s", clipped(entry))
    # Stable, so within one kind and scheme the catalogues keep the order they
    # answered in and the leading source still wins.
    headings.sort(
        key=lambda heading: (
            KIND_ORDER[kind_of(heading.kind)],
            SCHEME_ORDER.get(heading.scheme, len(SCHEME_ORDER)),
        )
    )
    return headings[:MAX_CLASSIFICATIONS_PER_BOOK]


def add_headings(
    book: Book, headings: Sequence[ClassificationIn], db: Session
) -> list[str]:
    """Add or complete this book's headings. Returns the numbers it **changed**.

    **Returning a filled in caption as a change is load bearing**, not
    bookkeeping. `apply_enrichment` commits only `if updated:`, and `get_db`
    closes the session in its `finally` without committing, so a call that
    returned `[]` after setting `stored.label` would have the caption rolled
    back and lost. That is reachable: the DNB answers
    `650 $0 (DE-588)4026894-9 $a Informatik` where a stored row from an earlier
    run carries the number and no caption, so a book already complete in every
    column gains nothing but the caption.

    The example used to be a Dewey one, and it stopped being possible on
    2026-08-24: no source captions a Dewey number now that the DNB reads MARC
    082, which carries the notation alone. GND is where a caption arrives.

    **Additive, and never a replacement.** Selecting the same Catalogue record
    may happen more than once. A writer that replaced the set would churn the
    table on every selection, and one that appended blindly would deposit a
    second copy of every heading.
    `uq_classifications_book_scheme_number` refuses the second copy at the
    database, and this refuses it before the flush, where there is still a
    request to answer.

    Deduplicated **within** the payload too. A client may post the same number
    twice (two catalogues agreed), and two identical rows in one flush trip the
    index rather than the check above.

    A label is never overwritten: a heading already stored came from a
    catalogue too, and the last writer is not the better one. Filling in a
    missing one is the exception, because a caption where there was none is
    strictly more than before.

    **`kind` fills in on the same rule, and that is the only thing that ever
    corrects a row written before `a1e7c93b60df`.** Those rows carry a null
    because the `$2` that would have said was never stored, so no migration can
    tell a disc from a subject among them; a record that declares one is the
    only place the answer exists. It reaches a book when that book is next
    enriched and not before, which is worth knowing rather than assuming. Not an
    overwrite, for the same reason the caption is not: a stored `subject` came
    from a catalogue saying so.

    **The ceiling is counted against the book, not against the payload.** Every
    caller is bounded per request and this writer is additive across requests,
    so without the count here the per book total is unbounded: `enrich/apply`
    takes a client supplied `BookMatch`, makes no outbound call and therefore
    carries no rate limiter, and eight rows per call times any number of calls
    is a stored denial of service that every listing pays for, since
    `books_to_out` selectin-loads this relationship onto every row of every
    page.
    """
    # Keyed on the pair the unique index is on, with the scheme coerced through
    # the enum on both sides. A stored row's `scheme` comes back from a plain
    # VARCHAR as a `str` and the payload's is a `ClassificationScheme`, so
    # comparing them raw works only for as long as that is a `StrEnum`;
    # coercing removes the dependency instead of commenting on it.
    existing = {
        (ClassificationScheme(entry.scheme), entry.number): entry
        for entry in book.classifications
    }
    changed: list[str] = []
    for heading in headings:
        key = (ClassificationScheme(heading.scheme), heading.number)
        stored = existing.get(key)
        if stored is not None:
            filled = False
            if stored.label is None and heading.label is not None:
                stored.label = heading.label
                filled = True
            if stored.kind is None and heading.kind is not None:
                stored.kind = heading.kind
                filled = True
            if filled:
                changed.append(heading.number)
            continue
        if len(existing) >= MAX_CLASSIFICATIONS_PER_BOOK:
            logger.info(
                "Book %s already carries %d classifications; dropping %r",
                book.id,
                len(existing),
                heading.number,
            )
            continue
        row = Classification(
            book=book,
            scheme=heading.scheme,
            number=heading.number,
            label=heading.label,
            kind=heading.kind,
        )
        db.add(row)
        existing[key] = row
        changed.append(heading.number)
    return changed
