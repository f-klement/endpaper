"""Tests for backend/notifications.py.

The outbound POST is intercepted with respx, so nothing here reaches a real
webhook. What is worth pinning is the three rules that are silent when they
break: private books never leave, a failed delivery retries, and the log
carries the host rather than the URL.
"""

import ast
import asyncio
import hashlib
import hmac
import json
import logging
import os
import smtplib
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx

import mailer
import notifications
import settings_store
from enums import OverdueNotifyReason, OverdueSender, SettingKey
from models import Book, Loan, User

HOOK = "https://hooks.example.org/t/abcdef"

#: The module tree the `ast` guards in this file read.
BACKEND = Path(__file__).resolve().parent.parent


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def units(text: str) -> int:
    """What Telegram measures a message in.

    Derived from the code points rather than re-encoding. Not calling
    `notifications._utf16_units` is not independence: the codec string is the
    part that can be wrong, and a copy of the expression carries the same one.
    `utf-16` would prepend a BOM and `utf-8` is a different count entirely, and
    a byte-for-byte copy agrees with either mistake.
    """
    return sum(2 if ord(character) > 0xFFFF else 1 for character in text)


@pytest.fixture(autouse=True)
def in_app_off(db):
    """Switch the in app channel off for every test in this file by default.

    **It ships on**, which is the whole of #86: it is the one channel that
    works with nothing configured, so a household that has set nothing up is
    still told. Every test below is about a channel that pushes, and with the
    fourth channel on it would sit first in `senders` and shift every index by
    one, which is a fixture problem dressed up as an assertion failure.

    So it is turned off here and turned back on where it is the subject:
    `TestTheInAppChannel` and `test_every_sender_is_handed_the_same_books`. The
    default itself is asserted in `TestTheInAppChannel`, not assumed.
    """
    settings_store.set_value(db, SettingKey.OVERDUE_IN_APP_ENABLED, "false")
    return db


@pytest.fixture
def in_app_on(db):
    """The shipped default, restored for the tests this channel is about."""
    settings_store.set_value(db, SettingKey.OVERDUE_IN_APP_ENABLED, "true")
    return db


@pytest.fixture
def configured(db):
    """A webhook that is switched on, with no secret."""
    settings_store.set_value(db, SettingKey.OVERDUE_WEBHOOK_ENABLED, "true")
    settings_store.set_value(db, SettingKey.OVERDUE_WEBHOOK_URL, HOOK)
    settings_store.set_value(db, SettingKey.OVERDUE_WEBHOOK_SECRET, "")
    return db


@pytest.fixture
def lend(db, admin):
    """Put a book out, overdue by `days`, and return the loan."""

    def _lend(*, title="Dune", days=3, private=False, borrower="Kim", notified=None):
        book = Book(title=title, is_private=private, added_by_user_id=admin["user"]["id"])
        db.add(book)
        db.flush()
        loan = Loan(
            book_id=book.id,
            loaned_to_name=borrower,
            loaned_by_user_id=admin["user"]["id"],
            due_at=now() - timedelta(days=days),
            notified_at=notified,
        )
        db.add(loan)
        db.commit()
        db.refresh(loan)
        return loan

    return _lend


class TestCheckedUrl:
    def test_accepts_https(self):
        assert notifications.checked_url(HOOK) == HOOK

    def test_accepts_http(self):
        assert notifications.checked_url("http://box.lan/hook") == "http://box.lan/hook"

    @pytest.mark.parametrize(
        "url",
        ["file:///etc/passwd", "gopher://box/1", "javascript:alert(1)", "//box/hook"],
    )
    def test_refuses_anything_else(self, url):
        with pytest.raises(notifications.WebhookRefused):
            notifications.checked_url(url)

    def test_refuses_an_empty_setting(self):
        with pytest.raises(notifications.WebhookRefused):
            notifications.checked_url("")


class TestSelection:
    def test_picks_up_an_overdue_loan(self, db, lend):
        lend()
        assert len(notifications.due_for_reminder(db, now(), 7)) == 1

    def test_ignores_a_loan_that_is_not_yet_due(self, db, lend):
        lend(days=-3)
        assert notifications.due_for_reminder(db, now(), 7) == []

    def test_ignores_a_loan_with_no_due_date(self, db, admin):
        book = Book(title="Dune", added_by_user_id=admin["user"]["id"])
        db.add(book)
        db.flush()
        db.add(
            Loan(
                book_id=book.id,
                loaned_to_name="Kim",
                loaned_by_user_id=admin["user"]["id"],
            )
        )
        db.commit()
        assert notifications.due_for_reminder(db, now(), 7) == []

    def test_ignores_a_returned_loan(self, db, lend):
        loan = lend()
        loan.returned_at = now()
        db.commit()
        assert notifications.due_for_reminder(db, now(), 7) == []

    def test_excludes_a_private_book(self, db, lend):
        """A webhook has no member identity and lands in a channel the whole
        library reads."""
        lend(private=True)
        assert notifications.due_for_reminder(db, now(), 7) == []

    def test_counts_what_privacy_held_back(self, db, lend):
        lend(private=True)
        assert notifications.count_private_overdue(db, now()) == 1

    def test_the_private_count_ignores_when_a_reminder_last_went_out(self, db, lend):
        """A book that was public when it was chased and was made private
        afterwards is the only way a private loan carries `notified_at` at all.
        Filtering on it hid exactly those for the length of the interval, so the
        count under-reported the thing it exists to report."""
        lend(private=True, notified=now() - timedelta(days=1))
        assert notifications.count_private_overdue(db, now()) == 1

    def test_ignores_a_trashed_book(self, db, lend):
        loan = lend()
        book = db.get(Book, loan.book_id)
        book.deleted_at = now()
        db.commit()
        assert notifications.due_for_reminder(db, now(), 7) == []

    def test_skips_a_loan_reminded_within_the_interval(self, db, lend):
        lend(notified=now() - timedelta(days=2))
        assert notifications.due_for_reminder(db, now(), 7) == []

    def test_picks_it_up_again_once_the_interval_has_passed(self, db, lend):
        lend(notified=now() - timedelta(days=9))
        assert len(notifications.due_for_reminder(db, now(), 7)) == 1


class TestTheDigest:
    def test_names_the_event_and_every_loan(self, db, lend):
        lend(title="Dune", days=4, borrower="Kim")
        digest = notifications.build_digest(notifications.due_for_reminder(db, now(), 7), now())

        assert digest["event"] == "overdue_loans"
        assert digest["count"] == 1
        assert digest["loans"][0]["title"] == "Dune"
        assert digest["loans"][0]["borrower"] == "Kim"
        assert digest["loans"][0]["days_overdue"] == 4

    def test_names_a_member_borrower_by_username(self, db, lend, member):
        loan = lend()
        loan.loaned_to_name = None
        loan.loaned_to_user_id = member["user"]["id"]
        db.commit()

        digest = notifications.build_digest(notifications.due_for_reminder(db, now(), 7), now())
        assert digest["loans"][0]["borrower"] == "member"


class TestSigning:
    def test_the_receiver_can_verify_it(self):
        """Compared with `compare_digest`, which is what a receiver must use."""
        body = b'{"event":"overdue_loans"}'
        header = notifications.sign(body, "s3cret")

        expected = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        assert hmac.compare_digest(header, f"sha256={expected}")

    def test_a_different_body_does_not_verify(self):
        header = notifications.sign(b"one", "s3cret")
        assert not hmac.compare_digest(header, notifications.sign(b"two", "s3cret"))


