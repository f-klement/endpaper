"""Tests for backend/ratelimit.py.

Two layers: the sliding-window counter on its own, and the login/registration
endpoints that use it. Guessing at a family password was unbounded before.
"""

import pytest
import respx
from fastapi import HTTPException

from ratelimit import (
    LOGIN_LIMIT,
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
        not lock the rest of the family out."""
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
    lookup fans out to as many as four public catalogues.

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
