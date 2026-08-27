"""One door for the catalogue requests this app makes, and every bound on them.

`metadata.py` and `google_books.py` ask six third party catalogues for records.
Every one of those requests used to be built by hand: nine `httpx.AsyncClient(...)`
constructions in `metadata.py` and one in `google_books.py`, each repeating the
timeout, each following redirects anywhere, and none of them bounding the bytes
read or the seconds spent. This module is the single definition of all four.

**Covers are deliberately not a caller, and that is the answer to "why is there
not one outbound policy for the whole app".** `covers.py` answers a different
question: `cover_url` arrives on `BookCreate` from any signed in member, so the
host is chosen by an attacker and has to be tested against an allowlist
(`covers.is_fetchable`) on every hop. Here the host is a module constant and the
member supplies at most a query string, so there is no allowlist to apply and
nothing an allowlist would refuse. Folding them together would mean adding six
catalogue hosts to `COVER_HOSTS`, and `COVER_HOSTS` is what the CSP's `img-src`
is generated from: the merge would widen the browser policy to pay for a fetch
policy. What the two do share is the *shape* of the read loop, and both now have
it: refuse a hop that leaves the host, count raw bytes, stop at a deadline. See
`docs/security.md`.
"""

import asyncio
import json as jsonlib
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urljoin

import httpx

logger = logging.getLogger("endpaper.fetch")

#: The wall clock budget for **one whole request**, redirects and body included.
#:
#: **Not a per-operation timeout, and the distinction is the whole point.**
#: httpx applies `timeout=` to each read separately, so a server trickling one
#: chunk just under the limit holds the connection forever: measured on httpx
#: 0.28.1, twenty bytes at 0.9s apiece completed in 18.0s under a 1.0s timeout.
#: At a 2 MiB cap and 10 second reads that is about 109 days for one request,
#: which is exactly the worker-holding this constant is meant to prevent.
#:
#: **Enforced by `asyncio.timeout` around the whole walk, and nothing weaker
#: works.** Shrinking each read's own timeout and testing the clock between
#: chunks was the first attempt and it overshot by a full budget, because the
#: per-read value is fixed before the stream opens and the clock is only
#: consulted once a chunk has already arrived: measured, a 1.0 second budget
#: returned after 1.982s. `get` has the numbers.
#:
#: 10 seconds is generous against the measurements: the largest honest body,
#: 687,481 bytes of MARC from K10plus, arrived in 0.60s.
TIMEOUT_SECONDS: Final = 10

#: How many redirects a catalogue may spend, per request.
#:
#: Two, matching `covers.MAX_REDIRECTS`. Measured live 2026-08-27 with
#: redirects **off**, exactly one source redirects at all: Open Library answers
#: `/isbn/{isbn}.json` with a single 302 to `/books/{key}.json` on its own host.
#: Nothing here needs a chain.
MAX_REDIRECTS: Final = 2

#: The most a catalogue may answer with, counted on the wire.
#:
#: **2 MiB rather than the 1 MB an earlier round proposed, because that number
#: was sampling the tail rather than bounding it.** `docs/decisions.md` measured
#: the largest honest body at 587,810 bytes on 2026-08-24; widening the query
#: sample two days later found 687,481 (K10plus, `pica.all=geschichte
#: deutschland`, 50 records), and nothing says a third sample would not find
#: more. 1 MB was 1.52x the second figure and 1.78x the first, which is a margin
#: that moved when somebody looked harder. This is 3.05x.
#:
#: What it defends: a hostile or broken source filling a pod limited to 512Mi,
#: where a 1.8 GB peak has already caused an OOMKill once. `metadata.search`
#: asks six sources at once and parsing retains a measured 15.28x the wire
#: bytes, so the worst case this admits is 6 x 2 MiB x 15.28, about 192 MB. Six
#: *honest* worst cases is 4 MiB on the wire and about 61 MB parsed.
#:
#: **Going over is not an error the reader sees.** Every caller already treats a
#: transport failure as "this source is unavailable" and answers from the
#: others, so a cap set slightly low costs one source's rows on one search
#: rather than the request. The `logger.warning` in `get` is the only signal
#: that it ever bit, and there is no metric on it.
MAX_RESPONSE_BYTES: Final = 2_097_152

