"""Tests for backend/z3950.py.

The module exists so that a Z39.50 target gets the same treatment `fetch.py` gives an
HTTP one: **bounded in bytes and in time by construction, so no call site has to remember
to ask.** That is what these pin, and everything else here is either a consequence of it
or a distinction the target survey got wrong once and must not get wrong again.

Four of these would be the only warning of a real regression:

* **A term cannot change the query's shape.** `@` followed by a digit is not text: with
  it unescaped, `title_query("@1=1016 harry")` was parsed by YAZ as
  `@attr 1=1016 "harry\\""`, so a member's title replaced the use attribute this module
  pins, and `@1=4 @set someset` referenced a result set. A control character is worse
  again, because escaping cannot reach it: a NUL ends the string at the C boundary.
* **Zero hits is a value and not an exception.** Three dispositions look alike from a
  distance and are not alike at all: unreachable, refused, and answered nothing. Measured
  2026-08-28, `z3950.bne.es` accepts an association and refuses every search with
  `[101] Access-control failure`, and neither that nor a dead host is a catalogue that
  does not hold the book.
* **One association is one clock and one exchange at a time.** A blocking client cannot
  be cancelled, so an abandoned call still owns the connection; and a `Session` holds one
  result set, so two concurrent searches destroy each other's records.
* **A large hit count buys no records.** The search returns a count and the records come
  back only for the positions asked for, so `records` is the whole of the byte cost.

Nothing here opens a socket. Every client is a fake, which is also why this file can run
on a machine with no Z39.50 client installed: `z3950._default_client` is never reached.
"""

import ast
import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

import pytest

import z3950
from z3950 import Answer, Record, Syntax, Target

TARGET = Target(host="catalogue.example", port=210, database="EXAMPLE")


def marc(size: int, *, syntax: Syntax = Syntax.MARC21, reported: str = "USmarc") -> Record:
    """A record of a given size. The bytes are opaque to this module by design."""
    return Record(syntax=syntax, reported=reported, raw=b"x" * size)


@dataclass
class FakeSession:
    """A `z3950.Session` that records what it was asked, in order, and answers a script."""

    hits: int = 1
    records: list[Record] = field(default_factory=lambda: [marc(100)])
    search_error: Exception | None = None
    fetch_error: Exception | None = None
    delay: float = 0.0
    #: Every call in the order the client saw it, which is what shows an interleave.
    log: list[str] = field(default_factory=list)
    closes: int = 0
    close_error: Exception | None = None
    _guard: Lock = field(default_factory=Lock)

    def _record(self, what: str) -> None:
        with self._guard:
            self.log.append(what)

    @property
    def searched(self) -> list[str]:
        return [line.removeprefix("search ") for line in self.log if line.startswith("search ")]

    @property
    def fetched(self) -> list[int]:
        return [int(line.removeprefix("fetch ")) for line in self.log if line.startswith("fetch ")]

    def search(self, pqf: str) -> int:
        self._record(f"search {pqf}")
        if self.delay:
            time.sleep(self.delay)
        if self.search_error is not None:
            raise self.search_error
        return self.hits

    def fetch(self, index: int) -> Record:
        self._record(f"fetch {index}")
        if self.delay:
            time.sleep(self.delay)
        if self.fetch_error is not None:
            raise self.fetch_error
        return self.records[index % len(self.records)]

    def close(self) -> None:
        with self._guard:
            self.closes += 1
        if self.close_error is not None:
            raise self.close_error


@dataclass
class FakeClient:
    """A `z3950.Client` handing out one session, or failing to."""

    session: FakeSession = field(default_factory=FakeSession)
    open_error: Exception | None = None
    open_delay: float = 0.0
    opens: list[tuple[Target, float]] = field(default_factory=list)

    def open(self, target: Target, *, timeout: float) -> FakeSession:
        self.opens.append((target, timeout))
        if self.open_delay:
            time.sleep(self.open_delay)
        if self.open_error is not None:
            raise self.open_error
        return self.session


