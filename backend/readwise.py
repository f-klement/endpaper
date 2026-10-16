"""Pulling a member's Readwise highlights into `highlights`, and nothing back.

**Pull only, by the owner's ruling.** What leaves this server, always to
`READWISE_ORIGIN`, is the member's own token, the time of the last pull as
`updatedAfter`, and Readwise's own values handed back to it: the `pageCursor`
it gave, and the book ids it gave as `ids`. No passage, note, title or Book
goes the other way.

**Readwise's `/api/v2/export/` is the one endpoint read**, for three reasons:
it nests each book's highlights under the book, so a page is matched and
written in one pass; `updatedAfter` makes every pull after the first carry only
what changed; and `includeDeleted` reports a deletion, which is what makes this
a sync rather than an import that only ever adds.

**A deletion removes the row.** Hiding it would leave a passage the member
deleted at its source stored here and shared if they had shared it; removing it
is what the member did.

**Which Book a Readwise book is**: `Index` says. A book nothing matches waits,
listed on the account page, and is never guessed onto a Book. Its highlights are
not stored while it waits; once a Book matches it, the next pull asks Readwise
for that book's highlights by its id, because an incremental pull would never
send them again.

**What a pull does with a highlight once it has its id is the ledger's**,
`highlights`: it re-finds the row, leaves out one the member deleted here
whatever a later page carries (counted as skipped), and makes a row moved to
another Book private again.

**One process, one pull per member at a time.** The Dockerfile runs a single
uvicorn, which is `notifications.ticker`'s premise as well; `_running` holds the
members whose pull is under way, so the button and the daily job cannot write
one member's rows at once.

What the pod needs from the network: HTTPS to `readwise.io`, port 443. A
deployment that filters egress has to allow it, or every pull ends
`unavailable`.
"""

import asyncio
import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final, Self

import anyio
import httpx
from sqlalchemy.orm import Session

import credentials
import errors
import fetch
import highlights
import identity
from database import SessionLocal
from deadline import in_, left
from enums import BookIdentifierScheme, HighlightSource, MemberLoginService, ReadwiseOutcome
from models import (
    AUTHOR_LINE_MAX,
    BOOK_IDENTIFIER_MAX,
    HIGHLIGHT_NOTE_MAX,
    HIGHLIGHT_TEXT_MAX,
    MAX_PAGE_NUMBER_IN_A_BOOK,
    READWISE_CURSOR_MAX,
    TITLE_MAX,
    Book,
    BookIdentifier,
    MemberLogin,
    ReadwiseBook,
)
from shelf import Shelf

logger = logging.getLogger("endpaper.readwise")

#: Where every request goes, and the one origin the token is ever sent to.
READWISE_ORIGIN: Final = "https://readwise.io"
_EXPORT: Final = f"{READWISE_ORIGIN}/api/v2/export/"
_AUTH: Final = f"{READWISE_ORIGIN}/api/v2/auth/"

#: The most one export page may be, on the wire. Chosen, not measured: four
#: times `fetch.MAX_RESPONSE_BYTES`, because a page nests every highlight of
#: the books on it and a long book carries thousands. One page is read and
#: applied at a time, so this is also the memory peak's bound.
PAGE_BYTES: Final = 8 * 1024 * 1024

#: Seconds one page may take, inside the pull's own budget.
PAGE_SECONDS: Final = 30

#: The most pages one pull reads, and the seconds it may spend. Past either,
#: what was read is kept and the cursor stays, so the next pull resumes from
#: the same point. They bound a pull that would otherwise follow a cursor
#: Readwise never ends.
MAX_PAGES: Final = 500
SYNC_SECONDS: Final = 600

#: How many Readwise book ids one request names when a waiting book is asked
#: for again, so the query string stays a few kilobytes.
IDS_PER_REQUEST: Final = 100

