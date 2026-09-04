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

import json
import secrets
from typing import Any, Final

from sqlalchemy.orm import Session

import config
import sources
from enums import CatalogueSource, Locale, SettingKey
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
    # The in app notice, and it is the one sender that is **on** by default.
    # The other three start silent because they send catalogue content
    # somewhere outside this app, and that should be a choice somebody makes.
    # This one sends nothing anywhere: it shows a member their own overdue
    # loans, scoped exactly as every other page they can already open. A
    # household that has configured nothing being told nothing is the whole
    # complaint this channel answers, and an off switch would reproduce it.
    SettingKey.OVERDUE_IN_APP_ENABLED: "true",
    # Library mode and the public catalogue, both off. The second is the only
    # setting in this table that makes catalogue rows readable **without a
    # session at all**, so its default is the one that matters most here: a
    # household that reads no setting publishes nothing.
    SettingKey.LIBRARY_MODE: "false",
    SettingKey.PUBLIC_CATALOGUE_ENABLED: "false",
    # Off, so a published catalogue is `noindex` until somebody says otherwise.
    SettingKey.PUBLIC_CATALOGUE_INDEXING_ENABLED: "false",
    # An empty JSON object: no sender has run yet. Not a preference, so it has
    # no field in `SettingsUpdate` and never reaches `_read_settings`.
    SettingKey.SENDER_HEALTH: "{}",
    # The provider list. An empty object rather than the nine sources spelled
    # out, because `sources.parse` already answers "absent means the defaults"
    # and writing them twice is two places for the default order to drift.
    SettingKey.CATALOGUE_SOURCES: "{}",
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


def get_json(db: Session, key: SettingKey) -> dict[str, Any]:
    """A stored JSON object, falling back to `{}` rather than raising.

    Same degrade rule as `get_int` and `get_locale`, and it matters more here:
    the one caller reads this on the hourly ticker, so a row a restore or a
    hand edit left as `null`, a list, or half a document would otherwise raise
    inside the background task and stop it for the life of the container.

    Objects only. A list parses as valid JSON and would then be indexed by a
    string somewhere downstream, which is a `TypeError` at a distance from the
    row that caused it.
    """
    try:
        parsed = json.loads(get_raw(db, key))
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def set_json(db: Session, key: SettingKey, value: dict[str, Any]) -> None:
    """Write a JSON object. `sort_keys` so an unchanged record writes an
    unchanged string, which is what makes a diff of the settings table
    readable and a backup comparison meaningful."""
    set_value(db, key, json.dumps(value, sort_keys=True))


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


def source_credentials(db: Session) -> frozenset[CatalogueSource]:
    """The sources a credential is actually in force for.

    **A different question from `ready_sources`, and the difference is a real
    screen.** A library that has a Google Books key but has switched the Google
    Books card off has the credential and is not ready. Reporting only the
    conjunction told it to add a key it already had, which is exactly the
    sentence this feature exists to stop somebody hunting for.
    """
    held = set(sources.DEFAULT_ORDER) - sources.NEEDS_A_KEY
    if google_books_api_key(db):
        held.add(CatalogueSource.GOOGLE_BOOKS)
    return frozenset(held)


def ready_sources(db: Session) -> frozenset[CatalogueSource]:
    """The sources whose prerequisites this deployment actually meets.

    Everything free and keyless is always ready. Google Books is ready only when
    its own section is switched on **and** a key is in force, from the
    environment or the table. Without both it cannot answer, and asking it
    anyway is what sent an ISBN to a third party with the feature switched off.
    """
    ready = set(sources.DEFAULT_ORDER) - sources.NEEDS_A_KEY
    if get_bool(db, SettingKey.GOOGLE_BOOKS_ENABLED) and google_books_api_key(db):
        ready.add(CatalogueSource.GOOGLE_BOOKS)
    return frozenset(ready)


def stored_catalogue_sources(db: Session) -> sources.Plan:
    """The provider list **as stored**, which is what the settings screen shows.

    The pair with `catalogue_sources` below is exactly `get_raw` and `in_force`,
    and for the same reason: a screen that hid a source because no key is
    configured would be a screen an admin cannot use, since they would switch it
    on and watch it come back off.

    Degrades rather than raising, like `get_int` and `get_locale`, and the reason
    is sharper here. The caller is on the path that adds a book, so a row a
    restore wrote would break scanning an ISBN rather than one screen.
    `sources.parse` answers with a full roster whatever it is given.
    """
    return sources.parse(get_json(db, SettingKey.CATALOGUE_SOURCES))


