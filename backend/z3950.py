"""One door for the Z39.50 requests this app makes, and every bound on them.

**A second transport beside `fetch.py`, not an extension of it.** `fetch.py` is the
single door for HTTP and everything it enforces is HTTP shaped: a cap counted on
`aiter_raw` chunks, a per request deadline around a redirect walk, a refusal of any hop
that leaves the host, and a refusal of a content encoding nobody asked for. Z39.50 has no
redirects, no content encoding and no chunked reads, so two of those four have no
equivalent here and the other two need building rather than importing.

What this module owes a caller is the property that makes `fetch.py` worth having: the
bounds arrive **by construction**, so no call site has to remember to ask.

| `fetch.py` | Here |
|---|---|
| `MAX_RESPONSE_BYTES`, on raw chunks | `MAX_RESPONSE_BYTES`, on record bytes, and `MAX_RECORDS` |
| `TIMEOUT_SECONDS` under one `asyncio.timeout` | one absolute deadline held by the association |
| `MAX_REDIRECTS` and the same host walk | nothing: the protocol has no redirect |
| `UnrequestedEncoding` | nothing: the protocol has no content encoding |
| `catalogue_client()` | `association()` |
| every refusal is an `httpx.HTTPError` | every refusal is a `Z3950Error` |

**The client is behind a seam and is not chosen yet.** `Session` and `Client` are the
whole of what a client has to be, and every bound is enforced on this side of them. The
one client that exists today is `z3950_provisional.py`, and its name is the status it
has: it exists so this module can be exercised and the Library of Congress control can be
checked, not because a route has been picked.

**Three dispositions, and the survey conflated two of them once already.**

| Disposition | What it is | How it arrives |
|---|---|---|
| **unreachable** | nothing answered | `Unreachable` |
| **refused** | the target answered, and said no | `Refused`, carrying the code |
| **answered nothing** | the target answered, and held nothing | `Answer(hits=0, records=())` |

The third is a value and not an exception, because a catalogue that does not hold a book
is the ordinary case. Measured 2026-08-28, all three are live: `z3950.bne.es` accepts the
association and refuses every search with `[101] Access-control failure`; `z3950.dbc.dk`
answers `[2] Temporary system error, HTTP error: 400` behind all four database names it
knows; `lx2.loc.gov/LCDB` returns 0 hits for an ISBN it does not hold.

**A blocking client is the reason `Association` exists rather than a bare handle.**
Z39.50 clients are synchronous, so every call runs off the event loop, and a thread cannot
be cancelled. Three consequences, each of which has been measured as a real failure and
each of which is answered by the association owning one worker thread and one lock:

* an abandoned call is still using the connection, so **closing it from the loop thread
  frees memory a live thread is reading**: measured, a 0.05s deadline on a search to the
  Library of Congress left the process to be SIGKILLed at 40s where not closing returned
  at 0.40s;
* two coroutines sharing one association corrupt each other's result set, because a
  `Session` holds one: measured over eight runs, five bogus `Unreachable`, two
  `Answer(hits=0)` on a query that returns 444 serially, and one SIGSEGV;
* a timed out open still produces a session, and nothing was holding it: measured,
  `sessions built: 1, closed: [0]`, a connection and a socket for the life of the process.

**There is no host allowlist and there is deliberately no SSRF guard.** The reasoning is
`fetch.py`'s: a `Target` is built from module constants, never from anything a member
supplies, so there is no host an attacker gets to choose and nothing an allowlist would
refuse. **That property lives in the callers, not here**, and the day a `Target` is built
from stored configuration or from a request body, this module needs the allowlist
`covers.is_fetchable` already is for the other direction.
"""

import asyncio
import logging
import re
import time
import unicodedata
from collections.abc import AsyncIterator, Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Final, Protocol

logger = logging.getLogger("endpaper.z3950")

#: The wall clock budget for one whole association: the open, every search on it, and
#: every record.
#:
#: 10 seconds, the same figure `fetch.TIMEOUT_SECONDS` carries, and it is a ceiling on one
#: target rather than the budget a caller actually spends.
#: `metadata.SEARCH_DEADLINE_SECONDS` is 4.0 for a whole fan out and
#: `authority.DEADLINE_SECONDS` is 8.0, and a caller passes its own absolute `deadline`
#: to `association()`, which then holds it for everything done through it.
#:
#: **The association holds the clock, and that is what makes this sentence true.** An
#: earlier version bounded each call separately and claimed to bound the exchange, so the
#: recommended path, one open and three searches, admitted 10.0 four times over: 40.0
#: seconds under a constant that says 10. `authority.py` reached the same shape from the
#: same problem, and its comment is the one to read: one lookup shares one absolute
#: deadline.
#:
#: **A target that costs nothing to ask is not free to wait for.** Measured 2026-08-28
#: from a pod on the worker node: `lx2.loc.gov:210/LCDB` answers an ISBN in **0.561s**
#: end to end, while `libris.kb.se:210/libris` takes **10.7s** for the search alone on
#: `@attr 1=4 "moby dick"` and a further 2.3s for its first record. Sweden is therefore
#: outside this ceiling and was already outside the 4.0s fan out by 2.7x.
TIMEOUT_SECONDS: Final = 10.0

