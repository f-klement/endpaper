"""One reader for the self hosted OPDS servers, and it runs here rather than in the browser.

**This is the documented exception to the rule that a member's library is parsed
in the browser, and it is not a contradiction of it.** That rule is about
**files**: never receive, never store, never serve somebody's book. An OPDS feed
is a **catalogue**, not a file, so there is nothing to avoid storing. Two
concrete reasons put it on this side:

* **CORS.** A browser cannot fetch a host that sends no permissive headers, and
  a self hosted library server almost never does. A browser side reader would
  fail on the ordinary case and work only where somebody had configured their
  server for us.
* **This shape already exists here.** A remote catalogue answering over HTTP,
  with a deadline, a byte cap and a redirect policy, is exactly what `fetch.py`
  models. See `docs/decisions.md`.

## What this reads, and the census that decided it

**Holdings, and a title and an author. Nothing else.** Owner's decision of
2026-09-05, taken against a census rather than against the specification: nine
self hosted candidates, two serve no OPDS, and the Atom serialiser of all seven
that do was read. **Not one emits an identifier of any kind**, although OPDS 1.2
provides the element and its own example shows an ISBN. Series arrives in three
shapes across those seven and none of them is a field.

So this establishes **what a member owns**. What they own is then described by
the catalogue chain that already supplies a description, which is what that
chain is for. There is no per server JSON adapter here and there is deliberately
not the cheap Calibre exception, whose own API sits on the same port under the
same authentication and does carry the ISBN: taking it would set the precedent
that grows one adapter at a time.

**The bound on that census**: it covers the candidates named on the ticket, not
deployed OPDS at large. A server outside the set may emit an identifier, so
`entry_record` reads one where it finds one rather than asserting there is none.

## What is refused, and which range refusal this door does and does not take

The address is typed by an admin, so this is a request forgery shape and is
treated as one. The address policy the typed catalogue host design requires is
**an address range refusal after resolution**, and this door now takes it, in
the one form that is worth taking: `fetch.HOUSEHOLD_ADDRESSES`, applied by
`fetch.pinned_client`, which resolves the name once, refuses the address by its
class, and connects to that same address rather than looking it up again.

**Two of the three private ranges are admitted, and that is the whole shape of
this row.** A household's own OPDS server is on the household's own network, so
`http://10.0.0.10:8083` and `http://localhost:8083` are the ordinary case rather
than the attack: refusing loopback or RFC 1918 would refuse the feature.
**Link local is refused**, because it is the one range that is never a
household's own server and is where the cloud metadata endpoint sits. So are
multicast, the unspecified address, and every range nobody enumerated, which
`fetch.AddressClass.RESERVED` collects.

**Refusing the literal was considered and refused, twice, and the second time it
was the owner's call.** A range test on the URL text is walked past by any name
that resolves into the range, which is a bound that guards the accident and not
the attacker. What makes the refusal above worth writing down is that the
address it classified is the address connected to, so no second lookup is left
to move it.

What is enforced, all of it by construction:

| bound | where |
|---|---|
| http or https, no userinfo, a parseable port | `is_fetchable`, over the address and over every paging link |
| **the address connected to is one the policy admits** | `fetch.HOUSEHOLD_ADDRESSES`, per request |
| **no byte of any response may move the origin** | `_next_page`, against the configured origin |
| a redirect may not leave the host | `fetch._same_host_hop` |
| the login is attached to that origin and no other | `credentials.Credential.header_for` |
| at most `fetch.MAX_RESPONSE_BYTES` per page, counted raw | `fetch.get` |
| at most `fetch.TIMEOUT_SECONDS` on one page | the `min` in `holdings`, not `fetch.get`'s own default |
| a whole sync deadline, a page cap, an entry cap | `holdings` |

**The seventh row names where the bound is applied rather than the constant it
comes from, and that is the correction a critic made rather than a style
choice.** It read `fetch.TIMEOUT_SECONDS`, which is not what bounded a page
here: `fetch.get` treats a deadline it is given as the whole budget, so a walk
handing it the sync deadline left the per request bound unapplied while the
table claimed it.

**The origin pin and the address policy answer two different questions, and
neither replaces the other.** The origin is fixed when an admin saves the server
and is never re-derived: a paging link is resolved against the page it came from
and then compared to the configured origin, so no byte of any response can walk
this server onto a second host. The address policy is about the address an admin
**types**, which nothing in a response chose.

**What an admin can still aim this at, with both applied.** Any machine on the
household's own network, which is the feature: `http://10.0.0.1/` is a router's
administration page and this will fetch it. Any public address, including one
whose host proxies inward, which no address policy can see. What they can no
longer aim it at is link local, whether they type `169.254.169.254` or a name
that resolves there, and `tests/test_opds.py::TestNoResponseMovesTheOrigin`
carries that address by name.

**Nothing here bounds what a member can start**: configuration is admin only, but
a member's sync is what makes the request. The response is never echoed, its
status code is, and titles parsed out of it are.

**An entry this reader passes over is counted and reported, and there are two
kinds.** An OPDS entry is a book only if it carries a link relation that says
the member holds it: see `HOLDING_RELS`, which admits two of the six the
specification defines. Everything else is a link to another feed, such as a
shelf index, or an entitlement rather than a holding, such as a title the server
offers to sell or lend. Both are counted together and reported as
`entries_not_held`, so somebody who pointed this at the wrong feed sees why
nothing arrived. **The navigation tree is deliberately not crawled**: a crawl
needs its own bounds on breadth, on cycles and on an entry reached twice, and
the ticket asks for a library rather than a spider.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

import httpx

import fetch
import isbn as isbn_module
import metadata
from catalogue import Record
from credentials import Credential, origin_of
from decoders import Decoding, Reader

logger = logging.getLogger("endpaper.opds")

#: The Atom namespace every OPDS 1.x feed is written in.
ATOM: Final = "{http://www.w3.org/2005/Atom}"

#: The link relations that say the member **holds** this book.
#:
#: **A closed set of two, and the four it leaves out are the whole point.** OPDS
#: defines six acquisition relations and they do not make one claim. The generic
#: one and `/open-access` say the file is there to be taken. `/borrow` is a
#: lending entitlement, `/buy` is an offer of sale, `/subscribe` is a
#: subscription and `/sample` is an excerpt, and **not one of those is a
#: holding**. This route's only assertion is ownership, so recording a title
#: somebody may buy as one they own is the assertion being wrong rather than
#: thin.
#:
#: **Enumerating what is admitted rather than what is refused**, which is the
#: direction `targets.TitleQuery` gives the reason for: a relation added to the
#: specification later is refused by construction instead of being admitted by a
#: prefix nobody revisited. The cost is a support conversation; the cost the
#: other way is a catalogue that says a household owns a shop's stock.
#:
#: The self hosted servers this reader was built for all serve the generic
#: relation.
HOLDING_RELS: Final = frozenset(
    {
        "http://opds-spec.org/acquisition",
        "http://opds-spec.org/acquisition/open-access",
    }
)

#: What this reader labels the records it produces.
#:
#: One label for every OPDS server rather than one per configured row.
#: `catalogue.Record.source` names which kind of thing said it, and a household
#: with two servers has two rows and one serialisation.
SOURCE: Final = "opds"

#: The one URN prefix `_entry_isbn` strips. Lower case, and compared against a
#: lower cased prefix of the value, because a URN's scheme is case insensitive.
_ISBN_URN: Final = "urn:isbn:"

#: The decoding `entry_record` is handed, and the whole of what it is told.
#:
#: Built here rather than off a row, which is `decoders.py`'s own test of the
#: seam: no address, no transport, no handle. A fixture on disk decodes through
#: exactly this object.
DECODING: Final = Decoding(source=SOURCE, reader=Reader.OPDS_ATOM)

#: How many pages of one feed a sync will walk.
#:
#: **Not the bound that bites a hostile server**, which is the deadline below.
#: This is the bound on an honest large one: Calibre-Web pages its OPDS at 60
#: entries, so 200 pages is 12,000 entries of paging for a `MAX_ENTRIES` of
#: 10,000, and the entry cap is reached first on any feed with a full page.
#: Pages are walked one at a time, so the peak cost is one page rather than 200.
MAX_PAGES: Final = 200

#: How many entries one sync will take from a feed.
#:
#: A household library rather than an institution's. `marc.MAX_RECORDS` is
#: 20,000 for an uploaded file, and this is half of it because a page is fetched
#: rather than read off disk: the wire cost is `MAX_PAGES` requests and the
#: write cost is one `Book` per entry.
MAX_ENTRIES: Final = 10_000

#: The wall clock a whole sync may spend fetching, redirects and bodies included.
#:
#: **The bound that actually bites a hostile server.** Each page is held to
#: `fetch.TIMEOUT_SECONDS`, 10 seconds, and `MAX_PAGES` alone would let a server
#: trickling just inside that limit hold a worker for 2,000 seconds. Twelve
#: pages at that per request limit fit inside this, and a real server answers a
#: page in well under a second.
#:
#: **The per page bound is applied at the call rather than inherited**, because
#: `fetch.get` treats a supplied deadline as the whole budget: see the `min` in
#: `holdings`, without which this constant was the only bound on one page and
#: the table in this module's docstring claimed one that did not exist.
#:
#: Spent on the fetching only. The applying is a separate cost and is bounded by
#: `MAX_ENTRIES` rather than by a clock, because a half applied import is worse
#: than a slow one.
SYNC_DEADLINE_SECONDS: Final = 120


class OpdsError(Exception):
    """Anything this module refuses to do, or cannot finish."""


class UnusableAddress(OpdsError):
    """The address is not one this server will open a connection to.

    Raised before any request is made, and raised again for a paging link that
    would leave the configured origin.
    """


class FeedUnreadable(OpdsError):
    """The bytes came back and they are not an OPDS feed this reader can read."""


def is_fetchable(url: str) -> bool:
    """Whether this server may open a connection to this address.

    **A different rule from `covers.is_fetchable`, and the difference is who
    chose the host.** There the host arrives on a book from any signed in
    member, so it is tested against an allowlist. Here it is typed by an admin
    and is a machine on their own network, so there is no list to test against
    and the module docstring says what stands in place of one.

    Refused, in this order: an address that cannot be parsed at all, a scheme
    that is not http or https, a port that is not a number or is out of range,
    an address carrying credentials, and an address with no host.

    **The credentials case is the one that matters most here**, for #131's
    reason: an admin reads back what they typed, and
    `http://calibre.home.example@evil.test:8083/opds` reads as the household's
    own server to a person and resolves to `evil.test` in every client. The
    login this deployment holds is bound to an origin computed from the same
    string, so a credential would not follow it, but the request would.

    **The parse is inside the `try` and that is not defensive habit**, for
    `covers.is_fetchable`'s measured reason: `urlsplit` raises on an
    unterminated IPv6 literal, and `.port` is a lazy property that raises on a
    port that is not a number or is out of range. A stored
    `http://host:99999/opds` would otherwise 500 every sync of that row, for
    good, with nothing naming the cause.

    **http is admitted and https is not required.** Every one of these servers
    is reachable over plaintext on a home network and most are configured that
    way. What that costs is stated where it is paid: the login travels in a
    `Authorization: Basic` header, so an admin choosing http is choosing to send
    it over their own LAN in the clear. A downgrade cannot be forced on them,
    because scheme is part of the origin every later hop is compared to.
    """
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if parsed.username or parsed.password:
        return False
    if port is not None and not 0 < port < 65536:
        # `urlsplit.port` raises for most of these rather than returning them,
        # so this arm is the belt: a parser that starts answering instead of
        # raising must not widen what is admitted.
        return False
    return bool(parsed.hostname)


def _text(node: ElementTree.Element | None) -> str | None:
    """One element's text, stripped, or None where there is nothing in it."""
    if node is None or node.text is None:
        return None
    value = node.text.strip()
    return value or None


