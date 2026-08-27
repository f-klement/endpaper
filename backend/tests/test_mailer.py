"""Tests for backend/mailer.py.

Nothing here opens a socket. `smtplib.SMTP` and `smtplib.SMTP_SSL` are replaced
with a recorder, so what is pinned is what the transport is **handed**: which
class, in which order, with which context, and what it does when a server says
no. Testing through a real SMTP server would test the server.
"""

import smtplib
import ssl

import pytest

import config
import mailer
import settings_store
from enums import SettingKey


@pytest.fixture
def configured(db):
    """A mail server that `checked_config` accepts."""
    settings_store.set_value(db, SettingKey.MAIL_SERVER, "smtp.example.org")
    settings_store.set_value(db, SettingKey.MAIL_PORT, "587")
    settings_store.set_value(db, SettingKey.MAIL_USE_TLS, "true")
    settings_store.set_value(db, SettingKey.MAIL_USE_SSL, "false")
    settings_store.set_value(db, SettingKey.MAIL_DEFAULT_SENDER, "library@example.org")
    settings_store.set_value(db, SettingKey.OVERDUE_MAIL_TO, "house@example.org")
    return db


class FakeSMTP:
    """Records the conversation. One instance per connection, kept on the class."""

    made: list[FakeSMTP] = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.context = context
        self.starttls_context = None
        self.login_with = None
        self.messages = []
        self.calls: list[str] = []
        self.starttls_supported = True
        self.refuses: dict[str, tuple[int, bytes]] = {}
        FakeSMTP.made.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        return False

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self, context=None):
        self.calls.append("starttls")
        if not self.starttls_supported:
            raise smtplib.SMTPNotSupportedError("no STARTTLS here")
        self.starttls_context = context

    def login(self, username, password):
        self.calls.append("login")
        self.login_with = (username, password)

    def send_message(self, message):
        self.calls.append("send_message")
        self.messages.append(message)
        return self.refuses


@pytest.fixture
def smtp(monkeypatch):
    """Both classes replaced, so a test cannot accidentally reach the network."""
    FakeSMTP.made = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


