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


def open_library_url(isbn: str) -> str:
    """`default=false` is load bearing.

    Without it Open Library answers every request with a grey placeholder
    image, so a book with no cover gets one that looks like a broken image
    rather than no cover at all, and nothing downstream can tell the
    difference.
    """
    return f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"


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