def _authors(entry: ElementTree.Element) -> str | None:
    """Every credited author, joined the way this application stores a credit list.

    **Joined with a comma, which is what `importing.identity_key` splits on and
    what `Book.author` holds elsewhere.** Atom gives each author its own
    `<author><name>` element, so the join happens here or it happens at three
    call sites.

    An `<author>` with no usable `<name>` is dropped rather than contributing an
    empty segment, because `", , Jane Doe"` is a credit list nobody wrote.
    """
    names = [
        name
        for author in entry.findall(f"{ATOM}author")
        if (name := _text(author.find(f"{ATOM}name")))
    ]
    return ", ".join(names) or None


def _is_held(entry: ElementTree.Element) -> bool:
    """Whether this entry is a book the member holds.

    **Two rules in one test, and both are refusals this route needs.** It stops
    a shelf index becoming a book: a navigation entry such as "Recently added"
    is a perfectly well formed Atom entry with a title and no acquisition link,
    and a reader that took every entry would file the shelf names as books on
    the first sync. And it stops an entitlement becoming a holding: see
    `HOLDING_RELS` for why `/borrow` and `/buy` are not in it.
    """
    # **An exact match, and a `.strip()` here was tried and removed.** It was
    # added to keep the one case the prefix rule tolerated, a trailing space,
    # and it also admitted a **leading** space, which the prefix rule refused
    # and which XML attribute value normalisation preserves in a CDATA
    # attribute. So it widened the rule in a direction its own comment did not
    # name, which is the tell this repository records: the code is defensible
    # and the stated reason is wrong. No surveyed server writes a padded `rel`.
    return any(
        (link.get("rel") or "") in HOLDING_RELS
        for link in entry.findall(f"{ATOM}link")
    )


