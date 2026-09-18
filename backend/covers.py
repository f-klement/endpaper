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

**Where a cover comes from, and what URL one is served at.** `cover_store` is the
other half and answers a different question: where the file is, and what it is
called.

## What this borrows from `fetch.py`, and what it cannot

The client, and with it the address policy: see `_client`. Not the read loop,
and the reason is the hop rule rather than the shape. `fetch._same_host_hop`
refuses a redirect that changes host; the Open Library chain **is** a change of
host, `covers.openlibrary.org` to `archive.org` to `ia<n>.us.archive.org`, and
`COVER_HOSTS` names all three so that it works. So a hop rule shared with that
module would have to be one `fetch.get` accepts from its caller, which widens
every catalogue door to buy this one. Two smaller things say the same:
`fetch.Fetched` carries no headers, and `_check` triages on `content-type`; and
`_check` is a probe that stops at the first chunk, where `get` reads to a cap
and refuses past it. `docs/decisions.md` has the round this was settled in.
"""

import asyncio
import logging
from collections import Counter
from enum import StrEnum
from typing import Final
from urllib.parse import urljoin, urlsplit

import httpx

import cover_store
import fetch
from config import MAX_UPLOAD_BYTES
from deadline import in_, left
from isbn import parse as parse_isbn
from uploads import sniff_image_extension

logger = logging.getLogger("endpaper.covers")

#: Wall clock one hop may take, redirect or body. Short, because this runs
#: alongside the metadata lookup on the scan path and must not be what makes
#: somebody wait.
#:
#: **Enforced by `asyncio.timeout` around the hop, and nothing weaker works.**
#: Handed to httpx as a `timeout=` it bounds each *read* rather than the hop, so
#: a service sending chunks just inside it holds the socket for as many reads as
#: it cares to make. `_hop_seconds` has the measurement and applies the figure.
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
#: neither.
#:
#: **The ceiling is this figure, and it was not until `_hop_seconds` enforced
#: it.** This paragraph used to say so on the strength of each request being
#: capped at whatever was left, which is true of the number handed to httpx and
#: not of the seconds spent. `_hop_seconds` carries what that cost, measured.
#: The guard written under the old sentence read the number off the request and
#: agreed with it, which is why the arithmetic is not the evidence here.
INTERACTIVE_BUDGET_SECONDS: Final = 4

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

#: How a cover host's name becomes addresses. The seam the suite replaces.
#:
#: **A module attribute rather than a parameter, and the reason is the call
#: chain rather than taste.** `opds.holdings` takes a `resolver` because its
#: caller is one route handler away. The two entry points here are `resolve`,
#: which `metadata.py` calls, and `resolve_and_store`, which `routers/books.py`
#: calls: a parameter would have to be threaded through both of those modules,
#: and through `store` and `download`, to reach the one line that reads it.
#:
#: Nothing in the application assigns to this. `tests/conftest.py` points it at
#: a fixed answer for the whole suite, because a lookup of a real image service
#: from a unit test is what `refuse_unmocked_network` exists to stop.
resolver: fetch.Resolver = fetch.system_resolver


def _client() -> httpx.AsyncClient:
    """The client both cover walks are made with, and what it carries.

    **`fetch.pinned_client`, so the address is classified after resolution and
    the connection goes to the literal that passed.** `COVER_HOSTS` says which
    *hosts* this server may ask; it says nothing about where a name answers, so
    a listed host whose resolver points inside this cluster was fetched. That
    is defence in depth here rather than the primary control, because the host
    is not the member's to choose: `is_fetchable` is what refuses a supplied
    URL, and this refuses an address behind a listed one. `fetch.PUBLIC_ADDRESSES`
    is exactly the set, since every image service on the list is on the internet.

    **`follow_redirects=False` is `fetch._client`'s and is load bearing here.**
    A client that follows a redirect follows it anywhere, and the hop is the one
    place a listed host gets to choose the next one. `_check` and `download`
    walk the hops themselves so that `is_fetchable` runs on every one.

    `accept-encoding: identity` comes with it, paired with the `aiter_raw` in
    both walks: `fetch._IDENTITY` carries the measurement. It costs nothing at
    this door, because JPEG, PNG and WebP are already compressed and no image
    service gzips them.

    **This client's own `timeout=` is `fetch.TIMEOUT_SECONDS`, which is longer
    than this module's, and it is not what bounds a cover hop.** `_hop_seconds`
    is, and it is the smaller of the two at every moment, so the figure a reader
    of this line might take for the bound never binds first.
    """
    return fetch.pinned_client(fetch.PUBLIC_ADDRESSES, resolver=resolver)


def _hop_seconds(deadline: float | None) -> float:
    """How long one hop may take: one request's timeout, or what is left of the
    budget, whichever is smaller.

    **The same number the walks used to hand httpx, enforced where it holds.**
    `timeout=` bounds each *read*, so a service sending chunks just inside it
    holds the socket for as many reads as it makes, and the budget check after a
    chunk runs only once a chunk has arrived. Measured on this tree against a
    local server, a 1.0 second budget and chunks at 0.98x of it: `download`
    returned after **1.973s**, and `_check` after **7.900s**, because
    `aiter_raw(512)` buffered to 512 bytes and its loop body therefore ran once.
    Under this wrapper neither runs past the budget.

    Recomputed per hop rather than once per walk, so the walk's own total is the
    budget: what is left shrinks by whatever the last hop spent. That also
    bounds a walk with **no** budget at `TIMEOUT_SECONDS` a hop, where a
    `timeout=` bounded only a read.
    """
    remaining = left(deadline)
    return TIMEOUT_SECONDS if remaining is None else min(TIMEOUT_SECONDS, remaining)


def _next_hop(current: str, response: httpx.Response) -> str | None:
    """Where this redirect points, resolved against the hop it came from.

    None when it carries no `Location` at all, which is a redirect this walk
    cannot follow rather than a service saying no. One home for the join, so the
    two walks cannot come to disagree about what a relative `Location` means.
    """
    location = response.headers.get("location")
    return None if not location else urljoin(current, location)


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


def stored_url(name: str) -> str:
    """The URL the store serves the file `name` at.

    The store names its own files (`cover_store` decides that a book's cover is
    `<id>.<ext>` and the login background is `login_bg.<ext>`); this says where
    they are served from, which is the one fact `LOCAL_COVER_PREFIX` holds.
    `local_url` is the same answer for the caller that has a book id rather
    than a file name.
    """
    return f"{LOCAL_COVER_PREFIX}{name}"


def local_url(book_id: int, extension: str) -> str:
    return stored_url(f"{book_id}.{extension}")


def local_url_for(book_id: int) -> str | None:
    """The URL a book's stored cover is served at, if it has one on disk."""
    path = cover_store.path_of(book_id)
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

    Every host in `COVER_HOSTS` serves the same bytes over TLS, so the
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

    **A hop is bounded by `asyncio.timeout` and not by the client's `timeout=`.**
    See `_hop_seconds`: this function is where the 7.900s against a 1.0 second
    budget was measured.
    """
    target = url
    for _ in range(MAX_REDIRECTS + 1):
        if not is_fetchable(target):
            logger.warning("Refused to check a cover on an unlisted host: %s", target[:200])
            return False
        remaining = left(deadline)
        if remaining is not None and remaining <= 0:
            return None
        try:
            async with asyncio.timeout(_hop_seconds(deadline)):
                async with client.stream("GET", target) as response:
                    if response.is_redirect:
                        following = _next_hop(target, response)
                        if following is None:
                            return None
                        target = following
                        continue
                    if response.status_code == 404:
                        return False
                    if response.status_code >= 400:
                        return None
                    content_type = response.headers.get("content-type", "")
                    if not content_type.startswith("image/"):
                        # A 200 that is not an image is an error page with the
                        # wrong status, which is the other way this fails.
                        return False
                    # **`aiter_raw()` with no size, and the size is what made
                    # this unbounded.** httpx chunks to whatever it is given, so
                    # `aiter_raw(512)` waited for 512 bytes and the loop body,
                    # which is the only thing that stops the read, ran once:
                    # measured, ceil(512 / the server's chunk size) reads, each
                    # bounded only by the per read timeout, so 7.900s under a
                    # 1.0 second budget at 64 bytes a chunk. The question is
                    # whether any bytes arrived, which is the first chunk.
                    # Raw rather than decoded for `fetch._IDENTITY`'s reason.
                    async for chunk in response.aiter_raw():
                        return len(chunk) > 0
                    return False
        except (httpx.HTTPError, TimeoutError):
            return None
        except UnicodeError:
            # **A host `idna` cannot decode raises here, out of `client.stream`,
            # and `is_fetchable` never sees it.** `idna.IDNAError` is a
            # `UnicodeError` rather than an `httpx.HTTPError`, so the handler
            # above misses it: measured on this tree, it left `covers.resolve`
            # as an `idna.core.InvalidCodepoint`, past that handler and past
            # `metadata.lookup`, which catches neither. `fetch._walk_hops`
            # records the same trap.
            #
            # **On the first hop as well as on a `Location`, and the first hop
            # is the one a member reaches.** `is_fetchable` admits
            # `https://xn--a.googleusercontent.com/x.jpg` through the
            # `*.googleusercontent.com` wildcard, and `httpx.URL()` raises on it
            # before any transport runs. On a `Location` the raise comes from
            # httpx building the redirect request inside `send()` even at
            # `follow_redirects=False`, to populate `response.next_request`. So
            # this wraps the whole hop rather than the redirect handling, and
            # the log line says which URL rather than which of the two it was.
            #
            # False rather than None for the same reason an unlisted host is: a
            # candidate to drop, not a blip to retry.
            logger.warning("Refused a cover URL with an unusable host: %s", target[:200])
            return False
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
    # One client for the whole candidate list, so the connection to a service
    # asked twice is reused. `_client` carries the bounds, including the two
    # that decide what this reaches: the address policy and `follow_redirects=False`.
    async with _client() as client:
        for url in order:
            remaining = left(deadline)
            if remaining is not None and remaining <= 0:
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
# see or fix. It also tells `covers.openlibrary.org` which books this library
# owns, once per grid render, from the reader's own browser.
#
# So the bytes are fetched once and served from this app, through the
# authenticated cover route that already applies `visible_to()`. They are files
# rather than a column; `docs/decisions.md` has why and what it costs, and
# `cover_store` is the module that holds the directory. The remote URL stays
# as the fallback when a download fails, which degrades to the old behaviour
# rather than to no cover at all.
#
# **Synchronous at the door, on a loop of its own behind it.** The fetch is a
# coroutine because the bounds are: `fetch.PinnedTransport` is an async
# transport and no `httpx.Client` can carry it, and `asyncio.timeout` needs a
# loop. So `download` runs `_download` on one. **Neither `download` nor `store`
# may be called from a coroutine**, which is the constraint `resolve_and_store`
# already carried.
#
# **Two reasons the door stays synchronous, and "it would push `asyncio.run` out
# to three call sites" was not one of them.** That sentence stood here and was
# false: `download` has one application caller, `store` at the end of this
# section, `store` has one, `resolve_and_store`, and that function already runs
# `asyncio.run`. The async form would move the call to **one** site and halve
# the loops built per book on the add path. What actually holds:
#
# * **26 call expressions in `tests/test_covers.py` call these two
#   synchronously**, 22 of `download` and 4 of `store`, counted with `ast`
#   rather than by line. An async door makes every one of them a coroutine to
#   await, for a door whose one application caller is in this file.
# * **`store` writes to disk.** `cover_store.save` is blocking IO, so an `async
#   def store` would do it on the event loop, which is the thing being avoided
#   rather than a cost of avoiding it.

# The three below are re-exports of `cover_store`, under this module's older
# names, and they carry no rule of their own. They exist because
# `routers/books.py` calls them at six sites and folding those into
# `cover_store` is a change to a file this one is not. Nothing in here calls
# them: where a cover lives is asked of `cover_store` directly.


def adoption_url(book_id: int, from_book_id: int) -> str | None:
    """The URL `adopt` will produce, worked out before any bytes move.

    Its whole reason for existing is that the two halves of an adoption belong
    on opposite sides of a commit. The URL goes into the row, so it has to be
    known first; moving the file is a filesystem write no transaction rolls
    back, so it has to happen last. Splitting them is what lets a merge commit
    the right `cover_url` and touch nothing on disk until that commit has
    landed.

    **The extension is read here and read again by `adopt`**, from the same
    `cover_store.path_of`, so the filesystem stays the one source of truth and neither
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
    source = cover_store.path_of(from_book_id)
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
    informational**. It is the only signal that the move did not happen:
    `cover_store.move` unlinks the source only once the write has succeeded, so
    None means "these bytes are the only copy, do not sweep them". A caller that
    discards this answer and then forgets the source id destroys a hand-uploaded
    cover for good, since nothing remote exists for the backfill to re-fetch.
    `merge_books` is the only caller and does exactly that check.
    """
    try:
        moved = cover_store.move(book_id, from_book_id)
    except OSError as error:
        logger.warning("Could not move a cover from book %d: %s", from_book_id, error)
        return None
    return None if moved is None else local_url(book_id, moved.suffix.lstrip("."))


def duplicate(book_id: int, from_book_id: int) -> str | None:
    """Copy a cover file from one book's id to another's. The new URL, or None.

    `adopt` without the delete, for adding a second copy of a title. The bytes
    are copied rather than shared, and `cover_store.copy` says what sharing one
    file between two rows would cost.

    Only worth doing for a cover this app already holds. A remote URL is
    inherited by assignment and a book with neither is resolved from its ISBN
    like any other new row, both of which cost no bytes on disk.
    """
    try:
        copied = cover_store.copy(book_id, from_book_id)
    except OSError as error:
        logger.warning("Could not copy a cover from book %d: %s", from_book_id, error)
        return None
    return None if copied is None else local_url(book_id, copied.suffix.lstrip("."))


def download(url: str, deadline: float | None = None) -> bytes | None:
    """Fetch a cover's bytes. None if they are not an image this app serves.

    **Calls `asyncio.run`, so it must not be called from a coroutine.** Every
    caller is already `def` and therefore already in a worker thread; the
    comment above this section says why the door is the synchronous one and the
    fetch behind it is not.
    """
    return asyncio.run(_download(url, deadline))


async def _download(url: str, deadline: float | None = None) -> bytes | None:
    """The fetch `download` runs. See it for why this half is a coroutine.

    Usable is decided by the magic bytes, never by the URL and never by the
    response's `Content-Type`: this is a file from a third party, neither of
    those is evidence about the bytes, and
    `portal.dnb.de/opac/mvb/cover?isbn=...` has no extension in it at all. The
    bytes are handed on unnamed, because what a cover file is called is
    `cover_store`'s to decide and one decision is all there is room for.

    The body is read in **raw** chunks against `MAX_COVER_BYTES` rather than
    with `response.read()`, so a service answering with an endless stream is
    refused at the cap instead of filling the container's memory. Raw because
    the decoded iterator expands a chunk before the cap can look at it: see
    `fetch._IDENTITY`.

    **The URL is tested against `is_fetchable` before every request, redirects
    included.** `cover_url` reaches here from `BookCreate`, which is member
    input, so without that this is an authenticated caller choosing which host
    the server connects to and reading an image-shaped answer back out.
    Redirects are followed by hand, with a hop limit, because a client that
    follows them turns one allowed host into a way to reach any other.
    """
    target = url
    chunks: list[bytes] = []
    async with _client() as client:
        for _ in range(MAX_REDIRECTS + 1):
            if not is_fetchable(target):
                logger.warning(
                    "Refused to download a cover from an unlisted host: %s", target[:200]
                )
                return None
            remaining = left(deadline)
            if remaining is not None and remaining <= 0:
                logger.info("Cover download ran out of budget: %s", target[:200])
                return None
            chunks = []
            try:
                async with asyncio.timeout(_hop_seconds(deadline)):
                    async with client.stream("GET", target) as response:
                        if response.is_redirect:
                            following = _next_hop(target, response)
                            if following is None:
                                return None
                            target = following
                            continue
                        if response.status_code >= 400:
                            logger.info(
                                "Cover download refused with %d: %s",
                                response.status_code,
                                target,
                            )
                            return None
                        encoding = (
                            response.headers.get("content-encoding", "").strip().lower()
                        )
                        if encoding not in ("", "identity"):
                            # **The braces to `accept-encoding: identity`'s
                            # belt, and without it the belt is a regression.**
                            # `aiter_raw` never decodes, so a service that gzips
                            # anyway would have its gzip bytes written to disk
                            # as the image, where the decoded iterator decoded
                            # them correctly before. `is_fetchable` limits this
                            # to `COVER_HOSTS`, so it is robustness rather than
                            # a hole, but refusing is one line and keeps "raw
                            # bytes" and "the image" the same thing.
                            # `fetch.UnrequestedEncoding` is the same check at
                            # the same point.
                            logger.info(
                                "Cover came back %s when identity was asked for: %s",
                                encoding,
                                target,
                            )
                            return None
                        total = 0
                        # `aiter_raw`, not `aiter_bytes`: see `fetch._IDENTITY`.
                        # **Nothing here tests the clock, and that is the
                        # wrapper's job now.** The version that did could only
                        # look once a chunk had already arrived, so a service
                        # sizing chunks just inside the per read timeout ran a
                        # full budget past the deadline: measured, 1.973s
                        # against 1.0s. `asyncio.timeout` cuts mid read.
                        async for chunk in response.aiter_raw():
                            total += len(chunk)
                            if total > MAX_COVER_BYTES:
                                logger.info(
                                    "Cover over %d bytes, refused: %s",
                                    MAX_COVER_BYTES,
                                    target,
                                )
                                return None
                            chunks.append(chunk)
            except (httpx.HTTPError, TimeoutError) as error:
                logger.info("Cover download failed for %s: %s", target, error)
                return None
            except UnicodeError:
                # A host `idna` cannot decode, on this hop or on the `Location`
                # that reached it. `_check` carries the measurement, why this is
                # not an `httpx.HTTPError`, and why the first hop is in scope.
                logger.warning(
                    "Refused a cover URL with an unusable host: %s", target[:200]
                )
                return None
            break
        else:
            logger.info(
                "Cover download gave up after %d redirects: %s", MAX_REDIRECTS, url[:200]
            )
            return None

    data = b"".join(chunks)
    if sniff_image_extension(data) is None:
        # A 200 that is not an image is an error page with the wrong status,
        # which is how both of these services report "no cover" on a bad day.
        # Counted as a failed download here rather than left to the store's
        # refusal, so the log says which of the two it was.
        logger.info("Cover download was not an image: %s", target)
        return None
    return data


def store(book_id: int, url: str, deadline: float | None = None) -> str | None:
    """Pull a remote cover in and write it. The local URL, or None on failure.

    Where the file goes and what it is called are `cover_store`'s: this function
    knows a book id and some bytes.
    """
    data = download(url, deadline)
    if data is None:
        record(CoverOutcome.DOWNLOAD_FAILED)
        return None

    try:
        destination = cover_store.save(book_id, data)
    except (OSError, cover_store.NotAnImage) as error:
        # A full or unwritable volume, or bytes `download` should already have
        # refused. Counted as a failed download rather than raised: the book is
        # already saved, and losing its cover must not turn a successful add
        # into a 500.
        record(CoverOutcome.DOWNLOAD_FAILED)
        logger.warning("Could not write the cover for book %d: %s", book_id, error)
        return None

    record(CoverOutcome.DOWNLOADED)
    logger.info("Stored a %d byte cover for book %d from %s", len(data), book_id, url)
    return local_url(book_id, destination.suffix.lstrip("."))


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
    the backfill, which passes no budget because nothing is waiting on it.

    **With no budget a fetch is bounded per hop and not per book.** `_hop_seconds`
    gives every hop `TIMEOUT_SECONDS` of wall clock whether or not a deadline was
    passed, so the backfill's ceiling is that figure times the hops rather than
    the nothing it used to be: a server sizing chunks at one byte used to stretch
    a download for as long as it liked, because `MAX_COVER_BYTES` against a per
    read timeout was the only bound left. What is still missing is a per **book**
    ceiling, which is one call in `routers/books.py` away and is what closes the
    difference between three hops and a whole run.

    **Calls `asyncio.run`, so it must not be called from a coroutine.** Every
    handler that adds a book is a `def` and therefore already runs in a worker
    thread; the two `async def` handlers reach it through `asyncio.to_thread`,
    which also gives it a thread with no running loop.
    """
    deadline = None if budget is None else in_(budget)
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