#: The most a target may answer with, counted on the records it hands over.
#:
#: The same 2 MiB `fetch.MAX_RESPONSE_BYTES` allows, so one hostile source costs the same
#: whichever transport it is reached over, and so the worst case `fetch.py` works out for
#: an eight source fan out does not have to be worked out twice. It is also the ceiling on
#: a caller supplied `limit`: a bound a caller can raise is not a bound.
#:
#: **Counted here because the protocol's own bound is advisory.** Z39.50 negotiates
#: `maximumRecordSize` and `preferredMessageSize` at Init, and a client should set both.
#: Measured 2026-08-28 with both set to 512, `lx2.loc.gov` returned a 2,227 byte record
#: and no diagnostic; at 1024 and at 4096 it returned the same 2,227. So the negotiation
#: is `accept-encoding: identity` all over again: worth sending, never worth trusting,
#: and the number that binds is the one this module counts.
#:
#: **What it does not bound, stated rather than pretended away.** A Present response is
#: one BER message and there is no chunked read to stop halfway, so a single record
#: larger than this is already in memory by the time it is counted. What keeps that
#: bounded is asking for few records: see `MAX_RECORDS`. Closing the gap properly needs a
#: client that can bound its own read off the socket, which is an input to choosing one.
MAX_RESPONSE_BYTES: Final = 2_097_152

#: The most records one `search()` may ask for.
#:
#: **Bounded by what a walk costs, because time is the only thing here that measures the
#: same twice.** Records are presented a position at a time, so a walk of N is N round
#: trips. Measured 2026-08-28 at `lx2.loc.gov:210/LCDB`, whose whole exchange for one
#: record is 0.561s, and stable to two decimal places across four option sets:
#:
#: | records | seconds of walk | of the 4.0s fan out |
#: |---|---|---|
#: | 5 | 0.62 | 15% |
#: | 10 | 1.30 | 33% |
#: | 20 | 2.70 | 68% |
#:
#: Those are the walk alone. End to end, `search_once` with `records=5` against the same
#: target measured 0.82s, 1.00s and 1.35s over three runs, the difference being the open
#: and the search.
#:
#: `metadata.SEARCH_DEADLINE_SECONDS` is 4.0 for the **whole fan out** across eight
#: sources, so 5 spends 15% of it on one target and 20 would spend two thirds. And
#: `_exchange` is all or nothing, so a walk that runs out of time discards every record
#: it already paid for.
#:
#: **What this is deliberately NOT bounded by.** A long walk can end in
#: `[13] Present request out of range`, and the position that happens at is not a limit
#: to design against: measured at records 43, 23, 11, 36 and **0** across five runs of
#: the identical request under four option sets, and it also appeared at record 0 on the
#: second search of a reused association, under a script that had opened about 25 of them
#: in 20 seconds. Paced, the same reuse ran 9 for 9 across three targets. So it tracks
#: load rather than position, a margin against a number that moved from 43 to 0 is not a
#: margin, and it arrives as `Refused`, which every caller already degrades on.
#: An earlier version of this comment quoted one of those readings as "the wall" and
#: derived a 7.2x margin from it, which is exactly the mistake `fetch.MAX_RESPONSE_BYTES`
#: records: sampling the tail rather than bounding it.
#:
#: The byte argument agrees and does not drive it: 5 times the fattest record measured,
#: LIBRIS at 32,565 bytes, is 162,825 bytes, or 7.8% of `MAX_RESPONSE_BYTES`. A future
#: target with fatter records hits the byte cap first, which is the right way round.
#:
#: **This is not what makes a large hit count cheap.** That is the protocol's: a search
#: answers with a count and no records, so `@attr 1=4 "moby dick"` costs the same at the
#: Library of Congress (444 hits) as at LIBRIS (350) as it would at fifty thousand.
MAX_RECORDS: Final = 5

#: The most a single search term may be, in characters.
#:
#: A title from a member is the only unbounded input that reaches a query, and PQF has no
#: length of its own. 300 is longer than any book title and short enough that a query
#: stays one line in a log.
MAX_TERM_CHARS: Final = 300

#: The most of a target's own words to repeat back in an exception message.
#:
#: A diagnostic is text from a third party and lands in a log line and an exception
#: string. `fetch.py` truncates a URL to 200 for the same reason. See `readable`.
MAX_DIAGNOSTIC_CHARS: Final = 200