#: How far behind the start of a pull the next one asks from. Readwise compares
#: `updatedAfter` with its own clock, and a pull re-reading a few minutes it
#: already applied writes nothing, so the overlap only costs bytes.
OVERLAP: Final = timedelta(minutes=10)

#: How often the daily job pulls for each member, and how often it looks.
EVERY: Final = timedelta(hours=24)
TICK_SECONDS: Final = 3600

_SERVICE: Final = MemberLoginService.READWISE


@dataclass(frozen=True)
class Token:
    """A member's Readwise token, and the one origin it may be sent to.

    `secret` is `repr=False` and `__str__` is overridden, `credentials.
    Credential`'s rule, so a logged exception cannot print it. `header_for` is
    `fetch.Credential`: the header goes only to `READWISE_ORIGIN`.
    """

    secret: str = field(repr=False)

    def __str__(self) -> str:
        return "<readwise token>"

    def header_for(self, url: str) -> dict[str, str]:
        # Both sides through `origin_of`, which writes the default port out:
        # comparing against the constant as typed matches no URL at all.
        if credentials.origin_of(url) != credentials.origin_of(READWISE_ORIGIN):
            return {}
        return {"Authorization": f"Token {self.secret}"}


# ── Reading a page ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReadwiseHighlight:
    id: int
    deleted: bool
    #: None when the highlight carries no storable text: empty, or past
    #: `HIGHLIGHT_TEXT_MAX`. Counted as skipped, never truncated.
    text: str | None
    note: str | None
    page: int | None
    highlighted_at: datetime | None


@dataclass(frozen=True)
class ReadwiseEntry:
    """One book of an export page and the highlights listed under it."""

    user_book_id: int
    deleted: bool
    #: Readwise's `books` category. Articles, tweets and podcasts are not.
    is_book: bool
    title: str
    author: str | None
    asin: str | None
    highlights: tuple[ReadwiseHighlight, ...]


@dataclass(frozen=True)
class Page:
    entries: tuple[ReadwiseEntry, ...]
    next_cursor: str | None


class Unreadable(ValueError):
    """A page that is not the export's shape."""


def _id(value: object) -> int | None:
    """A positive integer id, or None. `bool` is an `int` and is not an id."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _clean(value: object, ceiling: int | None = None) -> str | None:
    """Text as stored: NUL removed, since PostgreSQL's text types cannot hold
    it, trimmed, blank as None, and clipped to `ceiling` where one is given."""
    if not isinstance(value, str):
        return None
    cleaned = value.replace("\x00", "").strip()
    if not cleaned:
        return None
    return cleaned[:ceiling] if ceiling is not None else cleaned


def _instant(value: object) -> datetime | None:
    """An ISO 8601 time as naive UTC to the second, or None.

    A value with no offset is read as UTC, which is what Readwise writes.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed.replace(microsecond=0)


def _highlight(raw: object) -> ReadwiseHighlight | None:
    if not isinstance(raw, dict):
        return None
    ident = _id(raw.get("id"))
    if ident is None:
        return None
    text = _clean(raw.get("text"))
    location = _id(raw.get("location"))
    page = (
        location
        if raw.get("location_type") == "page"
        and location is not None
        and location <= MAX_PAGE_NUMBER_IN_A_BOOK
        else None
    )
    return ReadwiseHighlight(
        id=ident,
        deleted=raw.get("is_deleted") is True,
        text=text if text is not None and len(text) <= HIGHLIGHT_TEXT_MAX else None,
        note=_clean(raw.get("note"), HIGHLIGHT_NOTE_MAX),
        page=page,
        highlighted_at=_instant(raw.get("highlighted_at")) or _instant(raw.get("created_at")),
    )


