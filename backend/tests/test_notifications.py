"""Tests for backend/notifications.py.

The outbound POST is intercepted with respx, so nothing here reaches a real
webhook. What is worth pinning is the three rules that are silent when they
break: private books never leave, a failed delivery retries, and the log
carries the host rather than the URL.
"""

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

import httpx
import pytest
import respx

import mailer
import notifications
import settings_store
from enums import OverdueNotifyReason, OverdueSender, SettingKey
from models import Book, Loan, User

HOOK = "https://hooks.example.org/t/abcdef"


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
        self, configured, telegram_on, mail_on, lend, sent_mail
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
