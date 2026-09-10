"""One door for the catalogue requests this app makes, and every bound on them.

`metadata.py` and `google_books.py` ask eleven third party catalogues for records.
Every one of those requests used to be built by hand: nine `httpx.AsyncClient(...)`
constructions in `metadata.py` and one in `google_books.py`, each repeating the
timeout, each following redirects anywhere, and none of them bounding the bytes
read or the seconds spent. This module is the single definition of all four.

**Covers are deliberately not a caller, and that is the answer to "why is there
not one outbound policy for the whole app".** `covers.py` answers a different
question: `cover_url` arrives on `BookCreate` from any signed in member, so the
host is chosen by an attacker and has to be tested against an allowlist
(`covers.is_fetchable`) on every hop. Folding them together would mean adding
eleven catalogue hosts to `COVER_HOSTS`, and `COVER_HOSTS` is what the CSP's
`img-src` is generated from: the merge would widen the browser policy to pay for
a fetch policy. What the two do share is the *shape* of the read loop, and both
now have it: refuse a hop that leaves the host, count raw bytes, stop at a
deadline. See `docs/security.md`.

**That argument is about the allowlist and says nothing about the address policy
this module also holds**, which touches neither `COVER_HOSTS` nor the CSP.
Covers is unpinned because it has a read loop of its own rather than because
pinning would cost anything there, so a listed host whose resolver answers
inside this cluster is still fetched. It is the one door whose URL a **member**
supplies, which makes it the next one to wire rather than the one that needed it
least.

**"There is no allowlist here because the host is a module constant" is true of
`metadata.py` and `google_books.py` and is no longer true of this module's
callers as a set.** `opds.py` is the third one, and its address is typed by an
admin, which is #131's concession 1 arriving. It is admitted here rather than
given a fourth read loop because a fourth copy of these four bounds is how one
of them comes to be missing, and because it brings its own admission rule and
its own origin pin and applies both **before** every call into this module: no
byte of any response it reads may move the address of the next request.

What this module contributes to that is two things. The hop guard, which refuses
a redirect off the host whoever the caller is. And **the address policy**:
`pinned_client` resolves the name once, classifies every address it answers
with, and connects to the literal that passed, so the address a policy refused
is one no lookup afterwards can restore. That is resolve-then-pin, and it is
what makes an address range refusal worth writing down: on the URL text alone it
would be a bound that a name resolving into the range walks straight past.
**Which classes a door admits is the door's own decision** and the two policies
here differ: read `opds.py`'s docstring for what a household server may be at.
"""

