"""Admin-editable settings that survive a restart.

The split from `config.py` is deliberate and worth keeping:

* **`config.py`** reads the environment. It holds what an *operator* decides
  when deploying the container: where the data lives, which auth mode, the
  signing key. Changing one means redeploying, which is appropriate for things
  that alter how the app is wired.
* **this module** reads the database. It holds what an *admin* changes from the
  UI: an API key, a feature toggle, the default language. Changing one takes
  effect immediately, for everyone.

A container that behaves differently depending on database contents is harder
to reason about, so the second list is kept deliberately short.
"""

import secrets
from typing import Final

from sqlalchemy.orm import Session

import config
from enums import Locale, SettingKey
from models import Setting

# Defaults for anything never written. Stored as the same strings the table
# holds, so there is one representation to reason about.
DEFAULTS: Final[dict[SettingKey, str]] = {
    SettingKey.GOOGLE_BOOKS_API_KEY: "",
    # Off by default: enrichment calls a third party, and that should be an
    # explicit choice rather than something a new install starts doing.
    SettingKey.GOOGLE_BOOKS_ENABLED: "false",
    # On by default: this is only an outbound link, so it discloses nothing
    # and costs nothing.
    SettingKey.GOODREADS_LOOKUP_ENABLED: "true",
    SettingKey.DEFAULT_LOCALE: Locale.EN.value,
    # Every issued token carries this. See `bump_token_epoch`.
    SettingKey.TOKEN_EPOCH: "0",
    # Off by default: this is the one path in the app that sends catalogue
    # content somewhere with no session behind it, so it starts silent.
    SettingKey.OVERDUE_WEBHOOK_ENABLED: "false",
    SettingKey.OVERDUE_WEBHOOK_URL: "",
    SettingKey.OVERDUE_WEBHOOK_SECRET: "",
    # A week between reminders for the same loan. Weekly is the interval a
    # borrower reads as a reminder rather than as nagging, and it is the
    # differentiator Handy Library is known for: the timing is the library's
    # to set, not the app's to assume.
    SettingKey.OVERDUE_REMINDER_DAYS: "7",
    # Mail. Off by default for the reason the webhook is: it sends catalogue
    # content outward. The port and the two transport flags default to
    # submission over STARTTLS, which is what a household mail provider offers
    # and what `checked_mail` refuses to be talked out of once a password is set.
    SettingKey.OVERDUE_MAIL_ENABLED: "false",
    SettingKey.OVERDUE_MAIL_TO: "",
    SettingKey.MAIL_SERVER: "",
    SettingKey.MAIL_PORT: "587",
    SettingKey.MAIL_USERNAME: "",
    SettingKey.MAIL_PASSWORD: "",
    SettingKey.MAIL_USE_TLS: "true",
    SettingKey.MAIL_USE_SSL: "false",
    SettingKey.MAIL_DEFAULT_SENDER: "",
    # Telegram. Off by default, same reason.
    SettingKey.OVERDUE_TELEGRAM_ENABLED: "false",
    SettingKey.TELEGRAM_BOT_TOKEN: "",
    SettingKey.TELEGRAM_CHAT_ID: "",
}

# Settings whose value must never be sent back to a browser in full.
SECRET_KEYS: Final[frozenset[SettingKey]] = frozenset(
    {
        SettingKey.GOOGLE_BOOKS_API_KEY,
        SettingKey.OVERDUE_WEBHOOK_SECRET,
        SettingKey.MAIL_PASSWORD,
        # In the **URL path** of every Telegram call, so a log line that prints
        # a request URL prints the token. See `notifications._telegram_url`.
        SettingKey.TELEGRAM_BOT_TOKEN,
    }
)

#: The seven standard mail settings, in the order the settings screen shows
#: them. One list, so `SettingsOut.mail_from_env` and any future consumer agree
#: about what "the mail settings" means.
MAIL_KEYS: Final[tuple[SettingKey, ...]] = (
    SettingKey.MAIL_SERVER,
    SettingKey.MAIL_PORT,
    SettingKey.MAIL_USERNAME,
    SettingKey.MAIL_PASSWORD,
    SettingKey.MAIL_USE_TLS,
    SettingKey.MAIL_USE_SSL,
    SettingKey.MAIL_DEFAULT_SENDER,
)