def _entry(raw: object) -> ReadwiseEntry | None:
    if not isinstance(raw, dict):
        return None
    ident = _id(raw.get("user_book_id"))
    if ident is None:
        return None
    listed = raw.get("highlights")
    # Keyed on the id, the later winning, so one id listed twice is one row
    # rather than two inserts of one key.
    highlights = tuple(
        {
            found.id: found
            for found in (_highlight(one) for one in (listed if isinstance(listed, list) else ()))
            if found is not None
        }.values()
    )
    return ReadwiseEntry(
        user_book_id=ident,
        deleted=raw.get("is_deleted") is True,
        is_book=raw.get("category") == "books",
        title=_clean(raw.get("readable_title"), TITLE_MAX)
        or _clean(raw.get("title"), TITLE_MAX)
        or "",
        author=_clean(raw.get("author"), AUTHOR_LINE_MAX),
        asin=_clean(raw.get("asin"), BOOK_IDENTIFIER_MAX),
        highlights=highlights,
    )


def read_page(body: object) -> Page:
    """One export page. An entry or highlight without a usable id is dropped;
    a body that is not the export's shape is `Unreadable`."""
    if not isinstance(body, dict) or not isinstance(body.get("results"), list):
        raise Unreadable("Readwise answered with something that is not an export page.")
    cursor = body.get("nextPageCursor")
    # Keyed on the book's id for the reason `_entry` keys its highlights.
    return Page(
        entries=tuple(
            {
                found.user_book_id: found
                for found in (_entry(raw) for raw in body["results"])
                if found is not None
            }.values()
        ),
        next_cursor=str(cursor) if isinstance(cursor, str | int) and cursor != "" else None,
    )


# ── Which Book a Readwise book is ─────────────────────────────────────────────


@dataclass(frozen=True)
class Index:
    """The Books one member can see, keyed the two ways a Readwise book is matched.

    **An ASIN on exactly one Book first**, since an ASIN names an edition.
    **Then exactly one Book with the same `identity.work_key`**, title and first
    credit folded: the predicate the catalogue transfer uses, because a wrong
    answer here puts a member's highlights on somebody else's Book. Two Books
    answering either key is no answer, so a copy and its original wait for the
    member rather than being picked between.

    Built from `Shelf.seen_by`, so a Book the member cannot see is never a
    candidate, and from one query each, like `importing.MarcIndex`.
    """

    visible: frozenset[int]
    by_asin: Mapping[str, frozenset[int]]
    by_work: Mapping[str, frozenset[int]]

    @classmethod
    def build(cls, db: Session, member_id: int) -> Self:
        shelf = Shelf.seen_by(db, member_id)
        books = shelf.select(Book.id, Book.title, Book.author).all()
        asins = (
            shelf.select(BookIdentifier.value, Book.id)
            .join(BookIdentifier, BookIdentifier.book_id == Book.id)
            .filter(BookIdentifier.scheme == BookIdentifierScheme.ASIN)
            .all()
        )
        return cls(
            visible=frozenset(book_id for book_id, _title, _author in books),
            by_asin=_grouped((value.upper(), book_id) for value, book_id in asins),
            by_work=_grouped(
                (identity.work_key(title, author), book_id) for book_id, title, author in books
            ),
        )

    def match(self, asin: str | None, title: str, author: str | None) -> int | None:
        if asin:
            held = self.by_asin.get(asin.upper(), frozenset())
            if held:
                # Two Books carrying the ASIN is no answer, rather than a
                # reason to ask the title instead.
                return next(iter(held)) if len(held) == 1 else None
        held = self.by_work.get(identity.work_key(title, author), frozenset())
        return next(iter(held)) if len(held) == 1 else None


def _grouped(pairs: Iterable[tuple[str, int]]) -> dict[str, frozenset[int]]:
    grouped: dict[str, set[int]] = {}
    for key, book_id in pairs:
        grouped.setdefault(key, set()).add(book_id)
    return {key: frozenset(ids) for key, ids in grouped.items()}


# ── Writing a page ────────────────────────────────────────────────────────────


@dataclass
class Counts:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0
    skipped: int = 0

    def add(self, other: Counts) -> None:
        self.created += other.created
        self.updated += other.updated
        self.unchanged += other.unchanged
        self.deleted += other.deleted
        self.skipped += other.skipped


