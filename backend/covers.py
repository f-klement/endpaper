"""Finding a cover that actually exists.

The catalogues this app reads are bibliographic: the DNB and K10plus return
MARC and Dublin Core records with no image in them at all. So a cover has
always been a **guess** at a URL on a separate image service, and the guess was
stored without ever being checked.

Measured across ten ISBNs in five languages: a cover URL was offered for 10 of
10, and only **8 of them resolved to an image**. The other two were stored
anyway, so those books show a broken cover for good, with nothing in the record
saying the link was never valid.

Two changes follow from that.

**The URL is checked before it is kept.** A 404 means that service has no cover
for this book, and storing the link would be storing a broken image.

**A 404 and a 503 are not the same answer**, and this is the part worth getting
right. Open Library returned 503 for a book it very likely does have, twice in
a row. Treating that as "no cover" would throw one away over a blip that
resolves itself, so an unverifiable candidate is kept rather than discarded:
the worst case is the cover the app already had.

**The DNB's cover service is the second source**, and it is what makes German
publishing work. `portal.dnb.de/opac/mvb/cover` is the book trade's own image
service, needs no key, and returned real covers (43 KB, 42 KB) for two German
books Open Library has nothing for.
"""

import asyncio
import logging
from collections import Counter
from enum import StrEnum
from pathlib import Path
from time import monotonic
from typing import Final
from urllib.parse import urljoin, urlsplit

import httpx

from config import ALLOWED_IMAGE_EXTENSIONS, COVERS_DIR, MAX_UPLOAD_BYTES
from isbn import parse as parse_isbn
from uploads import replace_image, sniff_image_extension

logger = logging.getLogger("endpaper.covers")

#: Short. This runs alongside the metadata lookup on the scan path, so it must
#: not be what makes somebody wait.
TIMEOUT_SECONDS: Final = 6

#: Wall clock a cover may take on a path with a person waiting at the end of it.
#:
#: Without a ceiling, adding one book is up to three candidate checks and a
#: download at `TIMEOUT_SECONDS` each: **24 seconds** when both image services
#: blackhole rather than refuse. The import path avoids that by deferring to the
#: backfill entirely, which the interactive path cannot do, so it gets a budget
#: instead. Past it the best URL found so far is stored unverified and the bytes
#: are left to the backfill, which has no person waiting on it.
#:
#: A slow add that succeeds beats a fast add with no cover; 24 seconds is
#: neither. The budget also caps each individual request at whatever is left, so
#: the real ceiling is the budget rather than the budget plus one timeout.
INTERACTIVE_BUDGET_SECONDS: Final = 4

#: Enough to tell an image from an error page without downloading the cover
#: twice: the client renders it from the URL, not from these bytes.
_PROBE_BYTES: Final = 512

#: Bookland registration group for German-language publishing.
_GERMAN_PREFIX: Final = "9783"

#: Every host a cover may be served from, written as CSP source expressions.
#:
#: **This tuple is where the CSP's `img-src` comes from** (`middleware.py`
#: joins it), because the two used to be written separately and drifted:
#: `portal.dnb.de` was added here as the second source and never added to the
#: policy, so on a German shelf the browser blocked every single cover while
#: the stored record looked perfectly correct. Nothing in a log said why.
#:
#: Adding an image service means adding it here, and two tests hold that:
#: `tests/test_middleware.py` fails if any URL this module can build has a host
#: the policy does not permit, and `tests/test_covers.py` fails if any other
#: backend module so much as mentions one of these hosts.
COVER_HOSTS: Final = (
    "https://covers.openlibrary.org",  # open_library_url()
    "https://portal.dnb.de",  # dnb_url()
    # Google Books thumbnails. Not built here: they arrive as `supplied`, from
    # the volume record. Google serves them from two hosts.
    "https://books.google.com",
    "https://*.googleusercontent.com",
    # Where Open Library's covers actually live. `covers.openlibrary.org` serves
    # **every** cover as a 302 to `archive.org`, which 302s again to a numbered
    # `ia<n>.us.archive.org`. Measured 2026-08-22 against the live service:
    #
    #   covers.openlibrary.org  302 -> archive.org
    #   archive.org             302 -> ia800505.us.archive.org
    #   ia800505.us.archive.org 200    image/jpeg
    #
    # Omitting these is not a hypothetical: the first backfill on the live
    # deployment reported `unreachable: 4` out of 4, because the guard correctly
    # refused a redirect target it had never been told about. An allowlist for a
    # fetch has to name where the bytes are, not where the request is addressed.
    # The DNB serves its covers directly with no redirect, so only Open Library
    # needs this.
    "https://archive.org",
    "https://*.us.archive.org",
)