@pytest.mark.asyncio
class TestRunDigest:
    async def test_sends_nothing_while_switched_off(self, db, lend):
        lend()
        result = await notifications.run_digest(db)
        assert result["sent"] is False
        assert result["reason"] is OverdueNotifyReason.DISABLED
        assert "switched off" in result["detail"]

    async def test_sends_nothing_without_a_url(self, db, lend):
        settings_store.set_value(db, SettingKey.OVERDUE_WEBHOOK_ENABLED, "true")
        lend()
        result = await notifications.run_digest(db)
        assert result["sent"] is False
        assert result["reason"] is OverdueNotifyReason.NO_URL

    async def test_a_url_a_restore_wrote_is_refused_before_the_send(self, db, lend):
        """The scheme is checked again here, not only in `SettingsUpdate`: a
        restore writes the settings table through Core."""
        settings_store.set_value(db, SettingKey.OVERDUE_WEBHOOK_ENABLED, "true")
        settings_store.set_value(db, SettingKey.OVERDUE_WEBHOOK_URL, "file:///etc/passwd")
        lend()

        result = await notifications.run_digest(db)

        assert result["reason"] is OverdueNotifyReason.NO_URL

    async def test_sends_nothing_when_nothing_is_overdue(self, configured):
        result = await notifications.run_digest(configured)
        assert result["sent"] is False
        assert result["reason"] is OverdueNotifyReason.NOTHING_DUE
        assert result["loans"] == 0

    async def test_every_failure_names_a_reason(self, db, lend):
        """`sent: False` on its own made a refused webhook and a quiet week the
        same answer, which is what the button exists to tell apart."""
        lend()
        result = await notifications.run_digest(db)
        assert result["reason"] is not None

    async def test_posts_the_digest(self, configured, lend):
        lend()
        with respx.mock as mock:
            route = mock.post(HOOK).mock(return_value=httpx.Response(200))
            result = await notifications.run_digest(configured)

        assert result["sent"] is True
        # Null exactly when the send succeeded, which is the invariant the
        # client's rendering leans on.
        assert result["reason"] is None
        assert result["loans"] == 1
        body = json.loads(route.calls[0].request.content)
        assert body["event"] == "overdue_loans"

    async def test_a_sent_digest_stamps_the_loan(self, configured, lend):
        loan = lend()
        with respx.mock as mock:
            mock.post(HOOK).mock(return_value=httpx.Response(200))
            await notifications.run_digest(configured)

        configured.refresh(loan)
        assert loan.notified_at is not None

    async def test_the_same_loan_is_not_chased_twice_in_a_row(self, configured, lend):
        lend()
        with respx.mock as mock:
            mock.post(HOOK).mock(return_value=httpx.Response(200))
            await notifications.run_digest(configured)
            second = await notifications.run_digest(configured)

        assert second["sent"] is False

    async def test_a_failure_leaves_the_loan_to_retry(self, configured, lend):
        """The stamp goes on after a delivery that succeeded, never before."""
        loan = lend()
        with respx.mock as mock:
            mock.post(HOOK).mock(return_value=httpx.Response(500))
            result = await notifications.run_digest(configured)

        configured.refresh(loan)
        assert result["sent"] is False
        assert result["reason"] is OverdueNotifyReason.UNREACHABLE
        assert loan.notified_at is None

    async def test_a_transport_error_leaves_the_loan_to_retry(self, configured, lend):
        loan = lend()
        with respx.mock as mock:
            mock.post(HOOK).mock(side_effect=httpx.ConnectError("refused"))
            result = await notifications.run_digest(configured)

        configured.refresh(loan)
        assert result["sent"] is False
        assert loan.notified_at is None

    async def test_a_redirect_is_not_followed(self, configured, lend):
        """A 302 would send the library's book titles somewhere nobody
        approved."""
        lend()
        with respx.mock as mock:
            mock.post(HOOK).mock(
                return_value=httpx.Response(302, headers={"Location": "https://elsewhere.test/x"})
            )
            elsewhere = mock.post("https://elsewhere.test/x").mock(
                return_value=httpx.Response(200)
            )
            result = await notifications.run_digest(configured)

        assert elsewhere.call_count == 0
        assert result["sent"] is False

    async def test_it_signs_the_body_when_a_secret_is_set(self, configured, lend):
        settings_store.set_value(configured, SettingKey.OVERDUE_WEBHOOK_SECRET, "s3cret")
        lend()
        with respx.mock as mock:
            route = mock.post(HOOK).mock(return_value=httpx.Response(200))
            await notifications.run_digest(configured)

        request = route.calls[0].request
        expected = hmac.new(b"s3cret", request.content, hashlib.sha256).hexdigest()
        assert hmac.compare_digest(
            request.headers["X-Endpaper-Signature"], f"sha256={expected}"
        )

    async def test_it_sends_no_signature_without_a_secret(self, configured, lend):
        lend()
        with respx.mock as mock:
            route = mock.post(HOOK).mock(return_value=httpx.Response(200))
            await notifications.run_digest(configured)

        assert "X-Endpaper-Signature" not in route.calls[0].request.headers

    async def test_a_private_book_never_reaches_the_wire(self, configured, lend):
        lend(title="Public", private=False)
        lend(title="Secret", private=True)
        with respx.mock as mock:
            route = mock.post(HOOK).mock(return_value=httpx.Response(200))
            result = await notifications.run_digest(configured)

        assert b"Secret" not in route.calls[0].request.content
        assert result["skipped_private"] == 1

    async def test_a_failure_logs_the_host_and_not_the_url(self, configured, lend, caplog):
        """The URL may carry a token in its path or query string."""
        lend()
        with caplog.at_level(logging.WARNING), respx.mock as mock:
            mock.post(HOOK).mock(side_effect=httpx.ConnectError("refused"))
            await notifications.run_digest(configured)

        logged = caplog.text
        assert "hooks.example.org" in logged
        assert "abcdef" not in logged


class TestTheReplyIsNeverRead:
    """The digest is a send, and a receiver's answer is not data this app wants.

    Two defects, both on an **hourly ticker with no member action involved**, so
    a hostile or broken receiver gets a scheduled attempt at the pod rather than
    a one-off.
    """

    async def test_the_body_of_the_reply_is_not_buffered(self, configured, lend):
        """`client.post` reads the whole reply; `raise_for_status` needs none of it.

        A reply whose body raises on the second chunk, so reading it is the only
        thing that can fail. `client.post` buffers and the `RuntimeError`
        escapes; streaming and never reading finishes cleanly. Asserting on
        respx's `is_stream_consumed` instead does not work: httpx closes the
        stream on the way out of the context manager either way.
        """
        lend()

        async def explodes():
            yield b"x"
            raise RuntimeError("the reply was read")

        with respx.mock(assert_all_called=False) as mock:
            mock.post(HOOK).mock(return_value=httpx.Response(200, stream=explodes()))
            result = await notifications.run_digest(configured)

        assert result["sent"] is True

    async def test_a_receiver_that_never_answers_does_not_stop_the_ticker(
        self, configured, lend, monkeypatch
    ):
        """httpx's timeout is per operation, so it does not bound this at all.

        Measured on httpx 0.28.1: twenty bytes trickled at 0.9s apiece completed
        in 18.0s under a 1.0s timeout. `post_digest` therefore wraps the whole
        request in `asyncio.timeout`, and `run_digest` catches the `TimeoutError`
        that raises, because an uncaught one 500s the endpoint and kills the
        hourly run.
        """
        monkeypatch.setattr(notifications, "TIMEOUT_SECONDS", 0.05)
        lend()

        async def never() -> None:
            await asyncio.sleep(30)

        with respx.mock(assert_all_called=False) as mock:
            mock.post(HOOK).mock(side_effect=lambda request: never())
            started = time.monotonic()
            result = await notifications.run_digest(configured)
            spent = time.monotonic() - started

        assert result["sent"] is False
        assert result["reason"] is OverdueNotifyReason.UNREACHABLE
        assert spent < 5.0

    async def test_a_redirect_naming_an_unusable_host_is_not_a_500(
        self, configured, lend
    ):
        """Redirects are not followed, and httpx still builds the next request.

        `_build_redirect_request` reads `URL.host`, which calls `idna.decode`,
        so a receiver answering 302 with `location: http://xn--a.gov/x` raised
        `idna.IDNAError` out of `client.stream`. That is a `UnicodeError` and
        not an `httpx.HTTPError`, so it escaped this handler and 500ed
        `POST /api/loans/overdue/notify` on a webhook nobody here controls.
        """
        loan = lend()
        with respx.mock(assert_all_called=False) as mock:
            mock.post(HOOK).mock(
                return_value=httpx.Response(
                    302, headers={"location": "http://xn--a.gov/x"}
                )
            )
            result = await notifications.run_digest(configured)

        assert result["sent"] is False
        assert result["reason"] is OverdueNotifyReason.UNREACHABLE
        configured.refresh(loan)
        assert loan.notified_at is None

    async def test_the_loans_are_left_to_retry_after_a_timeout(self, configured, lend):
        """A digest that timed out did not arrive, so nothing may be stamped."""
        loan = lend()
        monkey = notifications.TIMEOUT_SECONDS
        try:
            notifications.TIMEOUT_SECONDS = 0.05

            async def never() -> None:
                await asyncio.sleep(30)

            with respx.mock(assert_all_called=False) as mock:
                mock.post(HOOK).mock(side_effect=lambda request: never())
                await notifications.run_digest(configured)
        finally:
            notifications.TIMEOUT_SECONDS = monkey

        configured.refresh(loan)
        assert loan.notified_at is None