def _delete(db: Session, member_id: int, ids: Sequence[int], counts: Counts) -> None:
    counts.deleted += highlights.remove(
        db, member_id, HighlightSource.READWISE, [str(ident) for ident in ids]
    )


def _write(
    db: Session,
    member_id: int,
    book_id: int,
    marks: Sequence[ReadwiseHighlight],
    counts: Counts,
) -> None:
    readable = {
        str(mark.id): highlights.Mark(
            text=mark.text,
            note=mark.note,
            page=mark.page,
            highlighted_at=mark.highlighted_at,
        )
        for mark in marks
        if mark.text is not None
    }
    written = highlights.write(db, member_id, HighlightSource.READWISE, book_id, readable)
    counts.created += written.created
    counts.updated += written.updated
    counts.unchanged += written.unchanged
    # Skipped is what had no text to store and what the member deleted here.
    counts.skipped += sum(mark.text is None for mark in marks) + written.left_deleted


def apply_page(
    db: Session,
    member_id: int,
    page: Page,
    index: Index,
    counts: Counts,
    *,
    whole: bool,
    carry: Callable[[], None] = lambda: None,
) -> set[int]:
    """Write one page's highlights and commit. Answers the Readwise book ids
    that this page matched to a Book for the first time.

    `whole` says the page lists each of its books' every highlight: the first
    pull, or a book asked for by id. **On an incremental page a newly matched
    book has only its changed highlights here**, so it is marked
    `whole_pending` and the caller asks for it again by id; that is what the
    answer is for.

    **A page beaten by a hand delete is written again** (`highlights.settled`),
    and the retry leaves the mark deleted rather than answering a 500. Each
    attempt counts afresh, merged into `counts` only once it commits, so a
    highlight is counted once however many attempts it took. `carry` sets what
    the caller commits beside the page, inside each attempt, because the
    rollback before a retry discards an assignment made before it.
    """

    def attempt() -> tuple[set[int], Counts]:
        carry()
        fresh = Counts()
        return _apply_once(db, member_id, page, index, fresh, whole=whole), fresh

    newly, written = highlights.settled(db, attempt)
    counts.add(written)
    return newly


def _apply_once(
    db: Session, member_id: int, page: Page, index: Index, counts: Counts, *, whole: bool
) -> set[int]:
    newly: set[int] = set()
    placed = [
        (entry, _placed(db, member_id, entry, index, newly, whole=whole))
        for entry in page.entries
    ]
    writers = _writers(db, member_id, placed, counts)
    # The page is one answer: a highlight live under any of its books is not
    # removed by another listing it deleted. Removed per entry, a deleted
    # listing would take the row a live one was keeping, or meet its update.
    alive = {
        mark.id
        for entry in page.entries
        if not entry.deleted
        for mark in entry.highlights
        if not mark.deleted
    }
    for position, (entry, book_id) in enumerate(placed):
        # Deletions first, whatever the category: a highlight deleted under a
        # book deleted whole, or under one moved out of `books`, is removed.
        # A moved book's live highlights stay, and its mapping row went above.
        _delete(
            db,
            member_id,
            [
                mark.id
                for mark in entry.highlights
                if (entry.deleted or mark.deleted) and mark.id not in alive
            ],
            counts,
        )
        if book_id is not None:
            live = [
                mark
                for mark in entry.highlights
                if not mark.deleted and writers.get(mark.id) == position
            ]
            _write(db, member_id, book_id, live, counts)
    db.commit()
    return newly


