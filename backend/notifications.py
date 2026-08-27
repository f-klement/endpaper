"""Chasing overdue loans, by posting a digest to a webhook.

A generic outbound webhook rather than email or an integration with one chat
service. A self-hosted app that other libraries run should not carry an
integration with something nobody else runs, and a webhook is the one shape
every receiver already speaks: a chat bridge, a home automation flow, or a
five-line script.

**Private books are excluded.** A webhook has no member identity behind it and
lands in a channel everyone here reads, so putting a private book's title
through it defeats the single promise the data model makes. The in-app overdue
view is per member and already scoped, so the owner still gets chased there.
See `docs/decisions.md` and `docs/security.md`.

The reminder interval is the library's, not this module's. Handy Library's
named differentiator in this space is configurable timing, and it is the right
one to copy: a week is nagging in one house and silence in another.

Not Koha's `--triggered` shape, which fires only when a loan is overdue by
exactly the configured number of days and therefore sends nothing at all if the
run is missed. State on the loan (`notified_at`) plus an interval is robust to a
skipped tick, which matters here because the ticker lives in the web process and
dies with a restart.
"""

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.sql.elements import ColumnElement

import settings_store
from database import SessionLocal
from enums import OverdueNotifyReason, SettingKey
from models import Book, Loan
from schemas.settings import MAX_REMINDER_DAYS, MIN_REMINDER_DAYS

logger = logging.getLogger("endpaper.notifications")

#: The receiver is somebody's own script or bridge, so it is allowed to be slow,
#: but not allowed to hold this process open. The ticker is one task; a hung
#: request would stop every later run, not only this one.
#:
#: **Passed to httpx *and* wrapped in `asyncio.timeout`, because httpx's is per
#: operation.** A receiver dribbling its status line one byte at a time restarts
#: httpx's read clock on every byte and holds the ticker open indefinitely,
#: which is the exact thing the paragraph above says this constant prevents.
#: Measured on httpx 0.28.1, twenty trickled bytes took 18.0s under a 1.0s
#: timeout. `fetch.TIMEOUT_SECONDS` carries the same note for the same reason.
TIMEOUT_SECONDS = 10.0

#: How often the background task looks. Hourly rather than daily, so a
#: library that sets a one day interval gets a reminder within an hour of it
#: coming due rather than at whatever time the container last restarted.
TICK_SECONDS = 60 * 60

EVENT_NAME = "overdue_loans"
SIGNATURE_HEADER = "X-Endpaper-Signature"


class WebhookRefused(Exception):
    """The destination is not one this app will post to."""


def checked_url(raw: str) -> str:
    """The webhook URL, if it is one at all.

    Checked here as well as in `SettingsUpdate`, and the duplication is the
    point: the schema guards the one writer that goes through it, and a restore
    writes the settings table straight through Core. This is the check that
    still runs for a row nobody validated.

    It refuses a scheme, not a destination. An admin can aim this inside the
    cluster, and that is an admin-to-admin capability of the same class as
    restore; a blocklist of private ranges would look like a control without
    being one, since DNS resolves after the check. `docs/security.md` says so
    rather than pretending otherwise.
    """
    trimmed = (raw or "").strip()
    if not trimmed:
        raise WebhookRefused("No webhook URL is configured.")
    parsed = urlparse(trimmed)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise WebhookRefused("The webhook URL must start with http:// or https://")
    return trimmed


def _host(url: str) -> str:
    """The host, for a log line. **Never the URL**: it may carry a token.

    Slack, Discord and every "post here" integration put the credential in the
    path or the query string, so logging the destination on a failure is how a
    secret ends up in a log aggregator.
    """
    try:
        return urlparse(url).hostname or "unknown"
    except ValueError:
        return "unknown"


def reminder_days(db: Session) -> int:
    return settings_store.get_int(
        db,
        SettingKey.OVERDUE_REMINDER_DAYS,
        minimum=MIN_REMINDER_DAYS,
        maximum=MAX_REMINDER_DAYS,
    )


def _overdue_clauses(now: datetime) -> list[ColumnElement[bool]]:
    """What makes a loan overdue and still worth looking at, in one place.

    Two callers ask this question, and restating it in both is how they drift.
    They already had: the private count carried a `notified_at` clause copied
    from the digest, where it does not belong, and under-reported because of it.
    """
    return [
        Loan.returned_at.is_(None),
        Loan.due_at.isnot(None),
        Loan.due_at < now,
        Book.deleted_at.is_(None),
    ]


