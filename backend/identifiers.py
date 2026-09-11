"""The `book_identifiers` table: what may be written to it, and how much.

One rule and one writer. `add_identifiers` puts a client's assertions on a Book
without ever exceeding `MAX_IDENTIFIERS_PER_BOOK` or depositing one twice.

**A module rather than a private function in `routers/books.py`**, which is
where `classifications.add_headings` was until MARC import gave it a second
caller. The same is coming here: `_create_book` is the only caller that writes
this table today, shared by `POST /api/books` and `POST /api/books/scan`, and a
store import that learns to refresh a Book it already added is the second, so
the ceiling and the deduplication have one home before there are two callers
rather than after.

**Nothing here queries.** It takes a Book somebody else resolved and adds rows
to it. The privacy rule is `shelf.py`'s and is applied before a Book reaches
this module, which is what keeps this file out of `tests/test_shelf.py`'s fourth
pass without an allowlist entry.
"""

import logging
from collections.abc import Sequence

from sqlalchemy.orm import Session

from enums import BookIdentifierScheme
from models import Book, BookIdentifier
from schemas.identifier import MAX_IDENTIFIERS_PER_BOOK, BookIdentifierIn

logger = logging.getLogger("endpaper.identifiers")


def add_identifiers(
    book: Book, entries: Sequence[BookIdentifierIn], db: Session
) -> list[str]:
    """Add this Book's identifiers. Returns the values it **added**.

    **Additive, and never a replacement or a retype.** A stored row says which
    edition a store told this library the member owns, and
    `models.AuthorIdentifier` states the rule this borrows: a display name may
    be overruled because it is a preference, and an identifier may not because
    it is a claim about which record in somebody else's file this is. So the
    only operations here are adding one and, elsewhere, deleting it. A writer
    that replaced the set would churn the table on every import, and one that
    appended blindly would deposit a second copy of every row.

    Deduplicated against what the Book already carries **and within the
    payload**: a client may post one identifier twice, and two identical rows in
    one flush trip `uq_book_identifiers_book_scheme_value` rather than the check
    above it. The index refuses the second copy at the database and this refuses
    it before the flush, where there is still a request to answer.

    **The ceiling is counted against the Book, not against the payload**, which
    is what makes `MAX_IDENTIFIERS_PER_BOOK` a per Book number at all: every
    caller is bounded per request and this writer is additive across requests,
    so without the count here the total is unbounded, and every listing pays for
    it because `books_to_out` selectin-loads this relationship onto every row of
    every page.

    **The drop is logged**, `add_headings`' rule: what is dropped is an
    assertion out of a member's own file and nothing regenerates it, so a silent
    drop is a loss with nowhere to read it off. The identifier itself is what is
    logged rather than the whole row, and it is bounded by
    `BOOK_IDENTIFIER_MAX` before it reaches here.
    """
    # Keyed on the triple the unique index is on, with the scheme coerced
    # through the enum on both sides. A stored row's `scheme` comes back from a
    # plain VARCHAR as a `str` and the payload's is a `BookIdentifierScheme`, so
    # comparing them raw works only for as long as that is a `StrEnum`;
    # coercing removes the dependency instead of commenting on it.
    existing = {
        (BookIdentifierScheme(row.scheme), row.value) for row in book.identifiers
    }
    added: list[str] = []
    for entry in entries:
        key = (BookIdentifierScheme(entry.scheme), entry.value)
        if key in existing:
            continue
        if len(existing) >= MAX_IDENTIFIERS_PER_BOOK:
            logger.info(
                "Book %s already carries %d identifiers; dropping %r",
                book.id,
                len(existing),
                entry.value,
            )
            continue
        db.add(BookIdentifier(book=book, scheme=entry.scheme, value=entry.value))
        existing.add(key)
        added.append(entry.value)
    return added