def _placed(
    db: Session,
    member_id: int,
    entry: ReadwiseEntry,
    index: Index,
    newly: set[int],
    *,
    whole: bool,
) -> int | None:
    """Keep `entry`'s `ReadwiseBook` row, and answer the Book its highlights
    go on: None for a book that waits, was deleted, or is not a book."""
    row = (
        db.query(ReadwiseBook)
        .filter(
            ReadwiseBook.user_id == member_id,
            ReadwiseBook.user_book_id == entry.user_book_id,
        )
        .one_or_none()
    )
    if entry.deleted or not entry.is_book:
        if row is not None:
            db.delete(row)
        return None
    if row is None:
        row = ReadwiseBook(user_id=member_id, user_book_id=entry.user_book_id)
        db.add(row)
    row.title, row.author, row.asin = entry.title, entry.author, entry.asin
    if row.book_id not in index.visible:
        row.book_id = index.match(entry.asin, entry.title, entry.author)
        if row.book_id is not None and not whole:
            # Kept as state rather than inferred from `book_id`, which is
            # committed with this page: a pull stopping before the re-ask
            # ends would otherwise leave the older highlights unasked for.
            row.whole_pending = True
            newly.add(entry.user_book_id)
    return row.book_id


def _writers(
    db: Session,
    member_id: int,
    placed: Sequence[tuple[ReadwiseEntry, int | None]],
    counts: Counts,
) -> dict[int, int]:
    """Which entry of the page writes each live highlight, by its position.

    **One highlight listed under two Books goes on the one already holding
    it, and on neither when neither does**, counted as skipped: two answers
    are no answer, as for a book two Books match. Written under both, the
    second write would insert a key the first had only added, and the page
    would meet the unique index at commit. Listed twice on one Book, the
    later entry writes it, as `_entry` keeps the later of an id listed twice.
    """
    listed: dict[int, dict[int, int]] = {}
    for position, (entry, book_id) in enumerate(placed):
        if book_id is None:
            continue
        for mark in entry.highlights:
            if not mark.deleted:
                listed.setdefault(mark.id, {})[book_id] = position
    held = highlights.holders(
        db,
        member_id,
        HighlightSource.READWISE,
        [str(ident) for ident, books in listed.items() if len(books) > 1],
    )
    writers: dict[int, int] = {}
    for ident, books in listed.items():
        book_id = next(iter(books)) if len(books) == 1 else held.get(str(ident))
        if book_id in books:
            writers[ident] = books[book_id]
        else:
            counts.skipped += 1
    return writers


def _rematched(db: Session, member_id: int, index: Index) -> set[int]:
    """Readwise books to ask for by id: those whose Book is gone or unseen and
    which a Book matches now, and those whose whole history was never read
    (`ReadwiseBook.whole_pending`)."""
    return {
        row.user_book_id
        for row in db.query(ReadwiseBook).filter(ReadwiseBook.user_id == member_id)
        if (row.whole_pending and row.book_id in index.visible)
        or (
            row.book_id not in index.visible
            and index.match(row.asin, row.title, row.author) is not None
        )
    }


def _pending(db: Session, member_id: int, ids: Sequence[int], value: bool) -> None:
    """Mark these Readwise books as owed their whole history, or paid it."""
    db.query(ReadwiseBook).filter(
        ReadwiseBook.user_id == member_id, ReadwiseBook.user_book_id.in_(ids)
    ).update({ReadwiseBook.whole_pending: value}, synchronize_session=False)
    db.commit()


def waiting_count(db: Session, member_id: int) -> int:
    return (
        db.query(ReadwiseBook)
        .filter(ReadwiseBook.user_id == member_id, ReadwiseBook.book_id.is_(None))
        .count()
    )


# ── Talking to Readwise ───────────────────────────────────────────────────────


class Stopped(Exception):
    """Readwise refused, or could not be read. `outcome` says which."""

    def __init__(self, outcome: ReadwiseOutcome) -> None:
        super().__init__(outcome.value)
        self.outcome = outcome


def _refusal(status: int) -> ReadwiseOutcome | None:
    if status == 401:
        return ReadwiseOutcome.REFUSED
    if status == 429:
        # Readwise names a wait in `Retry-After`. A pull stops rather than
        # sleeping on it: the button answers now, and the daily job's next
        # attempt is a day later, past any wait Readwise names.
        return ReadwiseOutcome.RATE_LIMITED
    return None