def catalogue_sources(db: Session) -> sources.Plan:
    """Which catalogues this library **actually asks**, and in what order.

    **Every caller that reaches outward goes through here rather than
    `stored_catalogue_sources`**, which is the same rule `in_force` states for
    the settable values: this answers "what will the next lookup ask", and the
    other answers "what is in the table".

    **Resolved here and passed down**, never read from inside `metadata.py`.
    That module makes every outbound catalogue request and touches no database
    at all, and the argument that keeps it that way is the one the Google Books
    key already uses: the router resolves the setting and hands it over.

    **One row read and one `json.loads` per request that reaches a catalogue**,
    and that is accepted rather than cached. It is the same cost
    `google_books_api_key` already pays beside it on the same call sites, a
    populated row holds nine sources, and the alternative is a process local
    cache that has to be invalidated on write: a second source of truth for a
    value whose whole point is that turning a source off takes effect
    immediately. If this ever shows up in a measurement, the honest fix is to
    resolve it once per request rather than to remember it between them.
    """
    return sources.in_force(stored_catalogue_sources(db), ready_sources(db))


def library_mode(db: Session) -> bool:
    """Whether the catalogue is presented to a **cataloguer** rather than a household.

    Call number and Classification in; ownership, lending willingness and
    reading status out. It publishes nothing, which is why it is a separate
    switch from the one below: an institution wanting the cataloguer's columns
    should not have to put its catalogue on the internet to get them.

    Which columns the table draws is a browser-local choice, remembered
    separately for each mode, so turning this on and off does not rearrange a
    household's catalogue. The sets and the reasoning are
    `frontend/src/lib/libraryColumns.ts`.

    **This docstring used to promise a third column, "record status", and there
    was never a definition of one anywhere.** The phrase reached three files
    verbatim from a single parenthetical in the archived plan. Two derivations
    were built and both were refused: completeness, because a column invented so
    that a promise in prose comes true looks like data; and anything reading
    `is_private`, because `visible_to` keeps the reader's **own** private Books
    in the listing, so such a column would read true on exactly the rows that
    must not leave the house, in a mode one switch away from a public catalogue.
    What a cataloguer actually wants there is the record's **source**, which is
    MARC `040` and is provenance rather than status. Nothing stores it, `marc.py`
    writes no `040`, and the lookup discards which source answered. That is a
    column with a migration behind it and it has its own ticket. Do not
    reintroduce a derived stand-in for it here.
    """
    return get_bool(db, SettingKey.LIBRARY_MODE)


def public_catalogue_is_published(db: Session) -> bool:
    """Whether a reader with no session may search and read item records.

    **Both rows, and the conjunction is enforced here rather than in the UI.**
    A publish switch left on while library mode is off has to be treated as
    off, or flipping library mode back off would leave a catalogue public with
    nothing on screen saying so. Disabling the control in the browser is not
    that guarantee: it is advice to one client.

    This is the single answer to "is anything served", and the public router is
    the only caller. Which **rows** a public reader may see is a different
    question and belongs to `Shelf.seen_by_the_public`; which **columns** is a
    third and belongs to `schemas/public.py`. Nothing here relaxes either: a
    Private Book stays private in every mode, and that rule is not this
    switch's to change.
    """
    return library_mode(db) and get_bool(db, SettingKey.PUBLIC_CATALOGUE_ENABLED)


def public_catalogue_may_be_indexed(db: Session) -> bool:
    """Whether a search engine is invited to crawl the published catalogue.

    Off by default and separately from publishing, because they are different
    decisions: a reading room's catalogue can be public without wanting to be
    the first result for every patron's name in it. False is what makes the
    public routes send `X-Robots-Tag: noindex`.

    Reads the publish state too, so an indexing row left on while nothing is
    published cannot invite a crawler to a catalogue that answers 404. The
    conjunction is the same shape as the one above and for the same reason.
    """
    return public_catalogue_is_published(db) and get_bool(
        db, SettingKey.PUBLIC_CATALOGUE_INDEXING_ENABLED
    )


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
