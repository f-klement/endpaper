"""Tests for backend/z3950_provisional.py.

**The client route is not settled and this module is not it.** What these tests pin is
therefore deliberately narrow: the rules that any client behind `z3950.Session` has to
follow, written where they currently live. The ctypes wiring is not tested and cannot be,
because the suite is hermetic and no shared library is present.

The one test here that would be the only warning of a real regression is the latch.
Measured 2026-08-28 against a closed port on a host that resolves: the connect reports
`[10007] Timeout`, and the search that follows reports **no error and zero hits**. So an
unreachable target arrives at a caller as "this catalogue does not hold the book" unless
the first failure is remembered. That is the exact conflation the target survey made once
already, and it is produced by the library rather than by anything here.
"""

import ctypes
from dataclasses import dataclass, field

import pytest

import z3950
import z3950_provisional as provisional
from z3950 import Syntax, Target

TARGET = Target(host="catalogue.example", port=210, database="EXAMPLE")

#: `(code, message, detail, diagset)`, as `ZOOM_connection_error_x` reports it.
CLEAN = (0, "No error", "", "ZOOM")
TIMED_OUT = (10007, "Timeout", "", "ZOOM")
CONNECT_FAILED = (10000, "Connect failed", "catalogue.example:210", "ZOOM")
INVALID_QUERY = (10010, "Invalid query", "", "ZOOM")
NO_AUTH = (101, "Access-control failure", "Failed to authenticate user.", "Bib-1")
NO_SYNTAX = (239, "Record syntax not supported", "1.2.840.10003.5.10", "Bib-1")


@dataclass
class FakeBindings:
    """A `Bindings` that answers from a script of diagnostics, one per `error()` call.

    The script is what makes the latch testable: the measured trap is a target that
    reports a failure once and then reports success, so the fake has to be able to do
    exactly that.
    """

    errors: list[tuple[int, str, str, str]] = field(default_factory=lambda: [CLEAN])
    hits: int = 1
    record_value: tuple[str, bytes] | None = ("USmarc", b"record")
    resultset_handle: int = 55
    options: dict[str, str] = field(default_factory=dict)
    connected: list[tuple[str, int]] = field(default_factory=list)
    searched: list[str] = field(default_factory=list)
    freed_resultsets: list[int] = field(default_factory=list)
    freed_connections: list[int] = field(default_factory=list)
    _errors_read: int = 0

    def create(self) -> int:
        return 7

    def option(self, connection: int, key: str, value: str) -> None:
        self.options[key] = value

    def connect(self, connection: int, host: str, port: int) -> None:
        self.connected.append((host, port))

    def error(self, connection: int) -> tuple[int, str, str, str]:
        index = min(self._errors_read, len(self.errors) - 1)
        self._errors_read += 1
        return self.errors[index]

    def search(self, connection: int, pqf: str) -> int:
        self.searched.append(pqf)
        return self.resultset_handle

    def size(self, resultset: int) -> int:
        return self.hits

    def record(self, resultset: int, index: int) -> tuple[str, bytes] | None:
        return self.record_value

    def free_resultset(self, resultset: int) -> None:
        self.freed_resultsets.append(resultset)

    def free_connection(self, connection: int) -> None:
        self.freed_connections.append(connection)


def opened(bindings: FakeBindings) -> z3950.Session:
    return provisional.ProvisionalYazClient(bindings).open(TARGET, timeout=5.0)