async def check(secret: str) -> ReadwiseOutcome | None:
    """None when Readwise accepts this token, else why not.

    `/api/v2/auth/` answers 204 for a good token and 401 for a bad one.
    """
    try:
        answer = await fetch.get_once(_AUTH, credential=Token(secret))
    except httpx.HTTPError as failure:
        logger.warning("Readwise could not be reached to check a token: %s", failure)
        return ReadwiseOutcome.UNAVAILABLE
    if answer.status_code == 204:
        return None
    return _refusal(answer.status_code) or ReadwiseOutcome.UNAVAILABLE


async def _page(
    client: httpx.AsyncClient,
    token: Token,
    params: Mapping[str, str],
    ends: float,
) -> Page:
    try:
        answer = await fetch.get(
            client,
            _EXPORT,
            params=params,
            limit=PAGE_BYTES,
            deadline=min(ends, in_(PAGE_SECONDS)),
            credential=token,
        )
    except httpx.HTTPError as failure:
        logger.warning("Readwise export could not be read: %s", failure)
        raise Stopped(ReadwiseOutcome.UNAVAILABLE) from None
    refused = _refusal(answer.status_code)
    if refused is not None:
        raise Stopped(refused)
    if answer.status_code != 200:
        logger.warning("Readwise export answered %s", answer.status_code)
        raise Stopped(ReadwiseOutcome.UNAVAILABLE)
    try:
        return read_page(answer.json())
    except ValueError:
        # `Unreadable` and a body that is not JSON alike.
        logger.warning("Readwise export answered with a body this cannot read")
        raise Stopped(ReadwiseOutcome.UNAVAILABLE) from None


# ── One pull ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SyncResult:
    outcome: ReadwiseOutcome
    counts: Counts
    waiting_count: int


class NoToken(Exception):
    """This member has saved no Readwise token."""


class AlreadyRunning(Exception):
    """A pull for this member is already under way in this process."""


_running: set[int] = set()


def login_of(db: Session, member_id: int) -> MemberLogin | None:
    return (
        db.query(MemberLogin)
        .filter(MemberLogin.user_id == member_id, MemberLogin.service == _SERVICE)
        .one_or_none()
    )


def running() -> frozenset[int]:
    """The members whose pull is under way in this process."""
    return frozenset(_running)


def new_login(member_id: int, envelope: str) -> MemberLogin:
    return MemberLogin(user_id=member_id, service=_SERVICE, envelope=envelope, set_at=_utcnow())


def replace_token(db: Session, login: MemberLogin, envelope: str) -> None:
    """Put a new token in place of the old one and start the pull over.

    **The cursor and the matched books go with the old token**: the new one may
    be another Readwise account, whose book ids mean nothing against these
    rows. The highlights already pulled stay.
    """
    login.envelope = envelope
    login.set_at = _utcnow()
    login.synced_through = None
    login.resume_cursor = None
    login.walk_started_at = None
    login.last_outcome = None
    db.query(ReadwiseBook).filter(ReadwiseBook.user_id == login.user_id).delete(
        synchronize_session=False
    )


def seal(member_id: int, secret: str) -> str:
    """The token sealed for this member. Raises `credentials.NoKeyConfigured`
    when this deployment has no key."""
    return credentials.seal_member_login(
        credentials.require_key(), _SERVICE.value, member_id, READWISE_ORIGIN, secret
    )


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def sync(
    db: Session,
    member_id: int,
    *,
    now: datetime | None = None,
    client: Callable[[], httpx.AsyncClient] = fetch.catalogue_client,
) -> SyncResult:
    """Pull this member's changed highlights, record how it went, and commit.

    Raises `NoToken` without a saved token and `AlreadyRunning` while another
    pull for the member is under way; every other ending is an outcome.

    **The cursor moves only when every page was read and applied.** A pull
    that stops keeps what it wrote, which re-running writes again unchanged.
    `client` is a seam for the catalogue client, which is the right door for a
    host that is a module constant (`fetch.catalogue_client`).
    """
    if member_id in _running:
        raise AlreadyRunning
    _running.add(member_id)
    try:
        return await _sync(db, member_id, now or _utcnow(), client)
    finally:
        _running.discard(member_id)