_INSECURE_SCHEME: Final = "http://"
_SECURE_SCHEME: Final = "https://"

#: Redirect hops a cover fetch will follow, each one re-checked against
#: `is_fetchable`. Two is enough for a service moving a path around and short
#: enough that a chain cannot be walked anywhere interesting.
MAX_REDIRECTS: Final = 2

#: Where this app serves the covers it stores itself. A relative path, so it
#: carries no scheme and no host at all.
LOCAL_COVER_PREFIX: Final = "/covers/"

#: A downloaded cover is untrusted input from a third party, so it is capped by
#: the same limit an upload is. A real cover is tens of kilobytes; this is three
#: orders of magnitude of headroom and still refuses a body that never ends.
MAX_COVER_BYTES: Final = MAX_UPLOAD_BYTES

#: How many covers are fetched at once during a backfill. Bounded because a
#: backfill runs over the whole library: an unbounded gather over five thousand
#: books would open five thousand sockets and get this deployment's address
#: refused by both image services at once.
MAX_CONCURRENT_FETCHES: Final = 6


class CoverOutcome(StrEnum):
    """What happened to one cover, for the log and the counters.

    This module used to leave exactly one trace of its work, the WARNING in
    `Book._store_covers_over_https` for a URL it refused. Everything else was
    silent, so "covers stopped appearing" could be the image service being
    down, the pod having no egress, the browser blocking the request, the
    stored URL having rotted, or nothing being resolved in the first place, and
    the log said the same thing about all five. Naming the outcome is what lets
    the next person tell them apart without a debugger.
    """

    #: A candidate answered with real image bytes.
    VERIFIED = "verified"
    #: Nothing could be checked (a 5xx, a timeout, a refused connection), so the
    #: best guess was kept rather than a cover thrown away over a blip.
    UNVERIFIED = "unverified"
    #: Every candidate said 404. The book has no cover at these services.
    NO_CANDIDATE = "no_candidate"
    #: The bytes were fetched and written into this app's own storage.
    DOWNLOADED = "downloaded"
    #: The fetch failed, was too large, or was not an image. The remote URL is
    #: kept, so this degrades to hotlinking rather than to no cover.
    DOWNLOAD_FAILED = "download_failed"


_COUNTS: Counter[str] = Counter()


def record(outcome: CoverOutcome) -> None:
    """Tally one outcome. The log line is written by the caller, which has the
    ISBN or the URL to name; this only counts."""
    _COUNTS[outcome.value] += 1


def outcome_counts() -> dict[str, int]:
    """Process-lifetime tally per outcome, for a backfill summary and for tests."""
    return dict(_COUNTS)


def reset_counts() -> None:
    """Only for tests, which need a known starting point per case."""
    _COUNTS.clear()


def is_local(url: str | None) -> bool:
    """Whether this app serves the cover itself, rather than a third party."""
    return url is not None and url.startswith(LOCAL_COVER_PREFIX)


def local_url(book_id: int, extension: str) -> str:
    return f"{LOCAL_COVER_PREFIX}{book_id}.{extension}"


def local_url_for(book_id: int) -> str | None:
    """The URL a book's stored cover is served at, if it has one on disk."""
    path = stored_path(book_id)
    return None if path is None else local_url(book_id, path.suffix.lstrip("."))