class TestTheFirstFailureIsLatched:
    """A failure once reported must not be washed away by a later clean read."""

    def test_a_connect_failure_is_raised_rather_than_becoming_an_empty_answer(self):
        # The measured trap: [10007] at the connect, then no error and zero hits.
        bindings = FakeBindings(errors=[TIMED_OUT, CLEAN], hits=0)
        with pytest.raises(z3950.Unreachable):
            opened(bindings)

    def test_a_failed_open_never_hands_back_a_session_to_search_with(self):
        bindings = FakeBindings(errors=[TIMED_OUT, CLEAN], hits=0)
        with pytest.raises(z3950.Unreachable):
            opened(bindings)
        assert bindings.searched == []

    def test_a_failed_open_releases_the_connection(self):
        bindings = FakeBindings(errors=[CONNECT_FAILED])
        with pytest.raises(z3950.Unreachable):
            opened(bindings)
        assert bindings.freed_connections == [7]

    def test_a_record_failure_is_re_raised_on_the_next_call(self):
        # Measured at `z3950.nlg.gr`: a clean 36 hit search, then [239] on the record.
        bindings = FakeBindings(errors=[CLEAN, CLEAN, NO_SYNTAX, CLEAN], hits=36)
        session = opened(bindings)
        session.search("q")
        with pytest.raises(z3950.Refused):
            session.fetch(0)
        with pytest.raises(z3950.Refused):
            session.fetch(1)

    def test_the_re_raised_failure_is_the_first_one_and_not_a_new_one(self):
        bindings = FakeBindings(errors=[CLEAN, CLEAN, NO_SYNTAX, CLEAN], hits=36)
        session = opened(bindings)
        session.search("q")
        with pytest.raises(z3950.Refused) as first:
            session.fetch(0)
        with pytest.raises(z3950.Refused) as second:
            session.search("q")
        assert second.value is first.value

    def test_a_search_after_a_latched_failure_never_reaches_the_target(self):
        bindings = FakeBindings(errors=[CLEAN, CLEAN, NO_SYNTAX, CLEAN], hits=36)
        session = opened(bindings)
        session.search("q")
        with pytest.raises(z3950.Refused):
            session.fetch(0)
        with pytest.raises(z3950.Refused):
            session.search("second")
        assert bindings.searched == ["q"]


class TestOneDiagnosticBecomesOneDisposition:
    """`classify` is the whole taxonomy, in one place, so the three cannot drift apart."""

    def test_a_diagnostic_from_the_target_is_a_refusal_carrying_its_code(self):
        error = provisional.classify(*NO_AUTH)
        assert isinstance(error, z3950.Refused)
        assert error.code == 101
        assert "Failed to authenticate user." in str(error)

    def test_a_client_side_failure_is_unreachable(self):
        assert isinstance(provisional.classify(*CONNECT_FAILED), z3950.Unreachable)
        assert isinstance(provisional.classify(*TIMED_OUT), z3950.Unreachable)

    def test_a_query_the_client_could_not_parse_is_ours_and_not_the_targets(self):
        # Classing it as unreachable would blame a catalogue for a bug here. Measured by
        # injecting `@attr 1=4 "moby" @attr 1=4 "dick"`, which never reaches the wire.
        assert isinstance(provisional.classify(*INVALID_QUERY), z3950.BadQuery)

    def test_an_unfamiliar_diagnostic_set_is_read_as_the_targets(self):
        # The test is "is it ours", not a list of theirs: YAZ uses more sets than Bib-1,
        # and enumerating them needs a new arm per target family. Reading an unknown set
        # as the target's is the conservative direction, because a refusal is not worth
        # retrying and an unreachable host is.
        for diagset in ("SRU", "info:srw/diagnostic/1", "HTTP", ""):
            assert isinstance(provisional.classify(7, "whatever", "", diagset), z3950.Refused)


