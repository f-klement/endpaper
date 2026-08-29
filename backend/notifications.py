"""Chasing overdue loans, by sending one digest on every channel that is on.

Four senders. **The app itself, a webhook, mail over SMTP, and Telegram**, each
switched on independently. The three that push outward carry the same content;
the fourth is read rather than sent, and carries what its reader may see.

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

**Private books are excluded from every sender that pushes.** A channel has no
member identity behind it and lands where the whole household reads, so putting
a private book's title through one defeats the single promise the data model
makes. See `docs/decisions.md` and `docs/security.md`.

**The in app channel is the exception, and it is the rule rather than a hole in
it.** Its audience is a member, so `overdue_for_viewer` roots the query at
`Shelf.seen_by` and each reader gets exactly what `visible_to` already says they
may see, their own private books included. Being told about your own book is not
a disclosure. That is the one capability the other three cannot have, and the
reason this module's exemption from the Shelf rule covers the digest only: the
digest has no viewer, and that query does.

**A per borrower mail would be the one audience that could carry a private
book**, because being reminded of a book you borrowed is not a disclosure. It is
**still not built**, and what changed is only the fact it was blocked on:
`models.User` now carries an `email` column (issue #80), so an address can
exist. Nothing here reads it. Mail goes to the household's own mailbox, which is
a channel like the other two and excludes private books like the other two, and
that stays true for a member who has filled the field in, because no code path
consults it yet.

So the column's arrival is invisible to this module by construction rather than
by discipline: `send_mail` takes its recipients from `mailer.checked_config`,
which reads `overdue_mail_to` and nothing else. A per borrower mode is a second
audience for `build_digest` and a second recipient list, which is issue #8's
remaining work rather than a column.

`notified_at` is stamped when **at least one sender that pushes** delivered,
because the column records that a reminder went out and one did. The
alternative, stamping only when every sender delivered, turns one broken
receiver into an hourly repeat of the same list on the channels that work,
which `build_digest` calls the behaviour people switch off. A sender that
failed is reported in its own entry rather than compensated for, and its
standing record is kept by `record_run` rather than left in the log.

The in app channel is outside that condition on purpose: it delivers nothing,
so counting it would stamp every loan on every run and cut the pushing senders
from hourly attempts to one per interval. `pushes_outward` carries the number.

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
from sqlalchemy import or_
from sqlalchemy.orm import Query, Session, joinedload
from sqlalchemy.sql.elements import ColumnElement

import mailer
import settings_store
from database import SessionLocal
from enums import OverdueNotifyReason, OverdueSender, SettingKey
from models import Book, Loan, User
from schemas.settings import MAX_REMINDER_DAYS, MIN_REMINDER_DAYS
from shelf import Shelf

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
    include one.

    **What has changed, and what has not.** `models.User` now carries an `email`
    column and the LDAP backend requests an attribute where one is configured
    (issue #80), so an address can exist: the premise this paragraph used to
    rest on is gone. What has not changed is the conclusion. Nothing reads that
    column here: `send_mail` takes its recipients from `mailer.checked_config`,
    which reads `overdue_mail_to` and nothing else, so mail still goes to the
    household's mailbox and is a channel like the other two. A member who has
    filled the field in is in exactly the position of one who has not.

    So this count is still every private overdue book in the library, and when a
    per borrower audience arrives this function grows a caller that asks for a
    different number, not a second definition of the rule.

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


def count_overdue(db: Session, now: datetime) -> int:
    """Every open overdue loan, private books included.

    The number the in app channel is showing, across the whole household. Not
    the number any one member sees: each of them sees the slice
    `overdue_for_viewer` gives them, and the slices overlap. It is reported to
    an admin pressing "Send now", who already reads `count_private_overdue`
    beside it, so it discloses nothing new.

    No reminder interval, for the reason `count_private_overdue` states: the in
    app notice is read rather than sent, so nothing about it is quieted by
    `notified_at`.
    """
    return (
        db.query(Loan)
        .join(Book, Loan.book_id == Book.id)
        .filter(*_overdue_clauses(now))
        .count()
    )


def sees_every_loan(viewer: User) -> bool:
    """Whether this viewer reads the whole overdue list rather than their own.

    **The seam library mode (#18) will widen, named rather than guessed.** The
    owner settled the audiences per sender: the household channels go to a
    mailbox or a chat, mail is addressed to the borrower, and the in app notice
    is per member **except in library mode or for an admin**, where the reader
    is staff checking open reminders and outstanding books.

    Library mode does not exist yet, so today this answers one question and
    that is the whole of it. What it must not become is `admins see all`: an
    admin is not a superuser over another member's private books anywhere else
    in this app, and this is not the thing that makes them one. Both arms of
    `overdue_for_viewer` are narrowed by the Shelf either way; this decides
    only whether the loans are further narrowed to the ones the viewer is
    party to.

    So when library mode lands, this function gains a clause and nothing else
    changes: the staff rule is already "every loan over a book this viewer may
    see", and that mode changes what the set contains rather than how it is
    computed.
    """
    return viewer.is_admin


def overdue_for_viewer(db: Session, viewer: User, now: datetime) -> Query[Loan]:
    """The overdue loans the in app notice tells **this member** about.

    **Rooted at the Shelf, which is what makes this different from every other
    query in this module.** The digest has no viewer and is exempt from the
    house rule for that reason; this one has a viewer, so it is not covered by
    that exemption and does not inherit it. `Shelf.seen_by` applies
    `visible_to` by construction, so a private book somebody else added cannot
    reach here whatever the clauses below do.

    That is also the capability the outward channels cannot have. A mailbox or
    a chat has no member behind it, so the digest excludes every private book
    and reports a count instead. This audience **is** a member, so their own
    private books belong in it: `visible_to()` has always said a private book
    is visible to the member who added it, and telling somebody about their own
    book is not a disclosure.

    Two arms, and `sees_every_loan` is the only place the difference is
    decided. Staff read every overdue loan on their shelf. A member reads the
    ones they are party to: they borrowed it, or they lent it out. Both are
    facts about the loan rather than about the book, which is why neither arm
    needs a second privacy rule on top of the Shelf's.

    No `notified_at` clause, deliberately. That column records that a reminder
    went **out**, and nothing goes out here: an overdue loan is on the member's
    screen for as long as it is overdue, and quieting it for a week would be
    the app forgetting something it is still looking at.

    **The query, not the rows, and the caller chooses.** The one production
    caller wants a number, and `len(query.all())` for a number is the defect it
    reads like: measured against 500 overdue loans it built 500 ORM objects, on
    every visit to the library page, to call `len` on them. `.count()` is one
    statement and none. `Shelf.select()` hands its own query out for the same
    reason, and the privacy predicate is already on this one by construction, so
    there is nothing a caller can widen: `.filter()` on it can only narrow.

    No eager loading here for the same reason. It was `joinedload(Loan.book)`
    and `joinedload(Loan.loaned_to)`, which were for rendering titles, and the
    notice reports a count and never a title.
    """
    query = (
        Shelf.seen_by(db, viewer.id)
        .select(Loan)
        .join(Loan, Loan.book_id == Book.id)
        .filter(*_overdue_clauses(now))
    )
    if not sees_every_loan(viewer):
        query = query.filter(
            or_(
                Loan.loaned_to_user_id == viewer.id,
                Loan.loaned_by_user_id == viewer.id,
            )
        )
    return query.order_by(Loan.due_at, Loan.id)


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
    OverdueSender.IN_APP: SettingKey.OVERDUE_IN_APP_ENABLED,
    OverdueSender.WEBHOOK: SettingKey.OVERDUE_WEBHOOK_ENABLED,
    OverdueSender.EMAIL: SettingKey.OVERDUE_MAIL_ENABLED,
    OverdueSender.TELEGRAM: SettingKey.OVERDUE_TELEGRAM_ENABLED,
}


#: Every settings row that configures one sender, keyed by sender.
#:
#: **Not the toggle alone, and that distinction is the whole of #82's exit.** A
#: health record describes a channel *as it was configured*, so any write that
#: changes what the next send will do to that channel makes the record describe
#: something that no longer exists. The case the ticket names is a household
#: replacing an expired bot token, and that write is not a toggle: with only the
#: switches owned, the record survived it, `_is_broken` compares `now` against a
#: `failing_since` that only grows, and the steady state of a household is
#: nothing overdue, so no later run would overwrite it either. The banner was
#: permanent and the only exit was switching the channel off and on again.
#:
#: **Every field, not just the credential.** `mail_use_tls` and `mail_use_ssl`
#: are the pair `mailer.checked_config` refuses a password over, so they produce
#: the `MISCONFIGURED` the banner reports at once; `mail_port` and `mail_server`
#: decide whether a socket opens at all; `overdue_mail_to` and `telegram_chat_id`
#: are destinations. A rule covering "credentials" would have left the commonest
#: mail fix outside it.
#:
#: `OVERDUE_REMINDER_DAYS` is deliberately absent: it says how often a loan is
#: chased, not whether a channel works, so changing it is not evidence about any
#: channel. `SENDER_HEALTH` is absent for the obvious reason.
_CONFIGURED_BY: Final[dict[OverdueSender, frozenset[SettingKey]]] = {
    OverdueSender.IN_APP: frozenset({SettingKey.OVERDUE_IN_APP_ENABLED}),
    OverdueSender.WEBHOOK: frozenset(
        {
            SettingKey.OVERDUE_WEBHOOK_ENABLED,
            SettingKey.OVERDUE_WEBHOOK_URL,
            SettingKey.OVERDUE_WEBHOOK_SECRET,
        }
    ),
    OverdueSender.EMAIL: frozenset(
        {
            SettingKey.OVERDUE_MAIL_ENABLED,
            SettingKey.OVERDUE_MAIL_TO,
            *settings_store.MAIL_KEYS,
        }
    ),
    OverdueSender.TELEGRAM: frozenset(
        {
            SettingKey.OVERDUE_TELEGRAM_ENABLED,
            SettingKey.TELEGRAM_BOT_TOKEN,
            SettingKey.TELEGRAM_CHAT_ID,
        }
    ),
}


def sender_for(key: SettingKey) -> OverdueSender | None:
    """Which sender this settings row configures, if it configures one.

    **The door the settings router writes through**, so that "this write
    invalidates that channel's health record" is a fact about the sender rather
    than a second table in a router. The router used to carry one keyed on the
    payload field, and it covered the four switches only, which is the defect
    above.
    """
    for sender, keys in _CONFIGURED_BY.items():
        if key in keys:
            return sender
    return None


def pushes_outward(sender: OverdueSender) -> bool:
    """Whether this sender hands the digest to something outside the app.

    **The one place the difference is decided, and it decides two things a
    reader would otherwise have to infer.** Which senders `run_digest` attempts
    at all, and which of them may advance `notified_at`.

    The stamp is the reason this is a function rather than a comment.
    `notified_at` records that a reminder went **out**, and `due_for_reminder`
    reads it, so counting the in app notice as a delivery would stamp every
    overdue loan on every run and then select nothing until the interval
    expired. Measured against the shipped default of 7 days: a broken mail
    server would be attempted **once a week instead of once an hour**, from a
    channel that is on by default. That is one sample a week for the failure
    window in `_is_broken`, which is the mechanism #82 exists to build.

    A `match` with an `assert_never` tail rather than a tuple of the three that
    push: a tuple is a list somebody adds to, and forgetting is silent. Here a
    fifth sender is a mypy error at this line, in the same shape `_deliver` and
    `_destination` already use.
    """
    match sender:
        case OverdueSender.WEBHOOK | OverdueSender.EMAIL | OverdueSender.TELEGRAM:
            return True
        case OverdueSender.IN_APP:
            return False
    assert_never(sender)

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
    if sender is OverdueSender.IN_APP:
        # Reached by nothing today: `_run_sender` is the only caller and
        # `run_digest` hands it pushing senders only. Answered rather than
        # raised because a destination is a log line, and a log line is not
        # worth a second failure on the failure path.
        return "the app"
    # A fifth sender added to `_ENABLED_KEY` and not here used to fall through
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
    elif sender is OverdueSender.IN_APP:
        # There is nothing to hand off. The notice is the app: a member reads
        # it from `GET /api/loans/overdue/mine`, scoped to them, which is what
        # `pushes_outward` says and what keeps this branch unreachable.
        #
        # A raise rather than a quiet return, because reaching it would mean
        # `run_digest` had started treating a pull channel as a delivery, and
        # that silently stamps `notified_at` on loans nothing chased. Pinned by
        # `test_the_in_app_channel_is_never_handed_to_a_sender`.
        raise AssertionError(
            "The in app channel does not push. See notifications.pushes_outward."
        )
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


#: How long a channel must have been failing before the app interrupts anybody.
#:
#: **Deliberately not `overdue_reminder_days`**, and the two must not be read as
#: one number. That interval says how often a loan is chased. This says how long
#: a channel may be broken before somebody is told on a screen they did not go
#: looking at. They answer different questions and a household is free to set
#: the first to 24 hours without meaning anything by it.
BROKEN_AFTER_HOURS: Final = 24

#: How many consecutive failures the window above must contain.
#:
#: **The window alone is not enough, and the case that breaks it is the common
#: one.** A working webhook beside a broken mail server stamps `notified_at`, so
#: mail is attempted once per reminder interval rather than once an hour. A
#: single failed attempt would then sit there while the clock ran, and cross 24
#: hours having failed exactly once, which is the network event this bar exists
#: to ignore. Two failures and a day together mean every attempt failed.
MIN_FAILURES_TO_INTERRUPT: Final = 2

#: The reasons the app decided by itself, before opening a socket.
#:
#: This is the whole of the network versus configuration distinction, and it is
#: a property of the code rather than a guess about the world: every one of
#: these comes out of `_REFUSALS`, and all three of those are raised before
#: anything is dialled. `checked_url` is string handling, `send_telegram`
#: matches both of its regexes before `_post`, and `mailer.checked_config`
#: raises long before `smtplib.SMTP(...)` is constructed.
#:
#: So a refusal is not an outage: nothing was tried, and nothing will succeed
#: until somebody changes a setting. Waiting a day to say so would tell the
#: household nothing it could not have been told at once. `UNREACHABLE` is the
#: opposite case and is the one the window is for.
_CONFIGURATION_REASONS: Final = frozenset(
    {OverdueNotifyReason.NO_URL, OverdueNotifyReason.MISCONFIGURED}
)


def _in_app_entry(db: Session, now: datetime) -> dict[str, Any]:
    """The in app channel's line in a run's report.

    `sent` is true and it is not a claim that anything was delivered: the
    entry's meaning is "this channel is carrying the notice", which for a
    channel read out of the app is true whenever it is switched on. The one way
    it stops being true is the app not running, and then nothing is reporting
    anything.

    `skipped_private` is **0**, and that is a number rather than an omission.
    The other three withhold every private book because their audience is a
    mailbox or a chat with no member behind it. This audience is the viewer, so
    nothing is withheld from it: each private book is shown to the member who
    added it and to nobody else, which is `visible_to`'s rule unchanged.

    `loans` is the household's whole overdue count, not one member's. There is
    no single per member number to report here, because there is a different
    one per member. Reported to an admin, beside `count_private_overdue`, which
    is a stronger figure than this one.
    """
    return _sender_entry(
        OverdueSender.IN_APP,
        loans=count_overdue(db, now),
        skipped_private=0,
    )


# ── The standing record of what each channel last did ─────────────────────────
#
# #82. `ticker()` used to call `run_digest` and throw the result away, so a
# household running mail and Telegram whose bot token expired got mail
# delivered, the loan stamped, and Telegram failing hourly and indefinitely with
# nothing anywhere but a warning in the container log. For a household running
# the published image, "read the container log" is not a worse form of alerting;
# it is the absence of one.
#
# One settings row holds it, keyed by sender. Not a table: a table needs a
# migration, a retention rule and a `backup._TABLES` entry, and what is wanted
# is one record per sender rather than a history. `settings` is already in
# `backup._TABLES`, so this survives a restore with everything else. A record
# restored from an old archive describes runs that happened before it, and the
# next tick overwrites it.


def _parsed(value: Any) -> datetime | None:
    """A stored timestamp as a **naive UTC** datetime, or None.

    Every read of this record goes through here rather than
    `datetime.fromisoformat` directly, because the row is settings data: a
    restore, a hand edit or an older release can put anything in it, and this
    is read on the hourly ticker where a raise stops the task for the life of
    the container.

    **The offset is stripped, and that is not tidying.** Everything in this app
    stores naive UTC (`datetime.now(UTC).replace(tzinfo=None)`), and `_is_broken`
    subtracts `failing_since` from a `now` of that shape. A row carrying
    `2020-01-01T00:00:00+00:00`, which `fromisoformat` parses perfectly happily,
    made that subtraction raise `TypeError: can't subtract offset-naive and
    offset-aware datetimes`, and the only thing between that row and a 500 on
    `GET /api/settings/sender-health` was that nothing here writes one. `settings`
    is in `backup._TABLES`, so the row crosses a restore, and the whole point of
    this function is the row nobody validated.

    Converted rather than merely stripped: dropping the offset off a `+02:00`
    timestamp would move it two hours, which is the kind of wrong that reads as
    right.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(UTC).replace(tzinfo=None)


def _reason(value: Any) -> OverdueNotifyReason | None:
    """A stored reason, or None if it is not one this release knows."""
    try:
        return OverdueNotifyReason(value)
    except ValueError:
        return None


def _is_broken(entry: dict[str, Any], now: datetime) -> bool:
    """Whether this channel's failure is worth interrupting somebody about.

    The bar the ticket set, in one expression: **one failed send is a network,
    every send failing for a day is a configuration**, and a design that cannot
    tell them apart is one a household switches off.

    Two ways past it and they are different kinds of evidence.

    A **refusal** is immediate, because the app refused it: see
    `_CONFIGURATION_REASONS`. Nothing was dialled, so there is no outage to wait
    out and no attempt that could succeed without somebody changing a setting.

    A **transport failure** has to persist: at least `BROKEN_AFTER_HOURS` since
    the first failure of the current run of them, and at least
    `MIN_FAILURES_TO_INTERRUPT` failures inside it. Both, for the reason
    `MIN_FAILURES_TO_INTERRUPT` states.
    """
    if entry.get("sent") is not False:
        return False
    if _reason(entry.get("reason")) in _CONFIGURATION_REASONS:
        return True
    since = _parsed(entry.get("failing_since"))
    failures = entry.get("failures")
    if since is None or not isinstance(failures, int):
        return False
    return (
        failures >= MIN_FAILURES_TO_INTERRUPT
        and now - since >= timedelta(hours=BROKEN_AFTER_HOURS)
    )


def record_run(db: Session, result: dict[str, Any], now: datetime) -> None:
    """Keep what each sender in this run did, so the next reader can see it.

    **Only the senders this run actually attempted.** A run that found nothing
    overdue reports no sender, and overwriting a standing failure with silence
    is how the record would come to say a broken channel is fine.

    `failing_since` is the start of the current unbroken run of failures and
    `failures` counts it, so a channel that failed once at 3am and has worked
    since reads differently from one that has failed every hour for a week.
    Both are needed: see `MIN_FAILURES_TO_INTERRUPT`.
    """
    record = settings_store.get_json(db, SettingKey.SENDER_HEALTH)
    for entry in result.get("senders", []):
        sender_key = OverdueSender(entry["sender"])
        # Only the channels that can fail. The in app notice hands the digest to
        # nobody, so "it worked" is not a measurement of anything: recording it
        # would put a row in the record whose only possible value is a success
        # nothing checked. `health()` filters on the same seam, and the settings
        # screen draws no line for it, for the same one reason stated once.
        if not pushes_outward(sender_key):
            continue
        sender = sender_key.value
        previous = record.get(sender)
        previous = previous if isinstance(previous, dict) else {}
        if entry["sent"]:
            record[sender] = {
                "sent": True,
                "reason": None,
                "detail": None,
                "at": now.isoformat(),
                "failing_since": None,
                "failures": 0,
            }
            continue
        was_failing = previous.get("sent") is False
        earlier = _parsed(previous.get("failing_since")) if was_failing else None
        count = previous.get("failures") if was_failing else 0
        record[sender] = {
            "sent": False,
            "reason": entry["reason"].value if entry["reason"] else None,
            "detail": entry["detail"],
            "at": now.isoformat(),
            "failing_since": (earlier or now).isoformat(),
            "failures": (count if isinstance(count, int) else 0) + 1,
        }
    settings_store.set_json(db, SettingKey.SENDER_HEALTH, record)


def forget_health(db: Session, sender: OverdueSender) -> None:
    """Drop a channel's record, because it describes a channel that changed.

    Called when a sender's own switch is written. A record from before somebody
    turned a channel off, or on again, is about a different configuration, and
    the case that matters is the second one: a household that fixes a bot token
    and switches Telegram back on should not meet a banner about the token they
    just replaced.
    """
    record = settings_store.get_json(db, SettingKey.SENDER_HEALTH)
    if record.pop(sender.value, None) is not None:
        settings_store.set_json(db, SettingKey.SENDER_HEALTH, record)


def health(db: Session, now: datetime) -> list[dict[str, Any]]:
    """What every switched-on channel that **pushes** last did, in sender order.

    **Switched on only.** A record for a channel nobody is using is a line
    about something that is not happening, and the banner would go on
    interrupting an admin about a webhook they turned off a month ago.
    `forget_health` covers the toggle; this covers a channel switched off by a
    restore or by an environment variable.

    **Pushing only, and the in app notice is therefore absent.** It hands the
    digest to nobody, so its outcome is never a failure and a row for it could
    only ever report a success: an assertion that a delivery worked, about a
    delivery nothing performed. That is worse than saying nothing, because a
    reader cannot tell it from a channel that was checked. The settings screen
    drew no line for it for this reason and the endpoint should not have gone on
    serving one, which is one fact with two spellings until it is one.

    A channel that has never run reports `last_run_at` of None rather than a
    success, because "not yet" and "fine" are the two answers a household most
    needs to tell apart on the day they configure one.
    """
    record = settings_store.get_json(db, SettingKey.SENDER_HEALTH)
    entries = []
    for sender in OverdueSender:
        if not pushes_outward(sender):
            continue
        if not settings_store.get_bool(db, _ENABLED_KEY[sender]):
            continue
        stored = record.get(sender.value)
        stored = stored if isinstance(stored, dict) else {}
        failures = stored.get("failures")
        entries.append(
            {
                "sender": sender,
                "last_run_at": _parsed(stored.get("at")),
                "sent": stored.get("sent") if isinstance(stored.get("sent"), bool) else None,
                "reason": _reason(stored.get("reason")),
                "detail": stored.get("detail") if isinstance(stored.get("detail"), str) else None,
                "failing_since": _parsed(stored.get("failing_since")),
                "failures": failures if isinstance(failures, int) and failures >= 0 else 0,
                "broken": _is_broken(stored, now),
            }
        )
    return entries


async def run_digest(db: Session) -> dict[str, Any]:
    """One pass: select, send on every channel that pushes, stamp, record.

    `notified_at` is stamped **after** at least one delivery that succeeded,
    never before. With nothing delivered it is left alone so the next run
    retries the same loans, which is why the state is a timestamp on the loan
    rather than a flag set when the first request goes out.

    **Only a sender that pushes may stamp it.** The in app channel is switched
    on in the same list and reported in the same shape, and it delivers nothing
    anywhere: counting it would advance `notified_at` on every run and quiet the
    three that do push for the length of the interval. `pushes_outward` carries
    the measurement.

    **One selection for every pushing sender, not one each.** They carry the
    same content by construction, and re-running `due_for_reminder` between
    senders would let a loan returned mid run reach one channel and not another.

    **The result is recorded before it is returned**, which is #82. It used to
    be returned to `ticker()` and thrown away, so a channel that failed every
    hour existed only as a warning in the container log. Recorded here rather
    than in the ticker because `POST /api/loans/overdue/notify` runs the same
    pass and had the same defect: with the write in one caller, a household
    pressing "Send now" would leave the health panel describing an older run.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    result = await _run_digest(db, now)
    record_run(db, result, now)
    return result


async def _run_digest(db: Session, now: datetime) -> dict[str, Any]:
    """The pass itself. `run_digest` is what records it; see there for why."""
    days = reminder_days(db)

    enabled = [
        sender
        for sender in OverdueSender
        if settings_store.get_bool(db, _ENABLED_KEY[sender])
    ]
    if not enabled:
        return _outcome(OverdueNotifyReason.DISABLED, "Overdue reminders are switched off.")

    # In sender order, so a report reads the same way every run. The in app
    # entry is built rather than attempted: it hands the digest to nothing.
    in_app = [_in_app_entry(db, now)] if OverdueSender.IN_APP in enabled else []
    pushing = [sender for sender in enabled if pushes_outward(sender)]

    loans = due_for_reminder(db, now, days)
    skipped = count_private_overdue(db, now)

    if not pushing:
        # In app is on and nothing else is. Nothing was sent and nothing was
        # meant to be, which is a different answer from "reminders are off" and
        # reads differently on the screen.
        return _outcome(
            OverdueNotifyReason.IN_APP_ONLY,
            "Nothing was sent: the in app notice is the only channel switched on.",
            loans=len(loans),
            skipped_private=skipped,
            senders=in_app,
        )

    if not loans:
        return _outcome(
            OverdueNotifyReason.NOTHING_DUE,
            "Nothing is overdue.",
            skipped_private=skipped,
            senders=in_app,
        )

    digest = build_digest(loans, now)
    subject = f"{len(loans)} overdue {'book' if len(loans) == 1 else 'books'}"
    pushed = [
        await _run_sender(
            sender, db, digest, subject, loans=len(loans), skipped_private=skipped
        )
        for sender in pushing
    ]
    outcomes = in_app + pushed

    # Asked of `pushed`, never of `outcomes`. The in app entry always reports
    # `sent`, so reading the whole list here would make every run look like a
    # delivery and stamp loans nothing chased.
    if not any(entry["sent"] for entry in pushed):
        # The first failure in sender order, so a single sender library reads
        # exactly as it did before there were three.
        first = pushed[0]
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

    **The result is no longer thrown away here, and it is not read here
    either.** It used to be discarded, which is what made a broken channel
    invisible: an hourly tick stamped `notified_at` on one success, the next
    "Send now" answered `nothing_due` with an empty `senders`, and the only
    standing record of the channel that failed was a warning line in the
    container log. `run_digest` records every run itself, so this caller and
    `POST /api/loans/overdue/notify` both leave the same record rather than one
    of them racing the other to it.
    """
    while True:
        await asyncio.sleep(TICK_SECONDS)
        try:
            with SessionLocal() as db:
                await run_digest(db)
        except Exception:
            logger.exception("The overdue ticker failed a run")