#: Sent on every request, and the reason is a defect this module shipped with.
#:
#: The first version counted `aiter_bytes()`, which yields the body **after**
#: content decoding. httpx hands the decoder a whole raw chunk and the
#: decompressed allocation therefore happens before the count is compared to the
#: cap, so the cap did not cap. Measured on httpx 0.28.1: a 65,250 byte gzip of
#: 64 MiB of `x` counted 67,108,864 bytes against an 8,192 byte limit, with a
#: 215.8 MB traced peak. `aiter_raw()` on the identical response counted 65,250.
#:
#: So the bytes are counted raw, and compression is not requested, which keeps
#: "the wire bytes" and "the memory" the same number. Measured live 2026-08-27,
#: all six sources answer under `identity`: DNB, the BnF and Google Books gzip
#: when offered and honour this, K10plus, Open Library and the Library of
#: Congress never compressed anyway. The one that would cost most, K10plus at
#: 687,481 bytes, is uncompressed today either way.
_IDENTITY: Final = {"accept-encoding": "identity"}


class FetchRefused(httpx.HTTPError):
    """This module declined to finish a request, on its own rules.

    **An `httpx.HTTPError` on purpose, and that is what made these bounds cost
    nothing at the call sites.** Every caller in `metadata.py` and
    `google_books.py` already catches `httpx.HTTPError` and degrades to
    `Outcome.UNAVAILABLE` or an empty list, so a refusal lands in the handler a
    timeout already lands in. A separate hierarchy would have needed an `except`
    clause added at ten sites, which is ten chances to miss one and turn a
    hostile response into a 500. Same reasoning as `metadata._parsed`, which
    raises `ParseError` because its six callers already caught that.
    """


class ResponseTooLarge(FetchRefused):
    """More than `MAX_RESPONSE_BYTES` on the wire."""


class DeadlineExceeded(FetchRefused):
    """More than `TIMEOUT_SECONDS` of wall clock for one request."""


class RedirectedOffHost(FetchRefused):
    """A catalogue tried to send this server somewhere else.

    **This is the SSRF, and it is the only one this module has.** The first
    host is a module constant, so an attacker cannot pick it; a redirect is how
    they would pick the second. `_LOC_URL` is plaintext `http://lx2.loc.gov:210`
    by necessity, so anyone on the path, or anyone answering DNS for the pod,
    can forge a 302 and turn a member's search into a GET at any address the pod
    can reach, cluster ClusterIPs and 169.254.169.254 included, with up to the
    cap reflected into the results if it parses as MODS.

    Refusing costs nothing measurable. Measured live 2026-08-27 with redirects
    off, one source redirects at all and it redirects to itself.
    """


class TooManyRedirects(FetchRefused):
    """A same-host chain longer than `MAX_REDIRECTS`."""


class UnrequestedEncoding(FetchRefused):
    """A body compressed with something this request did not ask for.

    The braces to `_IDENTITY`'s belt. Raw bytes are never expanded, so a server
    ignoring `identity` cannot get past the cap; without this it would instead
    get past the *parser*, as mojibake or a `JSONDecodeError`, which is a
    stranger failure to debug than a source reported unavailable.
    """


