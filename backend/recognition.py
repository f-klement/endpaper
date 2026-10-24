"""Which existing Book a record is, as one Member sees it.

`identity.py` says when two descriptions are one book, and takes no session.
This module asks the catalogue. It owns, per source kind, the key ladder, the
tie rule, which rows count (the Shelf, the trash view, the whole table) and
the ISBN forms, and it answers in one shape. Same split as `authors.py` under
`authorship.py`: the pure rules underneath, the database questions here.

## The interface

    index = Index.build(db, member_id, Source.CATALOGUE)
    match index.recognise(title=..., author=..., isbn=...):
        case Seen(book_id): ...

Built once per import, from a handful of queries, so a file of thousands of
rows costs no statement per row. `remember` keeps a Book the import just
created findable by the rows after it.

`recognise_one` asks for one record and reads only the Books that could
answer it, for a door that asks once a request.

## The answer

| answer | means | carries |
|---|---|---|
| `Seen` | one Book on this Member's shelf | its id |
| `Unknown` | nothing answers | nothing |
| `Tied` | two or more Books on the shelf answer and the tie rule picks none | their ids |
| `InTrash` | only Books in this Member's trash view hold the ISBN | their ids |
| `Hidden` | a Book this Member cannot see holds the ISBN | nothing |

**`Hidden` carries no id, and a caller must not name the row it answered.**
ADR 0003: a Book's existence is private to whoever may see it, and an id or a
title would answer "does a Book with this ISBN exist in this house". It exists
at all because `books.isbn` is unique across the whole table for any row with
no copy group, so creating the row would raise and abort the import.

## The ladder

Each source asks an identifier first and a title key second. **A tie on the
identifier is final**: the title is not asked, because two Books carrying one
identifier are a stronger claim than any title.

| source | identifier | title key | a tie inside one copy group |
|---|---|---|---|
| `READING_HISTORY` (CSV, OPDS) | ISBN | `identity.reading_history_title` | the lowest id |
| `CATALOGUE` (MARC) | ISBN | `identity.work_key` | the lowest id |
| `HIGHLIGHTS` (Readwise) | ASIN | `identity.work_key` | no answer |
| `CALIBRE` (an add) | Calibre uuid | none | the lowest id |
| `STORE` (an add) | ASIN, Google volume id | none | the lowest id |
| `ADD` (an add) | ISBN | none | the lowest id |

Any other tie is no answer. **An add asks no title**: two Books may share one,
and an add refused on a title would refuse a second edition. Every visible
answer refuses an add, a tie included, but only `Seen` names a Book: a client
lands files on the Book a refusal names and offers a copy of it, so a tie
outside one copy group refuses without naming either. The copy group rule is
the owner's of 2026-10-17 for the three imports: deliberate copies are one
book, and a status landing on either is right. Readwise keeps its own ruling
of 2026-10-15, under which a copy and its original wait for the member,
because a highlight belongs to the copy somebody read.

**Only the ISBN is asked off the shelf**, after both rungs miss, because only
`books.isbn` is unique: an identifier in `book_identifiers` may sit on two
Books, so a hidden holder refuses nothing and naming it would only disclose it.

**ISBNs are compared by `isbn.parse`**, so a row stored before
canonicalisation as an ISBN-10, with hyphens or with a lower case x, meets
the ISBN-13 every reader now produces. A value `parse` refuses is compared as
stored, less surrounding space.

## Not here

The file key, a partial MD5 or a file location, is `file_references`'.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final, Self

from sqlalchemy import or_
from sqlalchemy.orm import Session

import identity
import isbn as isbn_utils
from enums import BookIdentifierScheme
from models import Book, BookIdentifier
from shelf import Shelf, whole_table_for_uniqueness


class Source(Enum):
    """What kind of record is being recognised, which picks the ladder."""

    READING_HISTORY = "reading_history"
    CATALOGUE = "catalogue"
    HIGHLIGHTS = "highlights"
    CALIBRE = "calibre"
    STORE = "store"
    ADD = "add"


@dataclass(frozen=True, slots=True)
class Seen:
    book_id: int


@dataclass(frozen=True, slots=True)
class Unknown:
    pass


@dataclass(frozen=True, slots=True)
class Tied:
    book_ids: frozenset[int]


@dataclass(frozen=True, slots=True)
class InTrash:
    book_ids: frozenset[int]


@dataclass(frozen=True, slots=True)
class Hidden:
    pass


type Answer = Seen | Unknown | Tied | InTrash | Hidden


#: What one identifier is compared by: an ISBN alone, or a scheme with its
#: value, so an ASIN and a Google volume id spelled alike stay two keys.
type _Key = str | tuple[BookIdentifierScheme, str]


def _reading_history_key(title: str, _author: str | None) -> str:
    return identity.reading_history_title(title)


@dataclass(frozen=True, slots=True)
class _Ladder:
    #: The identifier asked first: `None` for `books.isbn`, else the schemes
    #: in `book_identifiers` it is read from.
    schemes: tuple[BookIdentifierScheme, ...] | None
    #: The title key asked second, or `None` where no title is asked.
    title: Callable[[str, str | None], str] | None
    copies_take_the_lowest: bool


_LADDERS: Final[Mapping[Source, _Ladder]] = {
    Source.READING_HISTORY: _Ladder(schemes=None, title=_reading_history_key, copies_take_the_lowest=True),
    Source.CATALOGUE: _Ladder(schemes=None, title=identity.work_key, copies_take_the_lowest=True),
    Source.HIGHLIGHTS: _Ladder(
        schemes=(BookIdentifierScheme.ASIN,),
        title=identity.work_key,
        copies_take_the_lowest=False,
    ),
    Source.CALIBRE: _Ladder(
        schemes=(BookIdentifierScheme.CALIBRE_UUID,), title=None, copies_take_the_lowest=True
    ),
    # Both store identifiers, under the owner's ruling that a store identifier
    # refuses an add: a Google volume id is the Play Books import's only key,
    # as the ASIN is the Kindle import's.
    Source.STORE: _Ladder(
        schemes=(BookIdentifierScheme.ASIN, BookIdentifierScheme.GOOGLE_BOOKS),
        title=None,
        copies_take_the_lowest=True,
    ),
    Source.ADD: _Ladder(schemes=None, title=None, copies_take_the_lowest=True),
}


@dataclass(frozen=True, slots=True)
class _Narrow:
    """The keys one record carries, which every read is filtered by."""

    #: Its ISBN as `_isbn_key` folds it, which a stored row must fold to.
    isbn_keys: frozenset[str]
    #: A LIKE pattern per form its ISBN takes, each matching every stored
    #: spelling that `isbn.normalise` folds to that form. A superset, which
    #: `isbn_keys` then narrows in Python.
    isbn_patterns: tuple[str, ...]
    #: Its identifier values as sent, upper cased and lower cased. Compared
    #: exactly so `ix_book_identifiers_scheme_value` serves the read, and in
    #: three spellings so an ASIN stored as another reader cased it is still
    #: found; `_identifier_key` then decides each scheme's own way. A value
    #: stored in mixed case is the one this misses.
    values: frozenset[str]


def _isbn_key(raw: str | None) -> str | None:
    if not raw or not raw.strip():
        return None
    return isbn_utils.parse(raw) or raw.strip()


def _spelled_anywhere(form: str) -> str:
    """A LIKE pattern matching every string holding `form`'s characters in
    order, whatever lies between them.

    `isbn.normalise` only drops characters and upper cases, so every stored
    spelling it folds to `form` holds those characters in order, and an ILIKE
    on this pattern finds it. **Escaped although a parsed form is digits and
    an X**: the fallback key is the record's own value, which `parse` refused
    and so may hold any character, and SQLite has no default LIKE escape.
    """
    escaped = ("\\" + character if character in "\\%_" else character for character in form)
    return "%" + "%".join(escaped) + "%"


def _identifier_key(scheme: BookIdentifierScheme, raw: str | None) -> tuple[BookIdentifierScheme, str] | None:
    """One stored or incoming identifier, folded to what compares.

    An ASIN is upper cased, as Amazon issues it. Nothing else is: a Google
    volume id is case sensitive, so folding it would merge two volumes.
    """
    if not raw or not raw.strip():
        return None
    value = raw.strip()
    return scheme, value.upper() if scheme is BookIdentifierScheme.ASIN else value


def _union[K](groups: Mapping[K, set[int]], keys: Iterable[K]) -> set[int]:
    found: set[int] = set()
    for key in keys:
        found |= groups.get(key, set())
    return found


def _grouped[K](pairs: Iterable[tuple[K, int]]) -> dict[K, set[int]]:
    grouped: dict[K, set[int]] = {}
    for key, book_id in pairs:
        grouped.setdefault(key, set()).add(book_id)
    return grouped


class Index:
    """The Books one Member can see, keyed the way one source is matched.

    **Every candidate comes from `Shelf.seen_by`**, so no rung can name a Book
    the Member cannot see. The two off shelf sets answer only `InTrash` and
    `Hidden`, and only for an ISBN.
    """

    __slots__ = (
        "_by_identifier",
        "_by_title",
        "_copy_group",
        "_held_anywhere",
        "_in_trash",
        "_ladder",
        "_visible",
    )

    def __init__(
        self,
        ladder: _Ladder,
        visible: set[int],
        copy_group: dict[int, str | None],
        by_identifier: dict[_Key, set[int]],
        by_title: dict[str, set[int]],
        in_trash: dict[_Key, set[int]],
        held_anywhere: dict[_Key, set[int]],
    ) -> None:
        self._ladder = ladder
        self._visible = visible
        self._copy_group = copy_group
        self._by_identifier = by_identifier
        self._by_title = by_title
        self._in_trash = in_trash
        self._held_anywhere = held_anywhere

    @classmethod
    def build(cls, db: Session, member_id: int, source: Source) -> Self:
        """Every Book on the Member's shelf, for an import asking once a row."""
        return cls._read(db, member_id, _LADDERS[source], narrow=None)

    @classmethod
    def _narrowed(
        cls,
        db: Session,
        member_id: int,
        source: Source,
        *,
        isbn: str | None = None,
        identifiers: Iterable[tuple[BookIdentifierScheme, str]] = (),
    ) -> Self:
        """Only the Books that could answer this one record, for a door asking
        once a request: every read is filtered by the record's own keys. An
        identifier is looked up through its index. An ISBN costs one scan of
        `books.isbn` (`_read` says why), and then lookups by id alone.

        **Refused for a ladder that asks a title**, because the title rung
        would answer from the narrowed rows alone and miss every Book that
        shares the title without sharing an identifier.
        """
        ladder = _LADDERS[source]
        if ladder.title is not None:
            raise ValueError(f"{source} asks a title, which a narrowed index cannot answer")
        keys: set[str] = set()
        forms: set[str] = set()
        values: set[str] = set()
        if ladder.schemes is None and (key := _isbn_key(isbn)) is not None:
            keys.add(key)
            forms.update(isbn_utils.equivalent_forms(isbn) or [key])
        elif ladder.schemes is not None:
            for scheme, value in identifiers:
                if scheme in ladder.schemes and (bare := value.strip()):
                    values.update((bare, bare.upper(), bare.lower()))
        if not keys and not values:
            # A record carrying none of this ladder's keys is answered by no
            # Book, so nothing is read for it.
            return cls(ladder, set(), {}, {}, {}, {}, {})
        narrow = _Narrow(
            isbn_keys=frozenset(keys),
            isbn_patterns=tuple(sorted(_spelled_anywhere(form) for form in forms)),
            values=frozenset(values),
        )
        return cls._read(db, member_id, ladder, narrow=narrow)

    @classmethod
    def _read(cls, db: Session, member_id: int, ladder: _Ladder, narrow: _Narrow | None) -> Self:
        shelf = Shelf.seen_by(db, member_id)
        columns = (Book.id, Book.isbn, Book.title, Book.author, Book.copy_group)
        by_identifier: dict[_Key, set[int]]
        in_trash: dict[_Key, set[int]] = {}
        held_anywhere: dict[_Key, set[int]] = {}

        if ladder.schemes is None:
            # The one read past the viewer, counted by
            # `tests/test_shelf.py::test_the_named_ways_past_a_viewer_have_the_callers_they_claim`.
            # Ids of rows nobody here may see stay inside this object: `Hidden`
            # is the only thing they ever decide, and it carries none of them.
            anywhere = whole_table_for_uniqueness(db, Book.id, Book.isbn)
            if narrow is None:
                anywhere = anywhere.filter(Book.isbn.isnot(None))
            else:
                # **A scan of `books.isbn`, not the unique index**: an exact
                # comparison misses a row stored with hyphens or a lower case
                # x, which the full index finds through `isbn.parse`, and the
                # door then made a second Book. The patterns are a superset;
                # the keys below decide.
                anywhere = anywhere.filter(
                    or_(*(Book.isbn.ilike(pattern, escape="\\") for pattern in narrow.isbn_patterns))
                )
            held_anywhere = _grouped(
                (key, book_id)
                for book_id, isbn in anywhere
                if (key := _isbn_key(isbn)) is not None and (narrow is None or key in narrow.isbn_keys)
            )
            # The full build reads every shelf row, which the title rung needs.
            # A narrowed one asks the shelf and the trash for the holders alone,
            # by primary key, since every holder is in `held_anywhere`, and not
            # at all when nothing holds the ISBN.
            holders: set[int] = set().union(*held_anywhere.values())
            in_the_trash = Shelf.trashed_by(db, member_id).select(Book.id, Book.isbn)
            if narrow is None:
                rows = shelf.select(*columns).all()
                trashed = in_the_trash.filter(Book.isbn.isnot(None)).all()
            elif holders:
                rows = shelf.select(*columns).filter(Book.id.in_(holders)).all()
                trashed = in_the_trash.filter(Book.id.in_(holders)).all()
            else:
                rows, trashed = [], []
            in_trash = _grouped(
                (key, book_id) for book_id, isbn in trashed if (key := _isbn_key(isbn)) is not None
            )
            by_identifier = _grouped(
                (key, book_id)
                for book_id, isbn, _title, _author, _group in rows
                if (key := _isbn_key(isbn)) is not None
            )
        else:
            carrying = (
                shelf.select(BookIdentifier.value, BookIdentifier.scheme, Book.id)
                .join(BookIdentifier, BookIdentifier.book_id == Book.id)
                .filter(BookIdentifier.scheme.in_(ladder.schemes))
            )
            if narrow is not None:
                carrying = carrying.filter(BookIdentifier.value.in_(narrow.values))
            by_identifier = _grouped(
                (pair, book_id)
                for value, scheme, book_id in carrying
                if (pair := _identifier_key(BookIdentifierScheme(scheme), value)) is not None
            )
            holders = set().union(*by_identifier.values())
            if narrow is None:
                rows = shelf.select(*columns).all()
            else:
                # Skipped when nothing carries the key, so an identifier held
                # only off the shelf costs exactly what one nobody holds does.
                rows = shelf.select(*columns).filter(Book.id.in_(holders)).all() if holders else []

        index = cls(
            ladder,
            visible=set(),
            copy_group={},
            by_identifier=by_identifier,
            by_title={},
            in_trash=in_trash,
            held_anywhere=held_anywhere,
        )
        for book_id, _isbn, title, author, group in rows:
            index._admit(book_id, title, author, group)
        return index

    def recognise(
        self,
        *,
        title: str,
        author: str | None = None,
        isbn: str | None = None,
        identifiers: Iterable[tuple[BookIdentifierScheme, str]] = (),
    ) -> Answer:
        """Which Book this record is. `title` should already be bounded the
        way it would be stored, or a record cannot find itself.

        `isbn` is read by a ladder keyed on ISBN and `identifiers` by one keyed
        on a scheme; each ladder ignores the other.
        """
        keys = self._identifier_keys(isbn, identifiers)
        held = _union(self._by_identifier, keys)
        if held:
            return self._settle(held)

        if self._ladder.title is not None:
            held = self._by_title.get(self._ladder.title(title, author), set())
            if held:
                return self._settle(held)

        if self._ladder.schemes is None:
            trashed = _union(self._in_trash, keys)
            hidden = _union(self._held_anywhere, keys) - trashed - self._visible
            # Hidden first: a holder nobody here may see refuses the row
            # whatever else is in the trash, and `InTrash` promises that every
            # holder is one this Member could restore or purge.
            if hidden:
                return Hidden()
            if trashed:
                return InTrash(frozenset(trashed))
        return Unknown()

    def sees(self, book_id: int | None) -> bool:
        """Whether this Book is on the Member's shelf, as of the build."""
        return book_id is not None and book_id in self._visible

    def remember(self, book: Book) -> None:
        """Keep a Book this import just created findable by later rows.

        A file listing one book twice would otherwise create it twice, or
        raise on the ISBN index the second time.
        """
        if self._ladder.schemes is None and (key := _isbn_key(book.isbn)) is not None:
            self._by_identifier.setdefault(key, set()).add(book.id)
            self._held_anywhere.setdefault(key, set()).add(book.id)
        self._admit(book.id, book.title, book.author, book.copy_group)

    def _admit(self, book_id: int, title: str, author: str | None, group: str | None) -> None:
        self._visible.add(book_id)
        self._copy_group[book_id] = group
        if self._ladder.title is not None:
            self._by_title.setdefault(self._ladder.title(title, author), set()).add(book_id)

    def _identifier_keys(
        self, isbn: str | None, identifiers: Iterable[tuple[BookIdentifierScheme, str]]
    ) -> set[_Key]:
        if self._ladder.schemes is None:
            key = _isbn_key(isbn)
            return {key} if key is not None else set()
        return {
            pair
            for scheme, value in identifiers
            if scheme in self._ladder.schemes and (pair := _identifier_key(scheme, value)) is not None
        }

    def _settle(self, held: set[int]) -> Answer:
        if len(held) == 1:
            return Seen(next(iter(held)))
        groups = {self._copy_group[book_id] for book_id in held}
        if self._ladder.copies_take_the_lowest and len(groups) == 1 and None not in groups:
            return Seen(min(held))
        return Tied(frozenset(held))


def recognise_one(
    db: Session,
    member_id: int,
    source: Source,
    *,
    isbn: str | None = None,
    identifiers: Iterable[tuple[BookIdentifierScheme, str]] = (),
) -> Answer:
    """Which Book this one record is, reading only the Books that could answer
    it. The same answer `Index.build(...).recognise(...)` gives, for a ladder
    that asks no title, except an identifier stored in mixed case (`_Narrow`
    says why)."""
    carried = tuple(identifiers)
    index = Index._narrowed(db, member_id, source, isbn=isbn, identifiers=carried)
    # The title rung is refused for a narrowed index, so the title is never read.
    return index.recognise(title="", isbn=isbn, identifiers=carried)