def is_renderable(url: str) -> bool:
    """Whether an `<img src>` may safely be pointed at this.

    Two shapes and deliberately nothing else: a remote cover over TLS, or a
    file this app uploaded and serves itself.

    `cover_url` is otherwise free text that ends up in an image tag, so
    `javascript:`, `data:` and a scheme-relative `//host` all fit inside it.
    None of the three is exploitable as the app stands (`javascript:` is inert
    in an `img`, an SVG rendered through `img` cannot run script, and `//host`
    is refused because `img-src` lists no bare-host wildcard), and all three
    become exploitable the day `img-src` gains a wildcard or a cover is
    rendered anywhere other than an `<img src>`. Refusing them now costs
    nothing and does not depend on remembering any of that later.
    """
    if url[: len(_SECURE_SCHEME)].lower() == _SECURE_SCHEME:
        return True
    # A prefix test alone is not containment: `/covers/../api/books/export`
    # starts with the prefix and names something else entirely. Nothing stored
    # here reaches the filesystem (routers/covers.py rebuilds the path from the
    # parsed int id and a letters-only extension), so this is not a traversal
    # hole; it is the difference between the invariant this function claims and
    # the one it enforces.
    return url.startswith(LOCAL_COVER_PREFIX) and ".." not in url


def is_fetchable(url: str) -> bool:
    """Whether **this server** may open a connection to this URL.

    A different question from `is_renderable`, with a different answer, and
    keeping them apart is the point. `is_renderable` governs what a browser may
    be pointed at, and it has to keep admitting any `https://` URL, because a
    hotlinked cover is the fallback when a download fails. This governs what the
    application itself will connect to, and there the answer is a short
    allowlist.

    **The hole this closes.** `cover_url` arrives on `BookCreate` from a member,
    and both `_check` and `download` used to hand it straight to httpx with
    `follow_redirects=True` and no host test at all. Any account, and
    registration is open by default, could make the server issue a GET to a host
    of its choosing, be redirected into private address space and down to plain
    http, and (once covers were stored) read an image-shaped response back out.
    The blind half of that predates covers being stored at all: `resolve` has
    put a supplied URL at the front of its candidate list and called `_check` on
    it since the day the check existed.

    Derived from `COVER_HOSTS`, which is the list of image services this app
    talks to and was already the source of the CSP's `img-src`. It was never
    applied at fetch time, which is exactly the drift the tuple exists to
    prevent, one door along.

    Refused, deliberately and in this order: a URL that cannot be parsed at all,
    anything but `https`, a URL carrying credentials, a non-default port, and a
    host not on the list. The credentials case matters because
    `https://covers.openlibrary.org@evil.test/` reads as a listed host to a
    person and resolves to `evil.test` in every client.

    **The parse is inside the `try`, and that is not defensive habit.**
    `urlsplit` raises on an unterminated IPv6 literal and `.port` is a lazy
    property that raises on a port that is not a number or is out of range, and
    `storable` admits all three because it only tests the `https://` prefix. So
    a member could store `https://books.google.com:99999/x.jpg` on a book, and
    from then on **every** backfill run 500ed for **every** member, for good:
    one poisoned row, deterministic, with nothing in the UI naming the cause.
    A URL this function cannot parse is a URL it will not fetch, which is the
    same answer as any other refusal.
    """
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    if port not in (None, 443):
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False

    for listed in COVER_HOSTS:
        allowed = urlsplit(listed).hostname or ""
        if allowed.startswith("*."):
            # A CSP wildcard means any subdomain, and not the bare domain.
            if host.endswith(allowed[1:]) and host != allowed[2:]:
                return True
        elif host == allowed:
            return True
    return False


def storable(url: str | None) -> str | None:
    """A cover URL a browser may be pointed at, or None.

    Named for its commonest use, which is deciding what to store, but the
    question is the same for a value on its way to a preview: `google_books`
    calls it too, because a search result is rendered in an `<img>` long before
    anything is written.

    The two rules below in the order they have to run: upgrade the scheme
    first, then decide whether the result is something an `<img src>` may be
    pointed at. Checking acceptance before the upgrade would refuse every
    `http://` cover instead of fixing it.

    One function because they are one rule, and because they were three copies
    of it. Two of the three repaired the upgrade half of a bug and left the
    acceptance half open, which is a shape that looks closed from either end:
    both reviewers of this change found exactly that, independently.

    Returns None for "do not store this", which is also the answer for a book
    with no cover, deliberately: a caller that wants to tell the two apart
    compares against its own input, and `BookCreate` is the only one that does.
    """
    upgraded = https_url(url)
    return upgraded if upgraded is None or is_renderable(upgraded) else None