async def _sync(
    db: Session,
    member_id: int,
    started: datetime,
    client: Callable[[], httpx.AsyncClient],
) -> SyncResult:
    login = login_of(db, member_id)
    if login is None:
        raise NoToken
    login.last_run_at = started
    # Committed now, so a pull that raises before its first page still counts
    # as today's for the daily job.
    db.commit()
    counts = Counts()
    try:
        token = Token(
            credentials.unseal_member_login(
                credentials.require_key(),
                _SERVICE.value,
                member_id,
                READWISE_ORIGIN,
                login.envelope,
            )
        )
    except credentials.CredentialError:
        return _finish(db, login, member_id, ReadwiseOutcome.UNREADABLE, counts, started)

    index = await anyio.to_thread.run_sync(Index.build, db, member_id)
    asked = await anyio.to_thread.run_sync(_rematched, db, member_id, index)
    ends = in_(SYNC_SECONDS)
    pages = 0
    # **An export walk a bound stopped resumes where it stopped**, from the page cursor
    # it kept, and its cursor is then the time it first started, so nothing
    # changed in between is skipped. A resumed cursor Readwise no longer takes
    # is dropped, so the next pull starts the walk over.
    cursor = login.resume_cursor
    walk_started = (login.walk_started_at or started) if cursor else started
    login.walk_started_at = walk_started
    # Once one cursor is too long to keep, none is kept for the rest of this
    # walk: resuming from a later one would carry no start time to resume with.
    keeping = True
    try:
        async with client() as http:
            params = {"includeDeleted": "true"}
            if login.synced_through is not None:
                params["updatedAfter"] = login.synced_through.strftime("%Y-%m-%dT%H:%M:%SZ")
            whole = login.synced_through is None
            while True:
                if pages >= MAX_PAGES or left(ends) <= 0:
                    return _finish(db, login, member_id, ReadwiseOutcome.INCOMPLETE, counts, started)
                try:
                    page = await _page(
                        http, token, params | ({"pageCursor": cursor} if cursor else {}), ends
                    )
                except Stopped as stopped:
                    if pages == 0 and cursor and stopped.outcome is ReadwiseOutcome.UNAVAILABLE:
                        login.resume_cursor = None
                    raise
                pages += 1
                cursor = page.next_cursor
                keeping = keeping and (cursor is None or len(cursor) <= READWISE_CURSOR_MAX)
                asked |= await _apply(
                    db,
                    member_id,
                    page,
                    index,
                    counts,
                    whole=whole,
                    carry=_resuming(login, walk_started, cursor if keeping else None),
                )
                if cursor is None:
                    break
            wanted = sorted(asked)
            for start in range(0, len(wanted), IDS_PER_REQUEST):
                ids = wanted[start : start + IDS_PER_REQUEST]
                await anyio.to_thread.run_sync(_pending, db, member_id, ids, True)
                chunk = ",".join(str(ident) for ident in ids)
                cursor = None
                while True:
                    if pages >= MAX_PAGES or left(ends) <= 0:
                        return _finish(
                            db, login, member_id, ReadwiseOutcome.INCOMPLETE, counts, started
                        )
                    page = await _page(
                        http,
                        token,
                        {"ids": chunk} | ({"pageCursor": cursor} if cursor else {}),
                        ends,
                    )
                    pages += 1
                    await _apply(db, member_id, page, index, counts, whole=True)
                    cursor = page.next_cursor
                    if cursor is None:
                        break
                # Cleared only once the walk for these ids reached its last page.
                await anyio.to_thread.run_sync(_pending, db, member_id, ids, False)
    except Stopped as stopped:
        return _finish(db, login, member_id, stopped.outcome, counts, started)
    return _finish(db, login, member_id, ReadwiseOutcome.SYNCED, counts, walk_started)


