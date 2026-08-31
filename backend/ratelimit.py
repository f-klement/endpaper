"""Rate limiting for the credential endpoints, bulk import and metadata lookups.

/auth/login and /auth/register are limited because the thing worth bounding is
the number of guesses someone can make at a token. The library import is
limited for a different reason: it is authenticated, but one call parses a whole
file and writes thousands of rows inside a single transaction, so a member
firing them back to back holds the one SQLite writer against the library. The
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
which is an accepted tradeoff for not adding Redis to a catalogue this size.
"""

import time
from collections import deque
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

# Every metadata call fans out to as many as eight public catalogues, none of
# which the library runs or pays for. One member holding the scan page open
# with a script behind it would spend somebody else's quota and put this
# deployment's address in front of their rate limiter, which is a way to lose
# metadata for everyone. Sixty a minute is far above scanning a shelf by hand
# and far below what would be noticed upstream.
METADATA_LIMIT = RateLimit(max_attempts=60, window_seconds=60)

# The authority files are not the catalogues and their published budget is much
# smaller, so they get their own limit rather than sharing `METADATA_LIMIT`.
#
# lobid's usage policy records **30 complex searches a minute** for the whole of
# its service, and one call to `GET /authors/authority` is one such search.
# `METADATA_LIMIT` is 60 a minute **per member**, so the route ran at twice a
# published budget with one member and further past it with two. That is the
# failure `METADATA_LIMIT`'s own comment describes: putting this deployment's
# address in front of somebody else's rate limiter.
#
# Ten a minute per member, across **two** routes rather than one.
# `GET /authors/authority` spends one, and since 2026-08-28 so does
# `POST /authors/identifiers`. So tidying one author costs two, not one, and
# ten is five authors a minute rather than ten lookups.
#
# **What one of those two spends upstream is not one request, and this comment
# used to imply it was.** It said the confirmation "now reads the confirmed
# record back to keep the cross references it carries", which describes one
# lobid fetch. A confirmation is up to **eight** outbound requests across three
# hosts: one lobid record, four Wikidata (`authority._cross_check` compares
# `P214` and `P213` on the resolve branch, so it is the item lookup, the
# description and two claims), and up to three to VIAF for the six national
# library numbers a GND record does not carry. At ten a minute that is up to
# eighty.
#
# **It is still not raised or split, and the reason is which supplier publishes
# a number, not which one takes the most traffic.** Those are different
# questions and an earlier version of this comment ran them together, saying the
# other two "ride under" lobid. They do not. Per member per minute at this
# ceiling, worst case by route:
#
#   ten lookups, resolve branch   lobid  50   Wikidata 200   VIAF   0
#   ten lookups, search branch    lobid  10   Wikidata 100   VIAF   0
#   ten confirmations             lobid  10   Wikidata  40   VIAF  30
#
# So **lobid is the lightest of the three and Wikidata the heaviest by far**,
# and the ceiling is sized on lobid anyway because lobid is the only one that
# states a budget to be sized against: Wikidata asks for a user agent and a
# reasonable rate rather than a number, and VIAF publishes neither and serves no
# `robots.txt` at all. Sizing on the one supplier that can be exceeded
# measurably, and staying well inside it, is what keeps the two unmeasured ones
# modest as a consequence rather than by assertion.
#
# Splitting the counter would let a member spend ten confirmations *and* ten
# lookups a minute, which is the thing this single counter exists to prevent.
#
# **Not raised to compensate, and the reason is which of lobid's two budgets
# binds.** Its policy allows 6,000 simple lookups a minute and 30 complex
# searches. A confirmation is a record fetch by key, which is a simple lookup and
# is nowhere near anything; a search is a complex one. This counter cannot tell
# them apart, so its ceiling has to be sized for the search: at ten, three
# members searching flat out are 30 and exactly at lobid's figure, and at twenty
# they would be double it. The cost of that is a member working through a long
# list waiting a minute, and the alternative is a stranger's rate limit.
AUTHORITY_LIMIT = RateLimit(max_attempts=10, window_seconds=60)