def https_url(url: str | None) -> str | None:
    """A cover URL the browser will actually load.

    Google Books returns `imageLinks.thumbnail` over plain **http**, and an
    http image on an https page is mixed content: the browser blocks it
    whatever the CSP says. The result is a stored cover that is correct, and
    invisible, with no error anywhere.

    All four hosts in `COVER_HOSTS` serve the same bytes over TLS, so the
    upgrade is free. A locally uploaded cover is a relative `/covers/1.jpg`
    with no scheme and is returned untouched.
    """
    if url is None:
        return None
    # Case-insensitively: a scheme is case-insensitive per RFC 3986, and the
    # one-shot data migration matches with SQLite's LIKE, which is too. A
    # case-sensitive test here would leave `HTTP://` stored as it arrived and
    # make the two disagree about the same row.
    if url[: len(_INSECURE_SCHEME)].lower() == _INSECURE_SCHEME:
        return "https://" + url[len(_INSECURE_SCHEME) :]
    return url


def open_library_url(isbn: str) -> str:
    """`default=false` is load bearing.

    Without it Open Library answers every request with a grey placeholder
    image, so a book with no cover gets one that looks like a broken image
    rather than no cover at all, and nothing downstream can tell the
    difference.
    """
    return f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"


def open_library_id_url(cover_id: int | str) -> str:
    """A cover by Open Library's own id rather than by ISBN.

    The search index hands back `cover_i` on a document, which resolves for
    editions the cover service has no ISBN mapping for. No `default=false`
    here: an id that exists has an image by construction, so the placeholder
    case `open_library_url` guards against cannot arise.
    """
    return f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"


def dnb_url(isbn: str) -> str:
    """The German book trade's cover service, through the DNB portal."""
    return f"https://portal.dnb.de/opac/mvb/cover?isbn={isbn}"


def candidates(isbn: str) -> tuple[str, ...]:
    """Which image services to ask, in order.

    German ISBNs go to the DNB first for the same reason the metadata chain
    does: it is the service that has them. Everything else keeps Open Library
    first, which is much the broadest for English publishing.
    """
    if isbn.startswith(_GERMAN_PREFIX):
        return (dnb_url(isbn), open_library_url(isbn))
    return (open_library_url(isbn), dnb_url(isbn))


def _time_left(deadline: float | None) -> float | None:
    """Seconds until the deadline, or None when there is no budget.

    A caller treats <= 0 as spent. Returning the figure rather than a boolean is
    what lets each request be capped at what is actually left, so a budget of
    four seconds is four seconds and not four plus one timeout.
    """
    return None if deadline is None else deadline - monotonic()


async def _check(
    client: httpx.AsyncClient, url: str, deadline: float | None = None
) -> bool | None:
    """True if it is an image, False if it is definitely absent, None if unknown.

    The three-way answer is the point. `False` means a service said 404, so the
    next candidate is worth trying. `None` means the question could not be
    answered (a 5xx, a timeout, a refused connection), and the caller keeps the
    URL rather than discarding a cover over a blip.

    A GET rather than a HEAD: some image services answer HEAD with a 405 or
    with headers that do not match what a GET returns, and only a few hundred
    bytes are read.

    **Every hop is checked against `is_fetchable` before the request**, this one
    included, because `resolve` puts a member-supplied URL at the front of its
    candidate list. Redirects are followed by hand rather than by the client, so
    that a listed host cannot hand the server an unlisted one to go and read.
    An unlisted host is `False`, not `None`: it is not a blip to retry, it is a
    candidate to drop.
    """
    target = url
    for _ in range(MAX_REDIRECTS + 1):
        if not is_fetchable(target):
            logger.warning("Refused to check a cover on an unlisted host: %s", target[:200])
            return False
        left = _time_left(deadline)
        if left is not None and left <= 0:
            return None
        timeout = TIMEOUT_SECONDS if left is None else min(TIMEOUT_SECONDS, left)
        try:
            async with client.stream("GET", target, timeout=timeout) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        return None
                    target = urljoin(target, location)
                    continue
                if response.status_code == 404:
                    return False
                if response.status_code >= 400:
                    return None
                content_type = response.headers.get("content-type", "")
                if not content_type.startswith("image/"):
                    # A 200 that is not an image is an error page with the wrong
                    # status, which is the other way this fails.
                    return False
                async for chunk in response.aiter_bytes(_PROBE_BYTES):
                    return len(chunk) > 0
                return False
        except httpx.HTTPError:
            return None
    logger.info("Cover check gave up after %d redirects: %s", MAX_REDIRECTS, url[:200])
    return None