import asyncio
import ipaddress
import json as jsonlib
import logging
import socket
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Protocol
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
#: asks eight sources at once and parsing retains a measured 15.28x the wire
#: bytes, so the worst case this admits is 8 x 2 MiB x 15.28, about 256 MB.
#:
#: **Which makes the ceiling sixteen concurrent sources, and it is worth having
#: written down before somebody proposes the seventeenth.** 536,870,912 divided
#: by (2,097,152 x 15.28) is 16.75, so eight spends 47.8% of the pod and the
#: seventeenth source exceeds it outright. **The roster is eleven of that
#: ceiling**, and #91 proposes national catalogues for more countries still, so
#: the next source but five is the one that does not fit. The provider list
#: (`sources.py`) lets a library switch sources **off**, never on beyond the
#: roster, so nothing a household does moves this: the bound is the roster's
#: size, which is why `tests/test_fetch.py::_concurrent_search_sources` counts
#: `sources.SEARCH_SOURCES` rather than whatever is enabled.
#: Eight *honest* worst cases is about 5.07 MiB on the wire and about 81 MB
#: parsed. The eighth is the NLG, and the figure is its **largest** measured
#: page, 604,964 bytes (`dc.title=history`, 50 records, 2026-08-31), not the
#: 287,736 a Greek language query happened to cost. The seventh was the ÖNB, at
#: 516,771 bytes (`alma.publisher=Zsolnay`, 2026-08-27). Picking the smaller
#: page each time would be this comment's own version of sampling the tail
#: rather than bounding it, which is the mistake the paragraph above exists to
#: record.
#:
#: **That 5.07 is two measured pages added to a base that was already rounded**,
#: the "4 MiB" the six-source version of this sentence carried, whose per source
#: bodies were not written down. So it is exact in its two newest terms and
#: rounded in the rest, and anyone re-deriving it from six live responses should
#: expect to land near rather than on it.
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
#: "the wire bytes" and "the memory" the same number. Measured live, all eleven
#: sources answer under `identity`: DNB, the BnF, Google Books, the ÖNB and the
#: BNE gzip when offered and honour this, K10plus, Open Library, the Library of
#: Congress, the NLG, the NKP and the BNA never compressed anyway, the last of
#: those measured 2026-09-07 over 53 requests. The one that would cost
#: most, K10plus at 687,481 bytes, is uncompressed today either way.
#:
#: **The two newest were each measured both ways rather than assumed**, because
#: a source that ignored the header would put a decompressed body past the cap.
#: The ÖNB was the seventh: one `alma.title=wien` page at `maximumRecords=50` is
#: **295,821 bytes** under `accept-encoding: identity` and **25,934** under
#: `gzip, deflate, br`, both 2026-08-27, so it honours the header. The NLG is
#: the eighth: `dc.title=history` at 50 records is **604,964 bytes under both**,
#: with no `content-encoding` on either reply, 2026-08-31, so it compresses
#: nothing to begin with. The NKP is the ninth and behaves the same way, 7,362
#: bytes under both with no `content-encoding`, 2026-08-31.
#:
#: **Two sources do not enter the arithmetic below**, and that is the one place
#: this file's counts and the roster's diverge. The bound is on what
#: `metadata.search` asks **concurrently**, which is `sources.SEARCH_SOURCES`,
#: and neither the NKP nor the BNE answers a title search: the NKP's server
#: renders one populated record per response whatever page size is asked for,
#: and the BNE's search gain was never measured. So the fan out is still eight
#: and every figure below is unchanged.
_IDENTITY: Final = {"accept-encoding": "identity"}


class Credential(Protocol):
    """What this module needs of a credential, which is one method.

    **A protocol rather than an import, and the reason is a dependency
    direction.** `credentials.Credential` is the implementation and it lives in
    a module that reaches the ORM; this is the outbound door, and the door
    knowing about the database would put SQLAlchemy behind every catalogue
    request. So the door states what it needs and the store satisfies it, the
    same shape `z3950.py` uses for its client.

    The method takes the URL of the hop about to be made and answers the headers
    that may go on it, which for anything but the origin the credential was set
    for is nothing at all.
    """

    def header_for(self, url: str) -> dict[str, str]: ...


class FetchRefused(httpx.HTTPError):
    """This module declined to finish a request, on its own rules.

    **An `httpx.HTTPError` on purpose, and that is what made these bounds cost
    nothing at the call sites.** Every caller in `metadata.py` and
    `google_books.py` already catches `httpx.HTTPError` and degrades to
    `Outcome.UNAVAILABLE` or an empty list, so a refusal lands in the handler a
    timeout already lands in. A separate hierarchy would have needed an `except`
    clause added at ten sites, which is ten chances to miss one and turn a
    hostile response into a 500. Same reasoning as `metadata._parsed`, which
    raises `ParseError` because its eleven callers already caught that. Eleven,
    counted 2026-09-03 and not eight: there are three functions named `_parsed`
    in this backend, and `marc.py` defines and calls its own despite importing
    `metadata`, so counting the name across the tree gives sixteen and counting
    the callers of the one named here gives eleven.
    """


class ResponseTooLarge(FetchRefused):
    """More than `MAX_RESPONSE_BYTES` on the wire."""


class DeadlineExceeded(FetchRefused):
    """More than `TIMEOUT_SECONDS` of wall clock for one request."""


