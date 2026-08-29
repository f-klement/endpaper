"""Sending one mail, over SMTP, with the refusals that belong to that transport.

Separate from `notifications.py` for one reason and it is not size: **SMTP is
blocking and everything else this app sends is not**. `smtplib` has no async
form, so every call here runs on a worker thread (`notifications` uses
`asyncio.to_thread`), and keeping it in its own module is what makes that
boundary a thing a reader can see rather than a thing they have to notice.

It is also outside `fetch.py` and outside that module's guard, correctly: this
speaks SMTP, not HTTP, so there is no client to build, no redirect to refuse and
no response body to cap. `backend/tests/test_fetch.py` is httpx shaped and names
"any HTTP library that is not httpx" among its blind spots; a protocol that is
not HTTP at all is not a blind spot, it is a different door.

**What this module refuses, and why a refusal rather than an attempt.** A mail
server accepts what it is given and says little, so "did it work" is not a
question the transport can answer for an operator. Every check here is therefore
about the *configuration*, made before a socket is opened:

* No host, no sender, no recipient: nothing to attempt.
* A password with neither STARTTLS nor implicit TLS: the credential would cross
  the network in the clear, and a household mail account is usually the same
  account as everything else that household owns.
* Both TLS flags at once: two different protocols on one socket. Guessing which
  was meant is how a deployment ends up believing it has TLS on a port that
  never negotiated any.
* An address carrying a newline: `From`, `To` and `Subject` are headers, and a
  newline in a header value is header injection. It would let an admin-set
  string add a `Bcc`.

**TLS verification cannot be switched off, and the way that is guaranteed is
that there is no setting for it.** `ssl.create_default_context()` checks the
chain and the hostname; nothing here takes a context from a caller.
"""

import logging
import re
import smtplib
import ssl
import unicodedata
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from sqlalchemy.orm import Session

import settings_store
from enums import SettingKey

logger = logging.getLogger("endpaper.mailer")

#: Per socket operation, which is the only kind `smtplib` has.
#:
#: **It does not bound the whole conversation**, for the same reason httpx's
#: does not bound a whole request: a server answering each command just inside
#: the limit can hold the connection indefinitely. What stops that mattering is
#: that this runs on a worker thread under `asyncio.timeout` in
#: `notifications.send_mail`, so a stuck server costs one thread until its next
#: socket read expires, and never the hourly ticker.
TIMEOUT_SECONDS = 10.0

#: How many addresses one reminder may go to.
#:
#: A cap rather than none, because `overdue_mail_to` is a text setting and a
#: restore writes it through Core: without a bound, one row turns the hourly
#: ticker into a mailing list. Ten is more than a household has and far less
#: than a sending reputation survives.
MAX_RECIPIENTS = 10

#: The longest address this app stores, RFC 5321's maximum for a path.
#:
#: Here rather than in a schema because three layers need the same number:
#: `users.email` is `String(320)`, `schemas/user.py` bounds what may be written
#: to it, and `auth_backends` bounds what a directory may assert into it. SQLite
#: does not enforce a column width, so the bound has to be applied before the
#: write, at every door.
#:
#: `schemas.settings.MAX_MAIL_ADDRESS` is the same number for the *household*
#: address, and predates this. Two constants for one fact, and folding them is a
#: one line change nobody should make while another seat is in that file.
MAX_ADDRESS = 320

#: Deliberately not RFC 5322, which admits quoted local parts, comments and
#: address literals that no household mailbox uses.
#:
#: What it has to reject is what makes this a control at all: whitespace, a
#: comma and a semicolon. Those are the characters that turn one header into
#: two, or one recipient into several. Everything it rejects beyond that is a
#: configuration mistake refused at the settings screen rather than discovered
#: as a bounce a week later.
#:
#: **Unanchored, because `looks_like_address` uses `fullmatch`.** It was
#: `^...$` under `match`, and `$` matches *before a trailing newline*: this
#: accepted `"kim@example.org\n"` while three docstrings and `docs/security.md`
#: said it was the header injection control. Nothing exploited it, because four
#: independent `.strip()` calls happened to stand in front of it, but a control
#: that only holds because of its callers is not a control. Anchors here would
#: now be redundant and would re-invite the same `$`.
_ADDRESS = re.compile(r"[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+")


def looks_like_address(value: str) -> bool:
    """Is this something this app will put in an envelope?

    The one public name for the rule, so `users.email` is checked the same way
    as `overdue_mail_to` and `mail_default_sender` rather than by a second
    regex that drifts from it.

    **Two checks, and each is a family rather than a list of characters.**

    `fullmatch` rather than `match`, so the whole string has to be the address.
    That is what closes the trailing newline, which is the injection character
    this was written to reject and the one spelling it accepted.

    A Unicode general category beginning `C` is refused before the pattern is
    tried: `Cc` control characters, `Cf` format characters, surrogates and
    unassigned code points. The negated class excludes whitespace and the five
    punctuation characters only, and therefore let a NUL or an ESC through;
    enumerating those two would have been the third arm of a rule with no end.
    What a header may not carry is not a list, it is "not printing text", and
    that is what a category test says.
    """
    if any(unicodedata.category(character)[0] == "C" for character in value):
        return False
    return bool(_ADDRESS.fullmatch(value))


class MailRefused(Exception):
    """This configuration is not one a mail will be attempted on."""


@dataclass(frozen=True)
class MailConfig:
    """A checked SMTP configuration. Only `checked_config` builds one.

    **`password` is `repr=False`, and that is not tidiness.** A frozen dataclass
    prints every field, so `logger.exception("... %s", config)`, an f-string in
    an assertion, or a `pytest` failure rendering the local variables would each
    put the mail password in a log. There is no call site that wants it and one
    line stops all of them.
    """

    host: str
    port: int
    username: str
    password: str = field(repr=False)
    use_ssl: bool
    use_tls: bool
    sender: str
    recipients: tuple[str, ...]