async def resolve(
    raw_isbn: str, supplied: str | None = None, deadline: float | None = None
) -> str | None:
    """A cover URL that has been checked, or the best unverified guess.

    `supplied` is a URL a metadata source returned itself, which is a different
    kind of thing from a guess: Google Books' thumbnail comes from the volume
    record, so it exists by construction. It is checked first and kept if it
    holds.

    Every return path is counted and logged. See `CoverOutcome` for why: the
    five ways this can end used to be indistinguishable from outside.
    """
    isbn = parse_isbn(raw_isbn)
    if isbn is None:
        return supplied

    order = list(candidates(isbn))
    if supplied and supplied not in order:
        order.insert(0, supplied)

    unverified: str | None = None
    # `follow_redirects=False`: `_check` walks them itself so that every hop is
    # tested against `is_fetchable`. Letting the client follow means trusting the
    # first host and then going wherever it points, which is the bug.
    async with httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS, follow_redirects=False
    ) as client:
        for url in order:
            left = _time_left(deadline)
            if left is not None and left <= 0:
                # Out of budget. Whatever was remembered as unverified is
                # returned below, which is the honest answer: a candidate that
                # could not be checked, not a candidate that failed.
                logger.info("Cover resolution ran out of budget for %s", isbn)
                break
            verdict = await _check(client, url, deadline)
            if verdict is True:
                record(CoverOutcome.VERIFIED)
                logger.info("Cover verified for %s: %s", isbn, url)
                return url
            if verdict is None and unverified is None:
                # Remembered, not returned yet: a later candidate may verify
                # cleanly, and a checked cover beats an unchecked one.
                unverified = url

    if unverified is not None:
        record(CoverOutcome.UNVERIFIED)
        logger.info("Kept an unverified cover for %s: %s", isbn, unverified)
        return unverified

    record(CoverOutcome.NO_CANDIDATE)
    logger.info("No cover for %s at any image service", isbn)
    return None


async def resolve_many(isbns: list[str]) -> dict[str, str | None]:
    """Covers for several ISBNs at once, for the rapid shelf scanner.

    Bounded by `MAX_CONCURRENT_FETCHES`. It used to be a bare gather, which is
    fine for the eight books somebody scans in a burst and is not fine for the
    backfill, which calls this with the whole library.
    """
    limit = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

    async def one(isbn: str) -> str | None:
        async with limit:
            return await resolve(isbn)

    results = await asyncio.gather(*(one(isbn) for isbn in isbns))
    return dict(zip(isbns, results, strict=True))


# ── Storing a cover instead of hotlinking one ─────────────────────────────────
#
# A cover URL on another company's server is five separate things that each
# have to keep working: the image service being up, the URL not rotting, the
# pod being able to reach it, every reader's browser being able to reach it,
# and the CSP permitting it. Four of the five are outside this application, so
# a library full of hotlinked covers can go blank for reasons nothing here can
# see or fix. It also tells `covers.openlibrary.org` which books this household
# owns, once per grid render, from the reader's own browser.
#
# So the bytes are fetched once and served from this app, through the
# authenticated cover route that already applies `visible_to()`. They are files
# under `COVERS_DIR`, named by book id; see `docs/decisions.md` for why that
# rather than a column, and for what it costs. The remote URL stays as the
# fallback when a download fails, which degrades to the old behaviour rather
# than to no cover at all.
#
# Deliberately synchronous, unlike `resolve` above. `resolve` runs on the event
# loop beside a metadata lookup, where six seconds of waiting must not block
# the process. A download happens after a book row exists, from handlers that
# are already `def` and therefore already in a worker thread; an `async` twin
# of this would exist only to be bridged back with `asyncio.run` at three call
# sites. An `async def` handler calls it through `asyncio.to_thread`.

