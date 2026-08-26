"""Tests for backend/notifications.py.

The outbound POST is intercepted with respx, so nothing here reaches a real
webhook. What is worth pinning is the three rules that are silent when they
break: private books never leave, a failed delivery retries, and the log
carries the host rather than the URL.
"""

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

import notifications
import settings_store
from enums import OverdueNotifyReason, SettingKey
from models import Book, Loan, User

HOOK = "https://hooks.example.org/t/abcdef"


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


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