_TRUE_VALUES: Final = frozenset({"true", "1", "yes", "on"})


def get_raw(db: Session, key: SettingKey) -> str:
    """The stored string, or the default if it has never been written."""
    row = db.get(Setting, key.value)
    if row is None or row.value is None:
        return DEFAULTS[key]
    return row.value


def get_bool(db: Session, key: SettingKey) -> bool:
    return get_raw(db, key).strip().lower() in _TRUE_VALUES


def get_int(db: Session, key: SettingKey, *, minimum: int, maximum: int) -> int:
    """A whole number, clamped, falling back to the default rather than raising.

    Same reasoning as `get_locale`: a value the current release no longer finds
    sensible should degrade, not break every request that reads it. The bounds
    are the caller's because they belong to the setting, not to the parser, and
    the one caller that matters here would otherwise let a stored 0 turn a
    reminder interval into "resend on every tick".
    """
    try:
        value = int(get_raw(db, key).strip())
    except ValueError:
        value = int(DEFAULTS[key])
    return max(minimum, min(maximum, value))


def get_locale(db: Session, key: SettingKey) -> Locale:
    """A locale, falling back to the default rather than raising.

    A value that is no longer a supported language (a locale removed in a later
    release, say) should degrade to the default, not break every page load.
    """
    try:
        return Locale(get_raw(db, key).strip().lower())
    except ValueError:
        return Locale(DEFAULTS[key])


def set_value(db: Session, key: SettingKey, value: str | None) -> None:
    """Write a setting. `None` clears it back to the default."""
    row = db.get(Setting, key.value)
    if row is None:
        row = Setting(key=key.value, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()


def mask(value: str) -> str:
    """Render a secret so it can be shown without being disclosed.

    An admin needs to see *that* a key is set, and enough of it to tell one
    from another, but the browser has no reason to receive the whole thing.
    Anything short enough that a fragment would give it away is fully hidden.
    """
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return f"{'•' * 8}{value[-4:]}"


def in_force(db: Session, key: SettingKey) -> str:
    """The value actually used: the environment's if it supplied one, else the stored one.

    **Every consumer of a settable value goes through here rather than
    `get_raw`, and the two are not interchangeable.** `get_raw` answers "what is
    in the table", which is what the settings screen needs in order to show what
    an admin may edit; this answers "what will the next send use". Reading the
    row directly is how a lookup fails for a reason the settings screen denies,
    which is the defect `google_books_api_key` was written to prevent and which
    every mail and Telegram setting can now reproduce.
    """
    return config.env_override(key) or get_raw(db, key)


def bool_in_force(db: Session, key: SettingKey) -> bool:
    """`in_force`, parsed the way `get_bool` parses the stored value.

    One parser for both sources, so `MAIL_USE_TLS=off` in the environment and
    `off` in the table cannot mean different things.
    """
    return in_force(db, key).strip().lower() in _TRUE_VALUES


def is_from_env(key: SettingKey) -> bool:
    """Whether the deployment pinned this setting, so the app must not offer an edit.

    Reporting *where* a value comes from is not reporting the value, which is
    what lets this be true for a secret.
    """
    return bool(config.env_override(key))


def google_books_api_key(db: Session) -> str:
    """The key actually in force. See `in_force`; this name has its own callers."""
    return in_force(db, SettingKey.GOOGLE_BOOKS_API_KEY)


def token_epoch(db: Session) -> str:
    """The value every access token is stamped with when it is issued."""
    return get_raw(db, SettingKey.TOKEN_EPOCH)


def bump_token_epoch(db: Session) -> str:
    """Invalidate every token issued so far.

    A restore replaces the users table wholesale, which means the id a live
    token names may afterwards belong to somebody else entirely: the token for
    user 3 comes back as a different person, with that person's books and, if
    the row happens to be an admin, their powers. Nothing in the token itself
    notices, because the id is still an id and the signature is still ours.

    Bumping this on restore ends every pre-restore session instead, which is
    the honest outcome: those sessions authenticated against a user table that
    no longer exists.

    A random value rather than a counter, because the settings table is itself
    part of the backup. A counter would be restored to an older number, and a
    token stamped with that number would start verifying again.
    """
    fresh = secrets.token_hex(8)
    set_value(db, SettingKey.TOKEN_EPOCH, fresh)
    return fresh
