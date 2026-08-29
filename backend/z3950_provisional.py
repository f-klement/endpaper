"""**PROVISIONAL.** The one Z39.50 client that exists today, and not the chosen one.

**The route is an open decision and this file is not it.** #92 asks for a transport; which
client fills it is being settled separately, and the candidate list is not complete. This
exists so that `z3950.py`'s bounds can be exercised and the Library of Congress control can
be checked against a real target, which is the only thing that tells a database name from a
guess. Do not harden it, do not build on its shape, and do not cite it as a decision.

**Nothing outside `z3950.py` may import it.** Everything a caller needs is on the seam:
`Target`, `Record`, `Answer` and the four failure classes. That is what makes swapping this
out a change to one function, `z3950._default_client`.

What it is, so the next reader does not have to guess: a `ctypes` binding to the ZOOM C API
in `libyaz.so.5`, which the image already ships (`docker/build-yaz.sh`,
`docs/architecture.md`). ZOOM is blocking, so `z3950.py` runs every call off the event loop.

**The ctypes wiring and the error taxonomy are deliberately separate.** `Bindings` is the
nine calls this needs; `_YazSession` is the rules on top of them. The rules are what earn a
test, and they are testable with no library present because `Bindings` can be faked. The
wiring is what a different route replaces.

**Two limitations, recorded because they are inputs to choosing a route rather than
defects to fix here.**

* ZOOM's own `timeout` option is whole seconds, so a sub second budget rounds to a floor of
  one second. The deadline a caller actually sees is `Association._call`'s
  `asyncio.wait_for` over the future on its own executor.
* A blocking call inside a thread cannot be cancelled, so a client that overruns is
  abandoned rather than stopped. Both bounds exist for that reason and neither is
  redundant.
"""

import ctypes
import logging
from typing import Any, Final, Protocol

from z3950 import (
    MAX_RESPONSE_BYTES,
    BadQuery,
    Closed,
    Record,
    Refused,
    Session,
    Syntax,
    Target,
    Unreachable,
    Z3950Error,
)

logger = logging.getLogger("endpaper.z3950")

#: Where the image puts YAZ. `docker/build-yaz.sh` bakes this prefix into the binary as its
#: RUNPATH, so the tree is not relocatable and neither is this path.
LIBRARY: Final = "/opt/yaz/lib/libyaz.so.5"

#: The client's own diagnostic set. Anything else came from the target.
#:
#: **The test is "is it ours", not a list of the target's.** A diagnostic set names who
#: produced the diagnostic, and YAZ uses more of them than Bib-1 (SRU and HTTP among them).
#: Enumerating the target's sets would need a new arm per target family; asking whether the
#: set is the client's needs none. An unknown set is read as the target's, which is the
#: conservative direction: a refusal is not worth retrying and an unreachable host is.
_CLIENT_DIAGSET: Final = "ZOOM"

#: The client could not parse the query, which is a bug here rather than a target's answer.
#: Measured 2026-08-28 by injecting `@attr 1=4 "moby" @attr 1=4 "dick"`, which never
#: reaches the wire.
_INVALID_QUERY: Final = 10010

#: How this client spells each format when it asks, and what it makes of what comes back.
#:
#: **Both directions live here because both spellings are the client's, not the seam's.**
#: There are three names for MARC21 in the measurements alone: `usmarc` is what YAZ wants
#: in `preferredRecordSyntax`, `MARC21` is how `libris.kb.se` labels its answer, and
#: `USmarc` is how `lx2.loc.gov` labels the identical bytes. Letting any of them reach a
#: caller would make `record.syntax == target.syntax` false on an honoured request, which
#: is worse than useless because it looks like the check the seam asks a caller to make.
_REQUESTED: Final[dict[Syntax, str]] = {
    Syntax.MARC21: "usmarc",
    Syntax.UNIMARC: "unimarc",
}

#: Lower cased, because the two labels measured differ only in case.
#:
#: Anything absent is `Syntax.OTHER`, which is an answer and not a failure: a target may
#: reply in SUTRS, GRS-1 or XML, and `Record.reported` carries the label verbatim for a
#: caller that wants to know which.
_REPORTED: Final[dict[str, Syntax]] = {
    "usmarc": Syntax.MARC21,
    "marc21": Syntax.MARC21,
    "unimarc": Syntax.UNIMARC,
}


