"""Tests for backend/ratelimit.py.

Two layers: the sliding-window counter on its own, and the login/registration
endpoints that use it. Guessing at a library password was unbounded before.
"""

import contextlib
import inspect

import pytest
import respx
from fastapi import HTTPException

from ratelimit import (
    LOGIN_LIMIT,
    MAX_TRACKED_KEYS,
    METADATA_LIMIT,
    REGISTER_LIMIT,
    RateLimit,
    SlidingWindowLimiter,
    login_limiter,
    register_limiter,
)
from tests.helpers import silence_catalogues


class TestSlidingWindowLimiter:
    def test_allows_up_to_the_limit(self):
        limiter = SlidingWindowLimiter(RateLimit(max_attempts=3, window_seconds=60))
        for _ in range(3):
            limiter.check("key")

    def test_rejects_the_next_attempt(self):
        limiter = SlidingWindowLimiter(RateLimit(max_attempts=3, window_seconds=60))
        for _ in range(3):
            limiter.check("key")
        with pytest.raises(HTTPException) as caught:
            limiter.check("key")
        assert caught.value.status_code == 429

    def test_says_how_long_to_wait(self):
        limiter = SlidingWindowLimiter(RateLimit(max_attempts=1, window_seconds=60))
        limiter.check("key")
        with pytest.raises(HTTPException) as caught:
            limiter.check("key")
        assert "Retry-After" in (caught.value.headers or {})

    def test_keys_are_independent(self):
        """One member exhausting their allowance must not lock out another."""
        limiter = SlidingWindowLimiter(RateLimit(max_attempts=1, window_seconds=60))
        limiter.check("alice")
        limiter.check("bob")

    def test_the_window_rolls(self, monkeypatch):
        """A fixed window would let a caller spend the whole allowance at the
        end of one window and again at the start of the next."""
        now = [1000.0]
        monkeypatch.setattr("ratelimit.time.monotonic", lambda: now[0])

        limiter = SlidingWindowLimiter(RateLimit(max_attempts=2, window_seconds=60))
        limiter.check("key")
        limiter.check("key")
        with pytest.raises(HTTPException):
            limiter.check("key")

        now[0] += 61  # the first two attempts have aged out
        limiter.check("key")

    def test_attempts_expire_individually(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr("ratelimit.time.monotonic", lambda: now[0])

        limiter = SlidingWindowLimiter(RateLimit(max_attempts=2, window_seconds=60))
        limiter.check("key")
        now[0] += 30
        limiter.check("key")
        now[0] += 31  # only the first has aged out
        limiter.check("key")
        with pytest.raises(HTTPException):
            limiter.check("key")

    def test_reset_clears_one_key(self):
        limiter = SlidingWindowLimiter(RateLimit(max_attempts=1, window_seconds=60))
        limiter.check("key")
        limiter.reset("key")
        limiter.check("key")

    def test_reset_with_no_key_clears_everything(self):
        limiter = SlidingWindowLimiter(RateLimit(max_attempts=1, window_seconds=60))
        limiter.check("alice")
        limiter.check("bob")
        limiter.reset()
        limiter.check("alice")
        limiter.check("bob")


# Reaching the real limit costs one bcrypt verify per attempt, which dominated
# the runtime of the whole suite. These tests are about the limiter's
# behaviour, so they run against a tighter limit; the configured values are
# pinned separately in TestLimitsAreSane.
TIGHT = RateLimit(max_attempts=2, window_seconds=60)


@pytest.fixture
def tight_login_limit(monkeypatch):
    # Mutates the shared limiter in place rather than rebinding the module
    # attribute: routers/auth.py imported the object by value at import time,
    # so replacing `ratelimit.login_limiter` would not affect the router.
    monkeypatch.setattr(login_limiter, "_limit", TIGHT)


@pytest.fixture
def tight_register_limit(monkeypatch):
    monkeypatch.setattr(register_limiter, "_limit", TIGHT)


class TestLoginRateLimit:
    def test_repeated_wrong_passwords_are_eventually_refused(
        self, client, admin, tight_login_limit
    ):
        for _ in range(TIGHT.max_attempts):
            client.post("/auth/login", json={"username": "admin", "password": "wrong"})
        res = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
        assert res.status_code == 429

    def test_the_refusal_says_when_to_retry(self, client, admin, tight_login_limit):
        for _ in range(TIGHT.max_attempts):
            client.post("/auth/login", json={"username": "admin", "password": "wrong"})
        res = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
        assert "retry-after" in res.headers

    def test_a_different_account_is_unaffected(self, client, admin, member, tight_login_limit):
        """Keyed on the username under attack, so hammering one account does
        not lock the rest of the library out."""
        for _ in range(TIGHT.max_attempts + 2):
            client.post("/auth/login", json={"username": "admin", "password": "wrong"})
        res = client.post("/auth/login", json={"username": "member", "password": "password123"})
        assert res.status_code == 200

    def test_a_successful_login_clears_the_count(self, client, admin, tight_login_limit):
        """Someone who mistypes and then gets it right should not be left
        rationed for the rest of the window."""
        for _ in range(TIGHT.max_attempts - 1):
            client.post("/auth/login", json={"username": "admin", "password": "wrong"})

        assert (
            client.post(
                "/auth/login", json={"username": "admin", "password": "password123"}
            ).status_code
            == 200
        )

        # The allowance is whole again: another full run of wrong attempts is
        # rejected on its merits (401), not refused as over-limit (429).
        for _ in range(TIGHT.max_attempts):
            res = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
        assert res.status_code == 401

    def test_the_limit_applies_to_unknown_usernames_too(self, client, admin, tight_login_limit):
        """Otherwise the limiter is trivially bypassed by spraying names."""
        for _ in range(TIGHT.max_attempts):
            client.post("/auth/login", json={"username": "ghost", "password": "x"})
        res = client.post("/auth/login", json={"username": "ghost", "password": "x"})
        assert res.status_code == 429

    def test_username_keying_is_case_insensitive(self, client, admin, tight_login_limit):
        """Otherwise the same account can be attacked N times per casing."""
        for _ in range(TIGHT.max_attempts):
            client.post("/auth/login", json={"username": "admin", "password": "wrong"})
        res = client.post("/auth/login", json={"username": "ADMIN", "password": "wrong"})
        assert res.status_code == 429


class TestRegisterRateLimit:
    def test_repeated_registrations_are_eventually_refused(self, client, tight_register_limit):
        for index in range(TIGHT.max_attempts):
            client.post(
                "/auth/register", json={"username": f"user{index}", "password": "password123"}
            )
        res = client.post(
            "/auth/register", json={"username": "onemore", "password": "password123"}
        )
        assert res.status_code == 429


class TestLimitsAreSane:
    def test_login_allows_a_few_honest_mistakes(self):
        assert LOGIN_LIMIT.max_attempts >= 5

    def test_login_window_is_short_enough_to_recover_from(self):
        assert LOGIN_LIMIT.window_seconds <= 300

    def test_registration_is_tighter_than_login(self):
        """Signing up is rare; guessing a password is not."""
        register_rate = REGISTER_LIMIT.max_attempts / REGISTER_LIMIT.window_seconds
        login_rate = LOGIN_LIMIT.max_attempts / LOGIN_LIMIT.window_seconds
        assert register_rate < login_rate

    def test_the_shared_limiters_are_the_configured_ones(self):
        assert login_limiter is not register_limiter


class TestTheMetadataLimit:
    """Unlike the others, what this protects is somebody else's server: every
    lookup fans out to as many as eight public catalogues.

    Every source is silenced, so the burst these tests fire never leaves the
    machine. Without that they would be sixty real requests to the DNB.
    """

    ISBN = "9783442267743"

    @pytest.fixture
    def catalogues(self):
        with respx.mock(assert_all_called=False) as mock:
            yield silence_catalogues(mock)

    def _lookup(self, client, account):
        return client.get(
            "/api/books/lookup", params={"isbn": self.ISBN}, headers=account["headers"]
        )

    def test_a_burst_of_lookups_is_cut_off(self, client, admin, catalogues):
        codes = [
            self._lookup(client, admin).status_code
            for _ in range(METADATA_LIMIT.max_attempts + 1)
        ]
        assert codes[-1] == 429
        assert 429 not in codes[:-1]

    def test_one_member_burning_the_quota_does_not_ration_another(
        self, client, admin, member, catalogues
    ):
        for _ in range(METADATA_LIMIT.max_attempts + 1):
            self._lookup(client, admin)

        assert self._lookup(client, member).status_code != 429

    def test_the_search_route_shares_the_same_budget(self, client, admin, catalogues):
        """One budget for the fan-out, not one per route: otherwise alternating
        between them doubles the outbound rate."""
        for _ in range(METADATA_LIMIT.max_attempts):
            self._lookup(client, admin)

        res = client.get("/api/books/search", params={"q": "dune"}, headers=admin["headers"])

        assert res.status_code == 429


class TestTheRateLimitTableInTheDocsIsTheModule:
    """`docs/security.md` states how many counters there are and lists them.

    **A number written in prose does not recount itself**, and that table has
    already been wrong once: it said five and listed four, omitting the
    authority and cover backfill limits entirely. So the number is derived here
    rather than trusted, and the rows are counted too, because a count that is
    right while the table is short is the same failure in a different place.
    """

    #: The heading the table sits under, and the row separator that follows it.
    _SECTION = "## Rate limiting"
    _WORDS = {
        4: "Four",
        5: "Five",
        6: "Six",
        7: "Seven",
        8: "Eight",
        9: "Nine",
        10: "Ten",
    }

    @staticmethod
    def _security_doc() -> str:
        from pathlib import Path

        return (Path(__file__).resolve().parents[2] / "docs" / "security.md").read_text()

    @staticmethod
    def _counters() -> int:
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "ratelimit.py").read_text()
        return source.count("SlidingWindowLimiter(") - source.count(
            "class SlidingWindowLimiter("
        )

    def test_the_module_defines_the_counters_this_rule_counts(self):
        """A guard that inspects nothing reads as coverage. If the module stops
        constructing limiters this way, everything below goes vacuous."""
        assert self._counters() >= 1

    def test_the_stated_number_is_the_number_of_counters(self):
        count = self._counters()
        assert f"**{self._WORDS[count]} counters," in self._security_doc(), (
            f"backend/ratelimit.py constructs {count} limiters. docs/security.md "
            "opens its rate limiting section with a different number."
        )

    def test_the_table_has_a_row_for_every_counter(self):
        """Counted against the table's own rows rather than against a list of
        route names, so a counter given a row that names the wrong route still
        counts and a counter given no row at all does not.

        The table carries one row per **route group**, and login and switch
        share a counter, so the rows are one more than the counters. That
        relationship is asserted rather than the raw number, because it is the
        thing that is true rather than the thing that happens to be.
        """
        section = self._security_doc().split(self._SECTION, 1)[1].split("\n## ", 1)[0]
        # Every table line, minus the header and the separator beneath it.
        rows = [line for line in section.splitlines() if line.startswith("|")][2:]
        assert len(rows) == self._counters() + 1, (
            f"{len(rows)} rows in the docs/security.md rate limit table against "
            f"{self._counters()} counters in backend/ratelimit.py, and login and "
            "switch share one. Every counter needs a row."
        )