#: Not a book, and therefore not something `stored_ids` or `forget` may touch.
#: `routers/settings.py` writes it and `routers/covers.get_login_background`
#: serves it; it is in this directory because that is where those two agree.
LOGIN_BG_BASE: Final = "login_bg"


def stored_path(book_id: int) -> Path | None:
    """The cover file this app holds for a book, in whatever format, or None."""
    for extension in ALLOWED_IMAGE_EXTENSIONS:
        candidate = Path(COVERS_DIR) / f"{book_id}.{extension}"
        if candidate.is_file():
            return candidate
    return None


def stored_ids() -> set[int]:
    """Every book id with a cover file behind it.

    One directory read rather than a `stat` per book, because the caller is the
    backfill and it asks about the whole library at once. On the deployment's
    NFS mount the difference between one readdir and three thousand stats is
    the difference between a click and a timeout.

    A name that is not `<int>.<ext>` is skipped, which is what keeps
    `login_bg.png` out of it.
    """
    directory = Path(COVERS_DIR)
    if not directory.is_dir():
        return set()

    found: set[int] = set()
    for entry in directory.iterdir():
        if not entry.is_file() or entry.suffix.lstrip(".").lower() not in ALLOWED_IMAGE_EXTENSIONS:
            continue
        if entry.stem.isdigit():
            found.add(int(entry.stem))
    return found


def forget(book_id: int) -> None:
    """Delete every stored cover for a book. Called when the book goes for good.

    A file is not deleted by deleting a row, so this is the cost of holding
    covers on disk rather than in the database. A cover whose book no longer
    exists is dead bytes no query will ever find, and worse than that: SQLite
    reuses an id once the highest row goes, so the next book to take it would
    inherit somebody else's cover.
    """
    for extension in ALLOWED_IMAGE_EXTENSIONS:
        (Path(COVERS_DIR) / f"{book_id}.{extension}").unlink(missing_ok=True)


def adoption_url(book_id: int, from_book_id: int) -> str | None:
    """The URL `adopt` will produce, worked out before any bytes move.

    Its whole reason for existing is that the two halves of an adoption belong
    on opposite sides of a commit. The URL goes into the row, so it has to be
    known first; moving the file is a filesystem write no transaction rolls
    back, so it has to happen last. Splitting them is what lets a merge commit
    the right `cover_url` and touch nothing on disk until that commit has
    landed.

    **The extension is read here and read again by `adopt`**, from the same
    `stored_path`, so the filesystem stays the one source of truth and neither
    half caches an answer the other could contradict. What that does not close
    is the gap between the two reads: an upload that replaces the loser's cover
    while the merge is committing leaves a row naming `.png` and a file written
    as `.jpg`. It needs a concurrent `upload_cover` on a book being merged away,
    and the outcome is a broken image with the keeper's bytes on disk under the
    keeper's own id, so re-uploading or renaming restores it. The backfill only
    helps if the cover came from a metadata provider; it has nothing to
    re-fetch for a hand-uploaded one. Carrying the extension across instead
    would trade that for a row naming a file that was never written.

    None when there is no file to adopt, which the caller stores as "no cover"
    rather than as a promise it cannot keep.
    """
    source = stored_path(from_book_id)
    if source is None:
        return None
    return local_url(book_id, source.suffix.lstrip(".").lower())