def _entry_isbn(entry: ElementTree.Element) -> str | None:
    """An ISBN this entry names, where it names one at all.

    **The census says none of the seven surveyed servers emits one**, and this
    reads one anyway, because that census covers those candidates rather than
    deployed OPDS at large and the specification does provide the element. A
    server outside the set that fills it in gets the better of the two matching
    rules for free.

    **A `urn:isbn:` prefix is stripped and nothing else is.** That is the URN
    form the specification's own example writes, and `isbn.parse` refuses it
    outright because the letters make it not an ISBN. Stripping is confined to
    this one prefix rather than "the part after the last colon", because the
    second admits the tail of every other URN scheme as a candidate and this
    admits none: `urn:uuid:...` and `calibre:1417` reach `isbn.parse` whole and
    are refused there.

    Every candidate goes through `isbn.parse`, which normalises, validates the
    check digit and answers the canonical ISBN-13, so a `dc:identifier` holding
    a UUID, a file path or a row id contributes nothing. That is the whole of
    the trust placed in this field: it is either thirteen digits that check, or
    it is absent.
    """
    for tag in (
        "{http://purl.org/dc/terms/}identifier",
        "{http://purl.org/dc/elements/1.1/}identifier",
    ):
        for node in entry.findall(tag):
            raw = _text(node) or ""
            if raw[: len(_ISBN_URN)].lower() == _ISBN_URN:
                raw = raw[len(_ISBN_URN) :]
            found = isbn_module.parse(raw)
            if found is not None:
                return found
    return None