def due_for_reminder(db: Session, now: datetime, days: int) -> list[Loan]:
    """Open loans past their date that nothing has chased recently.

    The two clauses on top of `_overdue_clauses` are the two this query owns.

    Privacy: `.is_(False)` rather than `not Book.is_private`, for the reason
    `visible_to` states. The latter collapses to a constant and matches every
    row, which here would ship every private title. Excluded **in the query**,
    not filtered out afterwards, so a counting mistake downstream cannot put
    one in the payload.

    The reminder interval: never notified, or notified longer ago than the
    interval. That is the whole state this feature keeps.
    """
    cutoff = now - timedelta(days=days)
    return (
        db.query(Loan)
        .join(Book, Loan.book_id == Book.id)
        .options(joinedload(Loan.book), joinedload(Loan.loaned_to))
        .filter(
            *_overdue_clauses(now),
            Book.is_private.is_(False),
            (Loan.notified_at.is_(None)) | (Loan.notified_at < cutoff),
        )
        .order_by(Loan.due_at, Loan.id)
        .all()
    )


def count_private_overdue(db: Session, now: datetime) -> int:
    """How many overdue loans the privacy exclusion held back.

    A count, never a title. Reported so a library that expects five entries
    and receives four can see why without reading the source.

    **No reminder interval here, and that is the difference from
    `due_for_reminder`.** A private book is never sent, so nothing in this
    feature ever stamps its `notified_at`; the only way one carries a value is
    a book that was public when a reminder went out and was made private
    afterwards. Filtering on it therefore hid exactly those from the count for
    the length of the interval, and the answer to "how many did privacy hold
    back" does not depend on when anything was last sent.

    It takes no `days` for the same reason: a parameter nothing reads is a
    parameter the next caller passes wrongly.
    """
    return (
        db.query(Loan)
        .join(Book, Loan.book_id == Book.id)
        .filter(*_overdue_clauses(now), Book.is_private.is_(True))
        .count()
    )


def build_digest(loans: list[Loan], now: datetime) -> dict[str, Any]:
    """One JSON object describing every loan worth chasing.

    One request per run rather than one per loan: the receiver is a channel,
    and eight separate messages about eight books is the behaviour people turn
    off. `days_overdue` is computed here rather than left to the receiver, so a
    three-line script can render a useful line without doing date arithmetic.
    """
    return {
        "event": EVENT_NAME,
        "generated_at": now.isoformat(),
        "count": len(loans),
        "loans": [
            {
                "loan_id": loan.id,
                "book_id": loan.book_id,
                "title": loan.book.title if loan.book else "",
                # A member's username, or the free-text name of somebody with
                # no account. Exactly one of the two is set; see
                # `ck_loans_one_borrower`.
                "borrower": (
                    loan.loaned_to.username if loan.loaned_to else loan.loaned_to_name
                ),
                "due_at": loan.due_at.isoformat() if loan.due_at else None,
                "days_overdue": (now - loan.due_at).days if loan.due_at else 0,
            }
            for loan in loans
        ],
    }


def sign(body: bytes, secret: str) -> str:
    """`sha256=<hex>`, over the **raw body** the receiver will read.

    Over the bytes rather than over a re-serialised dict, because the receiver
    verifies what arrived on the wire and any difference in key order or
    separators makes an honest payload fail its own signature.
    """
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def post_digest(url: str, body: bytes, secret: str) -> None:
    """POST the digest, or raise.

    **Redirects are not followed.** A 302 from the configured host to somewhere
    else would send the library's book titles to a destination nobody
    approved, and this is the one request in the app whose payload is
    catalogue content going somewhere unauthenticated. `fetch.get` refuses a
    redirect that leaves the host; this refuses one at all, because there is no
    hop a webhook needs and the payload is going out rather than coming in.

    **The reply is never read**, which is why this streams. `client.post`
    buffers the whole body, and the only thing done with it is
    `raise_for_status`, which reads the status line. A receiver answering a
    hostile reply would otherwise fill the pod on the hourly ticker, with no
    member action involved at all. Streaming and not reading costs nothing: the
    status is on the response before the body is touched.
    """
    headers = {"Content-Type": "application/json"}
    if secret:
        headers[SIGNATURE_HEADER] = sign(body, secret)

    async with (
        asyncio.timeout(TIMEOUT_SECONDS),
        httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client,
        client.stream("POST", url, content=body, headers=headers) as response,
    ):
        response.raise_for_status()