class TestCheckedConfig:
    def test_accepts_a_complete_configuration(self, configured):
        config_out = mailer.checked_config(configured)
        assert config_out.host == "smtp.example.org"
        assert config_out.port == 587
        assert config_out.recipients == ("house@example.org",)

    def test_refuses_no_server(self, db):
        with pytest.raises(mailer.MailRefused):
            mailer.checked_config(db)

    def test_refuses_a_port_that_is_not_a_number(self, configured):
        settings_store.set_value(configured, SettingKey.MAIL_PORT, "smtp")
        with pytest.raises(mailer.MailRefused):
            mailer.checked_config(configured)

    @pytest.mark.parametrize("port", ["0", "65536", "-1"])
    def test_refuses_a_port_outside_the_range(self, configured, port):
        settings_store.set_value(configured, SettingKey.MAIL_PORT, port)
        with pytest.raises(mailer.MailRefused):
            mailer.checked_config(configured)

    def test_refuses_both_tls_and_ssl(self, configured):
        """Two protocols on one socket. Guessing which was meant is how a
        deployment believes it has TLS on a port that negotiated none."""
        settings_store.set_value(configured, SettingKey.MAIL_USE_SSL, "true")
        with pytest.raises(mailer.MailRefused):
            mailer.checked_config(configured)

    def test_refuses_a_password_that_would_cross_the_wire_in_the_clear(self, configured):
        settings_store.set_value(configured, SettingKey.MAIL_USE_TLS, "false")
        settings_store.set_value(configured, SettingKey.MAIL_PASSWORD, "hunter2")
        with pytest.raises(mailer.MailRefused):
            mailer.checked_config(configured)

    def test_allows_no_password_without_encryption(self, configured):
        """An unauthenticated relay on a LAN is a real deployment. Only the
        credential is what must not travel in the clear."""
        settings_store.set_value(configured, SettingKey.MAIL_USE_TLS, "false")
        mailer.checked_config(configured)

    def test_refuses_no_recipient(self, configured):
        settings_store.set_value(configured, SettingKey.OVERDUE_MAIL_TO, "")
        with pytest.raises(mailer.MailRefused):
            mailer.checked_config(configured)

    def test_refuses_more_recipients_than_the_cap(self, configured):
        addresses = ",".join(f"a{index}@example.org" for index in range(11))
        settings_store.set_value(configured, SettingKey.OVERDUE_MAIL_TO, addresses)
        with pytest.raises(mailer.MailRefused):
            mailer.checked_config(configured)

    def test_takes_several_recipients_under_the_cap(self, configured):
        settings_store.set_value(
            configured, SettingKey.OVERDUE_MAIL_TO, "a@example.org, b@example.org"
        )
        assert mailer.checked_config(configured).recipients == (
            "a@example.org",
            "b@example.org",
        )

    @pytest.mark.parametrize(
        "address",
        [
            "not-an-address",
            "someone@localhost",
            "a b@example.org",
            "a@example.org\nBcc: attacker@evil.test",
            "<a@example.org>",
        ],
    )
    def test_refuses_a_recipient_that_is_not_an_address(self, configured, address):
        """The newline case is the one that matters: `To` is a header, and a
        newline in a header value adds a header."""
        settings_store.set_value(configured, SettingKey.OVERDUE_MAIL_TO, address)
        with pytest.raises(mailer.MailRefused):
            mailer.checked_config(configured)

    def test_refuses_a_sender_carrying_a_newline(self, configured):
        settings_store.set_value(
            configured,
            SettingKey.MAIL_DEFAULT_SENDER,
            "library@example.org\nBcc: attacker@evil.test",
        )
        with pytest.raises(mailer.MailRefused):
            mailer.checked_config(configured)

    def test_the_environment_wins_over_the_stored_server(self, configured, monkeypatch):
        monkeypatch.setenv("MAIL_SERVER", "smtp.deployment.test")
        assert mailer.checked_config(configured).host == "smtp.deployment.test"

    def test_the_environment_can_switch_tls_off(self, configured, monkeypatch):
        """A `bool` return from the environment could not tell "false" from
        "nobody set it", which is why `env_override` hands back a string."""
        monkeypatch.setenv("MAIL_USE_TLS", "false")
        assert mailer.checked_config(configured).use_tls is False

    def test_no_message_names_the_password(self, configured):
        settings_store.set_value(configured, SettingKey.MAIL_USE_TLS, "false")
        settings_store.set_value(configured, SettingKey.MAIL_PASSWORD, "hunter2")
        with pytest.raises(mailer.MailRefused) as raised:
            mailer.checked_config(configured)
        assert "hunter2" not in str(raised.value)


class TestTheConfigDoesNotPrintItsPassword:
    def test_repr_omits_it(self, configured):
        """A frozen dataclass prints every field, so one `logger.exception` or
        one failing assertion would put the mail password in a log."""
        settings_store.set_value(configured, SettingKey.MAIL_PASSWORD, "hunter2")
        settings_store.set_value(configured, SettingKey.MAIL_USERNAME, "library")
        rendered = repr(mailer.checked_config(configured))
        assert "hunter2" not in rendered
        assert "library" in rendered