def reported_syntax(label: str) -> Syntax:
    """What a target's own label for a record means in the seam's vocabulary."""
    return _REPORTED.get(label.strip().lower(), Syntax.OTHER)


class Bindings(Protocol):
    """The ZOOM surface this client uses. Handles are opaque integers.

    Narrow on purpose: it is the whole of what has to be faked to test the rules above it,
    and the whole of what a different binding would have to provide.

    **No count here.** This said "the nine ZOOM calls" against nine methods over ten
    entry points, which was two different things counted as one, and a number in prose
    does not recount itself. `SIGNATURES` and
    `test_every_call_the_binding_makes_is_declared` hold the real correspondence, both
    directions.
    """

    def create(self) -> int: ...
    def option(self, connection: int, key: str, value: str) -> None: ...
    def connect(self, connection: int, host: str, port: int) -> None: ...
    def error(self, connection: int) -> tuple[int, str, str, str]:
        """`(code, message, detail, diagset)`. Code 0 means no error."""
        ...

    def search(self, connection: int, pqf: str) -> int:
        """The result set handle, or 0."""
        ...

    def size(self, resultset: int) -> int: ...
    def record(self, resultset: int, index: int) -> tuple[str, bytes] | None:
        """`(syntax, raw)` for one record, or None where the target sent none."""
        ...

    def free_resultset(self, resultset: int) -> None: ...
    def free_connection(self, connection: int) -> None: ...


#: Every ZOOM entry point this binds, with its return type and its arguments.
#:
#: **`ZOOM_record_get` returns `c_void_p` and its bytes are read with `string_at`, not
#: `c_char_p`.** ctypes converts a `c_char_p` return by stopping at the first NUL, and
#: MARC21 is binary: a record holding one would be silently truncated, and the length in
#: its own leader would then disagree with what arrived. That is the one line here whose
#: correctness cannot be seen from the call site, so a test pins it.
#:
#: At module scope rather than inside `CtypesBindings.__init__` so it can be read without
#: a copy of YAZ present, which is every machine the suite runs on.
SIGNATURES: Final[tuple[tuple[str, Any, list[Any]], ...]] = (
    ("ZOOM_connection_create", ctypes.c_void_p, [ctypes.c_void_p]),
    ("ZOOM_connection_connect", None, [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]),
    ("ZOOM_connection_option_set", None, [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]),
    (
        "ZOOM_connection_error_x",
        ctypes.c_int,
        [ctypes.c_void_p] + [ctypes.POINTER(ctypes.c_char_p)] * 3,
    ),
    ("ZOOM_connection_search_pqf", ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_char_p]),
    ("ZOOM_connection_destroy", None, [ctypes.c_void_p]),
    ("ZOOM_resultset_size", ctypes.c_size_t, [ctypes.c_void_p]),
    ("ZOOM_resultset_record", ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_size_t]),
    ("ZOOM_resultset_destroy", None, [ctypes.c_void_p]),
    ("ZOOM_record_get", ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_int)]),
)