@dataclass(frozen=True)
class Fetched:
    """A response whose body has already been read, and bounded.

    Not an `httpx.Response`, because the body here is read inside the client's
    own context manager and several callers touch `.text` after that context
    has closed: an `httpx.Response` streamed and not read raises
    `ResponseNotRead` there. The three attributes callers use keep the names
    httpx gives them, so a call site changes only in how it gets the object.
    """

    status_code: int
    content: bytes
    #: The charset from the `Content-Type` header, or None where it named none.
    encoding: str | None = None

    @property
    def text(self) -> str:
        """The body as text, decoded the way `httpx.Response.text` decodes it.

        `errors="replace"` matches httpx, and the `LookupError` arm stands in
        for its `_is_known_encoding` guard: a catalogue is free to name a
        charset Python has never heard of, and that must cost mojibake rather
        than an exception no caller expects.
        """
        try:
            return self.content.decode(self.encoding or "utf-8", errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        """The body as JSON. Raises `ValueError` on anything else, as httpx does."""
        return jsonlib.loads(self.content)


def catalogue_client() -> httpx.AsyncClient:
    """The client every catalogue request is made with.

    **`follow_redirects=False`, and `get` walks the hops itself.** Not because
    redirects are unnecessary, they are: Open Library answers
    `/isbn/{isbn}.json` with one, so turning them off outright breaks a source.
    Because a client that follows them follows them *anywhere*, and the hop is
    the only place an attacker gets to choose a host here. `covers.py` reached
    the same shape from the other direction and for the same reason.

    `accept-encoding: identity` is set here rather than per request so that it
    holds for anything this client is used for. See `_IDENTITY`.
    """
    return httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS, follow_redirects=False, headers=_IDENTITY
    )


def _port(url: httpx.URL) -> int:
    """The port a URL reaches, filled in from the scheme where it is implicit.

    `httpx.URL.port` is None for a default port, so comparing it raw would
    read `https://host` and `https://host:443` as two different places and
    refuse a redirect between them.
    """
    return url.port or (443 if url.scheme == "https" else 80)


def _same_host_hop(response: httpx.Response) -> str:
    """The URL of the next hop, if it is on the same host. Raises if it is not.

    Scheme, host and port all have to match. The scheme matters on its own
    because `https` to `http` on the same name is a downgrade to a channel
    somebody on the path can rewrite, which is the position `_LOC_URL` is
    already in and the one this refuses to be moved into.
    """
    location = response.headers.get("location")
    if not location:
        raise RedirectedOffHost("A redirect carried no Location header")
    here = response.request.url
    there = httpx.URL(urljoin(str(here), location))
    if (
        (there.host or "").lower() != (here.host or "").lower()
        or there.scheme != here.scheme
        or _port(there) != _port(here)
    ):
        logger.warning(
            "Refused a catalogue redirect off %s to %s",
            here.host,
            str(there)[:200],
        )
        raise RedirectedOffHost(f"{here.host} tried to redirect to {str(there)[:200]}")
    return str(there)