#: BIB-1 use attributes, which is the attribute set every target measured defaults to.
#:
#: Named rather than spelled inline because the failure mode of a wrong one is silent:
#: #5 measured a wrong index returning 7,793,170 records under an HTTP 200 with no
#: diagnostic anywhere.
USE_TITLE: Final = 4
USE_ISBN: Final = 7

#: The two ways a budget runs out, spelled differently on purpose.
#:
#: Both raise `DeadlineExceeded`, because a caller wants one name to catch. But they are
#: not the same event: the first means nothing was ever asked, and the second means a
#: target was asked and did not finish. **Only the wording separates them, so it is
#: pinned by a test.** Removing the pre-flight check does not stop the timeout firing on
#: an already negative budget, so a test that asserts only the exception class passes with
#: the check deleted, and one that asserts the client was never called races the executor:
#: the call is submitted before the cancellation lands. Measured, that race went one way
#: in one mutation round and the other way in the next.
BEFORE_STARTING: Final = "ran out of time before starting"
STILL_ANSWERING: Final = "was still answering at the deadline"

_WHITESPACE = re.compile(r"\s+")

#: Unicode categories a search term may not contain, and the two reasons they are here.
#:
#: **Cc, because a NUL truncates the query at the C boundary.** Escaping cannot reach it:
#: a NUL is not whitespace, so collapsing leaves it, and the query crosses into the client
#: as a NUL terminated string. Measured, `moby\x00dick` built 21 characters and YAZ parsed
#: `@attr 1=4 moby`, which is the unbalanced quote failure reached without a quote. The
#: other control characters cannot truncate anything and are refused with it because the
#: hazard is the class rather than the character, and none of them means anything in a
#: search term.
#:
#: **Cs, because a lone surrogate raises `UnicodeEncodeError` inside the client**, on the
#: `.encode()` that hands the query over. That is not a `Z3950Error`, so it would escape
#: every caller's handler as a 500 rather than as a source being unavailable.
#:
#: **Cf and Cn are deliberately NOT here, and an earlier version refused both.** It tested
#: `str.isprintable()`, which is false for the format characters, so soft hyphen U+00AD,
#: zero width space U+200B and right to left mark U+200F were rejected as "a control
#: character". They are none of the three things this guards: measured, all encode to
#: ordinary UTF-8, none can truncate a C string, and **all occur in catalogue data**.
#: Unassigned codepoints are out for a second reason: `unicodedata` carries one Unicode
#: version, so refusing Cn would reject a character assigned in a newer one than this
#: Python knows. NBSP never reaches this test at all, being `Zs` and collapsed by
#: `_WHITESPACE` a line earlier.
_UNSENDABLE_CATEGORIES: Final = frozenset({"Cc", "Cs"})


def readable(text: str) -> str:
    """Third party text, made safe to put in a log line and short enough to read.

    Control characters become spaces, runs of whitespace collapse, and the result is
    truncated. Applied to **every** string that reaches a `Z3950Error`, because the words
    in a diagnostic are the target's and their length is the target's too: measured, one
    refusal from `lx2.loc.gov` carried 300 characters of a JSON error document from a CQL
    parser behind it, newlines and all.
    """
    printable = "".join(character if character.isprintable() else " " for character in text)
    return _WHITESPACE.sub(" ", printable).strip()[:MAX_DIAGNOSTIC_CHARS]


class Syntax(Enum):
    """A record format, named here so the seam has a vocabulary of its own.

    **The wire spellings belong to the client and must not leak through this.** There are
    three names for MARC21 in play at once: `usmarc` is what a request is spelled as,
    `MARC21` is what one target labels its answer, and `USmarc` is what another does. A
    `Target` carrying the string `"usmarc"` and a `Record` carrying the string `"USmarc"`
    give a caller nothing to compare, and `record.syntax == target.syntax` is then wrong
    even when the request was honoured. So the seam names the format and the client maps
    both directions.

    `OTHER` is not a failure. A target is free to answer in something neither of these
    is, and a caller decides whether it can use it; `Record.reported` carries the label
    verbatim for the caller that wants to know what it was.
    """

    MARC21 = "marc21"
    UNIMARC = "unimarc"
    OTHER = "other"


class Z3950Error(Exception):
    """This module declined to finish an exchange, or the target did.

    One base class, so a caller catches one name, which is the property that made
    `fetch.FetchRefused` cost nothing at its call sites. It is **not** a subclass of
    anything in httpx: there is no existing handler to land in, because nothing in the
    source chain speaks this protocol yet.

    **Every string that reaches one of these goes through `readable` first**, here rather
    than at the twelve places one is raised, because a diagnostic is a third party's words
    and one forgotten call site is one unbounded log line.
    """

    def __init__(self, *args: object) -> None:
        super().__init__(*(readable(a) if isinstance(a, str) else a for a in args))