class TestReminderDays:
    def test_defaults_to_a_week(self, db):
        assert notifications.reminder_days(db) == 7

    def test_reads_the_setting(self, db):
        settings_store.set_value(db, SettingKey.OVERDUE_REMINDER_DAYS, "3")
        assert notifications.reminder_days(db) == 3

    def test_a_nonsense_value_falls_back_rather_than_raising(self, db):
        settings_store.set_value(db, SettingKey.OVERDUE_REMINDER_DAYS, "soon")
        assert notifications.reminder_days(db) == 7

    def test_zero_is_clamped_off_the_resend_every_tick_case(self, db):
        settings_store.set_value(db, SettingKey.OVERDUE_REMINDER_DAYS, "0")
        assert notifications.reminder_days(db) == 1


def test_the_ticker_is_off_under_test():
    """A background task waking on a timer inside a suite that drops every
    table between tests is a source of order-dependent failures."""
    import config

    assert config.overdue_ticker_enabled() is False


def test_the_borrower_is_always_named(db, lend, admin):
    """`ck_loans_one_borrower` guarantees exactly one of the two, so the digest
    never carries a null borrower."""
    lend()
    digest = notifications.build_digest(notifications.due_for_reminder(db, now(), 7), now())
    assert digest["loans"][0]["borrower"]
    assert db.query(User).count() >= 1


# ── The two senders added beside the webhook ─────────────────────────────────

#: Shaped like a bot token, because `_TELEGRAM_TOKEN` insists on the shape
#: before the value is put in a URL path, and unmistakably not one.
#:
#: **The bot id is `0`.** A real Telegram bot id is eight to ten digits, so this
#: satisfies `^[0-9]{1,20}:` while no reader and no secret scanner can mistake it
#: for a credential. The previous fixture had a realistic id and a realistic
#: secret half, and GitHub's scanner flagged it on the public mirror: a value
#: that only *looks* like a secret costs exactly as much to triage as one that
#: is, and the mirror is where somebody else has to do that triage.
#:
#: Overridable from the environment for anyone pointing this at a live bot. The
#: default keeps the suite hermetic, which is why nothing in CI sets it.
BOT_TOKEN = os.getenv("TEST_TELEGRAM_BOT_TOKEN", "0:TEST-TOKEN-NOT-A-REAL-CREDENTIAL")
CHAT_ID = "-1001234567890"
TELEGRAM_SEND = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


@pytest.fixture
def telegram_on(db):
    settings_store.set_value(db, SettingKey.OVERDUE_TELEGRAM_ENABLED, "true")
    settings_store.set_value(db, SettingKey.TELEGRAM_BOT_TOKEN, BOT_TOKEN)
    settings_store.set_value(db, SettingKey.TELEGRAM_CHAT_ID, CHAT_ID)
    return db


@pytest.fixture
def mail_on(db):
    settings_store.set_value(db, SettingKey.OVERDUE_MAIL_ENABLED, "true")
    settings_store.set_value(db, SettingKey.MAIL_SERVER, "smtp.example.org")
    settings_store.set_value(db, SettingKey.MAIL_DEFAULT_SENDER, "library@example.org")
    settings_store.set_value(db, SettingKey.OVERDUE_MAIL_TO, "house@example.org")
    return db


@pytest.fixture
def sent_mail(monkeypatch):
    """`mailer.send` recorded rather than run. `checked_config` still runs."""
    calls: list[tuple] = []

    def record(config, subject, body):
        calls.append((config, subject, body, threading.current_thread().name))

    monkeypatch.setattr(mailer, "send", record)
    return calls


class TestRenderText:
    def test_it_names_every_book_and_borrower(self, db, lend):
        lend(title="Dune", days=4, borrower="Kim")
        text = notifications.render_text(
            notifications.build_digest(notifications.due_for_reminder(db, now(), 7), now())
        )
        assert "1 overdue book." in text
        assert "Dune" in text
        assert "Kim" in text
        assert "4 days overdue" in text

    def test_it_pluralises_the_count(self, db, lend):
        lend(title="One")
        lend(title="Two")
        text = notifications.render_text(
            notifications.build_digest(notifications.due_for_reminder(db, now(), 7), now())
        )
        assert text.startswith("2 overdue books.")

    def test_a_limit_drops_entries_and_says_how_many(self, db, lend):
        for index in range(20):
            lend(title=f"Book {index}")
        digest = notifications.build_digest(
            notifications.due_for_reminder(db, now(), 7), now()
        )
        text = notifications.render_text(digest, limit=200)

        assert units(text) <= 200
        assert "more." in text

    def test_the_limit_counts_the_units_telegram_counts(self, db, lend):
        """Telegram's 4096 is **UTF-16 code units**, and a code point outside
        the BMP is two of them, so `len()` under-counts exactly where a title
        carries an emoji: measured, `"\U0001f600" * 2100` is 2100 characters
        and 4200 units. Counting characters accepts a message the API rejects
        with a 400, and member-supplied catalogue content then silently stops
        every household reminder.

        50 titles of 100 emoji each is 5,000 characters and 10,000 units, so a
        renderer counting characters keeps far more of them than fits.
        """
        for _index in range(50):
            lend(title="\U0001f600" * 100)
        digest = notifications.build_digest(
            notifications.due_for_reminder(db, now(), 7), now()
        )
        text = notifications.render_text(digest, limit=notifications.TELEGRAM_MAX_UNITS)

        assert units(text) <= notifications.TELEGRAM_MAX_UNITS
        # The assertion above is the one that matters; this one says the test
        # would have failed before the fix rather than passing by accident.
        assert len(text) < units(text)

    def test_a_hard_cut_never_splits_a_surrogate_pair(self, db, lend):
        """The cut fires only when the header alone exceeds the limit. Dropping
        a code point at a time cannot land between the halves of a pair, which
        a slice counted in units could."""
        lend(title="\U0001f600" * 40)
        digest = notifications.build_digest(
            notifications.due_for_reminder(db, now(), 7), now()
        )
        text = notifications.render_text(digest, limit=5)

        assert units(text) <= 5
        # Re-encoding is the check: a lone surrogate cannot round trip.
        assert text.encode("utf-16-le").decode("utf-16-le") == text

    def test_it_leaves_a_short_list_whole(self, db, lend):
        lend(title="Dune")
        digest = notifications.build_digest(
            notifications.due_for_reminder(db, now(), 7), now()
        )
        assert "more." not in notifications.render_text(digest, limit=4096)

    def test_the_dropped_count_matches_what_was_dropped(self, db, lend):
        for index in range(20):
            lend(title=f"Book {index}")
        digest = notifications.build_digest(
            notifications.due_for_reminder(db, now(), 7), now()
        )
        text = notifications.render_text(digest, limit=300)

        kept = sum(1 for line in text.splitlines() if "days overdue" in line)
        dropped = int(text.rsplit("and ", 1)[1].split(" ", 1)[0])
        assert kept + dropped == 20