def entry_record(entry: ElementTree.Element, decoding: Decoding) -> Record | None:
    """One OPDS entry as a `catalogue.Record`, or None for one this reader refuses.

    A decoder in `decoders.py`'s sense: it is told a parsed record and a
    `Decoding`, and it is never told how the bytes arrived. Nothing here names a
    URL, a status code or a server.

    Refused, and each is a `None` rather than an exception because one bad entry
    must never cost a feed:

    * an entry carrying no holding relation, which is a link to another feed or
      an entitlement rather than a book;
    * an entry with no usable title, which is nothing this application can file.

    **A title too long for the column is not refused here and comes back as a
    record naming nothing.** `catalogue.Record.__post_init__` drops a scalar the
    column cannot hold rather than cutting it, because half a title is an
    assertion nobody made, and that rule belongs to the record rather than to
    any one decoder. `importing.OpdsImport` counts what arrives that way as
    skipped, which is where a person can see it.

    **Three fields and no fourth, and the absences are the measurement.** Series
    is not read because across the four servers of one lineage it is prose
    inside a description element, in another it is folded into the title string,
    and in a third it is absent: none of the three is a field, and guessing at
    prose is the enumerating shape this repository refuses. Publisher, year,
    language and page count are absent from the surveyed serialisers. The
    description this application shows comes from the catalogue chain, which is
    what that chain is for.
    """
    if not _is_held(entry):
        return None
    title = _text(entry.find(f"{ATOM}title"))
    if title is None:
        return None
    return Record(
        source=decoding.source,
        title=title,
        author=_authors(entry),
        isbn=_entry_isbn(entry),
    )