class Unreachable(Z3950Error):
    """Nothing answered: the connection failed, or it timed out before a reply.

    Distinct from `Refused` because the dispositions differ: a host that is down may be
    up tomorrow, while a host that demands credentials will refuse for ever.
    """


class Refused(Z3950Error):
    """The target answered, and said no.

    Carries the diagnostic so a caller can tell `[101] Access-control failure` from
    `[235] Database does not exist`, which are a dead target and a typo respectively.
    """

    def __init__(self, code: int, message: str, detail: str = "") -> None:
        readable_detail = readable(detail)
        super().__init__(f"[{code}] {readable(message)}{f': {readable_detail}' if readable_detail else ''}")
        self.code = code
        self.message = readable(message)
        self.detail = readable_detail


class ResponseTooLarge(Z3950Error):
    """More than the byte cap, counted across the records of one search."""


class DeadlineExceeded(Z3950Error):
    """More than the time budget the association was opened with."""


class BadQuery(Z3950Error):
    """A query this module would not send, or one the client could not parse.

    **Ours, not the target's**, and that is why it is not `Refused`. Measured
    2026-08-28, a PQF string with injected structure comes back from the client as
    `10010 Invalid query` before anything reaches the wire; classing that as a target
    condition would blame a catalogue for a bug here.
    """


class Closed(Z3950Error):
    """The association is over: it was closed, or it was abandoned at a deadline.

    **Raised rather than allowed through, because the alternative is a signal.** A client
    that has released its connection has freed memory, and calling into it again is a
    segfault rather than an exception: measured, `search()` after `close()` is signal 11.
    So the association latches its own end, the same way a session latches its first
    failure.
    """


@dataclass(frozen=True)
class Target:
    """Where to ask, and what to ask it for."""

    host: str
    port: int
    database: str
    #: The format to **ask** for. Never the one to believe: see `Record.syntax`.
    syntax: Syntax = Syntax.MARC21


@dataclass(frozen=True)
class Record:
    """One record, as the target labelled it and as its bytes arrived."""

    #: What the target said this is, normalised to the seam's vocabulary.
    #:
    #: **Read off the response and never off the request.** Measured 2026-08-28,
    #: `libris.kb.se` answers a request for UNIMARC with MARC21, labelled MARC21, and it
    #: validates database names no more carefully: six different names returned an
    #: identical hit count. So a caller that needs MARC21 tests
    #: `record.syntax is Syntax.MARC21`, and a caller that assumes the request was
    #: honoured is wrong on the first Swedish record it sees.
    syntax: Syntax
    #: The label verbatim, for a caller that wants to know what the target actually said.
    reported: str
    #: The record exactly as it arrived.
    #:
    #: Bytes rather than text because MARC21 is binary and self describing: the leader's
    #: first five characters are the record's own length, and position 9 names its
    #: character set. Decoding here would destroy both, and the mapping downstream needs
    #: them.
    raw: bytes


@dataclass(frozen=True)
class Answer:
    """What one search returned. Zero hits is an answer, not a failure."""

    hits: int
    records: tuple[Record, ...]


class Session(Protocol):
    """One open association with one target. Blocking.

    Three methods and no bounds: the bounds are `search()`'s job, on the other side of
    this seam, so that choosing a different client cannot quietly change them.

    An implementation raises `Unreachable`, `Refused` or `BadQuery` and nothing else.
    Two obligations that are not visible from the call site:

    * **`search()` must not report success after a failed open.** Measured 2026-08-28
      against a closed port, the reference library reports a connect timeout and then
      answers the next search with `no error` and zero hits, which is `Unreachable`
      wearing `Answer(hits=0)` as a costume. An implementation latches its first failure.
    * **`search()` and `fetch()` after `close()` must raise rather than crash.** The
      association latches its own end too, so this is the second lock on one door; it is
      here because the failure is a signal rather than an exception and one lock is not
      enough for that.
    """

    def search(self, pqf: str) -> int:
        """Run the query and return the hit count. No records."""
        ...

    def fetch(self, index: int) -> Record:
        """One record, by zero based position in the result set."""
        ...

    def close(self) -> None:
        """Release the association. Called even when the exchange failed."""
        ...


class Client(Protocol):
    """Whatever opens an association. The one thing a route has to provide."""

    def open(self, target: Target, *, timeout: float) -> Session:
        """Open an association, or raise `Unreachable`.

        `timeout` is the client's own bound in seconds, and it is not the deadline: the
        deadline is enforced by `Association`, which cannot cancel work already inside a
        client. Both exist because neither is sufficient.
        """
        ...


