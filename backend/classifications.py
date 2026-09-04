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
from enums import ClassificationScheme
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

    **Ordered by scheme before the slice, and this is the only place that can
    be.** A parser can only order the record in front of it, and by the time a
    list reaches here a merge has concatenated up to six catalogues, which is
    every source that builds a `Heading` at all: the
    leading source's subject headings sit in front of the second catalogue's
    Dewey number and the Library of Congress's call number, which are then the
    first things dropped. Ordering here is what makes "the Dewey number
    survives" true of a book rather than of a record.
    """
    headings: list[ClassificationIn] = []
    for entry in entries:
        try:
            headings.append(
                ClassificationIn(
                    scheme=entry.scheme, number=entry.number, label=entry.label
                )
            )
        except ValidationError:
            logger.info("Discarded an unusable classification: %s", clipped(entry))
    # Stable, so within one scheme the catalogues keep the order they answered
    # in and the leading source still wins.
    headings.sort(key=lambda heading: SCHEME_ORDER.get(heading.scheme, len(SCHEME_ORDER)))
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
            if stored.label is None and heading.label is not None:
                stored.label = heading.label
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
        )
        db.add(row)
        existing[key] = row
        changed.append(heading.number)
    return changed