#: Which decoder reads one entry, by `decoders.Reader`. The import family's
#: dispatch table, and `read_page` indexes it.
#:
#: **Indexed rather than declared, and the difference is what the guard over it
#: is worth.** The first version called `entry_record` directly and kept this
#: beside it, which made `tests/test_classifications.py`'s shape walk satisfied
#: by any `{Reader: callable}` nothing calls: point `read_page` at a different
#: decoder and the table went on naming this one with nothing red. Indexing it
#: also makes `Decoding.reader` load bearing, so a decoding naming a
#: serialisation this module does not read raises here instead of being decoded
#: as Atom in silence.
READERS: Final[dict[Reader, Callable[[ElementTree.Element, Decoding], Record | None]]] = {
    Reader.OPDS_ATOM: entry_record,
}


@dataclass(frozen=True)
class Page:
    """One page of a feed: the books on it, and where the next one is."""

    records: tuple[Record, ...]
    #: Entries this reader passed over: a link to another feed, or an
    #: entitlement rather than a holding. Counted so that pointing this at the
    #: wrong feed reports why nothing arrived. See `HOLDING_RELS`.
    not_held: int
    #: The `href` of `<link rel="next">` exactly as the feed wrote it, before it
    #: has been resolved or checked. `_next_page` does both.
    next_href: str | None


def read_page(body: str, decoding: Decoding = DECODING) -> Page:
    """One feed document as records and a paging link.

    **The doctype refusal is `metadata.DOCTYPE`, imported rather than spelled
    again**, for `marc.py`'s reason: it is the same construct refused for the
    same reason, and two spellings let one be tightened while the other stays.
    `xml.etree` expands internal entities, so a body carrying a doctype can
    define an entity worth many times its own bytes and `fetch.MAX_RESPONSE_BYTES`
    stops bounding the cost. Measured on this project's CPython 3.14.0 with
    libexpat 2.6.3, on the control plane node: a body of exactly 2,097,152
    bytes, the fetch cap, carrying ten characters nested seven deep, parses to
    100,000,000 characters with a **699.1 MB traced peak in 10.21 seconds**, and
    expat's own amplification guard does not fire. The pod limit is 512Mi.

    No OPDS server sends a doctype; Atom does not use one.

    Raised as `FeedUnreadable` rather than as a `ParseError`, because this
    module's caller is a route rather than a search fan out and the whole sync
    fails: there is no other source to answer from.
    """
    if metadata.DOCTYPE in body:
        raise FeedUnreadable("Refused a feed carrying a document type declaration.")
    try:
        root = ElementTree.fromstring(body)
    except (ElementTree.ParseError, ValueError) as error:
        # `ValueError` as well, for `marc._parsed`'s measured reason:
        # `ElementTree.fromstring` raises it, not `ParseError`, for a declared
        # multi-byte encoding, and without this arm that is a 500.
        raise FeedUnreadable(f"That address did not answer with a feed: {error}") from error
    if root.tag != f"{ATOM}feed":
        raise FeedUnreadable(
            "That address answered with XML that is not an Atom feed."
        )

    records: list[Record] = []
    not_held = 0
    for entry in root.findall(f"{ATOM}entry"):
        if not _is_held(entry):
            # **Counted here rather than from `entry_record` answering None**,
            # which is what this loop did first and was wrong: that function
            # refuses an entry that is not a holding and an unreadable book
            # entry alike, so a feed of a hundred untitled books reported a
            # hundred entries not held and told the reader they had pointed at
            # the wrong feed.
            not_held += 1
            continue
        # Through `READERS`, never `entry_record` by name: see that table.
        record = READERS[decoding.reader](entry, decoding)
        if record is not None:
            records.append(record)

    next_href = None
    for link in root.findall(f"{ATOM}link"):
        if (link.get("rel") or "") == "next":
            next_href = (link.get("href") or "").strip() or None
            break

    return Page(records=tuple(records), not_held=not_held, next_href=next_href)