def pqf_term(value: str) -> str:
    """One PQF term, quoted, with everything that could change the query escaped.

    **Getting this wrong does not raise, it rewrites the query.** Measured 2026-08-28
    with `p_query_rpn` and `yaz_rpnquery_to_wrbuf`, which render what the parser actually
    built, three characters matter and each fails differently:

    | in the term | built without escaping | the parser built |
    |---|---|---|
    | `"` | `"moby` | `@attr 1=4 moby` and 558 hits where the phrase returns 444 |
    | `\\` at the end | `"moby dick\\"` | the closing quote is escaped and the term runs on |
    | `@` then a digit | `"@1=1016 harry"` | `@attr 1=1016 "harry\\""`: **the pinned use attribute is gone** |

    The third is the sharp one and it is not only a term substitution: `@1=4 @set someset`
    parsed to `@set "someset\\""`, which references a result set, and
    `@1=4 @and @attr 1=4 aaa @attr 1=4 bbb` parsed to a two term `@and`. The reason it is
    not caught by the guard that gates `@and` mid query is that the parser tests for an
    escape character followed by a digit **before** the quoted run is read, and without
    the "preceded by a space" condition the operator keywords are gated on.

    Escaping `@` costs nothing: measured, all eight injected shapes collapse back to a
    single literal `@attr 1=4` term, and both benign shapes parse identically to before,
    `"moby @and dick"` included.

    **A control or surrogate character is refused rather than escaped, because escaping
    cannot reach it.** A NUL is not whitespace, so collapsing does not remove it, and the
    query crosses into C as a NUL terminated string: measured, `moby\\x00dick` builds 21
    characters and the parser sees `@attr 1=4 moby`. That is the quote failure again,
    reached without a quote, so the refusal is on the class rather than on the character.
    Which classes, and which look like they belong and do not: `_UNSENDABLE_CATEGORIES`.

    **A `[128] Illegal result set name` from `lx2.loc.gov` does not mean this leaked.**
    That target answers `@1=4 @set someset` with exactly that, and the addinfo is
    `someset"`, with a trailing quote, which reads like proof the escaping did nothing.
    It is not. Its gateway **re-renders the RPN back to PQF and re-parses it with YAZ**,
    meeting this identical lexer hole one hop downstream, and the quote is manufactured
    there. Reproduced without the target, by re-parsing the string the gateway would
    build:

    | our term | LoC says | re-parsing the re-render gives |
    |---|---|---|
    | `@1=4 @set someset` | `[128]`, addinfo `someset"` | `@set "someset\""` |
    | `@1=4 @set AAA` | `[128]`, addinfo `AAA"` | `@set "AAA\""` |
    | `@1=4 @set NAME extra` | `[2]`, `(ZOOM 10010 Invalid query)` | the parser refuses it |
    | `moby @set someset` | **0 hits, no diagnostic** | one literal term |

    **The fourth row is the discriminator.** It carries the same literal `@set someset`
    and draws nothing, so the target is not echoing our text back; what breaks the other
    three is an `@` followed by a digit at the front, which is this bug seen from the far
    side. What settles our own side needs no target at all: `p_query_rpn` renders every
    one of those built strings as a single `@attr 1=4` term, and **our term contains zero
    `"` characters** in all four.

    A previous version of this note said the target was echoing, and offered two other
    targets returning 0 hits as the proof. That does not discriminate: 0 hits is also
    what a term nobody holds returns.
    """
    collapsed = _WHITESPACE.sub(" ", value).strip()
    if not collapsed:
        # An empty term is not merely useless: measured, `@attr 1=4 ""` reaches the
        # target and comes back as `[1] Permanent system error` from a CQL parser
        # behind it. Refusing locally is a better error and costs no round trip.
        raise BadQuery("A search term cannot be empty")
    if len(collapsed) > MAX_TERM_CHARS:
        raise BadQuery(f"A search term cannot be longer than {MAX_TERM_CHARS} characters")
    if any(unicodedata.category(character) in _UNSENDABLE_CATEGORIES for character in collapsed):
        raise BadQuery("A search term cannot hold a control or surrogate character")
    escaped = collapsed.replace("\\", "\\\\").replace('"', '\\"').replace("@", "\\@")
    return f'"{escaped}"'