class TestTelegram:
    def test_the_host_is_a_constant_no_setting_can_reach(self):
        """Making it configurable would give away the one property this sender
        has that the webhook does not: the app chose the destination."""
        assert notifications.TELEGRAM_API == "https://api.telegram.org"
        assert not [key for key in SettingKey if "telegram_api" in key.value]
        assert notifications.telegram_url(BOT_TOKEN).startswith(
            "https://api.telegram.org/bot"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "token",
        ["", "nonsense", "../../evil", "123456:short", "123456:AA/../BBbbCCccDDddEEeeFF"],
    )
    async def test_a_token_that_is_not_a_token_is_refused(self, db, token):
        """It becomes a URL **path segment**, so a `/` or a `..` would choose
        the method being called or walk out of `/bot<token>/` entirely."""
        settings_store.set_value(db, SettingKey.TELEGRAM_BOT_TOKEN, token)
        settings_store.set_value(db, SettingKey.TELEGRAM_CHAT_ID, CHAT_ID)
        with pytest.raises(notifications.TelegramRefused):
            await notifications.send_telegram(db, "hello")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("chat", ["", "not a chat", "@a", "12 34"])
    async def test_a_chat_id_that_is_not_one_is_refused(self, db, chat):
        settings_store.set_value(db, SettingKey.TELEGRAM_BOT_TOKEN, BOT_TOKEN)
        settings_store.set_value(db, SettingKey.TELEGRAM_CHAT_ID, chat)
        with pytest.raises(notifications.TelegramRefused):
            await notifications.send_telegram(db, "hello")

    @pytest.mark.asyncio
    async def test_it_sends_plain_text_with_no_parse_mode(self, telegram_on):
        """With a parse mode set, a book called `Kiss & Tell` or `a_b` makes
        Telegram reject the whole send, and the reminder stops for everyone."""
        with respx.mock as mock:
            route = mock.post(TELEGRAM_SEND).mock(return_value=httpx.Response(200))
            await notifications.send_telegram(telegram_on, "Kiss & Tell <b> a_b")

        body = json.loads(route.calls[0].request.content)
        assert "parse_mode" not in body
        assert body["text"] == "Kiss & Tell <b> a_b"
        assert body["chat_id"] == CHAT_ID

    @pytest.mark.asyncio
    async def test_it_disables_the_link_preview(self, telegram_on):
        with respx.mock as mock:
            route = mock.post(TELEGRAM_SEND).mock(return_value=httpx.Response(200))
            await notifications.send_telegram(telegram_on, "http://example.org/book")

        assert json.loads(route.calls[0].request.content)["disable_web_page_preview"]

    @pytest.mark.asyncio
    async def test_a_failure_never_logs_the_token(self, telegram_on, lend, caplog):
        """Telegram takes the token in the URL **path**, so a log line naming
        the request URL is a log line naming the credential."""
        lend()
        with caplog.at_level(logging.WARNING), respx.mock as mock:
            mock.post(TELEGRAM_SEND).mock(return_value=httpx.Response(500))
            await notifications.run_digest(telegram_on)

        assert BOT_TOKEN not in caplog.text
        assert "AAaaBBbb" not in caplog.text
        assert "api.telegram.org" in caplog.text

    @pytest.mark.asyncio
    async def test_a_refusal_never_names_the_token(self, db, lend):
        lend()
        settings_store.set_value(db, SettingKey.OVERDUE_TELEGRAM_ENABLED, "true")
        settings_store.set_value(db, SettingKey.TELEGRAM_BOT_TOKEN, "sekrit-not-a-token")
        result = await notifications.run_digest(db)

        assert result["reason"] is OverdueNotifyReason.MISCONFIGURED
        assert "sekrit" not in result["detail"]

    @pytest.mark.asyncio
    async def test_a_private_book_never_reaches_the_chat(self, telegram_on, lend):
        lend(title="Public")
        lend(title="Secret", private=True)
        with respx.mock as mock:
            route = mock.post(TELEGRAM_SEND).mock(return_value=httpx.Response(200))
            result = await notifications.run_digest(telegram_on)

        assert "Secret" not in route.calls[0].request.content.decode()
        assert result["senders"][0]["skipped_private"] == 1

    @pytest.mark.asyncio
    async def test_a_long_digest_is_one_message_telegram_will_accept(
        self, telegram_on, lend
    ):
        """One message rather than several: two sends is a run that can half
        succeed, and `run_digest` would then have to decide what that means."""
        for index in range(400):
            lend(title=f"A rather long book title number {index}")
        with respx.mock as mock:
            route = mock.post(TELEGRAM_SEND).mock(return_value=httpx.Response(200))
            await notifications.run_digest(telegram_on)

        assert len(route.calls) == 1
        text = json.loads(route.calls[0].request.content)["text"]
        assert units(text) <= notifications.TELEGRAM_MAX_UNITS


class TestMailSender:
    @pytest.mark.asyncio
    async def test_it_runs_off_the_event_loop(self, mail_on, lend, sent_mail):
        """`smtplib` is blocking and every handler that reaches here is
        `async def`, so calling it inline would stop the event loop for the
        length of an SMTP conversation."""
        lend()
        await notifications.run_digest(mail_on)

        assert sent_mail[0][3] != threading.main_thread().name

    @pytest.mark.asyncio
    async def test_the_body_is_the_same_digest(self, mail_on, lend, sent_mail):
        lend(title="Dune", borrower="Kim", days=4)
        await notifications.run_digest(mail_on)

        _, subject, body, _ = sent_mail[0]
        assert subject == "1 overdue book"
        assert "Dune" in body
        assert "Kim" in body

    @pytest.mark.asyncio
    async def test_a_private_book_never_reaches_the_mailbox(
        self, mail_on, lend, sent_mail
    ):
        lend(title="Public")
        lend(title="Secret", private=True)
        result = await notifications.run_digest(mail_on)

        assert "Secret" not in sent_mail[0][2]
        assert result["senders"][0]["skipped_private"] == 1

    @pytest.mark.asyncio
    async def test_a_refused_configuration_is_recorded_not_silently_accepted(
        self, db, lend
    ):
        settings_store.set_value(db, SettingKey.OVERDUE_MAIL_ENABLED, "true")
        lend()
        result = await notifications.run_digest(db)

        assert result["sent"] is False
        assert result["reason"] is OverdueNotifyReason.MISCONFIGURED
        assert result["senders"][0]["sender"] is OverdueSender.EMAIL

    @pytest.mark.asyncio
    async def test_a_refused_send_leaves_the_loan_to_retry(
        self, mail_on, lend, monkeypatch
    ):
        loan = lend()

        def refuse(config, subject, body):
            raise smtplib.SMTPRecipientsRefused({"a@example.org": (550, b"no")})

        monkeypatch.setattr(mailer, "send", refuse)
        result = await notifications.run_digest(mail_on)

        mail_on.refresh(loan)
        assert result["reason"] is OverdueNotifyReason.UNREACHABLE
        assert loan.notified_at is None

    @pytest.mark.asyncio
    async def test_a_mail_server_that_stops_answering_does_not_hold_the_ticker(
        self, mail_on, lend, monkeypatch
    ):
        """`asyncio.to_thread` cannot be cancelled, so the deadline bounds this
        coroutine and not the thread. That is the property that matters: the
        hourly run is never held by a server that went quiet."""
        lend()
        monkeypatch.setattr(notifications, "MAIL_DEADLINE_SECONDS", 0.05)
        monkeypatch.setattr(mailer, "send", lambda *_: time.sleep(1.0))

        started = time.monotonic()
        result = await notifications.run_digest(mail_on)
        spent = time.monotonic() - started

        assert result["reason"] is OverdueNotifyReason.UNREACHABLE
        assert spent < 0.9