class TestWhatIsNegotiatedAtInit:
    def test_no_records_are_asked_for_in_the_search_response(self):
        # Measured at `libris.kb.se`, `count` of 1 or 10 drew
        # `[1005] Response records in Search response not supported` AND still returned
        # 350 hits and a fetchable record, so a non fatal Bib-1 diagnostic arrived on a
        # search that had worked. Zero is ZOOM's "no records please", not a trick.
        bindings = FakeBindings()
        opened(bindings)
        assert bindings.options["count"] == "0"

    def test_the_piggyback_parameters_are_not_sent(self):
        # They are the protocol's own lever and look more principled. Measured, they buy
        # nothing over `count=0` and cost reliability: with them a record walk on a 444
        # hit result set failed at record 0, where `count=0` alone fetched record 0 in
        # every run. Pinned so nobody adds them back on the strength of the name.
        bindings = FakeBindings()
        opened(bindings)
        for parameter in ("smallSetUpperBound", "largeSetLowerBound", "mediumSetPresentNumber"):
            assert parameter not in bindings.options

    def test_the_size_options_are_sent_even_though_they_are_not_trusted(self):
        # Measured with both at 512, `lx2.loc.gov` returned a 2,227 byte record and no
        # diagnostic. They are sent because they cost nothing, and `z3950.search` counts.
        bindings = FakeBindings()
        opened(bindings)
        assert bindings.options["maximumRecordSize"] == str(z3950.MAX_RESPONSE_BYTES)
        assert bindings.options["preferredMessageSize"] == str(z3950.MAX_RESPONSE_BYTES)

    def test_the_database_comes_from_the_target(self):
        bindings = FakeBindings()
        provisional.ProvisionalYazClient(bindings).open(
            Target(host="h", port=1, database="NKC", syntax=Syntax.UNIMARC), timeout=5.0
        )
        assert bindings.options["databaseName"] == "NKC"

    def test_the_seams_format_is_translated_into_this_clients_wire_spelling(self):
        # `usmarc` is YAZ's word and must not be the seam's: three names for MARC21 were
        # measured across one request and two targets.
        for syntax, wire in ((Syntax.MARC21, "usmarc"), (Syntax.UNIMARC, "unimarc")):
            bindings = FakeBindings()
            provisional.ProvisionalYazClient(bindings).open(
                Target(host="h", port=1, database="d", syntax=syntax), timeout=5.0
            )
            assert bindings.options["preferredRecordSyntax"] == wire

    def test_a_format_that_cannot_be_asked_for_is_refused_rather_than_a_key_error(self):
        # `Syntax.OTHER` is what a target may ANSWER with. A bare KeyError here would
        # surface as a 500 rather than as a source being unavailable.
        bindings = FakeBindings()
        with pytest.raises(z3950.BadQuery):
            provisional.ProvisionalYazClient(bindings).open(
                Target(host="h", port=1, database="d", syntax=Syntax.OTHER), timeout=5.0
            )
        assert bindings.connected == []

    def test_a_sub_second_budget_is_floored_at_one_second(self):
        # ZOOM's own option is whole seconds, so 0 would mean "no bound" rather than
        # "immediately". The real sub second bound is `asyncio.timeout` in z3950.py.
        bindings = FakeBindings()
        provisional.ProvisionalYazClient(bindings).open(TARGET, timeout=0.2)
        assert bindings.options["timeout"] == "1"

    def test_a_longer_budget_is_passed_through(self):
        bindings = FakeBindings()
        provisional.ProvisionalYazClient(bindings).open(TARGET, timeout=8.9)
        assert bindings.options["timeout"] == "8"

    def test_the_association_names_this_application(self):
        bindings = FakeBindings()
        opened(bindings)
        assert bindings.options["implementationName"] == "endpaper"


class TestTheSessionMatchesTheSeam:
    def test_a_search_returns_the_hit_count(self):
        assert opened(FakeBindings(hits=444)).search("q") == 444

    def test_a_record_carries_the_syntax_the_target_labelled_it_with(self):
        bindings = FakeBindings(record_value=("USmarc", b"\x00binary\x00"))
        session = opened(bindings)
        session.search("q")
        record = session.fetch(0)
        # The seam's vocabulary, and the target's own word beside it.
        assert record.syntax is Syntax.MARC21
        assert record.reported == "USmarc"
        # A NUL survives. `ZOOM_record_get` returns `c_void_p` for this reason.
        assert record.raw == b"\x00binary\x00"

    def test_fetching_before_searching_is_an_error_rather_than_a_record(self):
        with pytest.raises(z3950.Z3950Error):
            opened(FakeBindings()).fetch(0)

    def test_a_missing_record_reports_the_diagnostic_that_came_with_it(self):
        # Measured at `z3950.nlg.gr`: the record is null AND `[239]` is set. Reading the
        # null first would lose the reason and report a bare "sent no record", which is
        # the difference between "ask it in UNIMARC" and "something went wrong".
        bindings = FakeBindings(errors=[CLEAN, CLEAN, NO_SYNTAX], record_value=None)
        session = opened(bindings)
        session.search("q")
        with pytest.raises(z3950.Refused) as raised:
            session.fetch(0)
        assert raised.value.code == 239

    def test_a_missing_record_with_no_diagnostic_is_still_a_refusal(self):
        bindings = FakeBindings(record_value=None)
        session = opened(bindings)
        session.search("q")
        with pytest.raises(z3950.Refused):
            session.fetch(0)

    def test_a_second_search_releases_the_first_result_set(self):
        bindings = FakeBindings()
        session = opened(bindings)
        session.search("one")
        session.search("two")
        assert bindings.freed_resultsets == [55]

    def test_closing_releases_both_handles(self):
        bindings = FakeBindings()
        session = opened(bindings)
        session.search("q")
        session.close()
        assert bindings.freed_resultsets == [55]
        assert bindings.freed_connections == [7]

    def test_closing_twice_frees_nothing_twice(self):
        # `association()` closes on the way out and a caller may close as well. A double
        # free through ctypes is a segfault rather than an exception.
        bindings = FakeBindings()
        session = opened(bindings)
        session.close()
        session.close()
        assert bindings.freed_connections == [7]