def query(use: int, value: str) -> str:
    """A one term PQF query against a BIB-1 use attribute.

    No `@attrset`: BIB-1 is PQF's default and every target measured accepts the bare
    form. Callers use `isbn_query` and `title_query` rather than this, which exists so a
    new access point is one constant rather than a new string format.

    **The use attribute is checked, because `pqf_term` guards the other half of this
    string and nothing guarded this one.** Every caller in this module passes a module
    constant, so the check is dead here. It is not dead for `targets.Target.isbn_query`,
    which passes a field that a database row can supply: SQLite's INTEGER affinity is a
    preference rather than a constraint, and a critic measured
    `'7 @and @attr 1=4 anything'` storing in an INTEGER column as text, which renders
    here as a two term `@and`. That is the structure injection `pqf_term`'s own table
    describes, reached around it rather than through it.

    `bool` is refused with everything else: it is an `int` in Python, and `@attr 1=True`
    is not a query.
    """
    if type(use) is not int:
        raise BadQuery(f"not a use attribute: {use!r}")
    return f"@attr 1={use} {pqf_term(value)}"


def isbn_query(isbn: str) -> str:
    """Look an ISBN up on use attribute 7.

    Measured 2026-08-28, `lx2.loc.gov:210/LCDB` matches both ISBN-10 and ISBN-13 on this
    attribute, `aleph.nkp.cz:9991/NKC` matches only the ISBN-13, and
    `z3950.nlg.gr:210/biblios` matches with and without hyphens. So the caller decides
    which forms to try; this decides how one of them is spelled.
    """
    return query(USE_ISBN, isbn)


def title_query(title: str) -> str:
    """Look a title up on use attribute 4."""
    return query(USE_TITLE, title)


def _default_client() -> Client:
    """The client in use today.

    Imported here rather than at module scope so that this module can be imported, and
    every bound in it tested, on a machine with no Z39.50 client installed at all. The
    test suite is hermetic and never reaches this function.
    """
    from z3950_provisional import ProvisionalYazClient

    return ProvisionalYazClient()


class Association:
    """One open association, one worker thread, and one exchange at a time.

    **The thread is per association and is not the shared executor.** Every call into a
    blocking client runs on it, so an abandoned call and the close that follows are on the
    same thread in that order, and a client can never be entered from two threads. Using
    `asyncio.to_thread` instead puts the work on the loop's default executor, which
    `covers.py` and `notifications.py` also draw from: measured, one abandoned search
    against the Library of Congress under a 0.05s deadline pinned a worker until the
    process was SIGKILLed at 40s.

    **The lock is what a `Session` needs and cannot provide.** A session holds one result
    set, so a second search through it destroys the first's records. Measured over eight
    concurrent pairs on one association: five bogus `Unreachable`, two `Answer(hits=0)`
    on a query that returns 444 run serially, and one SIGSEGV. A wrong zero is the
    disposition the session's latch exists to prevent, arriving by another door.

    **It latches its own end**, so a call after a close or an abandonment raises `Closed`
    rather than reaching a client that has freed its connection.
    """

    def __init__(self, target: Target, deadline: float) -> None:
        self.target = target
        #: One absolute clock for the open, every search and every record. See
        #: `TIMEOUT_SECONDS` for what an earlier per call version of this admitted.
        self.deadline = deadline
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="endpaper-z3950")
        self._lock = asyncio.Lock()
        self._session: Session | None = None
        self._ended: Z3950Error | None = None

    @property
    def _where(self) -> str:
        return f"{self.target.host}:{self.target.port}"

    def _left(self, deadline: float) -> float:
        return deadline - time.monotonic()

    async def _open(self, client: Client) -> None:
        """Open the association, or end it. Never leaves a session nobody holds."""
        left = self._left(self.deadline)
        if left <= 0:
            self._end(DeadlineExceeded(f"{self._where} {BEFORE_STARTING}"))
            raise DeadlineExceeded(f"{self._where} {BEFORE_STARTING}")
        pending = self._executor.submit(client.open, self.target, timeout=left)
        try:
            self._session = await asyncio.wait_for(asyncio.wrap_future(pending), left)
        except TimeoutError:
            # **The session is still coming and nobody is waiting for it.** A thread
            # cannot be cancelled, so the client will finish and hand back a real
            # connection: measured before this callback existed, `sessions built: 1,
            # closed: [0]`, a connection and a socket for the life of the process.
            self._close_on_arrival(pending)
            self._ended = Closed(f"{self._where} {STILL_ANSWERING}")
            raise DeadlineExceeded(f"{self._where} {STILL_ANSWERING}") from None
        except BaseException:
            # **The door production actually takes, and it was the one left open.** An
            # outer deadline cancels this coroutine, and a cancellation arrives here as
            # `CancelledError`, never as the `TimeoutError` above:
            # `metadata.SEARCH_DEADLINE_SECONDS` is 4.0 against this module's 10.0s
            # ceiling, so the outer clock always expires first and this arm is the one a
            # fan out uses. Measured with the bare `shutdown` that used to be here, and
            # an outer `asyncio.timeout(0.05)`: 3 of 3 runs built a session whose
            # connection handle was still non-zero 3.0 seconds later, and `close()` zeroes
            # it, so that is proof it never ran. Identical defect to the `TimeoutError`
            # arm above, fixed on one door and live on the other.
            #
            # **`_close_on_arrival` and NOT a shutdown here.** Shutting the executor down
            # first makes the callback's own `submit` raise, so the close would never run;
            # it does the shutdown itself, afterwards. This also covers the ordinary
            # failure, where `pending` finished by raising: the callback's `result()` then
            # raises, nothing is closed, and the executor still goes.
            self._ended = Closed(f"{self._where} never opened")
            self._close_on_arrival(pending)
            raise

    def _close_on_arrival(self, pending: Future[Session]) -> None:
        """Close a session that arrives after everyone stopped waiting for it.

        The callback runs on the worker thread that completed the open, so the close is
        submitted behind it on that same thread and never races it. `shutdown` is last
        and does not wait: a queued item still runs before the worker sees the stop.
        """

        def close_it(done: Future[Session]) -> None:
            try:
                session = done.result()
            except BaseException:
                pass
            else:
                try:
                    self._executor.submit(session.close)
                except RuntimeError:  # already shut down
                    logger.warning("Could not close a late association with %s", self.target.host)
            finally:
                self._executor.shutdown(wait=False)

        pending.add_done_callback(close_it)

    def _end(self, reason: Z3950Error) -> None:
        """End the association, and release it on its own thread. Never blocks.

        **The close is submitted and not awaited**, which is what takes it out of the
        deadline question entirely. Awaiting it measured 3.007s against a 0.500s
        deadline, 6.0x, and bounding that wait with a second constant would only have
        made the overshoot a smaller number. Ordering is guaranteed by the single worker
        rather than by waiting.
        """
        if self._ended is not None:
            return
        self._ended = reason
        session, self._session = self._session, None
        if session is not None:
            self._executor.submit(session.close)
        self._executor.shutdown(wait=False)

    async def _call[T](self, run: Callable[[Session], T], *, deadline: float) -> T:
        """One blocking client call, on this association's thread, inside the deadline."""
        if self._ended is not None:
            raise self._ended
        session = self._session
        if session is None:
            raise Closed(f"{self._where} has no open session")
        left = self._left(deadline)
        if left <= 0:
            raise DeadlineExceeded(f"{self._where} {BEFORE_STARTING}")
        pending = self._executor.submit(run, session)
        try:
            return await asyncio.wait_for(asyncio.wrap_future(pending), left)
        except TimeoutError:
            # The call is still running and still holds the connection. Ending the
            # association queues the close behind it on the same thread.
            self._end(Closed(f"{self._where} {STILL_ANSWERING}"))
            raise DeadlineExceeded(f"{self._where} {STILL_ANSWERING}") from None

    @asynccontextmanager
    async def _one_exchange(self) -> AsyncIterator[None]:
        """One search and its records, with nothing else on this association meanwhile."""
        async with self._lock:
            yield