class TestThreeSendersOneDigest:
    @pytest.mark.asyncio
    async def test_every_sender_is_handed_the_same_books(
        self, configured, telegram_on, mail_on, in_app_on, lend, sent_mail
    ):
        """`build_digest` is the single source of what a reminder says. Three
        formats that decided for themselves is how the channels drift into
        describing different libraries."""
        lend(title="Dune", borrower="Kim")
        with respx.mock as mock:
            hook = mock.post(HOOK).mock(return_value=httpx.Response(200))
            chat = mock.post(TELEGRAM_SEND).mock(return_value=httpx.Response(200))
            result = await notifications.run_digest(configured)

        webhook_body = json.loads(hook.calls[0].request.content)
        chat_text = json.loads(chat.calls[0].request.content)["text"]

        assert [entry["title"] for entry in webhook_body["loans"]] == ["Dune"]
        assert "Dune" in chat_text
        assert "Dune" in sent_mail[0][2]
        # All four, in app included: it reports what it is showing rather than
        # receiving the digest, and a report missing a switched-on channel is
        # what #82 exists to stop.
        assert {entry["sender"] for entry in result["senders"]} == set(OverdueSender)

    @pytest.mark.asyncio
    async def test_the_withheld_count_is_reported_per_sender(
        self, configured, telegram_on, mail_on, lend, sent_mail
    ):
        """Every entry's number is what that sender actually withheld. They
        agree today because all three go to a channel; a single figure at the
        top would be a lie the moment one audience differs."""
        lend(title="Public")
        lend(title="Secret", private=True)
        with respx.mock as mock:
            mock.post(HOOK).mock(return_value=httpx.Response(200))
            mock.post(TELEGRAM_SEND).mock(return_value=httpx.Response(200))
            result = await notifications.run_digest(configured)

        assert [entry["skipped_private"] for entry in result["senders"]] == [1, 1, 1]

    @pytest.mark.asyncio
    async def test_one_broken_sender_does_not_stop_the_others(
        self, configured, telegram_on, mail_on, lend, sent_mail
    ):
        lend()
        with respx.mock as mock:
            mock.post(HOOK).mock(side_effect=httpx.ConnectError("refused"))
            chat = mock.post(TELEGRAM_SEND).mock(return_value=httpx.Response(200))
            result = await notifications.run_digest(configured)

        assert chat.call_count == 1
        assert len(sent_mail) == 1
        assert result["sent"] is True
        failed = [entry for entry in result["senders"] if not entry["sent"]]
        assert [entry["sender"] for entry in failed] == [OverdueSender.WEBHOOK]

    @pytest.mark.asyncio
    async def test_one_delivery_is_enough_to_stamp_the_loan(
        self, configured, telegram_on, lend
    ):
        """The column records that the loan was chased, and it was. Stamping
        only on a clean sweep would make one broken receiver repeat the same
        list hourly on the channels that work."""
        loan = lend()
        with respx.mock as mock:
            mock.post(HOOK).mock(side_effect=httpx.ConnectError("refused"))
            mock.post(TELEGRAM_SEND).mock(return_value=httpx.Response(200))
            await notifications.run_digest(configured)

        configured.refresh(loan)
        assert loan.notified_at is not None

    @pytest.mark.asyncio
    async def test_nothing_delivered_leaves_every_loan_to_retry(
        self, configured, telegram_on, lend
    ):
        loan = lend()
        with respx.mock as mock:
            mock.post(HOOK).mock(side_effect=httpx.ConnectError("refused"))
            mock.post(TELEGRAM_SEND).mock(return_value=httpx.Response(500))
            result = await notifications.run_digest(configured)

        configured.refresh(loan)
        assert result["sent"] is False
        assert loan.notified_at is None
        assert all(not entry["sent"] for entry in result["senders"])

    @pytest.mark.asyncio
    async def test_only_the_senders_that_are_on_are_reported(self, configured, lend):
        lend()
        with respx.mock as mock:
            mock.post(HOOK).mock(return_value=httpx.Response(200))
            result = await notifications.run_digest(configured)

        assert [entry["sender"] for entry in result["senders"]] == [
            OverdueSender.WEBHOOK
        ]

    @pytest.mark.asyncio
    async def test_no_sender_at_all_is_still_a_single_disabled_answer(self, db, lend):
        lend()
        result = await notifications.run_digest(db)

        assert result["reason"] is OverdueNotifyReason.DISABLED
        assert result["senders"] == []

    @pytest.mark.asyncio
    async def test_nothing_overdue_attempts_no_sender(self, configured, telegram_on):
        result = await notifications.run_digest(configured)

        assert result["reason"] is OverdueNotifyReason.NOTHING_DUE
        assert result["senders"] == []


# ── #86, the in app channel ───────────────────────────────────────────────────


@pytest.fixture
def lend_to(db, admin):
    """Put a book out to a member, overdue, and return the loan.

    `lend` above lends to a free-text name, which is the household case. This
    one names a borrower with an account, which is what the in app channel's
    per member arm is about: a loan concerns the member who borrowed it and the
    member who lent it, and neither of those is a string.
    """

    def _lend_to(*, title="Dune", days=3, owner=None, borrower=None, lender=None, private=False):
        owner_id = owner if owner is not None else admin["user"]["id"]
        book = Book(title=title, is_private=private, added_by_user_id=owner_id)
        db.add(book)
        db.flush()
        loan = Loan(
            book_id=book.id,
            loaned_to_user_id=borrower,
            loaned_to_name=None if borrower else "Kim",
            loaned_by_user_id=lender if lender is not None else admin["user"]["id"],
            due_at=now() - timedelta(days=days),
        )
        db.add(loan)
        db.commit()
        db.refresh(loan)
        return loan

    return _lend_to


class TestTheInAppChannel:
    """#86. The one reminder channel that needs nothing from the household."""

    def test_it_is_the_only_sender_that_ships_switched_on(self):
        """The asymmetry is the feature, so it is asserted rather than assumed.

        The other three send catalogue content somewhere outside this app, so
        they start silent and somebody chooses. This one sends nothing
        anywhere, and a household that configured nothing being told nothing is
        the complaint the channel exists to answer.
        """
        on = {
            sender
            for sender in OverdueSender
            if settings_store.DEFAULTS[notifications._ENABLED_KEY[sender]] == "true"
        }
        assert on == {OverdueSender.IN_APP}

    def test_exactly_one_sender_does_not_push_and_it_is_the_in_app_one(self):
        """Counted rather than stated. `pushes_outward` decides both which
        senders `run_digest` attempts and which may stamp `notified_at`, so a
        second non-pushing sender arriving unnoticed would silently stop
        stamping for a channel that does deliver."""
        assert [
            sender for sender in OverdueSender if not notifications.pushes_outward(sender)
        ] == [OverdueSender.IN_APP]

    @pytest.mark.asyncio
    async def test_the_in_app_channel_is_never_handed_to_a_sender(self, db):
        """`_deliver` has an arm for it and that arm must stay unreachable.

        Reaching it would mean `run_digest` had started treating a pull channel
        as a delivery, which stamps `notified_at` on loans nothing chased.
        """
        with pytest.raises(AssertionError, match="does not push"):
            await notifications._deliver(OverdueSender.IN_APP, db, {}, "subject")

    @pytest.mark.asyncio
    async def test_it_alone_sends_nothing_and_says_so(self, in_app_on, lend):
        """Not `DISABLED`: reminders are on, and every member reads them in the
        app. The two answers read differently on the screen."""
        loan = lend()
        result = await notifications.run_digest(in_app_on)

        assert result["sent"] is False
        assert result["reason"] is OverdueNotifyReason.IN_APP_ONLY
        assert [entry["sender"] for entry in result["senders"]] == [OverdueSender.IN_APP]
        in_app_on.refresh(loan)
        assert loan.notified_at is None

    @pytest.mark.asyncio
    async def test_it_does_not_stamp_a_loan_a_broken_channel_failed_to_send(
        self, configured, in_app_on, lend
    ):
        """The measurement `pushes_outward` exists for.

        With the in app entry counted as a delivery, every run would stamp,
        `due_for_reminder` would then select nothing until the interval expired,
        and a broken webhook would be attempted once a week instead of once an
        hour at the shipped default of seven days.
        """
        loan = lend()
        with respx.mock as mock:
            mock.post(HOOK).mock(side_effect=httpx.ConnectError("refused"))
            result = await notifications.run_digest(configured)

        configured.refresh(loan)
        assert loan.notified_at is None
        assert result["sent"] is False
        assert result["reason"] is OverdueNotifyReason.UNREACHABLE
        # Reported all the same: the member is being told even though the
        # webhook is not.
        assert any(entry["sender"] is OverdueSender.IN_APP for entry in result["senders"])

    @pytest.mark.asyncio
    async def test_a_pushing_sender_still_stamps_beside_it(
        self, configured, in_app_on, lend
    ):
        loan = lend()
        with respx.mock as mock:
            mock.post(HOOK).mock(return_value=httpx.Response(200))
            await notifications.run_digest(configured)

        configured.refresh(loan)
        assert loan.notified_at is not None

    @pytest.mark.asyncio
    async def test_it_is_reported_on_a_run_with_nothing_overdue(self, in_app_on, configured):
        """"Is this on" is what a household with no receiver is asking, and a
        quiet week used to answer with an empty list."""
        result = await notifications.run_digest(configured)

        assert result["reason"] is OverdueNotifyReason.NOTHING_DUE
        assert [entry["sender"] for entry in result["senders"]] == [OverdueSender.IN_APP]

    @pytest.mark.asyncio
    async def test_it_withholds_nothing_from_its_audience(self, in_app_on, configured, lend):
        """Zero, not the count the other three report. Its audience is a
        member, and a private book is shown to the member who added it."""
        lend(title="Public")
        lend(title="Secret", private=True)
        with respx.mock as mock:
            mock.post(HOOK).mock(return_value=httpx.Response(200))
            result = await notifications.run_digest(configured)

        by_sender = {entry["sender"]: entry for entry in result["senders"]}
        assert by_sender[OverdueSender.IN_APP]["skipped_private"] == 0
        assert by_sender[OverdueSender.WEBHOOK]["skipped_private"] == 1

    def test_the_household_count_includes_private_books(self, db, lend):
        """What the app is showing, across every member. The digest's own count
        excludes them by construction, so this is a different number."""
        lend(title="Public")
        lend(title="Secret", private=True)
        assert notifications.count_overdue(db, now()) == 2


