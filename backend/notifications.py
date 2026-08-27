"""Chasing overdue loans, by sending one digest on every channel that is on.

Three senders, one digest. **A webhook, mail over SMTP, and Telegram**, each
switched on independently, all carrying the same content.

**The webhook was once the only one, on an argument this module used to make and
that is now overruled.** It said a self-hosted app should not ship an
integration nobody else runs, and that a webhook is the one shape every receiver
already speaks. What that reasoning missed is that it makes the household build
the receiver: most have no webhook endpoint and no intention of writing one, so
the feature was off for them in practice. The two additions are chosen against
exactly that objection. **SMTP is universal**, carried by every household that
has a mailbox, and **Telegram is one fixed host**, so "an integration with
something nobody else runs" costs one constant here rather than a service.
Recorded so the next reader does not think a decision was quietly reversed:
issue #8, and `docs/decisions.md`.

**Private books are excluded, on every sender.** A channel has no member
identity behind it and lands where the whole household reads, so putting a
private book's title through one defeats the single promise the data model
makes. The in-app overdue view is per member and already scoped, so the owner
still gets chased there. See `docs/decisions.md` and `docs/security.md`.

**A per borrower mail would be the one audience that could carry a private
book**, because being reminded of a book you borrowed is not a disclosure. It is
not built, and the reason is a missing fact rather than a decision: no member
here has an address. `models.User` carries none and the LDAP backend requests
none, so there is nowhere to send it. Mail therefore goes to the household's own
mailbox, which is a channel like the other two and excludes private books like
the other two.

`notified_at` is stamped when **at least one** enabled sender delivered, because
the column records that the loan was chased and it was. The alternative,
stamping only when every sender delivered, turns one broken receiver into an
hourly repeat of the same list on the channels that work, which `build_digest`
calls the behaviour people switch off. A sender that failed is reported in its
own entry rather than compensated for.

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
import re
import smtplib
from datetime import UTC, datetime, timedelta
from typing import Any, Final, assert_never
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.sql.elements import ColumnElement

import mailer
import settings_store
from database import SessionLocal
from enums import OverdueNotifyReason, OverdueSender, SettingKey
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

#: How long the whole mail conversation may take, in seconds.
#:
#: `mailer.TIMEOUT_SECONDS` bounds each socket operation, and a conversation is
#: connect, EHLO, STARTTLS, EHLO, AUTH, MAIL, RCPT, DATA. This bounds the lot.
#:
#: **It bounds the caller, not the thread**, and that is a real limitation
#: stated rather than hidden: `asyncio.to_thread` cannot be cancelled, so a
#: server that stops answering costs one worker thread until its own socket
#: timeout expires. What it buys is the thing that matters, which is that the
#: hourly ticker and `POST /api/loans/overdue/notify` are never held by it.
MAIL_DEADLINE_SECONDS = 30.0

#: Telegram's one host, as a constant and **deliberately not a setting**.
#:
#: This is the property that makes Telegram a safer sender than the webhook
#: rather than a second copy of it: the webhook posts the library's book titles
#: wherever an admin typed, and this posts them to exactly one place that the
#: app, not the configuration, chose. Making the host settable would give that
#: away and buy nothing, since a different host would not be Telegram.
TELEGRAM_API: Final = "https://api.telegram.org"

#: `<digits>:<secret>`, which is the documented shape of a bot token.
#:
#: Matched before the token is put in a URL **path**, which is where Telegram
#: takes it. A token containing `/` or `..` would otherwise choose the method
#: being called, or walk up out of `/bot<token>/` entirely, from a settings row
#: a restore can write without passing any schema.
_TELEGRAM_TOKEN: Final = re.compile(r"^[0-9]{1,20}:[A-Za-z0-9_-]{20,255}$")

#: A numeric chat id, negative for a group, or an `@public_channel` name.
#:
#: In the JSON body rather than the path, so this is not a traversal. It is
#: refused anyway because a chat id that is not a chat id is a configuration
#: mistake worth naming on the settings screen, rather than a 400 from Telegram
#: that reaches nobody.
_TELEGRAM_CHAT: Final = re.compile(r"^(-?[0-9]{1,32}|@[A-Za-z][A-Za-z0-9_]{4,63})$")

#: Telegram's own limit on one message, in **UTF-16 code units**.
#:
#: **Counted in those units, not in characters, and the difference is a live
#: bug rather than pedantry.** A code point outside the BMP is one character and
#: *two* UTF-16 units, so `len()` under-counts exactly where a book title
#: carries an emoji. Measured: 2,100 grinning faces are 2,100 characters and
#: **4,200** units, which `len()` passes as under 4096 and Telegram rejects with
#: a 400. That is member-supplied catalogue content silently stopping every
#: household reminder, which is the same failure class the `parse_mode`
#: decision exists to avoid, on the same input. `_utf16_units` is the measure.
#:
#: **The digest is truncated to one message rather than split across several.**
#: Two messages are two sends, and a run where the first succeeded and the
#: second failed is a partial delivery that `run_digest` would have to decide
#: what to do with. One message is one outcome.
TELEGRAM_MAX_UNITS: Final = 4096


class WebhookRefused(Exception):
    """The destination is not one this app will post to."""


class TelegramRefused(Exception):
    """The bot token or the chat id is not one this app will send with."""


#: Every way a sender declines before opening a socket.
#:
#: A tuple rather than one base class, because `mailer.MailRefused` lives in the
#: module that owns SMTP and importing a base from here would be a cycle. The
#: cost is this line; the benefit is that neither module has to know the other's
#: hierarchy.
_REFUSALS: Final = (WebhookRefused, TelegramRefused, mailer.MailRefused)


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

    **This is the number for a sender whose audience is a channel, and every
    sender has one today**, so all three report it and all three agree. It is
    carried per sender in `SenderOutcome` rather than only once at the top, and
    the reason belongs here, at the function that exists to report what was
    withheld: what one channel withholds is not necessarily what another did.
    An audience with a member behind it could carry a private book the others
    may not, and a single figure would then be a lie on two channels of three.

    **A per borrower mail is that audience, and it does not exist yet.** Being
    reminded of a book you borrowed is not a disclosure, so such a mail could
    include one. No member here has an address (`models.User` carries none and
    the LDAP backend requests none), so mail goes to the household's mailbox and
    is a channel like the other two. When that changes, this function grows a
    caller that asks for a different number, not a second definition of the rule.

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


def _utf16_units(text: str) -> int:
    """How long Telegram thinks this message is.

    Telegram counts a message in UTF-16 code units, which is what its 4096 is
    denominated in. `len()` counts code points, and the two differ by one for
    every character outside the BMP: an emoji in a book title, a rarer CJK
    ideograph, a mathematical alphanumeric. `len()` therefore **under**-counts,
    which is the wrong direction, because it passes a message the API refuses.

    `utf-16-le` rather than `utf-16`, which prepends a two byte BOM and would
    make every message read one unit longer than it is.
    """
    return len(text.encode("utf-16-le")) // 2


def render_text(digest: dict[str, Any], *, limit: int | None = None) -> str:
    """The same digest as plain text, for the two senders a person reads.

    **`build_digest` stays the single source of what a reminder says.** This
    renders that object and adds nothing to it, so the three senders differ in
    transport and in audience and never in content. A second place that decided
    what a reminder mentions is how the webhook and the chat message drift into
    describing different libraries.

    English, and only English. The app's message catalogues are the frontend's
    (`frontend/src/i18n/`), and there is no server side one to translate a
    sentence with; inventing a second catalogue for two lines of text is a
    larger change than this feature. `default_locale` therefore does not reach
    here, and pretending it did would be worse than saying so.

    `limit` is in **UTF-16 code units**, and says how many entries were dropped,
    so a household with two hundred overdue books gets a message Telegram will
    accept rather than a 400 nobody sees. Only Telegram passes one; mail has no
    such ceiling. See `TELEGRAM_MAX_UNITS` for why the unit is not characters.
    """
    count = digest["count"]
    header = f"{count} overdue {'book' if count == 1 else 'books'}."
    lines = [
        f"{entry['title'] or 'Untitled'}: {entry['borrower']}, "
        f"{entry['days_overdue']} days overdue"
        for entry in digest["loans"]
    ]

    if limit is None:
        return "\n".join([header, "", *lines])

    kept: list[str] = []
    # Rebuilt on every candidate rather than measured incrementally: the tail
    # grows as entries are dropped, so a running total is wrong by the width of
    # its own sentence exactly when the message is closest to the limit.
    for line in lines:
        dropped = len(lines) - len(kept) - 1
        tail = [] if dropped == 0 else ["", f"and {dropped} more."]
        candidate = "\n".join([header, "", *kept, line, *tail])
        if _utf16_units(candidate) > limit:
            break
        kept.append(line)

    dropped = len(lines) - len(kept)
    tail = [] if dropped == 0 else ["", f"and {dropped} more."]
    rendered = "\n".join([header, "", *kept, *tail])
    if _utf16_units(rendered) <= limit:
        return rendered

    # The header alone can exceed a very small limit, and a hard cut is better
    # than a send this module knows will be refused. Dropped a code point at a
    # time rather than sliced: a slice counted in units could land between the
    # halves of a surrogate pair, and a code point is never more than two units,
    # so this cannot overshoot. `rendered` here is the header and the tail,
    # because nothing longer than the limit was ever kept.
    while rendered and _utf16_units(rendered) > limit:
        rendered = rendered[:-1]
    return rendered


def sign(body: bytes, secret: str) -> str:
    """`sha256=<hex>`, over the **raw body** the receiver will read.

    Over the bytes rather than over a re-serialised dict, because the receiver
    verifies what arrived on the wire and any difference in key order or
    separators makes an honest payload fail its own signature.
    """
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def _post(url: str, body: bytes, headers: dict[str, str]) -> None:
    """POST a body outward, or raise. The one outbound send in this module.

    **Redirects are not followed.** A 302 from the configured host to somewhere
    else would send the library's book titles to a destination nobody
    approved, and this is the one request in the app whose payload is
    catalogue content going somewhere unauthenticated. `fetch.get` refuses a
    redirect that leaves the host; this refuses one at all, because there is no
    hop a send needs and the payload is going out rather than coming in.

    **The reply is never read**, which is why this streams. `client.post`
    buffers the whole body, and the only thing done with it is
    `raise_for_status`, which reads the status line. A receiver answering a
    hostile reply would otherwise fill the pod on the hourly ticker, with no
    member action involved at all. Streaming and not reading costs nothing: the
    status is on the response before the body is touched.

    Telegram uses this too, and gets both properties for free. Not reading the
    reply also means its error JSON, which quotes the request back, never
    reaches a log.
    """
    async with (
        asyncio.timeout(TIMEOUT_SECONDS),
        httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client,
        client.stream("POST", url, content=body, headers=headers) as response,
    ):
        response.raise_for_status()


async def post_digest(url: str, body: bytes, secret: str) -> None:
    """POST the digest to the webhook, signed when a secret is set."""
    headers = {"Content-Type": "application/json"}
    if secret:
        headers[SIGNATURE_HEADER] = sign(body, secret)
    await _post(url, body, headers)


def telegram_url(token: str) -> str:
    """The one endpoint this app calls, with the token where Telegram wants it.

    **The token is a path segment, so this string is a secret.** It must never
    be logged, put in an exception message, or returned from the API. `_host`
    exists for the log line and answers `api.telegram.org`, which is a constant
    and therefore discloses nothing.
    """
    return f"{TELEGRAM_API}/bot{token}/sendMessage"


async def send_telegram(db: Session, text: str) -> None:
    """Send the digest to the household chat, or raise.

    **No `parse_mode`.** With one set, Telegram parses the message as HTML or as
    Markdown and rejects the whole send on an unbalanced character: a book
    titled `Kiss & Tell`, `*Star*` or `a_b` would silently stop every reminder,
    and the failure is a 400 with the borrower's own catalogue to blame. Plain
    text has no such character. The same trap, with the same fix, is documented
    for this household's own pager.

    `disable_web_page_preview` because a title that looks like a URL would
    otherwise make Telegram fetch it and render a card under the reminder.
    """
    token = settings_store.in_force(db, SettingKey.TELEGRAM_BOT_TOKEN).strip()
    chat = settings_store.in_force(db, SettingKey.TELEGRAM_CHAT_ID).strip()
    if not token:
        raise TelegramRefused("No Telegram bot token is configured.")
    if not _TELEGRAM_TOKEN.match(token):
        # The shape, never the value: this sentence reaches an admin and a log.
        raise TelegramRefused("The Telegram bot token is not a bot token.")
    if not _TELEGRAM_CHAT.match(chat):
        raise TelegramRefused("The Telegram chat id is not a chat id.")

    body = json.dumps(
        {"chat_id": chat, "text": text, "disable_web_page_preview": True}
    ).encode("utf-8")
    await _post(telegram_url(token), body, {"Content-Type": "application/json"})


async def send_mail(db: Session, subject: str, text: str) -> None:
    """Send the digest to the household mailbox, or raise.

    **On a worker thread.** `smtplib` is blocking and every FastAPI handler that
    reaches here is `async def`, so calling it inline would stop the event loop
    for the length of an SMTP conversation. `routers/imports.py` carries the
    measurement for the same mistake made the other way round: 7ms against 14.4
    seconds.

    The deadline bounds this coroutine, not the thread. See
    `MAIL_DEADLINE_SECONDS`.
    """
    config = mailer.checked_config(db)
    async with asyncio.timeout(MAIL_DEADLINE_SECONDS):
        await asyncio.to_thread(mailer.send, config, subject, text)


#: Which setting switches each sender on. One table, so "is this on" is asked
#: the same way for all three and adding a fourth is one line.
_ENABLED_KEY: Final[dict[OverdueSender, SettingKey]] = {
    OverdueSender.WEBHOOK: SettingKey.OVERDUE_WEBHOOK_ENABLED,
    OverdueSender.EMAIL: SettingKey.OVERDUE_MAIL_ENABLED,
    OverdueSender.TELEGRAM: SettingKey.OVERDUE_TELEGRAM_ENABLED,
}

#: Every transport failure, from three protocols, as one clause.
#:
#: `UnicodeError` because a receiver answering 302 with a malformed host in
#: `Location` raises `idna.IDNAError` from inside `client.stream`, even though
#: redirects are not followed: httpx builds the redirect request anyway to
#: populate `response.next_request`. Without it a webhook nobody controls 500s
#: `POST /api/loans/overdue/notify`. `fetch._walk_hops` carries the full trace.
#:
#: `TimeoutError` because both sends bound themselves with `asyncio.timeout`,
#: which raises the builtin rather than `httpx.TimeoutException`. Without it a
#: slow receiver 500s the endpoint and stops the hourly ticker, which is a worse
#: outcome than the hang it replaced.
#:
#: `OSError` for SMTP's sockets and TLS, `smtplib.SMTPException` for everything
#: the server said no to. `TimeoutError` is an `OSError` and is named anyway,
#: because the reason it is here is the paragraph above rather than the socket.
_TRANSPORT: Final = (
    httpx.HTTPError,
    httpx.InvalidURL,
    TimeoutError,
    UnicodeError,
    smtplib.SMTPException,
    OSError,
)


def _outcome(
    reason: OverdueNotifyReason,
    detail: str,
    *,
    loans: int = 0,
    skipped_private: int = 0,
    senders: list[dict[str, Any]] | None = None,
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
        "senders": senders or [],
    }


def _sender_entry(
    sender: OverdueSender,
    *,
    loans: int,
    skipped_private: int,
    reason: OverdueNotifyReason | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    """One sender's outcome, success or failure, built in one place.

    **`sent` is derived from `reason` rather than passed**, which is what makes
    "reason is null exactly when sent is true" an invariant instead of a rule
    two call sites have to remember. It was two: a dict literal for the success
    and this for the failure, six keys each, and the success one was where the
    invariant could be broken silently.
    """
    return {
        "sender": sender,
        "sent": reason is None,
        "loans": loans,
        "skipped_private": skipped_private,
        "reason": reason,
        "detail": detail,
    }


def _destination(sender: OverdueSender, db: Session) -> str:
    """A host, for a log line. **Never a URL and never a credential.**

    The webhook's URL may carry a token in its path or query string, and
    Telegram's carries the bot token as a path segment, so the log gets the host
    both times. Telegram's is a constant, and the mail server's is a hostname an
    operator typed; neither is a secret and both are the thing somebody reading
    a failure actually wants.

    It runs on the failure path, so it is written not to add a second failure to
    the first: `_host` swallows a URL it cannot parse, and an unset mail server
    reads "unknown" rather than empty. The one thing it does that can raise is
    reading the settings row, which every caller has already done before
    reaching here.
    """
    if sender is OverdueSender.WEBHOOK:
        return _host(settings_store.in_force(db, SettingKey.OVERDUE_WEBHOOK_URL))
    if sender is OverdueSender.TELEGRAM:
        return _host(TELEGRAM_API)
    if sender is OverdueSender.EMAIL:
        return settings_store.in_force(db, SettingKey.MAIL_SERVER).strip() or "unknown"
    # A fourth sender added to `_ENABLED_KEY` and not here used to fall through
    # to the mail branch and log the mail server's hostname for it. mypy fails
    # this line when the chain stops being exhaustive; nothing else does.
    assert_never(sender)


async def _deliver(
    sender: OverdueSender, db: Session, digest: dict[str, Any], subject: str
) -> None:
    """Hand one sender the digest. Raises a refusal or a transport error."""
    if sender is OverdueSender.WEBHOOK:
        url = checked_url(settings_store.in_force(db, SettingKey.OVERDUE_WEBHOOK_URL))
        body = json.dumps(digest).encode("utf-8")
        secret = settings_store.in_force(db, SettingKey.OVERDUE_WEBHOOK_SECRET)
        await post_digest(url, body, secret)
    elif sender is OverdueSender.EMAIL:
        await send_mail(db, subject, render_text(digest))
    elif sender is OverdueSender.TELEGRAM:
        await send_telegram(db, render_text(digest, limit=TELEGRAM_MAX_UNITS))
    else:
        # The `else` used to *be* the Telegram branch, so a fourth sender added
        # to `_ENABLED_KEY` and not here posted the digest to the household's
        # chat. mypy fails this call when the chain stops being exhaustive.
        assert_never(sender)


async def _run_sender(
    sender: OverdueSender,
    db: Session,
    digest: dict[str, Any],
    subject: str,
    *,
    loans: int,
    skipped_private: int,
) -> dict[str, Any]:
    """One sender's attempt, as the entry that will be reported for it.

    **`skipped_private` is carried per sender, not once for the run.** All three
    withhold the same rows today, because all three go to a channel rather than
    to a person, so all three report the same number. The count is attached here
    anyway: the moment one sender's audience differs, "3 private books withheld"
    has to mean what it says on the channel it appears on, and a single figure
    at the top would be a lie on the other two.

    Every failure is caught. One sender that cannot be reached must not stop the
    ones after it, and must not 500 the endpoint.
    """
    try:
        await _deliver(sender, db, digest, subject)
    except _REFUSALS as refusal:
        # `NO_URL` for the webhook keeps the reason the client already renders
        # for an empty destination. The other two have no URL to be missing.
        reason = (
            OverdueNotifyReason.NO_URL
            if isinstance(refusal, WebhookRefused)
            else OverdueNotifyReason.MISCONFIGURED
        )
        logger.warning(
            "The %s reminder to %s was refused: %s",
            sender.value,
            _destination(sender, db),
            refusal,
        )
        return _sender_entry(
            sender,
            loans=loans,
            skipped_private=skipped_private,
            reason=reason,
            detail=str(refusal),
        )
    except _TRANSPORT as error:
        # The type, never the error's own message. `httpx.HTTPStatusError`
        # renders the request URL, and for Telegram the URL is the bot token.
        logger.warning(
            "The %s reminder to %s failed, leaving %d loans to retry: %s",
            sender.value,
            _destination(sender, db),
            loans,
            type(error).__name__,
        )
        return _sender_entry(
            sender,
            loans=loans,
            skipped_private=skipped_private,
            reason=OverdueNotifyReason.UNREACHABLE,
            detail="The destination could not be reached.",
        )

    logger.info(
        "The %s reminder to %s covered %d loans",
        sender.value,
        _destination(sender, db),
        loans,
    )
    return _sender_entry(sender, loans=loans, skipped_private=skipped_private)


async def run_digest(db: Session) -> dict[str, Any]:
    """One pass: select, send on every channel that is on, stamp.

    `notified_at` is stamped **after** at least one delivery that succeeded,
    never before. With nothing delivered it is left alone so the next run
    retries the same loans, which is why the state is a timestamp on the loan
    rather than a flag set when the first request goes out.

    **One selection for all three senders, not one each.** They carry the same
    content by construction, and re-running `due_for_reminder` between senders
    would let a loan returned mid run reach one channel and not another.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    days = reminder_days(db)

    enabled = [
        sender
        for sender in OverdueSender
        if settings_store.get_bool(db, _ENABLED_KEY[sender])
    ]
    if not enabled:
        return _outcome(OverdueNotifyReason.DISABLED, "Overdue reminders are switched off.")

    loans = due_for_reminder(db, now, days)
    skipped = count_private_overdue(db, now)
    if not loans:
        return _outcome(
            OverdueNotifyReason.NOTHING_DUE, "Nothing is overdue.", skipped_private=skipped
        )

    digest = build_digest(loans, now)
    subject = f"{len(loans)} overdue {'book' if len(loans) == 1 else 'books'}"
    outcomes = [
        await _run_sender(
            sender, db, digest, subject, loans=len(loans), skipped_private=skipped
        )
        for sender in enabled
    ]

    if not any(entry["sent"] for entry in outcomes):
        # The first failure in sender order, so a single sender library reads
        # exactly as it did before there were three.
        first = outcomes[0]
        return _outcome(
            first["reason"],
            first["detail"],
            loans=len(loans),
            skipped_private=skipped,
            senders=outcomes,
        )

    for loan in loans:
        loan.notified_at = now
    db.commit()

    # The one exit with no reason: `reason` is null exactly when `sent` is true.
    return {
        "sent": True,
        "loans": len(loans),
        "skipped_private": skipped,
        "reason": None,
        "detail": None,
        "senders": outcomes,
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