@asynccontextmanager
async def association(
    target: Target,
    *,
    client: Client | None = None,
    deadline: float | None = None,
) -> AsyncIterator[Association]:
    """An open association with one target, released on the way out.

    **Reuse it across the queries for one target.** Measured 2026-08-28, opening one to
    `lx2.loc.gov:210` costs 0.204s and three searches through it then cost 0.216s,
    0.342s and 0.437s. Re opening per query would add that 0.204s to each, which is 5.1%
    of the 4.0s fan out budget spent saying hello again.

    **The deadline is the whole association's**, not each call's, so `TIMEOUT_SECONDS`
    means what it says. Everything done through the yielded object shares it, and
    `search` can only narrow it.

    **A deadline beyond `TIMEOUT_SECONDS` raises `ValueError`**, exactly as a `limit`
    above `MAX_RESPONSE_BYTES` and a `records` above `MAX_RECORDS` do. This is the one
    place the budget is set, so it is the one place it can be set too high, and a ceiling
    a caller can raise is not a ceiling. It also removes what actually contains a runaway
    exchange today: the client's own socket timeout is derived from this deadline, so a
    caller asking for an hour would set an hour there too.
    """
    ends = time.monotonic() + TIMEOUT_SECONDS if deadline is None else deadline
    if ends - time.monotonic() > TIMEOUT_SECONDS:
        raise ValueError(
            f"deadline must not be more than TIMEOUT_SECONDS ({TIMEOUT_SECONDS}) away"
        )
    open_association = Association(target, ends)
    await open_association._open(client or _default_client())
    try:
        yield open_association
    finally:
        open_association._end(Closed(f"{target.host}:{target.port} was closed"))