class TestWhoTheInAppNoticeIsFor:
    """The audience the owner settled: per member, except for staff."""

    def test_a_member_is_told_about_a_loan_they_borrowed(self, db, member, lend_to):
        loan = lend_to(borrower=member["user"]["id"])
        viewer = db.get(User, member["user"]["id"])
        # The row, not the count: a count of one cannot say it is the right one.
        assert [row.id for row in notifications.overdue_for_viewer(db, viewer, now())] == [
            loan.id
        ]

    def test_a_member_is_told_about_a_loan_they_made(self, db, member, lend_to):
        """They lent it out, so chasing it is theirs to do."""
        loan = lend_to(owner=member["user"]["id"], lender=member["user"]["id"])
        viewer = db.get(User, member["user"]["id"])
        assert [row.id for row in notifications.overdue_for_viewer(db, viewer, now())] == [
            loan.id
        ]

    def test_a_member_is_not_told_about_somebody_elses_loan(
        self, db, member, other_user, lend_to
    ):
        """The loans page is the household's ledger and shows every loan the
        viewer may see. This is a nudge, and a nudge about a book you neither
        lent nor borrowed is noise."""
        lend_to(owner=other_user["user"]["id"], lender=other_user["user"]["id"])
        viewer = db.get(User, member["user"]["id"])
        assert notifications.overdue_for_viewer(db, viewer, now()).all() == []

    def test_an_admin_is_told_about_every_loan_on_their_shelf(
        self, db, admin, other_user, lend_to
    ):
        """Staff read open reminders and outstanding books. `sees_every_loan`
        is the seam library mode widens."""
        loan = lend_to(owner=other_user["user"]["id"], lender=other_user["user"]["id"])
        viewer = db.get(User, admin["user"]["id"])
        assert [row.id for row in notifications.overdue_for_viewer(db, viewer, now())] == [
            loan.id
        ]

    def test_a_member_is_told_about_their_own_private_book(
        self, db, member, lend_to
    ):
        """The capability no outward channel can have. `visible_to()` has always
        said a private book is visible to the member who added it, and being
        told about your own book is not a disclosure."""
        loan = lend_to(owner=member["user"]["id"], lender=member["user"]["id"], private=True)
        viewer = db.get(User, member["user"]["id"])
        assert [row.id for row in notifications.overdue_for_viewer(db, viewer, now())] == [
            loan.id
        ]

    def test_an_admin_is_not_told_about_somebody_elses_private_book(
        self, db, admin, other_user, lend_to
    ):
        """"Staff see everything" must not become "an admin is a superuser over
        private books". The Shelf is applied first, on both arms."""
        lend_to(
            owner=other_user["user"]["id"],
            lender=other_user["user"]["id"],
            private=True,
        )
        viewer = db.get(User, admin["user"]["id"])
        assert notifications.overdue_for_viewer(db, viewer, now()).all() == []

    def test_library_mode_lets_a_member_read_a_loan_they_are_not_party_to(
        self, db, member, other_user, lend_to
    ):
        """The refusal the mode lifts, and the reason the item exists.

        A volunteer at an archive is not an admin and still has to chase a book
        somebody else lent out. With the mode off this is the assertion two
        tests above, which answers with nothing.
        """
        settings_store.set_value(db, SettingKey.LIBRARY_MODE, "true")
        loan = lend_to(owner=other_user["user"]["id"], lender=other_user["user"]["id"])
        viewer = db.get(User, member["user"]["id"])
        assert [row.id for row in notifications.overdue_for_viewer(db, viewer, now())] == [
            loan.id
        ]

    def test_library_mode_does_not_reach_somebody_elses_private_book(
        self, db, member, other_user, lend_to
    ):
        """The test the relaxation exists to pass.

        The mode widens the arm about the loan's **parties**. The Shelf is
        applied before it and is untouched, so a private book somebody else
        added is as far out of reach with the mode on as it is with it off,
        exactly as it is for an admin.
        """
        settings_store.set_value(db, SettingKey.LIBRARY_MODE, "true")
        lend_to(
            owner=other_user["user"]["id"],
            lender=other_user["user"]["id"],
            private=True,
        )
        viewer = db.get(User, member["user"]["id"])
        assert notifications.overdue_for_viewer(db, viewer, now()).all() == []

    def test_a_returned_loan_is_not_chased(self, db, member, lend_to):
        loan = lend_to(borrower=member["user"]["id"])
        loan.returned_at = now()
        db.commit()
        viewer = db.get(User, member["user"]["id"])
        assert notifications.overdue_for_viewer(db, viewer, now()).all() == []

    def test_a_recently_chased_loan_is_still_shown(self, db, member, lend_to):
        """No `notified_at` clause, deliberately: the notice is read rather than
        sent, so quieting it for a week would be the app hiding something it is
        still looking at."""
        loan = lend_to(borrower=member["user"]["id"])
        loan.notified_at = now()
        db.commit()
        viewer = db.get(User, member["user"]["id"])
        assert notifications.overdue_for_viewer(db, viewer, now()).count() == 1

    def test_the_staff_arm_is_decided_in_exactly_one_place(self):
        """A rule with two homes is a rule that drifts, and this one decides
        who reads another member's loans.

        Read with `ast` rather than counted as text, for the reason
        `test_shelf.py` gives: a docstring naming the attribute, or a comment
        arguing about it, would make a text count answer a different question
        every time somebody edits a paragraph.
        """
        tree = ast.parse((BACKEND / "notifications.py").read_text())
        reads = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr == "is_admin"
        ]
        assert len(reads) == 1, (
            "`sees_every_loan` is the only place this question is asked. A "
            f"second reader is a second rule: lines {reads}"
        )

    def test_the_mode_arm_is_decided_in_exactly_one_place(self):
        """A guard for the clause library mode added, for the reason its
        sibling exists: two readers of the mode in this module are two rules
        about who may read another member's loans.

        **Not the same guard as `is_admin`'s, and billing it as one is what
        made the first version wrong.** That subject has exactly one door,
        attribute access on a `User`, so matching an attribute matches
        everything. This subject has three, because the mode is a *setting*: it
        is reachable as `settings_store.library_mode(db)`, as
        `settings_store.get_bool(db, SettingKey.LIBRARY_MODE)`, which is what
        `routers/settings.py` and every helper in these tests actually write,
        and as either of those imported to a bare name. The first version
        required an `ast.Call` on an `ast.Attribute` named `library_mode` and
        so was walked past by two of the three, the dominant idiom included.

        So it counts the **subject** rather than one syntax for reaching it:
        every mention of either name, as an attribute or as a bare name,
        wherever it appears. That is structural rather than an arm per
        spelling, which is the shape this repository keeps having to rewrite.
        The baseline is 1 and not 2 because `LIBRARY_MODE` does not appear in
        this module at all: `library_mode()` is the function that names it.

        **An import alias is the subject under another name**, so the local
        names are resolved first, the way `test_shelf.py::_entity_aliases`
        resolves its own. Without that,
        `from settings_store import library_mode as _lm` followed by `_lm(db)`
        read the mode and passed, which is a docstring claiming the subject
        while the code counts two spellings of it: the same defect this guard
        was rewritten to fix, one round later. This repository has been walked
        past by an aliased import before.

        `import settings_store as ss` needs nothing extra: `ss.library_mode`
        is still an attribute named `library_mode`, and the attribute arm
        already sees it.

        `ast` rather than text, so the paragraphs in `sees_every_loan` that
        argue about the mode cannot move the count.
        """
        tree = ast.parse((BACKEND / "notifications.py").read_text())
        subject = {"library_mode", "LIBRARY_MODE"}
        # Local names bound to the subject by an aliased import. The `import
        # x as y` form needs no entry: it renames the module, not the subject,
        # and the attribute keeps its own name.
        subject |= {
            alias.asname
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
            if alias.name in subject and alias.asname
        }
        reads = [
            node.lineno
            for node in ast.walk(tree)
            if (isinstance(node, ast.Attribute) and node.attr in subject)
            or (isinstance(node, ast.Name) and node.id in subject)
        ]
        assert len(reads) == 1, (
            "`sees_every_loan` is the only place this module asks whether the "
            f"library is in library mode: lines {reads}"
        )