class CtypesBindings:
    """`Bindings` over `libyaz.so.5`, loaded on first use and never at import.

    Import time loading would make `z3950.py` unimportable on any machine without YAZ,
    which includes every machine the hermetic suite runs on.
    """

    def __init__(self, path: str = LIBRARY) -> None:
        lib = ctypes.CDLL(path)
        # Every signature is declared. ctypes defaults an undeclared return to `int`, which
        # truncates a 64 bit pointer on the platforms where it matters, and that failure is
        # a segfault rather than an exception.
        for name, restype, argtypes in SIGNATURES:
            function = getattr(lib, name)
            function.restype = restype
            function.argtypes = argtypes
        self._lib = lib

    def create(self) -> int:
        return int(self._lib.ZOOM_connection_create(None) or 0)

    def option(self, connection: int, key: str, value: str) -> None:
        self._lib.ZOOM_connection_option_set(connection, key.encode(), value.encode())

    def connect(self, connection: int, host: str, port: int) -> None:
        self._lib.ZOOM_connection_connect(connection, host.encode(), port)

    def error(self, connection: int) -> tuple[int, str, str, str]:
        message, detail, diagset = ctypes.c_char_p(), ctypes.c_char_p(), ctypes.c_char_p()
        code = int(
            self._lib.ZOOM_connection_error_x(
                connection, ctypes.byref(message), ctypes.byref(detail), ctypes.byref(diagset)
            )
        )
        return (
            code,
            (message.value or b"").decode(errors="replace"),
            (detail.value or b"").decode(errors="replace"),
            (diagset.value or b"").decode(errors="replace"),
        )

    def search(self, connection: int, pqf: str) -> int:
        return int(self._lib.ZOOM_connection_search_pqf(connection, pqf.encode()) or 0)

    def size(self, resultset: int) -> int:
        return int(self._lib.ZOOM_resultset_size(resultset))

    def record(self, resultset: int, index: int) -> tuple[str, bytes] | None:
        handle = self._lib.ZOOM_resultset_record(resultset, index)
        if not handle:
            return None
        raw = self._member(handle, "raw")
        syntax = self._member(handle, "syntax")
        if raw is None:
            return None
        return (syntax or b"").decode(errors="replace"), raw

    def _member(self, record: int, name: str) -> bytes | None:
        """One field of a ZOOM record, as bytes. See `SIGNATURES` for why `string_at`."""
        length = ctypes.c_int(0)
        pointer = self._lib.ZOOM_record_get(record, name.encode(), ctypes.byref(length))
        if not pointer:
            return None
        return ctypes.string_at(pointer, length.value)

    def free_resultset(self, resultset: int) -> None:
        self._lib.ZOOM_resultset_destroy(resultset)

    def free_connection(self, connection: int) -> None:
        self._lib.ZOOM_connection_destroy(connection)


def classify(code: int, message: str, detail: str, diagset: str) -> Z3950Error:
    """Turn one ZOOM diagnostic into one of the seam's failures.

    The whole of the taxonomy, in one place, so that "refused", "unreachable" and "our own
    bad query" cannot drift apart between the open, the search and the record.
    """
    if diagset != _CLIENT_DIAGSET:
        return Refused(code, message, detail)
    if code == _INVALID_QUERY:
        return BadQuery(f"{message}: {detail}" if detail else message)
    return Unreachable(f"[{code}] {message}{f': {detail}' if detail else ''}")


class _YazSession:
    """One open association, and the rules that keep its three failures apart.

    **The first failure is latched and every later call re-raises it.** Measured
    2026-08-28 against a closed port on a host that exists: the connect reports
    `[10007] Timeout` and the search that follows reports no error and zero hits. Without
    a latch, "unreachable" arrives at a caller as "this catalogue does not hold the book",
    which is the exact conflation the target survey made once already.

    `open` raises before a session is ever built, so the latch is not what catches that
    case. It catches the one measured at Greece, where a clean 36 hit search was followed
    by `[239] Record syntax not supported` on the record.
    """

    def __init__(self, bindings: Bindings, connection: int, target: Target) -> None:
        self._bindings = bindings
        self._connection = connection
        self._target = target
        self._resultset = 0
        self._failed: Z3950Error | None = None

    def _latch(self, error: Z3950Error) -> Z3950Error:
        if self._failed is None:
            self._failed = error
        return self._failed

    def _check(self) -> None:
        """Raise whatever the diagnostic says, and remember it. Silence is success."""
        code, message, detail, diagset = self._bindings.error(self._connection)
        if code:
            raise self._latch(classify(code, message, detail, diagset))

    def search(self, pqf: str) -> int:
        if self._failed is not None:
            raise self._failed
        self._release_resultset()
        resultset = self._bindings.search(self._connection, pqf)
        self._check()
        if not resultset:
            raise self._latch(Unreachable(f"{self._target.host} returned no result set"))
        self._resultset = resultset
        return self._bindings.size(resultset)

    def fetch(self, index: int) -> Record:
        if self._failed is not None:
            raise self._failed
        if not self._resultset:
            raise Z3950Error("fetch was called before search")
        got = self._bindings.record(self._resultset, index)
        # The diagnostic first: measured at `z3950.nlg.gr`, a refused record syntax comes
        # back as a null record AND a `[239]` diagnostic, and reporting the null alone
        # would lose the reason.
        self._check()
        if got is None:
            raise self._latch(Refused(0, "The target sent no record", f"position {index}"))
        label, raw = got
        return Record(syntax=reported_syntax(label), reported=label, raw=raw)

    def close(self) -> None:
        self._release_resultset()
        if self._connection:
            self._bindings.free_connection(self._connection)
            self._connection = 0
        # **Latched after the free, and this line is the difference between an exception
        # and a signal.** The connection's memory is gone, so a later `search` reaches
        # into it: measured, signal 11. `fetch` was safe only because it happened to test
        # `_resultset` first, which is an accident of ordering rather than a rule.
        # `if ... is None` so a real failure latched earlier keeps its place: a caller
        # should see why the association died, not that it was tidied up afterwards.
        if self._failed is None:
            self._failed = Closed("The association is closed")

    def _release_resultset(self) -> None:
        if self._resultset:
            self._bindings.free_resultset(self._resultset)
            self._resultset = 0