def test_every_limiter_in_the_module_is_reset_between_tests():
    """The suite's `reset_rate_limits` fixture has to know about all of them.

    Its own docstring records what happens when it does not: the import limiter
    was added later, and its absence turned twelve unrelated import tests red,
    every one of them passing on its own. That is a whole afternoon, and it is
    detectable in four lines.

    Derived from the module rather than compared against a list, so a limiter
    added tomorrow is caught rather than a list somebody remembered to extend.
    """
    import ratelimit
    from tests import conftest

    limiters = {
        name
        for name, value in vars(ratelimit).items()
        if isinstance(value, ratelimit.SlidingWindowLimiter)
    }
    assert limiters, "No limiters found; this rule now inspects nothing."

    source = inspect.getsource(conftest.reset_rate_limits)
    missing = sorted(name for name in limiters if f"{name}.reset()" not in source)
    assert missing == [], (
        f"These limiters are never reset between tests: {missing}. They are "
        "process global, so one test spending a budget rations every later test "
        "that shares it, and which test fails then depends on ordering."
    )


class TestTheKeyTableIsBounded:
    """The counters are keyed on caller supplied strings, and there was no cap.

    `_prune` read through a `defaultdict`, so a key was created on first sight
    and never removed, even once its window had expired and even when the read
    was a `reset`. Measured before the fix: 100,000 distinct keys retained
    87,774,824 bytes from one request apiece, none of them ever near a limit.
    After it, the same 100,000 retain 3,744,898 bytes across 4,096 entries.
    `login_key` is the sharp case because it embeds the username being attacked,
    which the attacker chooses.

    **The policy at the ceiling is what took two attempts.** Eviction of any
    kind is a bypass over a caller supplied key space: an attacker who chooses
    which keys exist can force any key out, their own included, so least
    recently used evicts the key they stopped touching and oldest window first
    evicts the key they started with. A live record is therefore never
    discarded, and a key the limiter has never seen is refused instead.
    """

    @staticmethod
    def _limiter(max_keys: int = 8, attempts: int = 3, window: int = 3600):
        return SlidingWindowLimiter(
            RateLimit(max_attempts=attempts, window_seconds=window), max_keys=max_keys
        )

    def test_a_key_never_seen_creates_no_entry_when_it_is_only_read(self):
        """A `reset` on an unknown key used to create it, which is the shape
        that made this unbounded through a path that is not even a request."""
        limiter = self._limiter()
        limiter.reset("nobody")
        assert len(limiter._hits) == 0

    def test_a_window_that_has_expired_is_not_a_record(self):
        """Ordinary churn, which is nearly all of it. Asserted through the
        **behaviour** rather than the table: with one attempt allowed, a second
        attempt after the window has to be permitted."""
        limiter = self._limiter(attempts=1, window=0)
        limiter.check("someone")
        limiter.check("someone")  # would raise if the first were still counted

    def test_an_expired_key_is_dropped_rather_than_kept_empty(self, monkeypatch):
        """`_prune`'s half, below capacity where no sweep runs at all.

        This is what keeps ordinary churn cheap: a key whose window has emptied
        is deleted by the check that emptied it, rather than sitting as an empty
        deque until something needs its slot. Asserted below the ceiling on
        purpose, so a passing sweep cannot be what makes it true.

        It used to assert `len <= 1` after twenty keys through a zero length
        window, which was encoding the sweep running on every insert. It does
        not: it runs at capacity, so the honest answer there is "up to the
        ceiling", which the ceiling test already says.
        """
        clock = [0.0]
        monkeypatch.setattr("ratelimit.time.monotonic", lambda: clock[0])
        limiter = self._limiter(max_keys=8, window=60)
        limiter.check("someone")

        clock[0] = 61
        limiter.check("someone")

        assert set(limiter._hits) == {"someone"}
        assert list(limiter._hits["someone"]) == [61]

    def test_a_resident_key_does_not_pin_the_sweep_behind_it(self, monkeypatch):
        """**The denial of service the first version of the sweep shipped.**

        It stopped at the first live key, on the stated invariant that the table
        is in window-start order so expired keys are a prefix. The table is in
        **insertion** order, and the two diverge as soon as a key takes a second
        hit: `hits[0]` is the oldest live hit and advances as `_prune` pops it,
        while an existing key never moves. One warm key at index 0 therefore
        made every dead key behind it unreachable.

        Driven on a clock, with **one** key touched every half window. Measured
        on the broken version at `max_keys=8` and a 60 second window: t=60
        through t=330 all answered a new caller 429 with the table at 8 of 8,
        five windows after keys 1 to 7 expired.

        **A `window=0` fixture cannot show this**, and the test that was here
        used one: with everything expired there is no live key for the walk to
        stop at, so it cannot tell "walks the table" from "stops at the first
        live key". That is the covered-case family this repository keeps
        producing, and it is why this one holds a clock.
        """
        clock = [0.0]
        monkeypatch.setattr("ratelimit.time.monotonic", lambda: clock[0])
        limiter = self._limiter(max_keys=8, attempts=10, window=60)
        for index in range(8):
            limiter.check(f"resident-{index}")

        # Half a window in, every record is still live and a refusal is correct.
        clock[0] = 30
        limiter.check("resident-0")
        with pytest.raises(HTTPException):
            limiter.check("a-new-caller")

        # A full window in, seven of the eight have expired. Only the warm key
        # is still a record, and it must not shield the other seven.
        clock[0] = 60
        limiter.check("resident-0")
        limiter.check("a-new-caller")
        assert set(limiter._hits) == {"resident-0", "a-new-caller"}

    def test_the_sweep_runs_only_when_it_buys_something(self, monkeypatch):
        """Below the ceiling nothing is being kept out, so a dead key costs one
        entry until something needs its slot. The walk is O(n) and the request
        that would otherwise be refused is the one that pays for it."""
        clock = [0.0]
        monkeypatch.setattr("ratelimit.time.monotonic", lambda: clock[0])
        limiter = self._limiter(max_keys=8, window=60)
        limiter.check("goes-stale")
        clock[0] = 120

        limiter.check("second")
        assert "goes-stale" in limiter._hits, "swept below capacity, for nothing"

    def test_the_table_never_grows_past_the_ceiling(self):
        limiter = self._limiter(max_keys=8)
        for index in range(100):
            with contextlib.suppress(HTTPException):
                limiter.check(f"key-{index}")
        assert len(limiter._hits) == 8

    def test_the_ceiling_is_the_backstop_and_not_the_mechanism(self):
        """Under the ceiling nothing is refused, so an ordinary deployment never
        meets any of this."""
        limiter = self._limiter(max_keys=8)
        for index in range(8):
            limiter.check(f"key-{index}")
        assert set(limiter._hits) == {f"key-{index}" for index in range(8)}

    def test_a_full_table_refuses_a_new_key_rather_than_evicting_one(self):
        """**The property the whole policy exists for.** Every counter already
        being tracked survives a flood, so the limit on an account under attack
        cannot be cleared by filling the table around it."""
        limiter = self._limiter(max_keys=4)
        for index in range(4):
            limiter.check(f"live-{index}")

        with pytest.raises(HTTPException) as refused:
            limiter.check("arriving")
        assert refused.value.status_code == 429
        assert set(limiter._hits) == {f"live-{index}" for index in range(4)}

    def test_flooding_cannot_clear_the_flooders_own_counter(self):
        """The attack the policy is named for, driven rather than argued.

        Three attempts is the limit. The attacker spends two on the account,
        floods the table with fresh keys, and comes back: the third attempt has
        to be refused, and it is refused because the record survived rather than
        because the table was full.
        """
        limiter = self._limiter(max_keys=4, attempts=3)
        limiter.check("the-attacked-account")
        limiter.check("the-attacked-account")
        for index in range(50):
            with contextlib.suppress(HTTPException):
                limiter.check(f"junk-{index}")

        assert "the-attacked-account" in limiter._hits
        limiter.check("the-attacked-account")
        with pytest.raises(HTTPException) as refused:
            limiter.check("the-attacked-account")
        assert refused.value.status_code == 429

    def test_a_table_that_filled_once_recovers_by_itself(self, monkeypatch):
        """Without the sweep a table that filled would refuse every new key for
        ever, because nothing else visits a key that is never checked again.

        On a clock rather than a zero length window. The `window=0` version of
        this passed on a sweep that stopped at the first live entry, because
        with everything expired there is never a live entry to stop at.
        """
        clock = [0.0]
        monkeypatch.setattr("ratelimit.time.monotonic", lambda: clock[0])
        limiter = self._limiter(max_keys=4, window=60)
        for index in range(4):
            limiter.check(f"live-{index}")
        with pytest.raises(HTTPException):
            limiter.check("too-early")

        clock[0] = 61
        limiter.check("arriving")
        assert "arriving" in limiter._hits

    def test_every_shipped_limiter_carries_the_ceiling(self):
        """Derived from the module rather than asserted on one of them: a
        limiter constructed with a different cap by a later edit would be
        unbounded again, and nothing else would notice."""
        import ratelimit

        unbounded = sorted(
            name
            for name, value in vars(ratelimit).items()
            if isinstance(value, SlidingWindowLimiter)
            and value._max_keys != MAX_TRACKED_KEYS
        )
        assert unbounded == [], f"These limiters do not carry the ceiling: {unbounded}"