def _outcome(
    reason: OverdueNotifyReason,
    detail: str,
    *,
    loans: int = 0,
    skipped_private: int = 0,
) -> dict[str, Any]:
    """One shape for every exit that sent nothing.

    Built here rather than at each return so a new exit cannot forget the
    reason and leave the client rendering "nothing was sent" over a failure,
    which is what every one of these used to do.
    """
    return {
        "sent": False,
        "loans": loans,
        "skipped_private": skipped_private,
        "reason": reason,
        "detail": detail,
    }


async def run_digest(db: Session) -> dict[str, Any]:
    """One pass: select, send, stamp. Returns what `OverdueNotifyResult` needs.

    `notified_at` is stamped **after** a delivery that succeeded, never before.
    On any failure it is left alone so the next run retries the same loans,
    which is why the state is a timestamp on the loan rather than a flag set
    when the request goes out.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    days = reminder_days(db)

    if not settings_store.get_bool(db, SettingKey.OVERDUE_WEBHOOK_ENABLED):
        return _outcome(OverdueNotifyReason.DISABLED, "Overdue reminders are switched off.")

    try:
        url = checked_url(settings_store.get_raw(db, SettingKey.OVERDUE_WEBHOOK_URL))
    except WebhookRefused as refusal:
        return _outcome(OverdueNotifyReason.NO_URL, str(refusal))

    loans = due_for_reminder(db, now, days)
    skipped = count_private_overdue(db, now)
    if not loans:
        return _outcome(
            OverdueNotifyReason.NOTHING_DUE, "Nothing is overdue.", skipped_private=skipped
        )

    body = json.dumps(build_digest(loans, now)).encode("utf-8")
    secret = settings_store.get_raw(db, SettingKey.OVERDUE_WEBHOOK_SECRET)

    try:
        await post_digest(url, body, secret)
    except (httpx.HTTPError, httpx.InvalidURL, TimeoutError, UnicodeError) as error:
        # `UnicodeError` because a receiver answering 302 with a malformed host
        # in `Location` raises `idna.IDNAError` from inside `client.stream`,
        # even though redirects are not followed: httpx builds the redirect
        # request anyway to populate `response.next_request`. Without it a
        # webhook nobody controls 500s `POST /api/loans/overdue/notify`.
        # `fetch._walk_hops` carries the full trace of that path.
        #
        # `TimeoutError` because `post_digest` bounds the whole request with
        # `asyncio.timeout`, and that raises the builtin rather than
        # `httpx.TimeoutException`. Without it a slow receiver 500s
        # `POST /api/loans/overdue/notify` and stops the hourly ticker, which is
        # a worse outcome than the hang it replaced.
        #
        # The host, never the URL. See `_host`.
        logger.warning(
            "Overdue digest to %s failed, leaving %d loans to retry: %s",
            _host(url),
            len(loans),
            type(error).__name__,
        )
        return _outcome(
            OverdueNotifyReason.UNREACHABLE,
            "The webhook could not be reached.",
            loans=len(loans),
            skipped_private=skipped,
        )

    for loan in loans:
        loan.notified_at = now
    db.commit()

    logger.info("Overdue digest to %s covered %d loans", _host(url), len(loans))
    # The one exit with no reason: `reason` is null exactly when `sent` is true.
    return {
        "sent": True,
        "loans": len(loans),
        "skipped_private": skipped,
        "reason": None,
        "detail": None,
    }


async def ticker() -> None:
    """Run the digest once an hour, forever.

    **One process, one ticker.** The Dockerfile's CMD is a single uvicorn with
    no `--workers`, so there is exactly one of these and no double-send. That
    is the assumption that breaks first: adding `--workers 4` would give four
    tickers racing on the same rows, and the fix then is an external caller of
    `POST /api/loans/overdue/notify` rather than a lock in here.

    Its own session per tick, opened and closed. A request-scoped session is
    not available to a background task, and holding one open for the life of
    the process would pin a SQLite connection and see a stale snapshot.

    Every failure is swallowed and logged. A raise here kills the task
    silently for the life of the container, so the loop that chases overdue
    books would stop without anything in the app looking wrong.
    """
    while True:
        await asyncio.sleep(TICK_SECONDS)
        try:
            with SessionLocal() as db:
                await run_digest(db)
        except Exception:
            logger.exception("The overdue ticker failed a run")