class TestSend:
    def test_starttls_before_anything_is_sent(self, configured, smtp):
        mailer.send(mailer.checked_config(configured), "subject", "body")
        conversation = smtp.made[0].calls
        assert conversation.index("starttls") < conversation.index("send_message")

    def test_implicit_tls_uses_the_ssl_class_and_never_starttls(self, configured, smtp):
        settings_store.set_value(configured, SettingKey.MAIL_USE_TLS, "false")
        settings_store.set_value(configured, SettingKey.MAIL_USE_SSL, "true")
        mailer.send(mailer.checked_config(configured), "subject", "body")
        assert "starttls" not in smtp.made[0].calls
        assert smtp.made[0].context is not None

    def test_verification_cannot_be_switched_off(self, configured, smtp):
        """There is no setting for it, and this is what that buys: the context
        checks the hostname and requires a certificate, on every send."""
        mailer.send(mailer.checked_config(configured), "subject", "body")
        context = smtp.made[0].starttls_context
        assert context.check_hostname is True
        assert context.verify_mode is ssl.CERT_REQUIRED

    def test_no_setting_can_reach_the_tls_context(self):
        """The rule above, stated as a rule: nothing configurable names TLS
        verification, so there is no value an admin or a restore could write."""
        assert not [
            key
            for key in SettingKey
            if any(word in key.value for word in ("verify", "insecure", "cert"))
        ]

    def test_a_server_without_starttls_fails_rather_than_continuing_in_the_clear(
        self, configured, smtp, monkeypatch
    ):
        original = FakeSMTP.__init__

        def refuse_starttls(self, *args, **kwargs):
            original(self, *args, **kwargs)
            self.starttls_supported = False

        monkeypatch.setattr(FakeSMTP, "__init__", refuse_starttls)
        with pytest.raises(smtplib.SMTPNotSupportedError):
            mailer.send(mailer.checked_config(configured), "subject", "body")
        assert "send_message" not in smtp.made[0].calls

    def test_it_logs_in_only_when_a_username_is_set(self, configured, smtp):
        mailer.send(mailer.checked_config(configured), "subject", "body")
        assert "login" not in smtp.made[0].calls

    def test_it_logs_in_when_one_is(self, configured, smtp):
        settings_store.set_value(configured, SettingKey.MAIL_USERNAME, "library")
        settings_store.set_value(configured, SettingKey.MAIL_PASSWORD, "hunter2")
        mailer.send(mailer.checked_config(configured), "subject", "body")
        assert smtp.made[0].login_with == ("library", "hunter2")

    def test_a_partly_accepted_envelope_is_a_failure(self, configured, smtp, monkeypatch):
        """Two of three addresses is not delivery. Treating it as one is what
        would let `run_digest` stamp a reminder somebody never got."""
        original = FakeSMTP.__init__

        def refuse_one(self, *args, **kwargs):
            original(self, *args, **kwargs)
            self.refuses = {"b@example.org": (550, b"no such user")}

        monkeypatch.setattr(FakeSMTP, "__init__", refuse_one)
        with pytest.raises(smtplib.SMTPRecipientsRefused):
            mailer.send(mailer.checked_config(configured), "subject", "body")

    def test_the_subject_carries_no_title(self, configured, smtp):
        """A subject is a header, is stored by every hop, and shows on a locked
        phone. The books are in the body, where the privacy rule already ran."""
        mailer.send(mailer.checked_config(configured), "3 overdue books", "Dune: Kim")
        message = smtp.made[0].messages[0]
        assert message["Subject"] == "3 overdue books"
        assert "Dune" not in message["Subject"]

    def test_the_body_survives_a_title_outside_ascii(self, configured, smtp):
        mailer.send(mailer.checked_config(configured), "subject", "Schöne Grüße 日本")
        message = smtp.made[0].messages[0]
        assert "Schöne Grüße 日本" in message.get_content()

    def test_it_carries_a_date_and_a_message_id(self, configured, smtp):
        """Without them a household mail server may score the reminder as spam,
        and a reminder in a spam folder is a reminder that did not happen."""
        mailer.send(mailer.checked_config(configured), "subject", "body")
        message = smtp.made[0].messages[0]
        assert message["Date"]
        assert message["Message-ID"]

    def test_every_recipient_is_on_the_envelope(self, configured, smtp):
        settings_store.set_value(
            configured, SettingKey.OVERDUE_MAIL_TO, "a@example.org,b@example.org"
        )
        mailer.send(mailer.checked_config(configured), "subject", "body")
        assert smtp.made[0].messages[0]["To"] == "a@example.org, b@example.org"


class TestTheEnvironmentTable:
    def test_mail_debug_is_not_honoured(self, monkeypatch):
        """The eighth standard `MAIL_*` name is deliberately absent: smtplib's
        debug output writes the AUTH exchange to stderr, so honouring it would
        be a supported way to print the mail password into the container log."""
        monkeypatch.setenv("MAIL_DEBUG", "1")
        assert "MAIL_DEBUG" not in config._ENV_OVERRIDES.values()

    def test_the_seven_mail_settings_all_read_the_environment(self):
        assert all(
            config.env_variable_name(key) for key in settings_store.MAIL_KEYS
        )