# ── #82, a broken channel is visible ──────────────────────────────────────────


def stored_health(db):
    return settings_store.get_json(db, SettingKey.SENDER_HEALTH)


def failure(reason=OverdueNotifyReason.UNREACHABLE, detail="nope"):
    return {"sender": OverdueSender.EMAIL, "sent": False, "reason": reason, "detail": detail}


class TestTheStandingRecord:
    """The ticker used to throw `run_digest`'s result away, so the only record
    of a channel failing hourly was a warning in the container log."""

    def test_a_failure_starts_a_run_of_them(self, db):
        moment = now()
        notifications.record_run(db, {"senders": [failure()]}, moment)

        entry = stored_health(db)["email"]
        assert entry["sent"] is False
        assert entry["failures"] == 1
        assert entry["failing_since"] == moment.isoformat()

    def test_a_second_failure_counts_up_and_keeps_the_start(self, db):
        first = now() - timedelta(hours=5)
        notifications.record_run(db, {"senders": [failure()]}, first)
        notifications.record_run(db, {"senders": [failure()]}, now())

        entry = stored_health(db)["email"]
        assert entry["failures"] == 2
        assert entry["failing_since"] == first.isoformat()

    def test_a_success_clears_the_run(self, db):
        notifications.record_run(db, {"senders": [failure()]}, now())
        notifications.record_run(
            db,
            {"senders": [{"sender": OverdueSender.EMAIL, "sent": True, "reason": None, "detail": None}]},
            now(),
        )

        entry = stored_health(db)["email"]
        assert entry["sent"] is True
        assert entry["failures"] == 0
        assert entry["failing_since"] is None

    def test_a_sender_this_run_did_not_attempt_is_left_alone(self, db):
        """A run with nothing overdue attempts nothing, and overwriting a
        standing failure with silence is how the record comes to say a broken
        channel is fine."""
        notifications.record_run(db, {"senders": [failure()]}, now())
        notifications.record_run(db, {"senders": []}, now())

        assert stored_health(db)["email"]["failures"] == 1

    @pytest.mark.asyncio
    async def test_a_run_records_itself_without_anybody_reading_the_result(
        self, configured, lend
    ):
        """The whole of #82: `ticker()` discards what `run_digest` returns, and
        the fix is that the run keeps its own record. Nothing here reads the
        return value, exactly as the ticker does not."""
        lend()
        with respx.mock as mock:
            mock.post(HOOK).mock(side_effect=httpx.ConnectError("refused"))
            await notifications.run_digest(configured)

        assert stored_health(configured)["webhook"]["sent"] is False

    @pytest.mark.asyncio
    async def test_a_manual_run_records_it_too(self, configured, lend):
        """The endpoint an admin presses runs the same pass, and if only the
        ticker recorded, "Send now" would leave the panel describing an older
        run. That race is the one the ticket describes."""
        lend()
        with respx.mock as mock:
            mock.post(HOOK).mock(return_value=httpx.Response(200))
            await notifications.run_digest(configured)

        assert stored_health(configured)["webhook"]["sent"] is True


class TestWhenAChannelCountsAsBroken:
    """One failed send is a network. Every send failing for a day is a
    configuration. A design that cannot tell them apart gets switched off."""

    def test_a_refusal_is_broken_at_once(self):
        """Nothing was dialled: `checked_url`, both Telegram regexes and
        `mailer.checked_config` all raise before a socket is opened, so there is
        no outage to wait out and nothing will succeed until a setting changes.
        """
        entry = {
            "sent": False,
            "reason": OverdueNotifyReason.MISCONFIGURED.value,
            "failing_since": now().isoformat(),
            "failures": 1,
        }
        assert notifications._is_broken(entry, now()) is True

    def test_one_transport_failure_is_not(self):
        entry = {
            "sent": False,
            "reason": OverdueNotifyReason.UNREACHABLE.value,
            "failing_since": now().isoformat(),
            "failures": 1,
        }
        assert notifications._is_broken(entry, now()) is False

    def test_a_day_of_them_is(self):
        started = now() - timedelta(hours=notifications.BROKEN_AFTER_HOURS + 1)
        entry = {
            "sent": False,
            "reason": OverdueNotifyReason.UNREACHABLE.value,
            "failing_since": started.isoformat(),
            "failures": 24,
        }
        assert notifications._is_broken(entry, now()) is True

    def test_a_single_failure_that_is_merely_old_is_not(self):
        """The case elapsed time alone gets wrong, and it is the common one: a
        working webhook beside a broken mail server stamps `notified_at`, so
        mail is attempted once per reminder interval. Its one failure would
        otherwise cross the window having failed exactly once."""
        started = now() - timedelta(days=7)
        entry = {
            "sent": False,
            "reason": OverdueNotifyReason.UNREACHABLE.value,
            "failing_since": started.isoformat(),
            "failures": 1,
        }
        assert notifications._is_broken(entry, now()) is False

    def test_a_success_is_never_broken(self):
        assert notifications._is_broken({"sent": True}, now()) is False

    def test_a_channel_that_has_never_run_is_not_broken(self):
        assert notifications._is_broken({}, now()) is False