class RedirectedOffHost(FetchRefused):
    """A catalogue tried to send this server somewhere else.

    **This is the SSRF for the catalogue callers.** There the first host is a
    module constant, so an attacker cannot pick it; a redirect is how they would
    pick the second. For `opds.py` the first host is an admin's and a redirect
    is one of two ways a response could pick the second, the other being a
    paging link, which that module refuses against the same origin this does.

    `targets.SEEDED[CatalogueSource.LOC].base_url` is plaintext
    `http://lx2.loc.gov:210`
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


class AddressRefused(FetchRefused):
    """The address this name resolved to is not one the caller's policy admits.

    **Not a statement that the host is hostile.** It says the address this
    server was about to open a connection to is in a range the door refuses,
    which is as much as any address policy ever knows.
    """


class AddressClass(Enum):
    """What kind of address this is, as an outbound policy has to decide it.

    **Seven values, and the seventh is a fallback rather than a range.**
    `RESERVED` is everything the other six did not name: 6to4, Teredo, the
    documentation and benchmarking ranges all land there, and a policy admits
    classes it names rather than whatever was left over. Enumerating what is
    **admitted** is the direction `opds.HOLDING_RELS` gives the reason for.

    **But the fallthrough is not the backstop it reads as, and the difference is
    a measurement.** `classify` reaches it through `is_global`, which on IPv6 is
    defined as `not is_private`, so a range `ipaddress` has not been taught is
    `PUBLIC` here and not `RESERVED`: `fec0::a9fe:a9fe` was admitted by both
    policies until `_NOT_GLOBALLY_REACHABLE` named it. What actually keeps this
    current is the interpreter, and that tuple is the seam for a range it has
    not caught up with.
    """

    UNSPECIFIED = "unspecified"
    LOOPBACK = "loopback"
    LINK_LOCAL = "link-local"
    MULTICAST = "multicast"
    PRIVATE = "private"
    RESERVED = "reserved"
    PUBLIC = "public"


#: The ranges `AddressClass.PRIVATE` means, written out rather than asked for.
#:
#: **`ipaddress.is_private` is not this question and admits things a policy
#: naming private space must not.** Measured on Python 3.14: it answers True for
#: `2001:db8::1`, for `198.18.0.1`, for `203.0.113.5`, for the whole of 6to4 and
#: for Teredo, so a household policy admitting "private" through that property
#: would admit `2002:a9fe:a9fe::1`, whose embedded address is the cloud metadata
#: endpoint. These five are the ranges a machine on somebody's own network
#: actually has.
#:
#: 100.64/10 is here because a household behind a carrier grade NAT has one, and
#: refusing it would refuse that household's own server.
#:
#: **RFC 1918's third block is spelled as an integer, and that is not
#: obfuscation.** The publish pipeline fails on that block's dotted form in any
#: file it publishes, which this one is, so written out it would stop a release
#: rather than fail a test. The guard is untouched by this and still catches
#: somebody writing that address in prose, which is what it is for; this is the
#: one place in the tree that legitimately needs the range itself.
#: `tests/test_fetch.py::TestWhichClassAnAddressIsIn` checks the block is the one
#: intended, by its integer, since a test carrying the dotted form would not
#: publish either.
_PRIVATE_NETWORKS: Final = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.IPv4Network((0xC0A80000, 16)),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fc00::/7"),
)

#: Ranges `ipaddress` does not know are unreachable, refused as `RESERVED`.
#:
#: **`IPv6Address.is_global` is defined as `not is_private`**, so on that family
#: the `RESERVED` fallthrough catches only what the interpreter already refuses,
#: and any v6 range Python's list is missing comes out `PUBLIC` rather than
#: reserved. Measured on Python 3.14: `fec0::a9fe:a9fe` classified `public` and
#: `PUBLIC_ADDRESSES` admitted it.
#:
#: So the freshness of this classification is the interpreter's rather than this
#: file's, and this tuple is where a range it has not caught up with goes.
#: `fec0::/10` is site local, deprecated by RFC 3879 and never a household's own
#: server; `5f00::/16` is the SRv6 block RFC 9602 marks not globally reachable.
_NOT_GLOBALLY_REACHABLE: Final = (
    ipaddress.ip_network("fec0::/10"),
    ipaddress.ip_network("5f00::/16"),
)

#: IPv6 prefixes that carry an IPv4 address in their low 32 bits.
#:
#: **Unwrapped before classification, because two of the three are `is_global`
#: and would otherwise be `PUBLIC`.** Measured on Python 3.14:
#: `::169.254.169.254` (the deprecated IPv4 compatible form) and
#: `64:ff9b::a9fe:a9fe` (the well known NAT64 prefix, which a host with NAT64
#: translates straight back to the v4 address) both answer `is_global=True`,
#: and `::ffff:169.254.169.254` is the mapped form every v4 only check is
#: written round.
#:
#: **6to4 and Teredo are deliberately not unwrapped.** They carry a v4 address
#: too, and both fall to `RESERVED` on their own, so unwrapping would move them
#: from refused-by-every-policy to refused-by-most. Refusing the whole prefix is
#: the stronger answer and the shorter one.
_EMBEDDED_V4: Final = (
    ipaddress.ip_network("::ffff:0:0/96"),
    ipaddress.ip_network("::/96"),
    ipaddress.ip_network("64:ff9b::/96"),
)


def _embedded_ipv4(address: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """The IPv4 address inside a v6 one, where the prefix carries one."""
    if address.ipv4_mapped is not None:
        return address.ipv4_mapped
    for network in _EMBEDDED_V4:
        if address in network:
            return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return None


def classify(address: str | ipaddress.IPv4Address | ipaddress.IPv6Address) -> AddressClass:
    """Which `AddressClass` an address is in. Raises `ValueError` on a non-address.

    **The order is load bearing at the top and at the bottom.** Unspecified and
    loopback are decided before the v4 unwrap, because `::1` and `::` are inside
    `::/96` and unwrapping them first would call `::1` whatever `0.0.0.1` is.
    `is_global` is consulted last, because it is True for multicast on both
    families, measured: `224.0.0.1` and `ff02::1` are both global and neither is
    a host this server has any business connecting to.

    The recursion terminates on the first step: what comes back from
    `_embedded_ipv4` is an `IPv4Address`, and an IPv4 address embeds nothing.
    """
    parsed = ipaddress.ip_address(address)
    if parsed.is_unspecified:
        return AddressClass.UNSPECIFIED
    if parsed.is_loopback:
        return AddressClass.LOOPBACK
    if isinstance(parsed, ipaddress.IPv6Address):
        inner = _embedded_ipv4(parsed)
        if inner is not None:
            return classify(inner)
    if parsed.is_link_local:
        return AddressClass.LINK_LOCAL
    if parsed.is_multicast:
        return AddressClass.MULTICAST
    if any(parsed in network for network in _PRIVATE_NETWORKS):
        return AddressClass.PRIVATE
    if any(parsed in network for network in _NOT_GLOBALLY_REACHABLE):
        return AddressClass.RESERVED
    if parsed.is_global:
        return AddressClass.PUBLIC
    return AddressClass.RESERVED


@dataclass(frozen=True)
class AddressPolicy:
    """Which classes of address one door will open a connection to.

    **A policy per door rather than one for the application**, because the doors
    do not reach the same places and a single policy would have to be the looser
    of the two: a household's own OPDS server is at `10.0.0.10` or `localhost`,
    so refusing private space there refuses the feature, and a catalogue
    somebody typed has no business at any address inside this cluster.

    `name` is for the log line, so a refusal says which door refused.
    """

    name: str
    admits: frozenset[AddressClass]

    def permits(self, address: str) -> bool:
        """Whether this policy will connect to this address.

        Anything that does not parse as an address is refused, which is the same
        answer `covers.is_fetchable` gives a URL it cannot parse: a resolver
        answering something unreadable is not a reason to connect to it.
        """
        try:
            return classify(address) in self.admits
        except ValueError:
            return False


#: The policy for a server on the household's own network, which is `opds.py`.
#:
#: **Loopback and private space are admitted deliberately and that is the whole
#: shape of this row.** A household library server is on the household's own
#: network, so `http://10.0.0.10:8083` and `http://localhost:8083` are the
#: ordinary case rather than the attack.
#:
#: **Link local is refused, and it is the one private range that is never a
#: household's own server.** It is where the cloud metadata endpoint sits, and
#: refusing it is the owner's decision of 2026-09-07 on the OPDS link local
#: ticket: not the literal, which guards the accident and not the attacker, but
#: the resolved address, which is what `PinnedTransport` makes possible.
HOUSEHOLD_ADDRESSES: Final = AddressPolicy(
    name="household",
    admits=frozenset(
        {AddressClass.LOOPBACK, AddressClass.PRIVATE, AddressClass.PUBLIC}
    ),
)

#: The policy for a host somebody typed into a settings screen.
#:
#: **Public addresses only**, which is #131's own case: a catalogue an admin
#: names is on the internet, and every other class of address is either this
#: pod's own network or a range no catalogue is served from.
#:
#: **It has no caller in this build.** The typed target feature is not written,
#: and this constant exists so the door it will use is the one already tested
#: rather than one written the day the row lands. The curated registry that
#: comes before it is vendored, so its hosts ship with the build and it needs
#: none of this: pointing that at this policy would refuse a registry entry
#: whose address is not public, which is a narrowing nobody asked for.
#:
#: **It is not the whole of what a typed target needs.** That design also
#: requires **no redirects at all**, and a client from `pinned_client` still
#: walks `_walk_hops`'s two same host hops, which is right for a catalogue and
#: is not what was specified there. Whoever builds the row adds that refusal;
#: this constant does not carry it.
PUBLIC_ADDRESSES: Final = AddressPolicy(
    name="public", admits=frozenset({AddressClass.PUBLIC})
)


class Resolver(Protocol):
    """A name to addresses, asked once per request. The seam tests replace.

    A protocol rather than a function type so a double can be a class with
    state, which is what a rebinding test needs: the second call answers
    differently from the first.
    """

    async def __call__(self, host: str, port: int) -> Sequence[str]: ...


async def system_resolver(host: str, port: int) -> Sequence[str]:
    """Every address this host resolves to, in the order the resolver gave them.

    `loop.getaddrinfo` rather than `socket.getaddrinfo`, because the second
    blocks the event loop for the length of a DNS lookup, which a hostile or
    merely broken nameserver chooses.

    Duplicates are dropped and the order is kept: `dict.fromkeys` is the idiom
    for that, and the order matters because the first admitted address is the
    one connected to.
    """
    infos = await asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM
    )
    return tuple(dict.fromkeys(str(info[4][0]) for info in infos))


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


#: Who this is, for the services being asked.
#:
#: **Set because a source asked for it in writing.** lobid's usage policy asks
#: for "a meaningful, recurring string" so the hbz can tell one caller from
#: another in its statistics, and asks that it stay the same for the life of a
#: project. It costs nothing and it is the only thing any of these services has
#: asked of this app in return for answering without a key.
#:
#: **No version number and no contact address.** A version would change with
#: every release, which is the opposite of what was asked for, and an address
#: here would be one in every published image. The project's own name is the
#: whole of the identification, and it names software rather than a person.
#:
#: Set on the client rather than per request, like `_IDENTITY` and for the same
#: reason: it holds for anything this client is used for.
_AGENT: Final = {"user-agent": "endpaper"}


def catalogue_client() -> httpx.AsyncClient:
    """The client every catalogue request is made with.

    **`follow_redirects=False`, and `get` walks the hops itself.** Not because
    redirects are unnecessary, they are: Open Library answers
    `/isbn/{isbn}.json` with one, so turning them off outright breaks a source.
    Because a client that follows them follows them *anywhere*, and the hop is
    the only place an attacker gets to choose a host here. `covers.py` reached
    the same shape from the other direction and for the same reason.

    `accept-encoding: identity` is set here rather than per request so that it
    holds for anything this client is used for. See `_IDENTITY`, and `_AGENT`
    for why there is a `user-agent` beside it.
    """
    return _client()


class PinnedTransport(httpx.AsyncBaseTransport):
    """Resolve the name, refuse the address, connect to that same address.

    **This is resolve-then-pin, and the pin is the half that is not a check.**
    Classifying the address a name resolves to is worth nothing on its own: the
    connection does its own lookup, the second answer may differ from the first,
    and that gap is DNS rebinding. So the name is resolved here, once **per
    request** and not once per caller, every address it answered with is
    classified, and the request handed to httpcore carries the **literal
    address** that passed, with the `Host` header and the TLS server name still
    carrying the name. httpcore resolves a literal to itself, so there is no
    second lookup left to move. A two hundred page walk therefore resolves two
    hundred times and classifies each answer, which is the property that makes a
    rebinding attempt land on a refusal rather than on a stale pin.

    **The caller's own request object is never rewritten**, and that is not
    tidiness. `httpx.AsyncClient` sets `response.request` to the object it was
    given, and `_same_host_hop` compares a `Location` against
    `response.request.url`: rewriting in place would make that comparison read
    the pinned literal, so a catalogue redirecting to its own name would be
    refused as a redirect off host and a relative `Location` would be walked as
    an address with no name attached. A second `httpx.Request` carrying the same
    stream and headers is what keeps both halves honest.

    **One inner transport per TLS server name**, and this is the subtle one.
    httpcore keys its connection pool on the request's origin, which is the
    pinned literal here, so two different names pinned to one address and port
    would share a pooled connection: the second name's request would travel on a
    TLS connection authenticated for the first name's certificate, since a
    reused connection does no handshake. Keying the pool by name removes that by
    construction rather than by nobody having done it yet.

    **What this does not stop**, none of which is narrowed by having it:

    * **Most of what an address policy is usually bought for, under
      `HOUSEHOLD_ADDRESSES`.** That policy admits loopback and RFC 1918 because
      a household server is there, so a name an admin types still reaches this
      pod's own loopback, every ClusterIP in the cluster and the router's
      administration page. **One range changed.** Read this as a link local
      refusal that a name cannot walk past, and not as request forgery having
      been closed at that door: what limits the rest is that configuration is
      admin only.
    * **A host at an admitted address that is itself the attack.** A name that
      resolves to a public address and proxies inward reaches whatever it likes,
      and no address policy anywhere can see that. This refuses addresses, not
      hosts.
    * **A name answering with both admitted and refused addresses.** The
      admitted ones are tried in turn, one per connect failure, and the refused
      ones are never used at all, so such a name is pinned rather than refused.
      The alternative, refusing the whole answer, refuses a household server
      whose name also carries a link local address, which mDNS routinely gives
      one.
    * **Anything about the response.** The bytes are `get`'s problem: the cap,
      the deadline and the hop guard are unchanged and still do all of that.
    * **The other outbound doors.** `covers.py` has its own read loop and its
      own host allowlist, and `z3950.py` is not HTTP at all, so neither is
      wired to this. Both reach hosts this build ships rather than hosts
      somebody typed, which is why that is a gap and not a hole.
    * **A proxy.** An egress proxy would take the connection out of this
      transport's hands entirely, which is why `pinned_client` refuses to read
      one from the environment. A deployment that needs one needs this decision
      re-taken rather than the variable set.
    """

    def __init__(
        self,
        policy: AddressPolicy,
        *,
        resolver: Resolver = system_resolver,
        inner: Callable[[], httpx.AsyncBaseTransport] = httpx.AsyncHTTPTransport,
    ) -> None:
        self._policy = policy
        self._resolve = resolver
        self._inner_factory = inner
        self._inner: dict[str, httpx.AsyncBaseTransport] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        # The punycode form, not `url.host`, which is the unicode one: it is
        # what goes on the wire as `Host`, what a certificate is checked
        # against, and what the resolver is asked about.
        name = request.url.raw_host.decode("ascii")
        # Refused before a pool is opened for the name, rather than after.
        addresses = await self._admitted(name, _port(request.url))
        transport = self._transport_for(name)

        # **Only a connect failure moves on**, and that is pinned by
        # `test_only_a_connect_failure_moves_on_to_the_next_address` rather than
        # stated here: widening this to `httpx.HTTPError` was caught by nothing
        # until that test existed, and what it admits is a request replayed
        # against a second address after bytes, and this door's `Authorization`
        # header, have already gone out.
        #
        # **A second address is only for a request with no body.** A stream is
        # read once, so replaying one would send an empty body to the second
        # address and look like a request the caller made. Every caller of this
        # door makes a GET; this is here so the first one that does not is not
        # silently given that.
        if request.method not in ("GET", "HEAD"):
            addresses = addresses[:1]

        # **Every admitted address in turn, and this is a reachability rule
        # rather than a security one.** Pinning removes the happy eyeballs walk
        # anyio does over `getaddrinfo`'s whole answer, so a dual stack
        # household name whose first address is an unroutable ULA would fail
        # here where it worked before, reported as a server that did not answer.
        # Only a **connect** failure moves on: nothing has been sent at that
        # point, so the next address is a first attempt rather than a replay.
        #
        # The last address is outside the loop rather than inside it, so its
        # failure is raised as it stands and there is no arm for a case
        # `_admitted` has already refused: it raises rather than answering with
        # nothing, so this is never empty.
        for address in addresses[:-1]:
            try:
                return await transport.handle_async_request(
                    self._pinned(request, name, address)
                )
            except (httpx.ConnectError, httpx.ConnectTimeout):
                logger.info("%s did not answer at %s, trying the next", name, address)
        return await transport.handle_async_request(
            self._pinned(request, name, addresses[-1])
        )

    def _pinned(
        self, request: httpx.Request, name: str, address: str
    ) -> httpx.Request:
        """The same request, addressed to a literal, still speaking as the name.

        A second request rather than a rewrite of the caller's, because
        `httpx.AsyncClient` sets `response.request` to the object it was given
        and `_same_host_hop` compares a `Location` against that URL.
        """
        return httpx.Request(
            request.method,
            request.url.copy_with(host=address),
            headers=request.headers,
            # `stream=` rather than `content=`, because it is the arm of
            # `httpx.Request.__init__` that populates no headers of its own: the
            # `Host` this carries is the one built from the name, and rebuilding
            # it from the pinned URL is exactly what must not happen.
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": name},
        )

    async def _admitted(self, name: str, port: int) -> tuple[str, ...]:
        """The addresses this request may be made to, in order. Refuses if none.

        **Resolved here and nowhere else.** What this returns goes into the URL
        as a literal, and httpcore resolves a literal to itself, so the answer
        classified is the answer connected to.
        """
        try:
            ipaddress.ip_address(name)
        except ValueError:
            candidates = await self._lookup(name, port)
        else:
            # A literal reaches no resolver, in this transport or in httpcore,
            # so it is classified as it stands. Without this arm every literal
            # address would go to `getaddrinfo`, which answers it back, at the
            # cost of a syscall and of a code path that is not the one read.
            candidates = (name,)

        admitted = tuple(
            address for address in candidates if self._policy.permits(address)
        )
        if not admitted:
            logger.warning(
                "Refused %s under the %s address policy: %s",
                name,
                self._policy.name,
                ", ".join(candidates) or "no address",
            )
            raise AddressRefused(
                f"{name[:200]} answers at no address this server will connect to"
            )
        return admitted

    async def _lookup(self, name: str, port: int) -> tuple[str, ...]:
        """The resolver's answer, with a lookup failure kept inside `httpx`.

        **`OSError` is caught because `socket.gaierror` is not an
        `httpx.HTTPError`.** Resolution used to happen inside
        `httpx.AsyncHTTPTransport`, under `map_httpcore_exceptions`, which
        turned a name that does not resolve into a `ConnectError`; doing it here
        moved it outside every handler in this tree, so a typo in a settings
        field became a 500 rather than "that server did not answer". Same shape
        as the `UnicodeError` `_walk_hops` records, and found the same way.

        Raised as the error httpx itself would have raised, so a lookup failure
        stays distinguishable from a refusal: `AddressRefused` means an admin's
        address is one this door will not open, and this means nobody answered
        for the name.
        """
        try:
            return tuple(await self._resolve(name, port))
        except OSError as unresolvable:
            raise httpx.ConnectError(
                f"{name[:200]} could not be resolved"
            ) from unresolvable

    def _transport_for(self, name: str) -> httpx.AsyncBaseTransport:
        """The pool for one server name. See the class docstring for why per name."""
        transport = self._inner.get(name)
        if transport is None:
            transport = self._inner[name] = self._inner_factory()
        return transport

    async def aclose(self) -> None:
        for transport in self._inner.values():
            await transport.aclose()
        self._inner.clear()


def pinned_client(
    policy: AddressPolicy, *, resolver: Resolver = system_resolver
) -> httpx.AsyncClient:
    """A catalogue client that resolves, refuses by address class, and pins.

    Every bound `catalogue_client` carries, plus `PinnedTransport`. Use it for a
    door whose host is configuration rather than a module constant.

    **`trust_env=False`, and it is the difference between a pin and a
    suggestion.** With it on, httpx reads `HTTP_PROXY`, `HTTPS_PROXY` and
    `ALL_PROXY` from the environment and mounts a proxy transport **in front of
    the one passed here**, so every request would leave through the proxy with
    the name unresolved and none of this would run. It also stops a `.netrc`
    putting credentials on a request this door makes.

    **The belt is httpx's own `allow_env_proxies = trust_env and transport is
    None`**, which already refuses an environment proxy for any client given a
    transport. This flag is the brace, and it is the half that survives somebody
    dropping the explicit `transport=` in a refactor. Both are here because
    either alone is one edit from nothing.

    **So no test can see this flag move, and that is measured rather than
    assumed.** Flipping it to `True` was caught by nothing, including the test
    named for it, because that test asserts the property (the request still
    leaves through this transport with a proxy set in the environment) and the
    belt alone satisfies it. The flag sits at the "stated" rung deliberately: a
    test that could tell it apart would have to assert the argument rather than
    the behaviour, which is a guard on an implementation detail of httpx.

    **This says nothing about the app's other outbound doors.**
    `catalogue_client` trusts the environment, so the eleven seeded catalogues
    still honour a proxy variable, which is the right answer for a host that is
    a module constant.
    """
    return _client(transport=PinnedTransport(policy, resolver=resolver), trust_env=False)


def _client(
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    trust_env: bool = True,
) -> httpx.AsyncClient:
    """The settings both clients share, in one place so they cannot drift."""
    return httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS,
        follow_redirects=False,
        headers=_IDENTITY | _AGENT,
        transport=transport,
        trust_env=trust_env,
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
    somebody on the path can rewrite, which is the position `targets.SEEDED[CatalogueSource.LOC].base_url` is
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
    credential: Credential | None,
) -> Fetched:
    """The redirect walk and the capped read. Time is `get`'s problem, not this.

    Split out so the budget is enforced in exactly one place, around this whole
    call, rather than recomputed at each step. Recomputing was the bug: see
    `get`.

    **The credential is asked for a header per hop, never carried on the
    client.** `_same_host_hop` already refuses a hop that leaves the host, so on
    this module's own rules the question never arises; it is asked anyway
    because the two guards defend different losses. A redirect that leaks a page
    is an information leak, and that is this module's to refuse. A redirect that
    carries an `Authorization` header off host is account theft, and
    `Credential.header_for` refuses it whatever happens here: set on the client
    the header would be attached by httpx to whatever the client is next used
    for, which is precisely the arrangement neither guard could see.
    """
    target = url
    query = params

    for _ in range(MAX_REDIRECTS + 1):
        headers = credential.header_for(target) if credential is not None else {}
        try:
            async with client.stream("GET", target, params=query, headers=headers) as response:
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
            # That is not cosmetic. Eight of the thirteen `try` blocks wrapping
            # a call into this module catch `(httpx.HTTPError,
            # ElementTree.ParseError)` and would have let it through: one
            # hostile source 500s the whole `GET /api/books/search` instead of
            # being dropped, and `targets.SEEDED[CatalogueSource.LOC].base_url` is
            # plaintext HTTP, so forging it
            # needs no TLS.
            #
            # **The unit is the `try` block, not the call**, because the handler
            # is what decides whether this escapes. Thirteen blocks, all in
            # `metadata.py`, wrap fourteen of the sixteen call expressions
            # across `metadata.py` and `google_books.py`; the other two are
            # covered by a `gather` and by a caller. Counted by walking both
            # trees, 2026-08-27.
            #
            # Neither uncovered call is exposed. `_open_library_author_names`
            # runs its `fetch.get` inside `asyncio.gather(...,
            # return_exceptions=True)` and drops a `BaseException` result, so
            # one author record failing costs that author's name.
            # `google_books.py`'s single call is caught a frame up, by
            # `metadata._google_books`'s `except (httpx.HTTPError, ValueError)`
            # around `lookup_by_isbn`.
            #
            # The pair this replaced said "six of the ten": a pre-change
            # denominator under a post-change numerator, with no unit stated
            # either way.
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
    credential: Credential | None = None,
) -> Fetched:
    """GET a catalogue, bounded four ways.

    At most `limit` bytes, at most `MAX_REDIRECTS` hops, none of them leaving
    the host, and all of it inside `deadline`.

    **`credential` is offered to every hop and attached by none of them but its
    own.** It is a login at a catalogue this deployment holds on an
    institution's behalf, and the rule that it never leaves the origin it was
    set for is the secret's rather than this module's: see
    `credentials.Credential.header_for`, and `_walk_hops` for why both guards
    exist.

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
            return await _walk_hops(client, url, params, cap, credential)
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
    credential: Credential | None = None,
) -> Fetched:
    """One bounded GET, with a client of its own."""
    async with catalogue_client() as client:
        return await get(
            client,
            url,
            params=params,
            limit=limit,
            deadline=deadline,
            credential=credential,
        )