async def search(
    open_association: Association,
    pqf: str,
    *,
    records: int = 1,
    limit: int | None = None,
    deadline: float | None = None,
) -> Answer:
    """Run one query, bounded three ways.

    At most `records` records, at most `limit` bytes across them, and all of it inside the
    association's deadline unless `deadline` names another one.

    **`deadline` can only narrow the association's clock, never widen it.** It used to
    replace it, and that was refused as a preference on the argument that
    `association(deadline=...)` has the same capability one level down, so narrowing one
    site and not the other would be inconsistent. The measurement reversed the argument
    rather than the conclusion: a **0.5s association ran a search to t+5.004s and returned
    a hit count**, ten times its own ceiling, and live the only thing that had contained
    it was the client's socket timeout, surfacing as `Unreachable [10004] Connection lost`
    rather than as a deadline. A bound held by a client accident is not held by the seam.
    If both sites widen, the answer is to bound both, which is what
    `association()` now does with a `ValueError`. This is the third caller supplied number
    that could raise a bound the seam exists to hold; `limit` and `records` were the other
    two, and all three now refuse.

    Narrowing is silent where the other two refuse, and that is the difference between
    composition and a bug: a caller asking for **less** time than the association has
    still gets everything it asked for, while a caller asking for a thousand records has
    a mistake that a smaller number would hide.

    **The count comes back before any record does, and that is the byte bound.** A
    Z39.50 search answers with a hit count alone; records arrive only for the positions
    asked for. So `records` is what decides the cost, and `hits` never is.

    `records` above `MAX_RECORDS` and `limit` above `MAX_RESPONSE_BYTES` both raise
    `ValueError` rather than being clamped. A clamp is silent, and a caller asking for a
    thousand records has a bug that a smaller number would hide. **`limit` is checked for
    the same reason `records` is**: a caller who can raise a cap is not bounded by it, and
    that half was missing when this was written, so `limit=209_715_200` was accepted and
    returned 4.8x the module's own maximum with no error.

    **One exchange at a time on one association.** A `Session` holds one result set, so
    two concurrent searches destroy each other's records: see `Association`.
    """
    if records < 1:
        raise ValueError("records must be at least 1")
    if records > MAX_RECORDS:
        raise ValueError(f"records must not exceed MAX_RECORDS ({MAX_RECORDS})")
    cap = MAX_RESPONSE_BYTES if limit is None else limit
    if cap < 1:
        raise ValueError("limit must be at least 1")
    if cap > MAX_RESPONSE_BYTES:
        raise ValueError(f"limit must not exceed MAX_RESPONSE_BYTES ({MAX_RESPONSE_BYTES})")
    ends = (
        open_association.deadline
        if deadline is None
        else min(open_association.deadline, deadline)
    )
    async with open_association._one_exchange():
        return await _exchange(open_association, pqf, records, cap, ends)


async def _exchange(
    open_association: Association, pqf: str, records: int, cap: int, ends: float
) -> Answer:
    """The search and the bounded record walk.

    Split out so the lock and the argument checks are in exactly one place, around the
    whole call, rather than repeated per record. `fetch._walk_hops` is split from
    `fetch.get` for the identical reason.

    **All or nothing.** A walk that runs out of time discards the records it already
    fetched, which is `fetch.py`'s behaviour too: a body that stops arriving yields
    nothing rather than a prefix. It is why `MAX_RECORDS` is bounded by time.
    """
    def run_search(session: Session) -> int:
        return session.search(pqf)

    hits = await open_association._call(run_search, deadline=ends)
    if hits <= 0:
        # Answered nothing. A value and not an exception: a catalogue that does not hold
        # a book is the ordinary case, and the two failures that look like this from the
        # outside are already `Unreachable` and `Refused` by the time we get here.
        return Answer(hits=0, records=())

    got: list[Record] = []
    total = 0
    for index in range(min(hits, records)):

        def run_fetch(session: Session, position: int = index) -> Record:
            return session.fetch(position)

        record = await open_association._call(run_fetch, deadline=ends)
        total += len(record.raw)
        if total > cap:
            logger.warning("Refused a Z39.50 answer over %d bytes at record %d", cap, index)
            raise ResponseTooLarge(f"The target answered with more than {cap} bytes")
        got.append(record)
    return Answer(hits=hits, records=tuple(got))


async def search_once(
    target: Target,
    pqf: str,
    *,
    records: int = 1,
    limit: int | None = None,
    deadline: float | None = None,
    client: Client | None = None,
) -> Answer:
    """One bounded search, with an association of its own.

    `association()` plus `search()` for the callers that ask one question. The pairing is
    `fetch.get_once` beside `fetch.get`, and the reason to reach for the other one is the
    same: several questions to one target should share one association, and here they
    share its clock as well.
    """
    ends = time.monotonic() + TIMEOUT_SECONDS if deadline is None else deadline
    async with association(target, client=client, deadline=ends) as open_association:
        return await search(open_association, pqf, records=records, limit=limit)