async def _walk_hops(
    client: httpx.AsyncClient,
    url: str,
    params: Mapping[str, str] | None,
    cap: int,
) -> Fetched:
    """The redirect walk and the capped read. Time is `get`'s problem, not this.

    Split out so the budget is enforced in exactly one place, around this whole
    call, rather than recomputed at each step. Recomputing was the bug: see
    `get`.
    """
    target = url
    query = params

    for _ in range(MAX_REDIRECTS + 1):
        try:
            async with client.stream("GET", target, params=query) as response:
                if response.is_redirect:
                    target = _same_host_hop(response)
                    # The Location carries the whole URL, so re-appending the
                    # original query string would duplicate every parameter.
                    query = None
                    continue

                encoding = response.headers.get("content-encoding", "").strip().lower()
                if encoding not in ("", "identity"):
                    raise UnrequestedEncoding(f"{url[:200]} answered with {encoding!r}")

                total = 0
                chunks: list[bytes] = []
                async for chunk in response.aiter_raw():
                    total += len(chunk)
                    if total > cap:
                        logger.warning(
                            "Refused a catalogue answer over %d bytes: %s", cap, url[:200]
                        )
                        raise ResponseTooLarge(
                            f"{url[:200]} answered with more than {cap} bytes"
                        )
                    chunks.append(chunk)
                return Fetched(
                    response.status_code, b"".join(chunks), response.charset_encoding
                )
        except UnicodeError as error:
            # **A malformed `Location` host raises here, not in `_same_host_hop`,
            # and the hop guard never runs.** httpx builds the redirect request
            # inside `send()` even with `follow_redirects=False`, to populate
            # `response.next_request`: `_send_handling_redirects` ->
            # `_build_redirect_request` -> `_redirect_url` -> `URL.host` ->
            # `idna.decode`. `idna.IDNAError` is a `UnicodeError`, so a plain
            # ASCII `location: http://xn--a.gov/x` came out as a `ValueError`
            # from `client.stream`.
            #
            # That is not cosmetic. Six of the ten call sites catch
            # `(httpx.HTTPError, ElementTree.ParseError)` and would have let it
            # through: one hostile source 500s the whole `GET /api/books/search`
            # instead of being dropped, and `_LOC_URL` is plaintext HTTP, so
            # forging it needs no TLS.
            #
            # Wrapping `httpx.URL(...)` in `_same_host_hop` does **not** fix
            # this: `URL()` constructs fine and `.host` is what raises, by which
            # point `stream` has already raised. Measured both ways.
            logger.warning(
                "Refused a catalogue redirect with an unusable host: %s", target[:200]
            )
            raise RedirectedOffHost(
                f"{target[:200]} sent a Location naming an unusable host"
            ) from error

    raise TooManyRedirects(f"{url[:200]} redirected more than {MAX_REDIRECTS} times")


async def get(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Mapping[str, str] | None = None,
    limit: int | None = None,
    deadline: float | None = None,
) -> Fetched:
    """GET a catalogue, bounded four ways.

    At most `limit` bytes, at most `MAX_REDIRECTS` hops, none of them leaving
    the host, and all of it inside `deadline`.

    **`aiter_raw`, not `aiter_bytes`.** The second decodes the content encoding
    first, so the allocation this cap exists to prevent happens before the cap
    is consulted. See `_IDENTITY` for the measurement.

    **`asyncio.timeout` around the whole walk, and that is the only shape that
    holds.** The first version passed `min(TIMEOUT_SECONDS, time left)` to each
    read and tested the clock after each chunk. Both are too late: the timeout
    is fixed before the stream opens, and the test runs only once a chunk has
    already arrived, so the read in flight may run a full budget past the
    deadline. Measured on httpx 0.28.1 with chunks arriving at 0.98x of budget,
    a 1.0 second budget returned after **1.982s**; with this wrapper, 1.018s.
    The same applies per hop, which is why the wrapper is outside the loop
    rather than inside it. `notifications.post_digest` uses the same shape.

    `limit` and `deadline` default to None and resolve here rather than in the
    signature, so `MAX_RESPONSE_BYTES` stays the single value: bound as a
    default argument it would be read once at import and a test could not reach
    it.

    Takes the client rather than making one, for the call sites that make
    several requests to the same host and want the connection back. Use
    `get_once` for the ones that make one.
    """
    cap = MAX_RESPONSE_BYTES if limit is None else limit
    ends = time.monotonic() + TIMEOUT_SECONDS if deadline is None else deadline
    left = ends - time.monotonic()
    if left <= 0:
        raise DeadlineExceeded(f"{url[:200]} ran out of time before answering")

    try:
        async with asyncio.timeout(left):
            return await _walk_hops(client, url, params, cap)
    except TimeoutError:
        # `from None`: the cancellation is machinery, and every caller catches
        # `httpx.HTTPError` rather than reading a chain.
        raise DeadlineExceeded(f"{url[:200]} was still sending at the deadline") from None


async def get_once(
    url: str,
    *,
    params: Mapping[str, str] | None = None,
    limit: int | None = None,
    deadline: float | None = None,
) -> Fetched:
    """One bounded GET, with a client of its own."""
    async with catalogue_client() as client:
        return await get(client, url, params=params, limit=limit, deadline=deadline)
