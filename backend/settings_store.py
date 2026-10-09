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
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy.orm import Session

import config
import credentials
import sources
import targets
from enums import CatalogueSource, Locale, SettingKey
from models import Setting

#: **`metadata` is imported inside the two functions that need it at run time,
#: and here for the annotation alone.** A module level import is a cycle, and it
#: is not the one the design round expected: the chain measured on 2026-09-17 is
#: `mailer` -> this module -> `metadata` -> `catalogue` -> `schemas.book` ->
#: `schemas` -> `schemas.user` -> `mailer`, which reaches `mailer.MAX_ADDRESS`
#: before `mailer` has defined it and fails at collection with an
#: `AttributeError`. The annotation costs nothing because PEP 649 never evaluates
#: it, which is the same arrangement `schemas/book.py` already relies on.
#:
#: **What goes red if this block is deleted is `mypy`, not the suite.** Measured
#: 2026-09-17 by neutralising it: collection succeeds and the targeted files
#: pass, while `mypy .` reports `Name "metadata" is not defined`. The rung is
#: tested rather than self enforcing, and the two function level imports below
#: are what the run time depends on.
if TYPE_CHECKING:
    import metadata

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
    # The provider list. An empty object rather than the eleven sources spelled
    # out, because `sources.parse` already answers "absent means the defaults"
    # and writing them twice is two places for the default order to drift.
    SettingKey.CATALOGUE_SOURCES: "{}",
    # Off, so a household that reads no setting asks nobody to prove anything.
    # On, it means accounts here are held by people outside the household, and
    # a new local account cannot sign in until its address is verified or an
    # admin says otherwise.
    SettingKey.ACCOUNTS_OPEN_TO_OUTSIDERS: "false",
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


#: The sources whose credential is a **settings row** rather than a sealed login.
#:
#: **One member, named here rather than spelled inline**, and the distinction it
#: draws is the one `credentials.py` opens with: Google Books' credential is an
#: API key in a query string, this deployment's own, held in `settings`. Every
#: other source that needs one needs a login at somebody else's server, held
#: sealed in `catalogue_credentials`. Two kinds of secret, and this is where the
#: routing between them lives.
#:
#: **A set is not the right shape and this is not the fix.** Which store a
#: source's secret uses is a property of the source, so it belongs beside
#: `Capability.NEEDS_A_CREDENTIAL` as a second capability, read through
#: `Target.can` like every other. That is an enum member, a column on
#: `models.CatalogueTarget`, a value on every seeded row, a line in the seeder
#: and a migration, which is more than this ticket may take for a rule with one
#: member. #210 carries this paragraph. Until then the
#: exception is named and in one place, which is what stops it being a
#: condition somebody has to notice inside a comprehension.
_SECRET_IS_A_SETTINGS_ROW: Final[frozenset[CatalogueSource]] = frozenset(
    {CatalogueSource.GOOGLE_BOOKS}
)


def _sources_with_a_credential(db: Session) -> set[CatalogueSource]:
    """Which credential-needing sources hold a readable login, from any level.

    **One source today, and that is a fact about the roster rather than about
    this function.** It was empty while `sources.NEEDS_A_KEY` was Google Books
    alone, whose secret is a settings row; the Biblioteca Nacional Argentina is
    the second member and the first whose secret is not one, so the loop runs
    once and the key is resolved on every call that reaches here. It was written
    for the set rather than for the member, which is why that cost the roster
    nothing to arrive at.
    `tests/test_settings_store.py` exercises it against a roster with a second
    such source in it.

    **Not "holds a sealed row", which is what this used to say.** `is_held` asks
    the whole ladder, so a source whose login this build ships answers true with
    nothing in `catalogue_credentials` at all. Reading the table here instead
    would report a stock install as unable to ask the one source it can.

    **Readable, not merely stored.** A credential written under a rotated key
    would otherwise report the source as ready and leave a member's search to
    discover otherwise.

    The key is resolved once for the whole loop rather than per source: see
    `credentials.KeyState`.
    """
    sealed = sources.NEEDS_A_KEY - _SECRET_IS_A_SETTINGS_ROW
    if not sealed:
        return set()
    state = credentials.key_state()
    return {
        source
        for source in sealed
        if credentials.is_held(
            db, source.value, targets.SEEDED[source].base_url, state
        )
    }