# One run of the cover backfill fetches up to a hundred images from the same two
# services the metadata limit protects, and it is the one call here that a
# member would reasonably press twice in frustration while the first is still
# running. Six a minute leaves a large library repairable in a few minutes and
# stops a held-down button becoming a fan-out at the image services.
COVER_BACKFILL_LIMIT = RateLimit(max_attempts=6, window_seconds=60)


# The public catalogue, and it is the only limit here whose caller holds no
# session at all. Everything else on this list is either a credential endpoint
# or an authenticated member spending somebody's resources; this one is the
# first surface in the app a stranger can reach, so it is the first that can be
# scraped.
#
# **Keyed on the source address, which is the weakest key in this module**, for
# the reason `client_address` states: X-Forwarded-For is not trusted because the
# client sets it, so behind a reverse proxy every public reader collapses into
# one bucket and this is closer to a global cap than a per client one. That is
# the honest description and it decides the number rather than being an excuse
# for it. A global cap has one failure mode, which is that one scraper can ration
# the catalogue for everybody, and one virtue, which is that it bounds what the
# deployment serves however many addresses the scraper has.
#
# 120 a minute is far above a person reading: a catalogue page is one request
# and a detail page is one more, so a reader turning a page every half second
# stays inside it.
#
# **It does not stop a scrape of the listing, and an earlier version of this
# comment claimed it did while stating the number that refutes it.**
# `MAX_PAGE_SIZE` is 200, not the 50 that comment used, so a catalogue of 3,000
# records is **15 requests** and finishes inside one window. What the ceiling
# actually bounds is the **record by record** read, which is one request per
# book: 3,000 records is 25 minutes of sustained 429s in somebody's logs rather
# than a quiet copy.
#
# That asymmetry is deliberate rather than tolerated. The listing is what the
# catalogue is **for**: a published catalogue is a public document, and rate
# limiting the act of reading it in bulk would be limiting the feature. The
# per record path is where the cost is, because it is one query and one
# serialisation each, and it is the one an indiscriminate crawler takes.
PUBLIC_CATALOGUE_LIMIT = RateLimit(max_attempts=120, window_seconds=60)


#: How many distinct keys one limiter remembers at once.
#:
#: **A bound, because the key is caller supplied on every limiter in this
#: module** and there was none. `_prune` read through a `defaultdict`, so a key
#: was created on first sight and never removed even once its window had
#: expired: measured, 100,000 distinct keys retained 87,774,824 bytes, 877 bytes
#: each, from one request apiece and without any of them ever reaching a limit.
#: `login_key` is the sharp case, because it embeds the username being attacked
#: and an attacker chooses that.
#:
#: Two things fix it and they cover different cases. Expired keys are dropped,
#: which handles ordinary churn and is nearly all of it. This ceiling is the
#: backstop for a burst **inside** one window, where nothing has expired yet,
#: and at it a key the limiter has never seen is refused rather than admitted by
#: evicting somebody else: see `check`.
#:
#: Measured after the bound, the same 100,000 distinct keys retain **3,744,898
#: bytes** across 4,096 entries, 914 bytes each, with the other 95,904 refused:
#: 23x less, and flat rather than growing. The per key figure is larger than the
#: 877 above because what is retained now is the surviving keys rather than the
#: average of all of them.
MAX_TRACKED_KEYS = 4096


