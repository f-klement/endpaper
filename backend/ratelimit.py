"""Rate limiting for the credential endpoints, bulk import and metadata lookups.

/auth/login and /auth/register are limited because the thing worth bounding is
the number of guesses someone can make at a token. The library import is
limited for a different reason: it is authenticated, but one call parses a whole
file and writes thousands of rows inside a single transaction, so a member
firing them back to back holds the one SQLite writer against the household. The
metadata routes are limited for a third reason again: the cost of a call lands
on somebody else's server.

**Why this is hand-rolled rather than slowapi.** The useful key for a login
limit is the *username being attempted*, and a middleware-style limiter cannot
see it: its key function runs before the request body is parsed. Keying on the
source address instead is worse than it looks here, because the app sits behind
a reverse proxy: every request appears to come from the proxy, so the limit is
either effectively global or depends on `X-Forwarded-For`, a header the client
sets and can therefore rotate to evade the limit. A username cannot be rotated:
it is the thing being attacked. So the check happens inside the handler, where
the username is known.

Storage is in-process, which suits a single-container, single-worker app: there
is no second process to share counters with. Restarting clears the windows,
which is an accepted tradeoff for not adding Redis to a household bookshelf.
"""

import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import HTTPException, Request, status


@dataclass(frozen=True)
class RateLimit:
    """`max_attempts` within a rolling window of `window_seconds`."""

    max_attempts: int
    window_seconds: int


# Generous enough that someone mistyping a password is unaffected, tight enough
# that guessing is hopeless: 10 tries a minute is ~14k a day against a single
# account, against a keyspace that dwarfs it.
LOGIN_LIMIT = RateLimit(max_attempts=10, window_seconds=60)
REGISTER_LIMIT = RateLimit(max_attempts=5, window_seconds=3600)

# An import parses a whole file and writes thousands of rows inside one
# transaction, which holds the single SQLite writer for its duration. Nobody
# migrates a library twice in a minute; somebody firing them back to back would
# wedge the database for everyone else.
IMPORT_LIMIT = RateLimit(max_attempts=3, window_seconds=60)

# Every metadata call fans out to as many as four public catalogues, none of
# which the household runs or pays for. One member holding the scan page open
# with a script behind it would spend somebody else's quota and put this
# deployment's address in front of their rate limiter, which is a way to lose
# metadata for everyone. Sixty a minute is far above scanning a shelf by hand
# and far below what would be noticed upstream.
METADATA_LIMIT = RateLimit(max_attempts=60, window_seconds=60)


class SlidingWindowLimiter:
    """A rolling-window counter per key.

    A fixed window would let a caller spend its whole allowance at the end of
    one window and again at the start of the next, giving double the intended
    rate across the boundary. This keeps the actual timestamps and expires them
    individually, so the limit holds over any window of the given length.
    """

    def __init__(self, limit: RateLimit) -> None:
        self._limit = limit
        self._hits: defaultdict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits[key]
        cutoff = now - self._limit.window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
        return hits

    def check(self, key: str) -> None:
        """Record an attempt for `key`, or raise 429 if it is over the limit."""
        now = time.monotonic()
        hits = self._prune(key, now)
        if len(hits) >= self._limit.max_attempts:
            retry_after = int(self._limit.window_seconds - (now - hits[0])) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many attempts. Please wait and try again.",
                headers={"Retry-After": str(retry_after)},
            )
        hits.append(now)

    def reset(self, key: str | None = None) -> None:
        """Forget a key's history. Called after a successful login, so getting
        it right does not leave you rationed. With no key, clears everything
        (used to isolate tests from one another)."""
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)


login_limiter = SlidingWindowLimiter(LOGIN_LIMIT)
register_limiter = SlidingWindowLimiter(REGISTER_LIMIT)
import_limiter = SlidingWindowLimiter(IMPORT_LIMIT)
metadata_limiter = SlidingWindowLimiter(METADATA_LIMIT)


def client_address(request: Request) -> str:
    """Best-effort source address, used only where no better key exists.

    Deliberately does NOT trust X-Forwarded-For: the client sets it, so
    honouring it would let an attacker rotate the header to reset their own
    limit. Behind a proxy this collapses to the proxy's address, making the
    registration limit closer to global than per-client. Acceptable, because
    registration is a rare action and often disabled outright.
    """
    return request.client.host if request.client else "unknown"


def login_key(username: str, request: Request) -> str:
    """Key on the attacked username, plus the address so that one member
    mistyping their password does not ration the account for everyone."""
    return f"{username.lower()}|{client_address(request)}"