def _addresses(raw: str) -> tuple[str, ...]:
    """Split a comma separated setting into addresses, refusing anything odd."""
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if not parts:
        raise MailRefused("No recipient address is configured.")
    if len(parts) > MAX_RECIPIENTS:
        raise MailRefused(f"At most {MAX_RECIPIENTS} recipients, got {len(parts)}.")
    for part in parts:
        if not looks_like_address(part):
            raise MailRefused("A recipient address is not an address.")
    return tuple(parts)


def checked_config(db: Session) -> MailConfig:
    """The mail configuration in force, or a refusal naming what is wrong.

    Read through `settings_store.in_force`, so a deployment that supplies
    `MAIL_SERVER` in the environment is the one that is checked and the one that
    is used. Reading the stored row here while the environment supplied another
    is exactly the disagreement `in_force` exists to prevent.

    The message is shown to an admin and written to a log, so it names the
    *field* and never the value: `mail_password` is a secret and
    `mail_server` is not worth a log line either.
    """
    host = settings_store.in_force(db, SettingKey.MAIL_SERVER).strip()
    if not host:
        raise MailRefused("No mail server is configured.")
    if any(character.isspace() for character in host):
        raise MailRefused("The mail server is not a hostname.")

    try:
        port = int(settings_store.in_force(db, SettingKey.MAIL_PORT).strip())
    except ValueError:
        raise MailRefused("The mail port is not a number.") from None
    if not 1 <= port <= 65535:
        raise MailRefused("The mail port is outside 1 to 65535.")

    use_ssl = settings_store.bool_in_force(db, SettingKey.MAIL_USE_SSL)
    use_tls = settings_store.bool_in_force(db, SettingKey.MAIL_USE_TLS)
    if use_ssl and use_tls:
        raise MailRefused(
            "Choose implicit TLS or STARTTLS, not both. They are two protocols."
        )

    username = settings_store.in_force(db, SettingKey.MAIL_USERNAME).strip()
    password = settings_store.in_force(db, SettingKey.MAIL_PASSWORD)
    if password and not (use_ssl or use_tls):
        raise MailRefused(
            "A mail password with neither STARTTLS nor TLS would cross the "
            "network in the clear. Switch one of them on."
        )

    sender = settings_store.in_force(db, SettingKey.MAIL_DEFAULT_SENDER).strip()
    if not sender:
        raise MailRefused("No sender address is configured.")
    if not looks_like_address(sender):
        raise MailRefused("The sender address is not an address.")

    recipients = _addresses(settings_store.in_force(db, SettingKey.OVERDUE_MAIL_TO))

    return MailConfig(
        host=host,
        port=port,
        username=username,
        password=password,
        use_ssl=use_ssl,
        use_tls=use_tls,
        sender=sender,
        recipients=recipients,
    )


def _build(config: MailConfig, subject: str, body: str) -> EmailMessage:
    """One plain text message.

    `set_content` with a `str` picks the transfer encoding itself, so a title
    with an umlaut or a CJK character arrives intact rather than as mojibake.

    **The subject carries a count and never a title.** A subject line is a
    header, is stored unencrypted by every hop, and shows in a notification on a
    locked phone. The books are in the body, where the privacy rule already put
    only the ones that may go out at all.
    """
    message = EmailMessage()
    message["From"] = config.sender
    message["To"] = ", ".join(config.recipients)
    message["Subject"] = subject
    # Without these two a household mail server is entitled to score the message
    # as spam, and a reminder in a spam folder is a reminder that did not happen.
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid()
    message.set_content(body)
    return message


def send(config: MailConfig, subject: str, body: str) -> None:
    """Deliver one message, or raise.

    **Blocking. Call it on a worker thread.** See the module docstring.

    `ssl.create_default_context()` is built here and nowhere else, so there is no
    parameter, no setting and no environment variable that relaxes certificate or
    hostname checking.

    **`starttls` is not attempted optimistically.** With `use_tls` set and a
    server that does not offer it, `smtplib` raises `SMTPNotSupportedError` and
    this fails, rather than continuing in the clear on a configuration that asked
    for encryption.

    **A partly accepted envelope is a failure.** `send_message` returns the
    recipients the server refused, and treating a message that reached two of
    three addresses as delivered is what would let `run_digest` stamp
    `notified_at` on a reminder somebody never got.
    """
    message = _build(config, subject, body)
    context = ssl.create_default_context()

    if config.use_ssl:
        with smtplib.SMTP_SSL(
            config.host, config.port, timeout=TIMEOUT_SECONDS, context=context
        ) as smtp:
            _deliver(smtp, config, message)
        return

    with smtplib.SMTP(config.host, config.port, timeout=TIMEOUT_SECONDS) as smtp:
        smtp.ehlo()
        if config.use_tls:
            smtp.starttls(context=context)
            # Again after the upgrade: the server's advertised capabilities
            # before and after STARTTLS are allowed to differ, and AUTH is
            # commonly one of the ones that only appears after it.
            smtp.ehlo()
        _deliver(smtp, config, message)


def _deliver(smtp: smtplib.SMTP, config: MailConfig, message: EmailMessage) -> None:
    if config.username:
        smtp.login(config.username, config.password)
    refused = smtp.send_message(message)
    if refused:
        # The count, not the addresses: this goes to a log, and a recipient
        # list is the one part of the envelope worth keeping out of one.
        raise smtplib.SMTPRecipientsRefused(refused)