def source_credentials(db: Session) -> frozenset[CatalogueSource]:
    """The sources a credential is actually in force for.

    **A different question from `ready_sources`, and the difference is a real
    screen.** A library that has a Google Books key but has switched the Google
    Books card off has the credential and is not ready. Reporting only the
    conjunction told it to add a key it already had, which is exactly the
    sentence this feature exists to stop somebody hunting for.

    **In force, whoever supplied it**, which since 2026-09-07 includes a login
    this build ships because its catalogue publishes one. `credentials.is_held`
    is the one function that answers that, so this set does not have to know how
    many levels there are.
    """
    held = set(sources.DEFAULT_ORDER) - sources.NEEDS_A_KEY
    if google_books_api_key(db):
        held.add(CatalogueSource.GOOGLE_BOOKS)
    return frozenset(held | _sources_with_a_credential(db))


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
    return frozenset(ready | _sources_with_a_credential(db))


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
    populated row holds eleven sources, and the alternative is a process local
    cache that has to be invalidated on write: a second source of truth for a
    value whose whole point is that turning a source off takes effect
    immediately. If this ever shows up in a measurement, the honest fix is to
    resolve it once per request rather than to remember it between them.
    """
    return sources.in_force(stored_catalogue_sources(db), ready_sources(db))


def _catalogue_logins(db: Session) -> dict[CatalogueSource, credentials.Credential]:
    """The login each catalogue's request will carry, resolved before it is made.

    **Resolved here rather than in `metadata`, and that is the same rule the
    Google Books key follows.** `metadata` builds every outbound catalogue
    request and reaches no database; opening a sealed row there would put the
    ORM behind every request to every catalogue. So this answers "what will the
    next request send", which is `credentials.for_request`'s own question, and
    `library_access` below hands the answer over as an argument.

    **Only the targets whose door carries one**, which is
    `metadata.carries_a_credential` and is asked rather than restated here: the
    rule and this loop must not be able to disagree about which rows to resolve,
    because a row skipped here is a request that goes out unauthenticated with
    nothing saying so.

    **The key is resolved once for the whole loop, never per source**, which is
    the rule `_sources_with_a_credential` above states over the same shape of
    loop. Resolving it reads every entry in `credentials.KEY_SOURCES`
    and runs a BIP-39 decode per phrase held, so it is a keychain round trip per
    source per lookup, on the path that adds a book, which is a member request
    rather than an admin visit. The size it was costing is on the issue.

    **The doors are collected before the key is touched, so a roster with none
    resolves nothing.** That was today's roster until the Biblioteca Nacional
    Argentina joined it, and the property is worth keeping stated because what
    it bounds has not changed: the cost is **one** resolution per request now
    that there is a door, and it stays one however many doors the roster grows,
    where the defect this replaced was one per source. An install that has
    stored no credential pays that one and **opens no envelope**, and so does
    one whose credentials are all pinned by the environment: neither a pinned
    credential nor a login this build ships reaches the store. What comes back
    is no longer empty, since `sources.SHIPS_A_CREDENTIAL` is not, and the two
    are worth keeping apart here because what this paragraph bounds is the
    resolution rather than the mapping.
    `tests/test_settings_store.py::TestTheKeyIsResolvedOncePerRequest` pins both
    ends.

    **It is not the only resolution on a lookup.** `ready_sources` above
    resolves the key as well, to answer whether a credentialled source can be
    asked at all, so a request that reaches a catalogue pays two. Both are an
    environment read, a file read and a BIP-39 decode with no key derivation
    function behind it; it is written down here rather than measured away
    because the thing to watch is the shape, one per request, not the constant.

    Written for the set rather than for its members because the next source to
    declare that capability is the reason this plumbing exists.
    """
    import metadata  # noqa: PLC0415  the cycle above

    doors = [
        targets.SEEDED[source]
        for source in sorted(sources.NEEDS_A_KEY)
        if metadata.carries_a_credential(targets.SEEDED[source])
    ]
    if not doors:
        return {}
    state = credentials.key_state()
    resolved: dict[CatalogueSource, credentials.Credential] = {}
    for target in doors:
        login = credentials.for_request(
            db, target.source.value, target.base_url, state
        )
        if login is not None:
            resolved[target.source] = login
    return resolved


def library_access(db: Session) -> metadata.Access:
    """Everything one request may ask of the catalogues, resolved once.

    **One question, one mechanism.** Every one of the six handlers that reaches a
    catalogue used to assemble these three by hand, and four of them guarded the
    key with `GOOGLE_BOOKS_ENABLED` as well. That switch is already a condition of
    `ready_sources` above, so the plan had dropped Google before the second test
    ran: two mechanisms answering one question, with a paragraph per site saying
    which of them covered it. The plan is the gate, here and at every door.

    **The key is resolved whatever the provider list says**, which is what the
    two handlers that never had the conjunction already did. It travels no
    further than a source in the plan: `metadata._lookup_one` hands it to a
    bespoke adapter and `_search_one` to a metered one, and neither is
    constructed for a source the plan left out.

    **Not a FastAPI dependency.** `solve_dependencies` runs them in declaration
    order and the first `HTTPException` propagates, so one declared before
    `CurrentUser` would answer an unauthenticated caller with this route's 409
    instead of a 401. It is resolved in the handler body, below the limiter.

    What it costs is a handful of settings row reads and, where the roster holds
    a door that carries a login, one keychain round trip. The second is the one
    that can grow with the roster and the one that is bounded, at
    `_catalogue_logins` above; the first is not itemised here because a number
    written down beside a function stops being re-derived. The instruments are
    `tests/routers/test_books_identifier_backfill.py::TestWhatABatchCostsTheDatabase`
    and `tests/test_settings_store.py::TestTheKeyIsResolvedOncePerRequest`.
    """
    import metadata  # noqa: PLC0415  the cycle above

    return metadata.Access(
        plan=catalogue_sources(db),
        api_key=google_books_api_key(db),
        logins=_catalogue_logins(db),
    )


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


def accounts_are_open_to_outsiders(db: Session) -> bool:
    """Whether accounts here belong to people outside the household.

    The one switch that decides whether a new local account has to prove its
    address, and it means nothing else. Every candidate for reusing an existing
    signal was refused in turn on issue #104: the auth mode is about where
    credentials are checked, library mode is about cataloguing, the public
    catalogue switch is about readers rather than accounts, and gating on
    whether registration is open would admit every account that registered while
    it was open and never verified, the moment an admin closed signups.

    Read at the two doors that produce or accept a session, at account creation,
    and on the two settings responses that publish it, and nowhere else. It is
    deliberately not a second condition on any book query: an account it refuses
    holds no session at all, which is the property that makes the boundary check
    enough. See `docs/decisions.md`.
    """
    return get_bool(db, SettingKey.ACCOUNTS_OPEN_TO_OUTSIDERS)


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