async def settle(predicate, seconds: float = 5.0) -> None:
    """Wait for work on an association's own thread, which the loop cannot await."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not predicate():
        await asyncio.sleep(0.01)


class TestATermCannotChangeTheQuery:
    """PQF terms carry member input, and getting the escaping wrong does not raise.

    Every parse below was measured on 2026-08-28 with `p_query_rpn` and
    `yaz_rpnquery_to_wrbuf`, which render what YAZ actually built rather than what was
    sent.
    """

    def test_a_plain_term_is_quoted_against_the_use_attribute(self):
        assert z3950.title_query("moby dick") == '@attr 1=4 "moby dick"'

    def test_an_isbn_uses_attribute_seven_and_a_title_uses_four(self):
        assert z3950.isbn_query("9780142437247") == '@attr 1=7 "9780142437247"'
        assert z3950.title_query("x").startswith("@attr 1=4 ")

    def test_a_double_quote_is_escaped_rather_than_closing_the_term(self):
        assert z3950.title_query('moby"dick') == '@attr 1=4 "moby\\"dick"'

    def test_a_backslash_is_escaped_so_a_trailing_one_cannot_eat_the_quote(self):
        assert z3950.title_query("moby dick\\") == '@attr 1=4 "moby dick\\\\"'

    def test_an_at_sign_is_escaped_because_it_can_replace_the_use_attribute(self):
        # **This replaced a test that asserted the opposite.** It said an `@` needs no
        # escaping and is read as text, which is true of `@and` mid term and false of
        # `@` followed by a digit: YAZ tests for an escape character and a digit before
        # the quoted run is read, and without the "preceded by a space" condition that
        # gates the operator keywords. Unescaped, `@1=1016 harry` parsed as
        # `@attr 1=1016 "harry\\""`: the 1=4 this module pins was gone.
        assert z3950.title_query("@1=1016 harry") == '@attr 1=4 "\\@1=1016 harry"'

    def test_an_injected_operator_cannot_reach_the_parser(self):
        # Unescaped this parsed as a two term `@and`, so a title changed the query's
        # shape and not only its terms.
        built = z3950.title_query("@1=4 @and @attr 1=4 aaa @attr 1=4 bbb")
        assert built == '@attr 1=4 "\\@1=4 \\@and \\@attr 1=4 aaa \\@attr 1=4 bbb"'

    def test_an_injected_result_set_reference_cannot_reach_the_parser(self):
        # Unescaped, `@1=4 @set someset` parsed as `@set "someset\\""`.
        assert z3950.title_query("@1=4 @set someset") == '@attr 1=4 "\\@1=4 \\@set someset"'

    def test_escaping_the_at_sign_leaves_an_ordinary_term_alone(self):
        # Measured: `"moby \\@and dick"` and `"moby @and dick"` parse identically, so the
        # fix costs nothing on the benign shape it used to be justified by.
        assert z3950.title_query("moby @and dick") == '@attr 1=4 "moby \\@and dick"'

    def test_a_format_character_from_catalogue_data_is_not_refused(self):
        # An earlier version tested `str.isprintable()`, which is false for `Cf`, so soft
        # hyphen, zero width space and right to left mark were rejected as "a control
        # character". They encode to ordinary UTF-8, none can truncate a C string, and all
        # occur in catalogue data.
        for character in ("\u00ad", "\u200b", "\u200f"):
            assert character in z3950.title_query(f"mo{character}by dick")

    def test_an_unassigned_codepoint_is_not_refused(self):
        # `unicodedata` carries one Unicode version, so refusing `Cn` would reject a
        # character assigned in a newer one than this Python knows about.
        assert "\u0378" in z3950.title_query("mo\u0378by")

    def test_a_non_breaking_space_never_reaches_the_category_test(self):
        # It is `Zs`, and `_WHITESPACE` collapses it a line earlier. Worth pinning because
        # it is the one character whose safety comes from somewhere else.
        assert z3950.title_query("moby\u00a0dick") == '@attr 1=4 "moby dick"'

    def test_a_surrogate_is_refused_because_it_cannot_be_encoded(self):
        # A lone surrogate raises `UnicodeEncodeError` on the `.encode()` that hands the
        # query to the client. That is not a `Z3950Error`, so it would escape every
        # caller's handler as a 500 rather than as a source being unavailable.
        with pytest.raises(z3950.BadQuery):
            z3950.title_query("moby\udc00dick")

    def test_a_control_character_is_refused_because_escaping_cannot_reach_it(self):
        # A NUL is not whitespace, so collapsing leaves it, and the query crosses into C
        # as a NUL terminated string: `title_query("moby\x00dick")` built 21 characters
        # and the parser saw `@attr 1=4 moby`. That is the unbalanced quote failure
        # reached without a quote, so the refusal is on the class.
        for bad in ("moby\x00dick", "moby\x01dick", "moby\x7fdick"):
            with pytest.raises(z3950.BadQuery):
                z3950.title_query(bad)

    def test_ordinary_whitespace_is_collapsed_rather_than_refused(self):
        # Measured inert: a newline inside a quoted term parses as a space, and a stray
        # one in a pasted title is not worth a failure.
        assert z3950.title_query("  moby \n\t dick  ") == '@attr 1=4 "moby dick"'

    def test_an_empty_term_is_refused_here_rather_than_at_the_target(self):
        # Measured: `@attr 1=4 ""` reaches the control and comes back
        # `[1] Permanent system error` from a CQL parser behind it.
        with pytest.raises(z3950.BadQuery):
            z3950.title_query("   ")

    def test_a_term_longer_than_the_bound_is_refused(self):
        with pytest.raises(z3950.BadQuery):
            z3950.title_query("x" * (z3950.MAX_TERM_CHARS + 1))
        assert z3950.title_query("x" * z3950.MAX_TERM_CHARS)

    def test_a_bad_query_is_a_z3950_error_so_one_except_clause_covers_it(self):
        assert issubclass(z3950.BadQuery, z3950.Z3950Error)


class TestATargetsOwnWordsAreNotRepeatedUnbounded:
    def test_a_diagnostic_is_truncated(self):
        refusal = z3950.Refused(1, "Permanent system error", "x" * 5_000)
        assert len(refusal.detail) == z3950.MAX_DIAGNOSTIC_CHARS

    def test_control_characters_in_a_diagnostic_become_spaces(self):
        refusal = z3950.Refused(1, "broken", "line one\nline\x00two")
        assert refusal.detail == "line one line two"

    def test_every_failure_class_sanitises_its_message(self):
        # On the base class rather than at the twelve places one is raised: one forgotten
        # call site is one unbounded log line.
        for failure in (z3950.Unreachable, z3950.BadQuery, z3950.DeadlineExceeded, z3950.Closed):
            assert str(failure("a\x00b " + "y" * 5_000)) == "a b " + "y" * (
                z3950.MAX_DIAGNOSTIC_CHARS - 4
            )


class TestTheThreeDispositionsStayApart:
    """Unreachable, refused and answered nothing are three answers, not one."""

    async def test_answering_nothing_is_a_value_and_not_an_exception(self):
        client = FakeClient(FakeSession(hits=0))
        answer = await z3950.search_once(TARGET, '@attr 1=7 "1"', client=client)
        assert answer == Answer(hits=0, records=())

    async def test_answering_nothing_fetches_no_records(self):
        client = FakeClient(FakeSession(hits=0))
        await z3950.search_once(
            TARGET, '@attr 1=7 "1"', records=z3950.MAX_RECORDS, client=client
        )
        assert client.session.fetched == []

    async def test_an_unreachable_target_propagates_from_the_open(self):
        client = FakeClient(open_error=z3950.Unreachable("[10000] Connect failed"))
        with pytest.raises(z3950.Unreachable):
            await z3950.search_once(TARGET, '@attr 1=7 "1"', client=client)

    async def test_a_refusal_propagates_from_the_search(self):
        client = FakeClient(FakeSession(search_error=z3950.Refused(101, "Access-control failure")))
        with pytest.raises(z3950.Refused) as raised:
            await z3950.search_once(TARGET, '@attr 1=7 "1"', client=client)
        assert raised.value.code == 101

    async def test_a_refusal_propagates_from_a_record_after_a_clean_search(self):
        # Measured at `z3950.nlg.gr`: 36 hits, then `[239] Record syntax not supported`.
        session = FakeSession(hits=36, fetch_error=z3950.Refused(239, "Record syntax not supported"))
        with pytest.raises(z3950.Refused):
            await z3950.search_once(TARGET, '@attr 1=4 "x"', client=FakeClient(session))

    def test_every_failure_shares_one_base_class(self):
        for failure in (
            z3950.Unreachable,
            z3950.Refused,
            z3950.ResponseTooLarge,
            z3950.DeadlineExceeded,
            z3950.BadQuery,
            z3950.Closed,
        ):
            assert issubclass(failure, z3950.Z3950Error)


class TestTheAnswerIsBoundedInBytes:
    async def test_the_records_are_refused_once_they_pass_the_cap(self):
        session = FakeSession(hits=10, records=[marc(60)])
        with pytest.raises(z3950.ResponseTooLarge):
            await z3950.search_once(TARGET, "q", records=5, limit=100, client=FakeClient(session))

    async def test_it_stops_at_the_record_that_crossed_the_cap(self):
        session = FakeSession(hits=10, records=[marc(60)])
        with pytest.raises(z3950.ResponseTooLarge):
            await z3950.search_once(TARGET, "q", records=5, limit=100, client=FakeClient(session))
        # Two fetched: 60 is under 100 and 120 is over. A third would mean the cap is
        # tested after the walk rather than during it.
        assert session.fetched == [0, 1]

    async def test_a_total_exactly_at_the_cap_is_allowed(self):
        session = FakeSession(hits=2, records=[marc(50)])
        answer = await z3950.search_once(
            TARGET, "q", records=2, limit=100, client=FakeClient(session)
        )
        assert sum(len(r.raw) for r in answer.records) == 100

    async def test_the_default_cap_is_the_module_constant(self):
        session = FakeSession(hits=1, records=[marc(z3950.MAX_RESPONSE_BYTES + 1)])
        with pytest.raises(z3950.ResponseTooLarge):
            await z3950.search_once(TARGET, "q", client=FakeClient(session))

    async def test_a_caller_cannot_raise_the_cap_above_the_module_constant(self):
        # A bound a caller can raise is not a bound. Without this,
        # `limit=209_715_200` was accepted and returned 4.8x the maximum, no error.
        with pytest.raises(ValueError):
            await z3950.search_once(
                TARGET, "q", limit=z3950.MAX_RESPONSE_BYTES + 1, client=FakeClient()
            )

    async def test_a_cap_of_nothing_is_refused_rather_than_looping(self):
        with pytest.raises(ValueError):
            await z3950.search_once(TARGET, "q", limit=0, client=FakeClient())

    async def test_the_cap_is_checked_before_the_target_is_asked(self):
        client = FakeClient()
        with pytest.raises(ValueError):
            await z3950.search_once(
                TARGET, "q", limit=z3950.MAX_RESPONSE_BYTES + 1, client=client
            )
        assert client.session.searched == []


class TestALargeHitCountCostsWhatASmallOneCosts:
    """The property the ticket asked for, and it is the protocol's rather than ours.

    A `SearchRequest` answers with a count; records come back only for the positions
    asked for. Measured 2026-08-28, `@attr 1=4 "moby dick"` returns 444 hits at the
    Library of Congress and 350 at LIBRIS, and neither search carries a record.
    """

    async def test_fifty_thousand_hits_fetch_the_records_that_were_asked_for(self):
        session = FakeSession(hits=50_000)
        answer = await z3950.search_once(TARGET, "q", records=1, client=FakeClient(session))
        assert session.fetched == [0]
        assert answer.hits == 50_000
        assert len(answer.records) == 1

    async def test_fewer_hits_than_records_fetches_only_the_hits(self):
        session = FakeSession(hits=2)
        answer = await z3950.search_once(TARGET, "q", records=5, client=FakeClient(session))
        assert session.fetched == [0, 1]
        assert len(answer.records) == 2

    async def test_asking_for_more_than_the_record_bound_is_a_bug_and_not_a_clamp(self):
        # A clamp is silent, and a caller asking for a thousand records has a bug that a
        # smaller number would hide.
        with pytest.raises(ValueError):
            await z3950.search_once(
                TARGET, "q", records=z3950.MAX_RECORDS + 1, client=FakeClient()
            )

    async def test_asking_for_no_records_is_refused(self):
        with pytest.raises(ValueError):
            await z3950.search_once(TARGET, "q", records=0, client=FakeClient())


class TestOneAssociationIsOneClock:
    """`TIMEOUT_SECONDS` says "the open, every search and every record", so it must be."""

    async def test_a_deadline_already_passed_never_opens_an_association(self):
        client = FakeClient()
        with pytest.raises(z3950.DeadlineExceeded) as raised:
            await z3950.search_once(TARGET, "q", deadline=time.monotonic() - 1, client=client)
        # **The wording, not just the class.** The timeout fires on a negative budget too,
        # so deleting the pre-flight check still raises `DeadlineExceeded`; and asserting
        # the client was never called races the executor, which submits before the
        # cancellation lands. Measured both ways across two mutation rounds.
        assert z3950.BEFORE_STARTING in str(raised.value)
        assert z3950.STILL_ANSWERING not in str(raised.value)
        assert client.opens == []

    async def test_every_search_on_one_association_spends_the_same_budget(self):
        # Five searches at 0.2s against a 0.3s association budget must not all succeed.
        # With a budget per call, they did: the recommended path of one open and three
        # searches admitted 10.0 four times over under a constant that says 10.
        client = FakeClient(FakeSession(delay=0.2))
        started = time.monotonic()
        with pytest.raises(z3950.DeadlineExceeded):
            async with z3950.association(
                TARGET, client=client, deadline=time.monotonic() + 0.3
            ) as open_association:
                for _ in range(5):
                    await z3950.search(open_association, "q")
        assert time.monotonic() - started < 1.0

    async def test_a_slow_target_is_released_at_the_deadline_and_not_after_it(self):
        session = FakeSession(delay=2.0)
        started = time.monotonic()
        with pytest.raises(z3950.DeadlineExceeded) as raised:
            await z3950.search_once(
                TARGET, "q", deadline=time.monotonic() + 0.05, client=FakeClient(session)
            )
        assert z3950.STILL_ANSWERING in str(raised.value)
        assert z3950.BEFORE_STARTING not in str(raised.value)
        assert time.monotonic() - started < 1.0

    def test_the_two_ways_a_budget_runs_out_read_differently(self):
        # Through a set rather than `!=`: both are `Final` string literals, so mypy
        # narrows a direct comparison to "non-overlapping equality" and fails the gate on
        # the very check that stops the two collapsing.
        wordings = [z3950.BEFORE_STARTING, z3950.STILL_ANSWERING]
        assert len(set(wordings)) == 2
        assert z3950.STILL_ANSWERING not in z3950.BEFORE_STARTING
        assert z3950.BEFORE_STARTING not in z3950.STILL_ANSWERING

    async def test_a_search_deadline_can_narrow_the_association_but_not_widen_it(self):
        # Measured before this: a 0.5s association ran a search to **t+5.004s** and
        # returned a hit count, ten times its own ceiling, contained live only by the
        # client's socket timeout, which surfaced as `Unreachable [10004] Connection
        # lost`. A bound held by a client accident is not held by the seam.
        client = FakeClient(FakeSession(delay=2.0))
        started = time.monotonic()
        with pytest.raises(z3950.DeadlineExceeded):
            async with z3950.association(
                TARGET, client=client, deadline=time.monotonic() + 0.05
            ) as open_association:
                await z3950.search(
                    open_association, "q", deadline=time.monotonic() + 8.0
                )
        assert time.monotonic() - started < 1.0

    async def test_a_search_deadline_shorter_than_the_association_still_binds(self):
        # Narrowing is composition and must keep working: the fix is `min`, not "ignore".
        client = FakeClient(FakeSession(delay=2.0))
        async with z3950.association(TARGET, client=client) as open_association:
            started = time.monotonic()
            with pytest.raises(z3950.DeadlineExceeded):
                await z3950.search(
                    open_association, "q", deadline=time.monotonic() + 0.05
                )
            assert time.monotonic() - started < 1.0

    async def test_an_association_cannot_be_opened_past_the_module_ceiling(self):
        # The one place the budget is set is the one place it can be set too high, and a
        # ceiling a caller can raise is not a ceiling. Same treatment as `limit` and
        # `records`, which is the other two thirds of this shape.
        client = FakeClient()
        with pytest.raises(ValueError):
            async with z3950.association(
                TARGET, client=client, deadline=time.monotonic() + z3950.TIMEOUT_SECONDS + 1
            ):
                pass
        assert client.opens == []

    async def test_an_association_at_exactly_the_ceiling_is_allowed(self, monkeypatch):
        # **The clock is frozen, because a monotonic one cannot be at a boundary twice.**
        # The obvious spelling computes `time.monotonic() + TIMEOUT_SECONDS` and the module
        # reads the clock again a moment later, so the remaining span is always strictly
        # less than the ceiling and the boundary is never actually reached. Measured: that
        # version passed with the comparison changed from `>` to `>=`, which is the off by
        # one it exists to catch, so it was a fixture named for something it did not test.
        frozen = time.monotonic()
        # Patched on the stdlib module `z3950` imports, not on an attribute of it:
        # `z3950.time` is not an export and mypy refuses to reach through it.
        monkeypatch.setattr(time, "monotonic", lambda: frozen)
        client = FakeClient()
        async with z3950.association(
            TARGET, client=client, deadline=frozen + z3950.TIMEOUT_SECONDS
        ):
            pass
        assert len(client.opens) == 1

    async def test_the_client_is_told_the_remaining_budget_and_not_the_ceiling(self):
        client = FakeClient()
        await z3950.search_once(TARGET, "q", deadline=time.monotonic() + 1.5, client=client)
        _, timeout = client.opens[0]
        assert 0 < timeout <= 1.5

    async def test_no_deadline_falls_back_to_the_module_ceiling(self):
        client = FakeClient()
        await z3950.search_once(TARGET, "q", client=client)
        _, timeout = client.opens[0]
        assert timeout <= z3950.TIMEOUT_SECONDS


class TestAnAssociationIsNeverLeftBehind:
    """A blocking client cannot be cancelled, so nothing may be abandoned unowned."""

    async def test_it_is_released_on_the_way_out(self):
        client = FakeClient()
        async with z3950.association(TARGET, client=client):
            pass
        await settle(lambda: client.session.closes == 1)
        assert client.session.closes == 1

    async def test_it_is_released_when_the_body_raises(self):
        client = FakeClient()
        with pytest.raises(RuntimeError):
            async with z3950.association(TARGET, client=client):
                raise RuntimeError("boom")
        await settle(lambda: client.session.closes == 1)
        assert client.session.closes == 1

    async def test_a_session_that_arrives_after_a_timed_out_open_is_still_closed(self):
        # **The leak this class exists for.** The open times out, the caller is released,
        # and the client keeps working because a thread cannot be cancelled. Measured
        # before the fix: sessions built 1, closed 0, which is a connection and a socket
        # for the life of the process.
        client = FakeClient(open_delay=0.3)
        with pytest.raises(z3950.DeadlineExceeded):
            async with z3950.association(
                TARGET, client=client, deadline=time.monotonic() + 0.05
            ):
                pass
        await settle(lambda: client.session.closes == 1)
        assert client.session.closes == 1

    async def test_a_session_arriving_after_an_outer_cancellation_is_still_closed(self):
        # **The door a fan out actually takes.** An outer deadline cancels this coroutine,
        # and that arrives as `CancelledError`, never as this module's own `TimeoutError`:
        # `metadata.SEARCH_DEADLINE_SECONDS` is 4.0 against a 10.0s ceiling, so the outer
        # clock always expires first. Measured before the fix, under
        # `asyncio.timeout(0.05)`: 3 of 3 runs left a live connection handle 3.0s later.
        client = FakeClient(open_delay=0.3)
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.05):
                async with z3950.association(TARGET, client=client):
                    pass
        await settle(lambda: client.session.closes == 1)
        assert client.session.closes == 1

    async def test_an_open_that_fails_outright_still_shuts_its_thread_down(self):
        # The same arm carries the ordinary failure, where the client raised rather than
        # being cancelled. Nothing to close, and the executor must still go.
        client = FakeClient(open_error=z3950.Unreachable("[10000] Connect failed"))
        with pytest.raises(z3950.Unreachable):
            async with z3950.association(TARGET, client=client):
                pass
        assert client.session.closes == 0

    async def test_releasing_does_not_wait_for_the_close(self):
        # Awaiting it measured 3.007s against a 0.500s deadline. The single worker thread
        # is what orders the close, not a wait, so this returns immediately.
        client = FakeClient(FakeSession(close_error=None))
        client.session.delay = 0.0
        started = time.monotonic()
        async with z3950.association(TARGET, client=client):
            pass
        assert time.monotonic() - started < 0.5

    async def test_a_failing_close_does_not_replace_the_bodys_exception(self):
        client = FakeClient(FakeSession(close_error=RuntimeError("stuck")))
        with pytest.raises(ValueError):
            async with z3950.association(TARGET, client=client):
                raise ValueError("the real failure")

    async def test_a_failing_close_alone_is_swallowed(self):
        client = FakeClient(FakeSession(close_error=RuntimeError("stuck")))
        async with z3950.association(TARGET, client=client):
            pass

    async def test_one_association_serves_several_searches(self):
        # Measured 2026-08-28: opening one to `lx2.loc.gov:210` costs 0.204s, which is
        # 5.1% of the 4.0s fan out budget and is paid once rather than per query.
        client = FakeClient()
        async with z3950.association(TARGET, client=client) as open_association:
            for _ in range(3):
                await z3950.search(open_association, "q")
        assert len(client.opens) == 1
        assert len(client.session.searched) == 3

    async def test_work_after_a_release_raises_rather_than_reaching_the_client(self):
        # A client that has released its connection has freed memory, so this path is a
        # signal rather than an exception: measured, `search()` after `close()` is
        # signal 11.
        client = FakeClient()
        async with z3950.association(TARGET, client=client) as open_association:
            pass
        with pytest.raises(z3950.Closed):
            await z3950.search(open_association, "q")
        assert client.session.searched == []

    async def test_a_later_call_reports_why_the_association_ended(self):
        # **The latch stores the reason, and `_session is None` does not.** Without this
        # a mutation removing the latch survived, because the missing session raised
        # `Closed` anyway and the test could not tell the two apart. "Abandoned at a
        # deadline" and "closed normally" are different things to read in a log.
        session = FakeSession(delay=1.0)
        async with z3950.association(TARGET, client=FakeClient(session)) as abandoned:
            with pytest.raises(z3950.DeadlineExceeded):
                await z3950.search(abandoned, "slow", deadline=time.monotonic() + 0.05)
            with pytest.raises(z3950.Closed) as raised:
                await z3950.search(abandoned, "after")
        assert z3950.STILL_ANSWERING in str(raised.value)

        client = FakeClient()
        async with z3950.association(TARGET, client=client) as released:
            pass
        with pytest.raises(z3950.Closed) as closed:
            await z3950.search(released, "after")
        assert "was closed" in str(closed.value)

    async def test_work_after_an_abandonment_raises_too(self):
        session = FakeSession(delay=1.0)
        async with z3950.association(TARGET, client=FakeClient(session)) as open_association:
            with pytest.raises(z3950.DeadlineExceeded):
                await z3950.search(
                    open_association, "slow", deadline=time.monotonic() + 0.05
                )
            with pytest.raises(z3950.Closed):
                await z3950.search(open_association, "after")
        assert session.searched == ["slow"]


class TestOneExchangeAtATime:
    """A `Session` holds one result set, so two searches through it destroy each other.

    Measured over eight concurrent pairs on one association before the lock: five bogus
    `Unreachable`, two `Answer(hits=0)` on a query that returns 444 run serially, and one
    SIGSEGV. A wrong zero is the disposition the session's latch exists to prevent.
    """

    async def test_a_second_search_cannot_land_between_a_search_and_its_records(self):
        session = FakeSession(hits=2, delay=0.01)
        async with z3950.association(TARGET, client=FakeClient(session)) as open_association:
            await asyncio.gather(
                z3950.search(open_association, "one", records=2),
                z3950.search(open_association, "two", records=2),
            )
        first, second = sorted([session.log[:3], session.log[3:]])
        assert first == ["search one", "fetch 0", "fetch 1"]
        assert second == ["search two", "fetch 0", "fetch 1"]

    async def test_both_concurrent_searches_get_their_own_records(self):
        session = FakeSession(hits=2, delay=0.01)
        async with z3950.association(TARGET, client=FakeClient(session)) as open_association:
            answers = await asyncio.gather(
                z3950.search(open_association, "one", records=2),
                z3950.search(open_association, "two", records=2),
            )
        assert [a.hits for a in answers] == [2, 2]
        assert [len(a.records) for a in answers] == [2, 2]


class TestTheRecordIsReadOffTheResponse:
    async def test_the_syntax_is_the_targets_label_and_not_the_request(self):
        # Measured: `libris.kb.se` answers a request for UNIMARC with MARC21, labelled
        # MARC21. A caller that trusts `Target.syntax` is wrong on the first such record.
        target = Target(host="h", port=210, database="d", syntax=Syntax.UNIMARC)
        session = FakeSession(records=[marc(10, syntax=Syntax.MARC21, reported="MARC21")])
        answer = await z3950.search_once(target, "q", client=FakeClient(session))
        assert answer.records[0].syntax is Syntax.MARC21
        assert target.syntax is Syntax.UNIMARC

    async def test_the_label_the_target_used_is_kept_verbatim_beside_it(self):
        # Three spellings of MARC21 were measured across two targets and one request:
        # `usmarc`, `MARC21` and `USmarc`. The enum is what a caller compares; this is
        # what a caller reads when it wants to know which target said what.
        session = FakeSession(records=[marc(10, reported="USmarc")])
        answer = await z3950.search_once(TARGET, "q", client=FakeClient(session))
        assert answer.records[0].reported == "USmarc"

    def test_the_seam_names_the_format_so_a_caller_has_something_to_compare(self):
        # `Record.syntax`'s docstring tells a caller to test the field. Without a shared
        # vocabulary that instruction has nothing to test against, and
        # `record.syntax == target.syntax` is wrong even on an honoured request.
        assert Target(host="h", port=1, database="d").syntax is Syntax.MARC21
        assert {Syntax.MARC21, Syntax.UNIMARC, Syntax.OTHER} == set(Syntax)

    async def test_the_bytes_are_passed_through_untouched(self):
        # MARC21 is binary and self describing: the leader's first five characters are the
        # record's own length. Any decoding or trimming here breaks the mapping downstream
        # and makes the leader disagree with what arrived.
        raw = b"00042cam a2200000 a 4500\x1frecord\x00with a nul\x1e\x1d"
        session = FakeSession(records=[Record(syntax=Syntax.MARC21, reported="USmarc", raw=raw)])
        answer = await z3950.search_once(TARGET, "q", client=FakeClient(session))
        assert answer.records[0].raw == raw


class TestTheProvisionalClientIsReachedOnlyThroughTheSeam:
    """One import site, so swapping the route is a change to one function.

    **Blind spots, listed rather than left to be found.** A module name assembled at
    runtime from pieces (`"z3950_" + "provisional"`) is not caught, and neither is one
    read from a file. Both are visible in review and neither has ever been written here;
    what this catches is the ordinary import, in every spelling of it, and the string
    form `importlib.import_module` and `__import__` take.
    """

    MODULE = "z3950_provisional"

    def backend_modules(self) -> list[Path]:
        root = Path(__file__).resolve().parent.parent
        # **Resolved paths, not basenames.** Excluding by name skipped any file called
        # `z3950.py` anywhere under `backend/`, so a copy in a subpackage would have been
        # exempt from the rule for its name alone.
        exempt = {(root / name).resolve() for name in (f"{self.MODULE}.py", "z3950.py")}
        found = [
            path
            for path in sorted(root.rglob("*.py"))
            if "tests" not in path.parts
            and ".venv" not in path.parts
            and path.resolve() not in exempt
        ]
        # A count that cannot go to zero without failing: a rglob that stops matching
        # would otherwise make this whole class pass by checking nothing.
        assert len(found) > 20, found
        return found

    def test_no_backend_module_but_the_seam_imports_it(self):
        offenders = []
        for path in self.backend_modules():
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Import | ast.ImportFrom):
                    continue
                names = [alias.name for alias in node.names]
                if isinstance(node, ast.ImportFrom):
                    names.append(node.module or "")
                if self.MODULE in names:
                    offenders.append(f"{path.name}:{node.lineno}")
        assert offenders == []

    def test_no_backend_module_names_it_in_a_string_either(self):
        # `importlib.import_module("z3950_provisional")` is not an `Import` node.
        offenders = []
        for path in self.backend_modules():
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and node.value == self.MODULE:
                    offenders.append(f"{path.name}:{node.lineno}")
        assert offenders == []

    def test_the_seam_itself_does_import_it(self):
        # Otherwise the two tests above pass with the module deleted, and this class
        # would be guarding nothing at all.
        #
        # **An `ast` check and not a substring one.** `z3950.py`'s own docstring names
        # this module, so a text search would keep passing with the import gone: the
        # guard would then be asserting that a docstring quotes itself, which is a shape
        # this repository has shipped before.
        tree = ast.parse(Path(z3950.__file__).read_text())
        imported = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import | ast.ImportFrom)
            for alias in node.names
        ] + [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert self.MODULE in imported


def import_time_names(node: ast.AST) -> list[str]:
    """Every module and symbol imported when a file is executed.

    **Descends into everything except a function body**, because a class body, an `if`, a
    `try` and a `with` all run at import. Reading `tree.body` alone missed four of five
    module scope shapes, including
    `with contextlib.suppress(ImportError): import z3950_provisional`, which is exactly
    what somebody writes to make a dependency optional and which does load it.
    """
    names: list[str] = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if isinstance(child, ast.Import | ast.ImportFrom):
            names += [alias.name for alias in child.names]
            if isinstance(child, ast.ImportFrom):
                names.append(child.module or "")
        names += import_time_names(child)
    return names


class TestTheModuleCanBeImportedWithNoClientInstalled:
    def test_importing_the_seam_loads_no_shared_library(self):
        # `_default_client` imports the client, which loads YAZ. Doing that at import
        # time would make every machine without YAZ unable to import this, the suite's
        # machines included.
        at_import = import_time_names(ast.parse(Path(z3950.__file__).read_text()))
        assert "ctypes" not in at_import
        assert "z3950_provisional" not in at_import

    def test_the_walk_sees_past_the_top_level_statement_list(self):
        # The guard above is only as good as this: `tree.body` alone is not a scope.
        hidden = ast.parse(
            "import contextlib\n"
            "with contextlib.suppress(ImportError):\n"
            "    import z3950_provisional\n"
        )
        assert "z3950_provisional" in import_time_names(hidden)

    def test_the_walk_sees_a_branch_that_is_not_the_body(self):
        # `node.body` is not the same as every child: an `else:` is `orelse`, and a
        # `try/except` puts its imports in `handlers` and `finalbody`. A walk over `body`
        # alone misses all three and passes the fixture above, which is why that one is
        # not enough on its own.
        for source in (
            "if False:\n    pass\nelse:\n    import z3950_provisional\n",
            "try:\n    pass\nexcept ImportError:\n    import z3950_provisional\n",
            "try:\n    pass\nfinally:\n    import z3950_provisional\n",
        ):
            assert "z3950_provisional" in import_time_names(ast.parse(source)), source

    def test_the_walk_ignores_a_deferred_import(self):
        # And it must not flag the door it exists to promote: `_default_client` imports
        # inside a function, which is the correct shape.
        deferred = ast.parse("def load():\n    import z3950_provisional\n    return 1\n")
        assert "z3950_provisional" not in import_time_names(deferred)


class TestTheBoundsAgreeWithEachOther:
    def test_the_record_bound_fits_a_target_inside_the_fan_out_budget(self):
        # Measured 2026-08-28 at `lx2.loc.gov:210/LCDB`, stable to two decimal places
        # across four option sets: 5 records 0.62s, 10 records 1.30s, 20 records 2.70s,
        # against `metadata.SEARCH_DEADLINE_SECONDS` of 4.0 for the WHOLE fan out across
        # seven sources. 5 spends 15% of it on one target; 20 would spend two thirds.
        import metadata

        seconds_for_the_bound = 0.62
        assert seconds_for_the_bound < metadata.SEARCH_DEADLINE_SECONDS / 4
        assert z3950.MAX_RECORDS == 5

    def test_the_bound_is_not_derived_from_where_a_walk_stops_working(self):
        # `[13] Present request out of range` arrives at a position that moved between
        # runs of the identical request: 43, 23, 11, 36 and 0. A margin against a number
        # that moved from 43 to 0 is not a margin, and an earlier version of this class
        # asserted one. It is a target condition, so it is `Refused` and nothing else.
        assert issubclass(z3950.Refused, z3950.Z3950Error)

    def test_the_record_bound_times_the_largest_measured_record_fits_the_byte_bound(self):
        # LIBRIS, the fattest record measured on 2026-08-28, at 32,565 bytes. The byte
        # argument agrees with the time one and does not drive it.
        largest_measured = 32_565
        assert z3950.MAX_RECORDS * largest_measured < z3950.MAX_RESPONSE_BYTES

    def test_the_byte_bound_matches_the_http_door(self):
        # One hostile source costs the same whichever transport it is reached over, so
        # the worst case worked out for a fan out does not have to be worked out twice.
        import fetch

        assert z3950.MAX_RESPONSE_BYTES == fetch.MAX_RESPONSE_BYTES

    def test_the_time_ceiling_is_above_the_fan_out_budget_it_serves(self):
        import metadata

        assert z3950.TIMEOUT_SECONDS > metadata.SEARCH_DEADLINE_SECONDS


async def test_the_event_loop_is_not_blocked_while_a_client_works():
    """The client is blocking, so it has to run off the loop or a fan out serialises.

    Each association costs 0.6s of its own: the fake sleeps 0.3s in the search and 0.3s
    in the record. Two of them in parallel are therefore about 0.6s and two of them
    serialised would be about 1.2s, so the bound sits between the two and not near either.
    """
    clients = [FakeClient(FakeSession(delay=0.3)) for _ in range(2)]
    started = time.monotonic()
    await asyncio.gather(*(z3950.search_once(TARGET, "q", client=c) for c in clients))
    assert time.monotonic() - started < 0.9