class ProvisionalYazClient:
    """`z3950.Client` over ZOOM. See this module's docstring for its status."""

    def __init__(self, bindings: Bindings | None = None) -> None:
        self._bindings = bindings

    def _load(self) -> Bindings:
        if self._bindings is None:
            self._bindings = CtypesBindings()
        return self._bindings

    def open(self, target: Target, *, timeout: float) -> Session:
        if target.syntax not in _REQUESTED:
            # `Syntax.OTHER` is what a target may ANSWER with. It is not something to ask
            # for, and a bare KeyError here would surface as a 500 rather than as a
            # source being unavailable.
            raise BadQuery(f"There is no way to ask a target for {target.syntax.value}")
        bindings = self._load()
        connection = bindings.create()
        if not connection:
            raise Unreachable("Could not allocate a Z39.50 connection")
        for key, value in self._options(target, timeout):
            bindings.option(connection, key, value)
        bindings.connect(connection, target.host, target.port)
        code, message, detail, diagset = bindings.error(connection)
        if code:
            bindings.free_connection(connection)
            raise classify(code, message, detail, diagset)
        return _YazSession(bindings, connection, target)

    @staticmethod
    def _options(target: Target, timeout: float) -> list[tuple[str, str]]:
        """What is negotiated at Init, and why each one is here.

        **`count` is 0, and that is asking for no records rather than a trick.** It is
        ZOOM's "how many records do you want", and a search that wants none carries none:
        measured 2026-08-28 at `libris.kb.se`, `count` of 1 or 10 drew
        `[1005] Response records in Search response not supported` **and still returned
        350 hits and a fetchable record**, so a non fatal Bib-1 diagnostic arrived on a
        search that had worked, while 0 was clean. Zero also means each record is its own
        Present, which is what lets `z3950.search` stop the wire at the byte cap instead
        of counting a batch already in memory: at `count` of 10 the ten records arrived
        together in 0.00s.

        **`smallSetUpperBound`, `largeSetLowerBound` and `mediumSetPresentNumber` were
        tried here and are deliberately absent.** They are the protocol's own piggyback
        parameters and look like the more principled lever. Measured, they buy nothing
        over `count=0` and cost reliability: with them the record walk described below
        failed **at record 0** on a 444 hit result set, where `count=0` alone fetched
        record 0 in every run and every case tried.

        **A record walk against a real target is not reliable, and that is the target's
        business rather than a bound to design around.** `lx2.loc.gov` ends a walk with
        `[13] Present request out of range` at a position that moves between runs of the
        identical request: measured at records 43, 23, 11, 36 and 0 across five runs of
        four option sets. It arrives as `Refused`, which every caller already degrades on.
        `z3950.MAX_RECORDS` is therefore bounded by time, which is stable, and not by this,
        which is not.

        **The two size options are sent and not trusted.** Measured with both at 512,
        `lx2.loc.gov` returned a 2,227 byte record and no diagnostic; the same at 1024 and
        4096. `z3950.MAX_RESPONSE_BYTES` is what actually binds, counted on this side.

        **The timeout floor is one second**, because ZOOM's option is whole seconds. A
        shorter budget is carried by `Association._call`'s `asyncio.wait_for` alone.
        """
        return [
            ("databaseName", target.database),
            ("preferredRecordSyntax", _REQUESTED[target.syntax]),
            ("count", "0"),
            ("maximumRecordSize", str(MAX_RESPONSE_BYTES)),
            ("preferredMessageSize", str(MAX_RESPONSE_BYTES)),
            ("timeout", str(max(1, int(timeout)))),
            # lobid asked for a stable identifying string and the same courtesy applies
            # here: a target's operator can tell one caller from another. `fetch._AGENT`
            # carries the same name for the same reason, with no version and no address.
            ("implementationName", "endpaper"),
        ]
