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
from typing import Final

import httpx

from isbn import parse as parse_isbn

logger = logging.getLogger("endpaper.covers")

#: Short. This runs alongside the metadata lookup on the scan path, so it must
#: not be what makes somebody wait.
TIMEOUT_SECONDS: Final = 6

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
)

_INSECURE_SCHEME: Final = "http://"
_SECURE_SCHEME: Final = "https://"

#: Where this app serves the covers it stores itself. A relative path, so it
#: carries no scheme and no host at all.
LOCAL_COVER_PREFIX: Final = "/covers/"


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


async def _check(client: httpx.AsyncClient, url: str) -> bool | None:
    """True if it is an image, False if it is definitely absent, None if unknown.

    The three-way answer is the point. `False` means a service said 404, so the
    next candidate is worth trying. `None` means the question could not be
    answered (a 5xx, a timeout, a refused connection), and the caller keeps the
    URL rather than discarding a cover over a blip.

    A GET rather than a HEAD: some image services answer HEAD with a 405 or
    with headers that do not match what a GET returns, and only a few hundred
    bytes are read.
    """
    try:
        async with client.stream("GET", url) as response:
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


async def resolve(raw_isbn: str, supplied: str | None = None) -> str | None:
    """A cover URL that has been checked, or the best unverified guess.

    `supplied` is a URL a metadata source returned itself, which is a different
    kind of thing from a guess: Google Books' thumbnail comes from the volume
    record, so it exists by construction. It is checked first and kept if it
    holds.
    """
    isbn = parse_isbn(raw_isbn)
    if isbn is None:
        return supplied

    order = list(candidates(isbn))
    if supplied and supplied not in order:
        order.insert(0, supplied)

    unverified: str | None = None
    async with httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS, follow_redirects=True
    ) as client:
        for url in order:
            verdict = await _check(client, url)
            if verdict is True:
                return url
            if verdict is None and unverified is None:
                # Remembered, not returned yet: a later candidate may verify
                # cleanly, and a checked cover beats an unchecked one.
                unverified = url

    if unverified is not None:
        logger.info("Kept an unverified cover for %s: %s", isbn, unverified)
    return unverified


async def resolve_many(isbns: list[str]) -> dict[str, str | None]:
    """Covers for several ISBNs at once, for the rapid shelf scanner."""
    results = await asyncio.gather(*(resolve(isbn) for isbn in isbns))
    return dict(zip(isbns, results, strict=True))