class SlidingWindowLimiter:
    """A rolling-window counter per key.

    A fixed window would let a caller spend its whole allowance at the end of
    one window and again at the start of the next, giving double the intended
    rate across the boundary. This keeps the actual timestamps and expires them
    individually, so the limit holds over any window of the given length.
    """

    def __init__(self, limit: RateLimit, max_keys: int = MAX_TRACKED_KEYS) -> None:
        self._limit = limit
        self._max_keys = max_keys
        # A plain dict, and it was an `OrderedDict` while the order was load
        # bearing. Nothing reads the order any more, and leaving the ordered
        # type in place would advertise a guarantee `_sweep` was wrong to rely
        # on once already.
        self._hits: dict[str, deque[float]] = {}

    def _prune(self, key: str, now: float) -> deque[float]:
        """This key's hits inside the window, and **nothing left behind**.

        A `defaultdict` here was the whole defect: reading `self._hits[key]`
        created the entry, so every distinct key ever seen was retained for the
        life of the process even when its window had long expired and even when
        the read was a `reset`. A key whose window has emptied is deleted rather
        than kept as an empty deque, because an expired window is not a record
        of anything.
        """
        hits = self._hits.get(key)
        if hits is None:
            return deque()
        cutoff = now - self._limit.window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if not hits:
            del self._hits[key]
            return deque()
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
        if key in self._hits:
            hits.append(now)
            return

        # A key this limiter is not already tracking. Everything below is about
        # making room for it without ever discarding a record that is still
        # inside its window.
        if len(self._hits) >= self._max_keys:
            # Only at capacity, because the sweep walks the whole table and
            # below the ceiling that walk buys nothing: nothing is being kept
            # out, so a dead key costs one entry until something needs its slot.
            self._sweep(now)

        if len(self._hits) >= self._max_keys:
            # **Refuse rather than evict, and this is the half that took two
            # attempts to get right.** The key space is caller supplied on every
            # limiter here, and `login_key` embeds the attacked username, so an
            # attacker chooses which keys exist. Under *any* eviction policy
            # they can therefore force a chosen key out, their own included:
            # least recently used evicts the key they stopped touching, and
            # oldest window first evicts the key they started with. Both are a
            # bypass wearing a bound's clothes.
            #
            # So a live record is never discarded. When the table is full of
            # windows that have not expired, a key it has never seen is refused
            # instead. That fails closed: the limit on every account already
            # being tracked is untouched, and the cost is that a **new** key
            # waits, for at most one window, while somebody floods. Filling
            # 4,096 live windows is itself visible traffic.
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many attempts. Please wait and try again.",
                headers={"Retry-After": str(self._limit.window_seconds)},
            )

        hits.append(now)
        # The table is in **insertion** order and nothing depends on that.
        # Saying so is the point: an earlier version claimed it was in
        # window-start order and had `_sweep` stop at the first live entry on
        # the strength of it. See `_sweep`.
        self._hits[key] = hits

    def _sweep(self, now: float) -> None:
        """Drop every key whose window has entirely expired.

        **The whole table, with no early exit, and the early exit was a denial
        of service.** It stopped at the first live key on the stated invariant
        that the table is in window-start order so the expired keys are a
        prefix. The table is in **insertion** order, and the two diverge the
        moment a key takes a second hit: `hits[0]` is the oldest *live* hit and
        advances as `_prune` pops it, while an existing key never moves. So one
        resident key that keeps being touched pins the walk at index 0 and every
        dead key behind it becomes unreachable.

        Measured on the version that returned early, `max_keys=8`, a 60 second
        window and **one** key hit every 30 seconds: `t=60` through `t=330` all
        answered a new caller 429 with the table at 8 of 8, and keys 1 to 7 had
        expired at `t=60`. At the shipped ceiling that is 4,096 addresses once
        plus one warm key to make the catalogue refuse every new address, and on
        `login_limiter`, whose key is `username|address` with both halves
        caller-chosen, a sign-in lockout of every member not already in the
        table.

        Walking everything is O(n) and is why the caller only sweeps **at
        capacity**: it is the request that would otherwise be refused that pays
        for the search, and it pays once. Measured at the ceiling with 4,096
        live keys, so the walk finds nothing to drop, which is its worst case:
        **0.306 ms median and 1.262 ms worst** on a refused request, against
        0.0008 ms for a request below capacity, which runs no sweep at all.

        Collected then deleted, because a dict cannot be mutated while it is
        being iterated.
        """
        cutoff = now - self._limit.window_seconds
        dead = []
        for key, hits in self._hits.items():
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if not hits:
                dead.append(key)
        for key in dead:
            del self._hits[key]

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
authority_limiter = SlidingWindowLimiter(AUTHORITY_LIMIT)
cover_backfill_limiter = SlidingWindowLimiter(COVER_BACKFILL_LIMIT)
public_catalogue_limiter = SlidingWindowLimiter(PUBLIC_CATALOGUE_LIMIT)


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