async def _apply(
    db: Session,
    member_id: int,
    page: Page,
    index: Index,
    counts: Counts,
    *,
    whole: bool,
    carry: Callable[[], None] = lambda: None,
) -> set[int]:
    """`apply_page` off the event loop, `routers/opds.py::sync_server`'s
    arrangement: the session is touched by one thread at a time, since the
    next page is not fetched until this returns."""
    return await anyio.to_thread.run_sync(
        lambda: apply_page(db, member_id, page, index, counts, whole=whole, carry=carry)
    )


def _resuming(
    login: MemberLogin, walk_started: datetime, cursor: str | None
) -> Callable[[], None]:
    """What an export page commits beside its highlights: the cursor the walk
    resumes from and when the walk began. Both, because a retried page that
    kept only the cursor would commit it without the walk's start, and the pull
    that resumes it would take its own start for the walk's, skipping whatever
    changed in between."""

    def carry() -> None:
        login.walk_started_at = walk_started
        login.resume_cursor = cursor

    return carry


def _finish(
    db: Session,
    login: MemberLogin,
    member_id: int,
    outcome: ReadwiseOutcome,
    counts: Counts,
    started: datetime,
) -> SyncResult:
    """Record how the pull ended. `started` is when the walk that completed
    began, which for a resumed walk is an earlier pull's start."""
    login.last_outcome = outcome
    if outcome is ReadwiseOutcome.SYNCED:
        login.synced_through = started - OVERLAP
        login.resume_cursor = None
        login.walk_started_at = None
    db.commit()
    return SyncResult(outcome=outcome, counts=counts, waiting_count=waiting_count(db, member_id))


def forget(db: Session, member_id: int) -> None:
    """Remove this member's token and the pull's state. Their highlights stay."""
    login = login_of(db, member_id)
    if login is not None:
        db.delete(login)
    db.query(ReadwiseBook).filter(ReadwiseBook.user_id == member_id).delete(
        synchronize_session=False
    )
    db.commit()


# ── The daily job ─────────────────────────────────────────────────────────────


def due(db: Session, now: datetime) -> list[int]:
    """Members whose last pull started a day or more ago, or never."""
    cutoff = now - EVERY
    return [
        member_id
        for (member_id,) in db.query(MemberLogin.user_id)
        .filter(
            MemberLogin.service == _SERVICE,
            (MemberLogin.last_run_at.is_(None)) | (MemberLogin.last_run_at <= cutoff),
        )
        .order_by(MemberLogin.user_id)
    ]


async def run_due(now: datetime | None = None) -> int:
    """One pass of the daily job: pull for every member who is due. Answers how
    many pulls ran. A member's failure is logged and the pass goes on."""
    moment = now or _utcnow()
    with SessionLocal() as db:
        members = due(db, moment)
    ran = 0
    for member_id in members:
        with SessionLocal() as db:
            try:
                await sync(db, member_id, now=moment)
                ran += 1
            except (AlreadyRunning, NoToken):
                continue
            except errors.DATABASE_ERRORS as error:
                logger.error(
                    "A Readwise pull failed: %s\n%s",
                    errors.database_error_summary(error),
                    errors.frames(error),
                )
            except Exception:
                logger.exception("A Readwise pull failed")
    return ran


async def ticker() -> None:
    """Look once an hour for members due a pull, forever.

    Each member is pulled at most once a day (`EVERY`), and a pull that failed
    is tried again a day later. Every failure is logged and swallowed, for
    `notifications.ticker`'s reason: a raise here ends the task silently for the
    life of the container.
    """
    while True:
        await asyncio.sleep(TICK_SECONDS)
        try:
            await run_due()
        except Exception:
            logger.exception("The Readwise ticker failed a pass")