class TestATargetsLabelIsTranslatedAndKept:
    """Both directions of the vocabulary live here, and neither may leak to the seam."""

    def test_the_two_measured_spellings_of_marc21_mean_the_same_thing(self):
        # `lx2.loc.gov` says `USmarc` and `libris.kb.se` says `MARC21` for identical
        # bytes. A caller comparing raw labels would read those as two formats.
        assert provisional.reported_syntax("USmarc") is Syntax.MARC21
        assert provisional.reported_syntax("MARC21") is Syntax.MARC21
        assert provisional.reported_syntax("UNIMARC") is Syntax.UNIMARC

    def test_the_label_is_matched_without_regard_to_case_or_padding(self):
        assert provisional.reported_syntax("  uSmArC  ") is Syntax.MARC21

    def test_an_unfamiliar_label_is_a_format_and_not_a_failure(self):
        # A target is free to answer in SUTRS, GRS-1 or XML. The caller decides whether
        # it can use it, and `Record.reported` says which it was.
        for label in ("SUTRS", "GRS-1", "XML", ""):
            assert provisional.reported_syntax(label) is Syntax.OTHER


class TestClosingLatchesBecauseTheAlternativeIsASignal:
    """The connection's memory is gone, so a later call reads freed memory.

    Measured: `search()` after `close()` is signal 11. `fetch()` survived only because it
    happens to test the result set handle first, which is an accident of ordering.
    """

    def test_searching_after_a_close_raises(self):
        session = opened(FakeBindings())
        session.close()
        with pytest.raises(z3950.Closed):
            session.search("q")

    def test_searching_after_a_close_never_reaches_the_client(self):
        bindings = FakeBindings()
        session = opened(bindings)
        session.close()
        with pytest.raises(z3950.Closed):
            session.search("q")
        assert bindings.searched == []

    def test_fetching_after_a_close_raises(self):
        bindings = FakeBindings()
        session = opened(bindings)
        session.search("q")
        session.close()
        with pytest.raises(z3950.Closed):
            session.fetch(0)

    def test_a_real_failure_keeps_its_place_over_the_close(self):
        # A caller should see why the association died, not that it was tidied up
        # afterwards.
        bindings = FakeBindings(errors=[CLEAN, CLEAN, NO_SYNTAX, CLEAN], hits=36)
        session = opened(bindings)
        session.search("q")
        with pytest.raises(z3950.Refused):
            session.fetch(0)
        session.close()
        with pytest.raises(z3950.Refused) as raised:
            session.search("q")
        assert raised.value.code == 239


class TestTheCtypesDeclarationsAreComplete:
    """Read from `SIGNATURES` rather than from a loaded library, which is not present.

    An undeclared `restype` defaults to `int`, which truncates a 64 bit pointer, and the
    failure is a segfault rather than an exception. That is the one class of defect here
    a hermetic test can still catch.
    """

    def test_the_record_getter_returns_an_opaque_pointer_and_not_a_string(self):
        # `c_char_p` would make ctypes stop at the first NUL, silently truncating a MARC
        # record and leaving the length in its own leader disagreeing with what arrived.
        declared = {name: restype for name, restype, _ in provisional.SIGNATURES}
        assert declared["ZOOM_record_get"] is ctypes.c_void_p

    def test_every_call_the_binding_makes_is_declared(self):
        source = (
            __import__("pathlib").Path(provisional.__file__).read_text()
        )
        declared = {name for name, _, _ in provisional.SIGNATURES}
        used = {
            line.split("self._lib.")[1].split("(")[0]
            for line in source.splitlines()
            if "self._lib." in line
        }
        assert used - declared == set()
        # And nothing is declared that is never called, so the table cannot rot into a
        # list of names the binding stopped using.
        assert declared - used == set()

    def test_every_pointer_returning_call_is_declared_as_a_pointer(self):
        for name, restype, _ in provisional.SIGNATURES:
            if name.endswith(("_create", "_search_pqf", "_record", "_get")):
                assert restype is ctypes.c_void_p, name


def test_the_client_and_the_session_satisfy_the_seams_protocols():
    """A structural mismatch is a mypy error and would not otherwise fail a test."""
    client: z3950.Client = provisional.ProvisionalYazClient(FakeBindings())
    session: z3950.Session = client.open(TARGET, timeout=1.0)
    assert session.search("q") == 1