def adopt(book_id: int, from_book_id: int) -> str | None:
    """Move a cover file from one book's id to another's. The new URL, or None.

    A merge lets the keeper absorb the loser's `cover_url`, which is a
    `/covers/<loser id>.<ext>` naming a file that is about to be deleted with
    the loser. Renaming it is what keeps the keeper's cover working, and it is
    the second thing files cost that a column would not: the pointer and the
    bytes are two facts that have to be kept in step by hand.

    **Called after the transaction commits**, with the URL already written by
    `adoption_url`, and the return value is **load bearing rather than
    informational**. It is the only signal that the move did not happen, and
    `replace_image` is atomic: on `OSError` it removes its own temporary file
    and re-raises, so the source is still there and None means "these bytes are
    the only copy, do not sweep them". A caller that discards this answer and
    then forgets the source id destroys a hand-uploaded cover for good, since
    nothing remote exists for the backfill to re-fetch. `merge_books` is the
    only caller and does exactly that check.
    """
    source = stored_path(from_book_id)
    if source is None:
        return None
    extension = source.suffix.lstrip(".").lower()
    # Through `replace_image` rather than a rename, so the keeper's existing
    # covers in other formats go the same way they do on an upload.
    try:
        replace_image(Path(COVERS_DIR), str(book_id), extension, source.read_bytes())
    except OSError as error:
        logger.warning("Could not move a cover from book %d: %s", from_book_id, error)
        return None
    source.unlink(missing_ok=True)
    return local_url(book_id, extension)


def duplicate(book_id: int, from_book_id: int) -> str | None:
    """Copy a cover file from one book's id to another's. The new URL, or None.

    `adopt` without the delete, for adding a second copy of a title. The two
    rows must not share a file: files are named by book id and `forget` deletes
    by id, so purging either copy would blank the other's cover while leaving a
    `cover_url` pointing at nothing.

    Only worth doing for a cover this app already holds. A remote URL is
    inherited by assignment and a book with neither is resolved from its ISBN
    like any other new row, both of which cost no bytes on disk.
    """
    source = stored_path(from_book_id)
    if source is None:
        return None
    extension = source.suffix.lstrip(".").lower()
    try:
        replace_image(Path(COVERS_DIR), str(book_id), extension, source.read_bytes())
    except OSError as error:
        logger.warning("Could not copy a cover from book %d: %s", from_book_id, error)
        return None
    return local_url(book_id, extension)


def download(url: str, deadline: float | None = None) -> tuple[bytes, str] | None:
    """Fetch a cover and identify its format. None if it is not usable.

    The extension comes from the magic bytes, never from the URL and never from
    the response's `Content-Type`: this is a file from a third party, neither of
    those is evidence about the bytes, and
    `portal.dnb.de/opac/mvb/cover?isbn=...` has no extension in it at all. Same
    rule, and the same function, as an upload.

    The body is read in chunks against `MAX_COVER_BYTES` rather than with
    `response.read()`, so a service answering with an endless stream is refused
    at the cap instead of filling the container's memory.

    **The URL is tested against `is_fetchable` before every request, redirects
    included.** `cover_url` reaches here from `BookCreate`, which is member
    input, so without that this is an authenticated caller choosing which host
    the server connects to and reading an image-shaped answer back out.
    Redirects are followed by hand, with a hop limit, because a client that
    follows them turns one allowed host into a way to reach any other.
    """
    target = url
    chunks: list[bytes] = []
    for _ in range(MAX_REDIRECTS + 1):
        if not is_fetchable(target):
            logger.warning(
                "Refused to download a cover from an unlisted host: %s", target[:200]
            )
            return None
        left = _time_left(deadline)
        if left is not None and left <= 0:
            logger.info("Cover download ran out of budget: %s", target[:200])
            return None
        timeout = TIMEOUT_SECONDS if left is None else min(TIMEOUT_SECONDS, left)
        chunks = []
        try:
            with (
                httpx.Client(timeout=timeout, follow_redirects=False) as client,
                client.stream("GET", target) as response,
            ):
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        return None
                    target = urljoin(target, location)
                    continue
                if response.status_code >= 400:
                    logger.info(
                        "Cover download refused with %d: %s", response.status_code, target
                    )
                    return None
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_COVER_BYTES:
                        logger.info("Cover over %d bytes, refused: %s", MAX_COVER_BYTES, target)
                        return None
                    chunks.append(chunk)
        except httpx.HTTPError as error:
            logger.info("Cover download failed for %s: %s", target, error)
            return None
        break
    else:
        logger.info("Cover download gave up after %d redirects: %s", MAX_REDIRECTS, url[:200])
        return None

    data = b"".join(chunks)
    extension = sniff_image_extension(data)
    if extension is None:
        # A 200 that is not an image is an error page with the wrong status,
        # which is how both of these services report "no cover" on a bad day.
        logger.info("Cover download was not an image: %s", target)
        return None
    return data, extension


