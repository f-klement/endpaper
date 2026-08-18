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
}

# Settings whose value must never be sent back to a browser in full.
SECRET_KEYS: Final[frozenset[SettingKey]] = frozenset({SettingKey.GOOGLE_BOOKS_API_KEY})

_TRUE_VALUES: Final = frozenset({"true", "1", "yes", "on"})


def get_raw(db: Session, key: SettingKey) -> str:
    """The stored string, or the default if it has never been written."""
    row = db.get(Setting, key.value)
    if row is None or row.value is None:
        return DEFAULTS[key]
    return row.value


def get_bool(db: Session, key: SettingKey) -> bool:
    return get_raw(db, key).strip().lower() in _TRUE_VALUES


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


def google_books_api_key(db: Session) -> str:
    """The key actually in force: the environment's if it has one, else the stored one.

    Every caller that needs the key goes through here rather than reading the
    setting directly, so the precedence is decided once. Reading the row
    directly would use the stored key while the settings screen showed the
    environment one, which is the kind of disagreement nobody finds until a
    lookup fails for a reason the UI denies.
    """
    return config.google_books_api_key_from_env() or get_raw(
        db, SettingKey.GOOGLE_BOOKS_API_KEY
    )