def _next_page(here: str, href: str, origin: str) -> str:
    """The paging link, resolved and held to the origin the admin configured.

    **This is the half the address policy does not cover.** The first address is
    an admin's and `fetch.HOUSEHOLD_ADDRESSES` is what refuses it by range;
    every address after it is written by whatever answered, and this is the only
    place a response gets to choose where the next request goes. It does not get
    to, and it would not get to even if the policy admitted the range it named.

    Resolved against the page it was written on, because a feed is free to write
    `?page=2`, then compared to the origin computed from the address that was
    **configured**, not from the page in hand: comparing against the previous
    hop would let a chain walk one host at a time.
    """
    there = urljoin(here, href)
    if not is_fetchable(there) or origin_of(there) != origin:
        logger.warning("Refused an OPDS paging link off %s", origin)
        raise UnusableAddress(
            "That feed's next page is at a different address than the server "
            "this library was told about."
        )
    return there


@dataclass(frozen=True)
class Holdings:
    """What one walk of one feed found."""

    records: tuple[Record, ...]
    pages_read: int
    #: See `Page.not_held`, summed over the walk.
    not_held: int
    #: Whether a cap or the deadline stopped the walk before the feed ran out.
    truncated: bool


async def holdings(
    base_url: str,
    *,
    credential: Credential | None = None,
    max_pages: int = MAX_PAGES,
    max_entries: int = MAX_ENTRIES,
    deadline_seconds: float = SYNC_DEADLINE_SECONDS,
    resolver: fetch.Resolver = fetch.system_resolver,
) -> Holdings:
    """Walk one acquisition feed and answer what it says the member holds.

    **Sequential, deliberately.** `metadata.search` fans out because it asks
    eight different catalogues one question; this asks one server for page after
    page of the same answer, and a fan out would put the household's own server
    under a burst it never asked for while multiplying the peak by the width.
    One page at a time makes the memory peak one page.

    **The deadline is on the whole walk and not per request**, for `fetch.get`'s
    measured reason: a per request timeout multiplied by a page count is not a
    bound anybody would accept written down as one.

    **A repeated page ends the walk rather than spending the cap on it.** A feed
    whose `next` points at itself, or at a page already read, is a loop, and
    `max_pages` would turn it into 200 requests to the household's own server
    before answering with one page's worth of books.

    Refuses rather than degrades: every caller here is a route acting on one
    address a person just chose, so "this server is unavailable" is the answer
    they need rather than an empty import that looks like success.

    **`resolver` is a seam and never a policy.** It says who answers the name,
    not which answers are admitted, so a caller cannot widen what this door
    connects to by passing one: `fetch.HOUSEHOLD_ADDRESSES` is applied to
    whatever comes back. It exists because a test of the rebinding case has to
    answer differently on the second call, and because no test in this tree may
    make a real lookup.
    """
    if not is_fetchable(base_url):
        raise UnusableAddress(
            "That is not an address this server will fetch. An OPDS feed is an "
            "http or https address carrying no username or password."
        )
    origin = origin_of(base_url)
    if not origin:
        # `is_fetchable` parses with `urlsplit` and this parses with `httpx.URL`,
        # and the two disagree on ports written with an underscore and on some
        # IDN forms: see `credentials.origin_of`. An address only one of them can
        # read binds no credential and pins no origin, so it is refused here
        # rather than walked with an origin of "".
        raise UnusableAddress("That address cannot be used as a server's identity.")

    ends = time.monotonic() + deadline_seconds
    found: list[Record] = []
    not_held = 0
    pages = 0
    truncated = False
    seen: set[str] = set()
    target: str | None = base_url

    # **The pinned client, not `fetch.catalogue_client`.** The seeded catalogues
    # use that one because their host is a module constant; this address is
    # typed, so the name is resolved once, the address is classified against
    # `fetch.HOUSEHOLD_ADDRESSES`, and the connection is made to that same
    # address. Swapping this line for `catalogue_client` puts the range refusal
    # back to nothing while every other bound still reads as present.
    async with fetch.pinned_client(
        fetch.HOUSEHOLD_ADDRESSES, resolver=resolver
    ) as client:
        while target is not None:
            if pages >= max_pages or len(found) >= max_entries:
                truncated = True
                break
            if time.monotonic() >= ends:
                truncated = True
                break
            seen.add(target)

            try:
                answer = await fetch.get(
                    client,
                    target,
                    # **Both bounds, and the smaller one wins per page.**
                    # `fetch.get` takes one deadline and treats a supplied one
                    # as the whole budget, so handing it `ends` alone would let
                    # a single page spend the entire sync: the per request bound
                    # this module claims would exist only as
                    # `catalogue_client`'s per socket operation timeout, which
                    # bounds a read and not a request. Found by a critic reading
                    # the bounds table against `fetch.py:497`.
                    deadline=min(ends, time.monotonic() + fetch.TIMEOUT_SECONDS),
                    credential=credential,
                )
            except fetch.AddressRefused as refusal:
                # Ahead of the `httpx.HTTPError` arm below, which this is a
                # subclass of. A refused address is a fact about the address an
                # admin configured rather than about the server being down, and
                # the two need different messages: "unavailable" would send
                # somebody looking for a server that answered fine.
                logger.warning("OPDS feed at %s is at a refused address: %s", origin, refusal)
                raise UnusableAddress(
                    "That server is at an address this library will not connect to."
                ) from refusal
            except httpx.HTTPError as refusal:
                # `fetch.FetchRefused` is an `httpx.HTTPError` on purpose, so
                # one arm covers this module's four bounds and every transport
                # failure underneath them.
                #
                # **The message names the failure and never the address.**
                # `fetch`'s four refusals all format `{url[:200]}` and
                # `RedirectedOffHost` adds the host it was sent to, and this
                # error reaches a member as a 502 detail while the address is
                # otherwise admin only: a sleeping server is the case a member
                # will actually hit. The address goes to the log, where the
                # person who configured it can read it.
                logger.warning("OPDS feed at %s could not be read: %s", origin, refusal)
                raise OpdsError(
                    "That server did not answer with a feed this library could read."
                ) from refusal
            if answer.status_code >= 400:
                # 401 is the ordinary one and it is the message a person acts
                # on, so the status is named rather than folded into "failed".
                raise OpdsError(
                    f"That server answered {answer.status_code} for its feed."
                )

            page = read_page(answer.text)
            pages += 1
            not_held += page.not_held
            taken = page.records[: max_entries - len(found)]
            found.extend(taken)
            if len(taken) < len(page.records):
                truncated = True

            if page.next_href is None:
                break
            following = _next_page(target, page.next_href, origin)
            if following in seen:
                break
            target = following

    return Holdings(
        records=tuple(found),
        pages_read=pages,
        not_held=not_held,
        truncated=truncated,
    )