def store(book_id: int, url: str, deadline: float | None = None) -> str | None:
    """Pull a remote cover in and write it. The local URL, or None on failure.

    The write goes through `uploads.replace_image`, which writes beside the
    destination and `os.replace`s it into place, so a failure mid-write cannot
    leave a book pointing at a file that no longer exists, and which clears the
    other formats of the same book afterwards, so which one is served does not
    depend on lookup order. Reimplementing either here would be a second copy of
    reasoning that took an incident to get right.
    """
    fetched = download(url, deadline)
    if fetched is None:
        record(CoverOutcome.DOWNLOAD_FAILED)
        return None

    data, extension = fetched
    try:
        replace_image(Path(COVERS_DIR), str(book_id), extension, data)
    except OSError as error:
        # A full or unwritable volume. Counted as a failed download rather than
        # raised: the book is already saved, and losing its cover must not turn
        # a successful add into a 500.
        record(CoverOutcome.DOWNLOAD_FAILED)
        logger.warning("Could not write the cover for book %d: %s", book_id, error)
        return None

    record(CoverOutcome.DOWNLOADED)
    logger.info("Stored a %d byte cover for book %d from %s", len(data), book_id, url)
    return local_url(book_id, extension)


def resolve_and_store(
    book_id: int,
    isbn: str | None,
    supplied: str | None,
    budget: float | None = None,
) -> str | None:
    """The cover URL to record for a book, having tried to store the bytes.

    **This function does not raise.** A cover is a decoration on a book that has
    already been saved, and every caller is a request that must succeed without
    it: adding a book commits the row before this runs, so a raise here is a 500
    on an add that in fact worked, and in the backfill one poisoned row would
    take the whole run down for every member. `store` already absorbs a failed
    download and an unwritable volume; the blanket guard below is for the class
    of failure nobody predicted, which is exactly the class that produced a
    stored, permanent denial of service the first time round. Logged at ERROR
    with the traceback, so a real bug is loud in the log rather than silent.

    The whole add path in one call: ask the image services when nothing usable
    was supplied, download whatever came out of that, and fall back to the
    remote URL when the download fails. None means there is no cover to be had.

    A `supplied` URL pointing at this app is **not** a candidate: it names this
    application, which is the thing being asked to produce the bytes. A book
    carrying one with no file behind it re-resolves from its ISBN like any
    other, which is what stops the column and the directory drifting apart
    silently.

    `budget` is a wall clock ceiling in seconds for the whole call, for the
    paths with a person waiting: see `INTERACTIVE_BUDGET_SECONDS`. Past it the
    best candidate found so far is returned unverified and the bytes are left to
    the backfill, which passes no budget because nothing is waiting on it and it
    is bounded by its batch size instead.

    **Calls `asyncio.run`, so it must not be called from a coroutine.** Every
    handler that adds a book is a `def` and therefore already runs in a worker
    thread; the two `async def` handlers reach it through `asyncio.to_thread`,
    which also gives it a thread with no running loop.
    """
    deadline = None if budget is None else monotonic() + budget
    try:
        candidate = None if is_local(supplied) else supplied
        if candidate is None and isbn:
            candidate = asyncio.run(resolve(isbn, deadline=deadline))
        if candidate is None:
            return None

        return store(book_id, candidate, deadline) or candidate
    except Exception:
        logger.error("Cover work failed for book %d", book_id, exc_info=True)
        return None