class TestReadingTheRecord:
    def test_only_switched_on_channels_that_push_are_reported(
        self, configured, in_app_on
    ):
        """The in app notice is switched on here and absent anyway.

        It hands the digest to nobody, so a row for it could only ever report a
        success: an assertion about a delivery nothing performed, which a reader
        cannot tell from a channel that was actually checked.
        """
        assert [entry["sender"] for entry in notifications.health(configured, now())] == [
            OverdueSender.WEBHOOK
        ]

    def test_the_in_app_channel_is_kept_out_of_the_record_too(self, configured, in_app_on):
        """Not filtered on the way out while being written on the way in: one
        seam, `pushes_outward`, read in both places, so the row does not exist
        rather than existing and being hidden."""
        notifications.record_run(
            configured,
            {
                "senders": [
                    {
                        "sender": OverdueSender.IN_APP,
                        "sent": True,
                        "reason": None,
                        "detail": None,
                    }
                ]
            },
            now(),
        )

        assert stored_health(configured) == {}

    def test_a_channel_that_has_never_run_says_so(self, configured):
        """"Not yet" and "fine" are the two answers a household most needs to
        tell apart on the day they configure a channel."""
        entry = notifications.health(configured, now())[0]
        assert entry["sender"] is OverdueSender.WEBHOOK
        assert entry["last_run_at"] is None
        assert entry["sent"] is None
        assert entry["broken"] is False

    def test_switching_a_channel_off_and_on_forgets_its_record(self, configured):
        """A household that replaces an expired bot token should not meet a
        banner about the token they replaced."""
        notifications.record_run(
            configured,
            {"senders": [{**failure(), "sender": OverdueSender.WEBHOOK}]},
            now(),
        )
        notifications.forget_health(configured, OverdueSender.WEBHOOK)

        assert notifications.health(configured, now())[0]["last_run_at"] is None

    def test_a_row_a_restore_mangled_degrades_rather_than_raising(self, configured):
        """Read on the hourly ticker, where a raise stops the task for the life
        of the container. The row is settings data, so a restore or a hand edit
        can put anything in it."""
        settings_store.set_value(configured, SettingKey.SENDER_HEALTH, "not json at all")
        assert notifications.health(configured, now()) != []

        settings_store.set_value(configured, SettingKey.SENDER_HEALTH, '["a list"]')
        assert notifications.health(configured, now()) != []

        settings_store.set_value(
            configured, SettingKey.SENDER_HEALTH, '{"webhook": {"sent": false, "at": "nope"}}'
        )
        entry = notifications.health(configured, now())[0]
        assert entry["last_run_at"] is None
        assert entry["broken"] is False

    def test_a_timestamp_with_an_offset_does_not_raise(self, configured):
        """The one hostile shape that actually raised, and the one the three
        above missed.

        Everything here stores naive UTC, and `_is_broken` subtracts
        `failing_since` from a `now` of that shape, so an aware timestamp is a
        `TypeError` rather than a wrong answer: a **500** on
        `GET /api/settings/sender-health`. `fromisoformat` parses it happily, so
        nothing before this caught it, and `settings` is in `backup._TABLES` so
        the row crosses a restore.
        """
        settings_store.set_value(
            configured,
            SettingKey.SENDER_HEALTH,
            '{"webhook": {"sent": false, "reason": "unreachable", "failures": 9, '
            '"at": "2020-01-01T00:00:00+00:00", '
            '"failing_since": "2020-01-01T00:00:00+00:00"}}',
        )

        entry = notifications.health(configured, now())[0]

        assert entry["broken"] is True
        assert entry["failing_since"].tzinfo is None

    def test_an_offset_is_converted_rather_than_dropped(self):
        """Stripping `+02:00` would move the timestamp two hours, which is the
        kind of wrong that reads as right: a channel broken since 09:00 local
        would report 09:00 UTC and cross the window an hour early."""
        assert notifications._parsed("2026-08-20T11:00:00+02:00") == datetime(
            2026, 8, 20, 9, 0, 0
        )

    def test_the_failure_window_is_a_constant_of_this_module(self):
        """One of two, and the two catch **disjoint** mutations.

        This one pins the property where the value lives: both constants are
        assigned a plain literal, so nothing derives them from the reminder
        interval, from each other, or from anything else. That is the whole of
        "these are two different quantities and must not be read as one number".

        It exists because the sibling below is weak on its own: the mutation
        `BROKEN_AFTER_HOURS = MAX_REMINDER_DAYS * 24`, using a name this module
        already imports, passes a rule that reads the body of `_is_broken`.

        A `next()` rather than a search, so a constant that is deleted or
        renamed raises here instead of leaving the assertion with nothing to
        check.
        """
        tree = ast.parse((BACKEND / "notifications.py").read_text())
        for name in ("BROKEN_AFTER_HOURS", "MIN_FAILURES_TO_INTERRUPT"):
            assigned = next(
                node.value
                for node in tree.body
                if isinstance(node, ast.AnnAssign | ast.Assign)
                and name
                in {
                    target.id
                    for target in (
                        [node.target] if isinstance(node, ast.AnnAssign) else node.targets
                    )
                    if isinstance(target, ast.Name)
                }
            )
            assert isinstance(assigned, ast.Constant), (
                f"{name} is computed from something rather than stated. It bounds "
                "how long a channel may be broken before somebody is interrupted, "
                "which is not a function of how often a loan is chased."
            )

    def test_the_failure_window_is_not_read_from_the_reminder_interval(self):
        """The other of two, and it was deleted for being weak rather than kept
        for being disjoint. That was the mistake this docstring records.

        It reads the body of `_is_broken` and asserts it names neither
        `reminder_days` nor `OVERDUE_REMINDER_DAYS`. Weak **today**, and only
        today, because `_is_broken(entry, now)` takes no `Session` and so cannot
        reach a setting whatever it names. That is precisely what makes it worth
        keeping: it is the tripwire on the signature changing. A future
        `_is_broken(entry, now, db)` computing
        `timedelta(hours=reminder_days(db) * 24)`, with both constants left as
        literals, passes the sibling above and fails here.

        Neither rule is sufficient and neither subsumes the other. Measured
        against the two mutations: `BROKEN_AFTER_HOURS = MAX_REMINDER_DAYS * 24`
        is caught by the sibling and passes this; reading the interval inside the
        body is caught by this and passes the sibling.
        """
        tree = ast.parse((BACKEND / "notifications.py").read_text())
        broken = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_is_broken"
        )
        named = {
            node.id if isinstance(node, ast.Name) else node.attr
            for node in ast.walk(broken)
            if isinstance(node, ast.Name | ast.Attribute)
        }
        assert not named & {"reminder_days", "OVERDUE_REMINDER_DAYS"}, (
            "`_is_broken` reads how often a loan is chased. That is a different "
            "quantity from how long a channel may be broken before somebody is "
            "interrupted, and reading one as the other is what naming them "
            "separately exists to prevent."
        )


class TestEverySenderSettingIsOwned:
    """The guard that replaces a `KeyError` that never existed.

    The ownership table used to live in `routers/settings.py`, keyed on the
    payload field, and its docstring claimed a missing entry was "a `KeyError`
    at import". Nothing indexed it that way: the loop read `.get(field)` and the
    webhook was handled outside the loop entirely, so a fifth sender's toggle
    would have kept a stale health record silently. One of its own four entries
    already broke the stated invariant, `overdue_webhook_enabled` being absent
    from the table it claimed to be checked against, and nothing raised.

    So the invariant is asserted rather than asserted-about. Two halves, because
    a row can be missed in two different places.
    """

    def test_every_settings_row_the_senders_read_belongs_to_one(self):
        """Half one: a new sender setting cannot arrive unclassified.

        Read off the modules that do the sending rather than off a list, so a
        `SettingKey` added for a channel and forgotten in `_CONFIGURED_BY` fails
        here. The exemptions are named with a reason each, which is the house
        shape: an exemption nobody can defend in one line is the query to change.
        """
        not_a_channel = {
            # How often a loan is chased, not whether a channel works.
            SettingKey.OVERDUE_REMINDER_DAYS,
            # The record itself.
            SettingKey.SENDER_HEALTH,
        }
        owned = {key for keys in notifications._CONFIGURED_BY.values() for key in keys}
        read = set()
        # The paths rather than `module.__file__`, which mypy types as
        # `str | None`: a module without one is a builtin, and neither of these
        # is, but a guard that needs an ignore comment to compile is a guard
        # somebody edits into passing.
        for source in (BACKEND / "notifications.py", BACKEND / "mailer.py"):
            tree = ast.parse(source.read_text())
            read |= {
                getattr(SettingKey, node.attr)
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "SettingKey"
                and hasattr(SettingKey, node.attr)
            }

        assert read - owned - not_a_channel == set(), (
            "These settings rows are read while sending and belong to no sender, "
            "so writing one leaves that channel's health record describing a "
            "configuration that no longer exists."
        )

    def test_every_sender_owns_at_least_its_own_switch(self):
        """Half two: a sender cannot be added with no rows at all.

        `_ENABLED_KEY` is what `run_digest` reads, so a sender missing from
        `_CONFIGURED_BY` would still send and still never clear its record.
        """
        for sender, key in notifications._ENABLED_KEY.items():
            assert key in notifications._CONFIGURED_BY[sender], sender

    def test_the_mail_settings_are_owned_as_a_group(self):
        """`MAIL_KEYS` is spliced in rather than retyped, so an eighth mail
        setting is owned the day it is added. Retyping the seven is how the
        commonest fix, a corrected server or port, would have been left out."""
        assert set(settings_store.MAIL_KEYS) <= notifications._CONFIGURED_BY[
            OverdueSender.EMAIL
        ]


class TestTheInAppCountIsCounted:
    def test_the_notice_asks_for_a_number_rather_than_rows(self, db, admin, lend_to):
        """Measured, because the shape is the whole finding.

        `len(query.all())` built one ORM object per overdue loan on every visit
        to the library page, to take their length. The query is handed out
        rather than the rows so the one production caller can say `.count()`.
        """
        from sqlalchemy import event

        for index in range(20):
            lend_to(title=f"Book {index}")
        viewer = db.get(User, admin["user"]["id"])

        statements: list[str] = []

        def record(conn, cursor, statement, *rest):
            statements.append(statement)

        db.expunge_all()
        bind = db.get_bind()
        event.listen(bind, "before_cursor_execute", record)
        try:
            counted = notifications.overdue_for_viewer(db, viewer, now()).count()
        finally:
            event.remove(bind, "before_cursor_execute", record)

        loans_held = [
            obj for obj in db.identity_map.values() if isinstance(obj, Loan)
        ]

        assert counted == 20
        # Not one Loan in the session. The list form loaded twenty, one per
        # row, to take their length, and that is the whole finding.
        assert loans_held == []
        # **One statement over `loans`**, which is the claim, rather than one
        # statement in the window, which is what this asserted until library
        # mode gave `sees_every_loan` a setting to read. The narrower form is
        # the honest one: a second SELECT over `loans` is the defect, and a row
        # read from `settings` is not, so a bare total would have had to be
        # bumped again by whatever reads a setting next.
        over_loans = [line for line in statements if " loans" in line.lower()]
        assert len(over_loans) == 1, statements
        # The ceiling is kept beside it, so a second settings read cannot
        # arrive unnoticed either: the count is the loan query plus the
        # `library_mode` row `sees_every_loan` asks for.
        assert len(statements) == 2, statements
