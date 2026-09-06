from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

import config
import covers
import credentials
import metadata
import notifications
import settings_store
import sources
from auth import require_admin
from config import ALLOWED_IMAGE_EXTENSIONS, COVERS_DIR
from dependencies import DbSession
from enums import CatalogueSource, SettingKey
from models import User
from schemas import (
    CatalogueSourceOut,
    CredentialKeyOut,
    FeatureFlagsOut,
    LoginImageOut,
    RecoveryPhraseIn,
    RecoveryPhraseOut,
    SenderHealth,
    SettingsOut,
    SettingsUpdate,
    SourceCredentialIn,
)
from uploads import read_image_upload, replace_image

#: One definition, in the module that owns what the covers directory is called.
#: It used to be spelled out here and again in `routers/covers.py`, justified by
#: a circular import that does not exist: `covers.py` imports `config`, `isbn`
#: and `uploads` and no router.
LOGIN_BG_BASE = covers.LOGIN_BG_BASE

router = APIRouter(prefix="/api/settings", tags=["settings"])

#: The reminder sender settings whose write is uniform: trim it, store it,
#: refuse it when the deployment pinned it.
#:
#: **A table rather than twelve `if payload.x is not None` blocks**, which is
#: what the four settings above this feature are. The older ones each carry a
#: rule of their own (the Google key's 409, the webhook URL's scheme note) and
#: are left as they are; these twelve carry the same rule as each other, and
#: writing it twelve times is twelve places to forget the environment check.
_SENDER_TEXT: Final[dict[str, SettingKey]] = {
    "overdue_mail_to": SettingKey.OVERDUE_MAIL_TO,
    "mail_server": SettingKey.MAIL_SERVER,
    "mail_port": SettingKey.MAIL_PORT,
    "mail_username": SettingKey.MAIL_USERNAME,
    "mail_password": SettingKey.MAIL_PASSWORD,
    "mail_default_sender": SettingKey.MAIL_DEFAULT_SENDER,
    "telegram_bot_token": SettingKey.TELEGRAM_BOT_TOKEN,
    "telegram_chat_id": SettingKey.TELEGRAM_CHAT_ID,
}

#: The three library mode switches, whose write is uniform: a boolean, stored,
#: with no environment override to refuse and no sender health to forget.
#:
#: A table for the same reason `_SENDER_BOOL` is one, and separate from it
#: because these are not senders: `notifications.sender_for` answers None for
#: all three, so routing them through `_SENDER_BOOL` would work and would file
#: them under a heading they do not belong to.
#:
#: **Nothing here refuses a combination.** `public_catalogue_enabled` may be
#: stored true while `library_mode` is false; the catalogue is still not
#: published, because `settings_store.public_catalogue_is_published` reads both
#: and the routes ask it rather than reading a row. Enforcing the nesting at
#: the write instead would make the order of two toggles in one form matter.
_LIBRARY_MODE_BOOL: Final[dict[str, SettingKey]] = {
    "library_mode": SettingKey.LIBRARY_MODE,
    "public_catalogue_enabled": SettingKey.PUBLIC_CATALOGUE_ENABLED,
    "public_catalogue_indexing_enabled": SettingKey.PUBLIC_CATALOGUE_INDEXING_ENABLED,
}

_SENDER_BOOL: Final[dict[str, SettingKey]] = {
    "overdue_mail_enabled": SettingKey.OVERDUE_MAIL_ENABLED,
    "mail_use_tls": SettingKey.MAIL_USE_TLS,
    "mail_use_ssl": SettingKey.MAIL_USE_SSL,
    "overdue_telegram_enabled": SettingKey.OVERDUE_TELEGRAM_ENABLED,
    # One field, because the channel is the app: no destination, no credential,
    # and nothing an operator can pin from the environment.
    "overdue_in_app_enabled": SettingKey.OVERDUE_IN_APP_ENABLED,
}

def _store(db: DbSession, key: SettingKey, value: str | dict[str, Any]) -> None:
    """Write one settings row, and drop the health record it invalidates.

    **Every write in `update_settings` goes through here**, which is what makes
    the second half impossible to forget. It used to be a table in this module
    keyed on the payload field and covering the four on/off switches only, so a
    household replacing an expired bot token cleared nothing: the record
    survived, `_is_broken` measures against a `failing_since` that only grows,
    and a household with nothing overdue attempts no sender, so no later run
    overwrote it either. The banner was permanent.

    `notifications.sender_for` is the single answer to "which channel does this
    row configure", and it lives with the senders rather than here. A row that
    configures nothing (the locale, the Google key, the reminder interval)
    answers `None` and this is then an ordinary write.

    **A `dict` goes to `set_json` and a `str` to `set_value`, through this same
    door rather than a second one.** The provider list is the first row here
    that holds an object, and giving it a `_store_json` sibling would have made
    "every write goes through one door" a sentence about two doors.
    `TestEverySettingsWriteClearsWhatItInvalidates` counts the writers in this
    module and expects exactly one, and it caught the bypass that produced this
    paragraph.
    """
    if isinstance(value, dict):
        settings_store.set_json(db, key, value)
    else:
        settings_store.set_value(db, key, value)
    sender = notifications.sender_for(key)
    if sender is not None:
        notifications.forget_health(db, sender)


def _refuse_if_pinned(key: SettingKey) -> None:
    """409 rather than a write nothing will read.

    Same rule as the Google Books key, and the same reason: a value the
    environment supplies wins, so storing a different one produces a settings
    screen that disagrees with what the next send actually uses. The message
    names the variable, because "the environment" alone sends an operator
    hunting through a compose file.
    """
    variable = config.env_variable_name(key) if settings_store.is_from_env(key) else ""
    if variable:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{variable} is supplied by this deployment's environment and "
                "cannot be changed here. Change it where the app is configured."
            ),
        )


def _find_login_bg() -> Path | None:
    for extension in ALLOWED_IMAGE_EXTENSIONS:
        candidate = COVERS_DIR / f"{LOGIN_BG_BASE}.{extension}"
        if candidate.exists():
            return candidate
    return None


@router.get("/login-image", response_model=LoginImageOut)
async def get_login_image() -> LoginImageOut:
    """Public: the login page renders before anyone holds a token."""
    path = _find_login_bg()
    if path is None:
        raise HTTPException(status_code=404, detail="No login background set")
    return LoginImageOut(url=f"/covers/{path.name}")


@router.post("/login-image", response_model=LoginImageOut)
async def set_login_image(
    file: Annotated[UploadFile, File()],
    current_user: Annotated[User, Depends(require_admin)],
) -> LoginImageOut:
    # Identified by content, not by the caller-supplied filename.
    data, extension = await read_image_upload(file)

    # Into place first, stale formats after: _find_login_bg picks whichever it
    # sees first, and deleting before writing meant a failure left no
    # background at all. See uploads.replace_image.
    destination = replace_image(COVERS_DIR, LOGIN_BG_BASE, extension, data)
    return LoginImageOut(url=f"/covers/{destination.name}")


# ── Runtime settings ──────────────────────────────────────────────────────────


def _credential_view(
    db: DbSession, source: CatalogueSource, state: credentials.KeyState
) -> dict[str, Any]:
    """The three credential fields on one roster row, and no secret among them.

    **Built here rather than in `sources.describe`**, which is where the other
    derived fields come from. That module owns which catalogues are asked and in
    what order, holds no database by design, and a credential is neither of
    those things. Masking is here for the same reason it is here for the mail
    password: it is presentation, and `settings_store.mask` is the one rule.
    """
    held = credentials.view(db, source.value, state)
    return {
        "has_credential": held.has_credential,
        "credential_username_preview": settings_store.mask(held.username),
        "credential_from_env": held.from_env,
        "credential_unreadable": held.unreadable,
    }


def _read_settings(db: DbSession) -> SettingsOut:
    # Resolved once for the whole roster. Per row it was one keychain round trip
    # per stored credential on a desktop; see `credentials.KeyState`.
    encryption_key = credentials.key_state()
    from_env = config.google_books_api_key_from_env()
    # The one in force, which is the environment's when it has one. Showing the
    # stored key's preview while a different key is actually being used would
    # be worse than showing nothing.
    key = from_env or settings_store.get_raw(db, SettingKey.GOOGLE_BOOKS_API_KEY)
    webhook_secret = settings_store.get_raw(db, SettingKey.OVERDUE_WEBHOOK_SECRET)
    # The one in force for both, for the reason the Google key's preview is:
    # showing a preview of a secret that is not the one being used is worse
    # than showing none at all.
    mail_password = settings_store.in_force(db, SettingKey.MAIL_PASSWORD)
    telegram_token = settings_store.in_force(db, SettingKey.TELEGRAM_BOT_TOKEN)

    return SettingsOut(
        google_books_enabled=settings_store.get_bool(db, SettingKey.GOOGLE_BOOKS_ENABLED),
        google_books_api_key_preview=settings_store.mask(key),
        has_google_books_api_key=bool(key),
        google_books_api_key_from_env=bool(from_env),
        goodreads_lookup_enabled=settings_store.get_bool(
            db, SettingKey.GOODREADS_LOOKUP_ENABLED
        ),
        default_locale=settings_store.get_locale(db, SettingKey.DEFAULT_LOCALE),
        overdue_webhook_enabled=settings_store.get_bool(
            db, SettingKey.OVERDUE_WEBHOOK_ENABLED
        ),
        # In full, unlike the secret below it. A destination an admin cannot
        # read back is a destination nobody can proofread, and spotting a wrong
        # one is what the field is for.
        overdue_webhook_url=settings_store.get_raw(db, SettingKey.OVERDUE_WEBHOOK_URL),
        overdue_webhook_secret_preview=settings_store.mask(webhook_secret),
        has_overdue_webhook_secret=bool(webhook_secret),
        overdue_reminder_days=notifications.reminder_days(db),
        # Mail. Every field reports the value **in force**, which is the
        # environment's where it supplied one, for the reason the Google key's
        # preview does: a screen showing a value that is not the one the next
        # send will use is worse than one showing nothing. `mail_from_env` names
        # which of the seven that applies to, so the UI can disable the field
        # rather than offering an edit `_refuse_if_pinned` would 409.
        overdue_mail_enabled=settings_store.get_bool(db, SettingKey.OVERDUE_MAIL_ENABLED),
        overdue_mail_to=settings_store.get_raw(db, SettingKey.OVERDUE_MAIL_TO),
        mail_server=settings_store.in_force(db, SettingKey.MAIL_SERVER),
        mail_port=settings_store.in_force(db, SettingKey.MAIL_PORT),
        mail_username=settings_store.in_force(db, SettingKey.MAIL_USERNAME),
        mail_password_preview=settings_store.mask(mail_password),
        has_mail_password=bool(mail_password),
        mail_use_tls=settings_store.bool_in_force(db, SettingKey.MAIL_USE_TLS),
        mail_use_ssl=settings_store.bool_in_force(db, SettingKey.MAIL_USE_SSL),
        mail_default_sender=settings_store.in_force(db, SettingKey.MAIL_DEFAULT_SENDER),
        mail_from_env=[
            pinned.value
            for pinned in settings_store.MAIL_KEYS
            if settings_store.is_from_env(pinned)
        ],
        overdue_telegram_enabled=settings_store.get_bool(
            db, SettingKey.OVERDUE_TELEGRAM_ENABLED
        ),
        telegram_bot_token_preview=settings_store.mask(telegram_token),
        has_telegram_bot_token=bool(telegram_token),
        telegram_bot_token_from_env=settings_store.is_from_env(
            SettingKey.TELEGRAM_BOT_TOKEN
        ),
        telegram_chat_id=settings_store.in_force(db, SettingKey.TELEGRAM_CHAT_ID),
        telegram_chat_id_from_env=settings_store.is_from_env(SettingKey.TELEGRAM_CHAT_ID),
        overdue_in_app_enabled=settings_store.get_bool(
            db, SettingKey.OVERDUE_IN_APP_ENABLED
        ),
        # The two switches as stored, so the form shows what an admin typed,
        # plus the conjunction that decides whether anything is actually
        # served. See `SettingsOut` for why the screen needs all three.
        library_mode=settings_store.get_bool(db, SettingKey.LIBRARY_MODE),
        public_catalogue_enabled=settings_store.get_bool(
            db, SettingKey.PUBLIC_CATALOGUE_ENABLED
        ),
        public_catalogue_indexing_enabled=settings_store.get_bool(
            db, SettingKey.PUBLIC_CATALOGUE_INDEXING_ENABLED
        ),
        public_catalogue_published=settings_store.public_catalogue_is_published(db),
        # **The stored list, not the one in force.** An admin has to see what
        # they set: a screen that hid Google Books because no key is configured
        # would be one they cannot use, since they would switch it on and watch
        # it come back off. `ready` beside it is what says it cannot answer yet.
        catalogue_sources=[
            CatalogueSourceOut(
                **vars(described), **_credential_view(db, described.source, encryption_key)
            )
            for described in sources.describe(
                settings_store.stored_catalogue_sources(db),
                ready=settings_store.ready_sources(db),
                credentials=settings_store.source_credentials(db),
            )
        ],
    )


@router.get("/features", response_model=FeatureFlagsOut)
def get_feature_flags(db: DbSession) -> FeatureFlagsOut:
    """What the UI needs to decide what to render.

    Public on purpose: the login page is localised, so the default language has
    to be known before anyone holds a token. Carries no secrets.
    """
    google_books_enabled = settings_store.get_bool(db, SettingKey.GOOGLE_BOOKS_ENABLED)
    # Only whether a key exists, never the key itself.
    has_key = bool(settings_store.google_books_api_key(db))

    return FeatureFlagsOut(
        google_books_enabled=google_books_enabled,
        google_books_ready=google_books_enabled and has_key,
        goodreads_lookup_enabled=settings_store.get_bool(
            db, SettingKey.GOODREADS_LOOKUP_ENABLED
        ),
        default_locale=settings_store.get_locale(db, SettingKey.DEFAULT_LOCALE),
        # The raw row here, because the two MARC routes gate on the raw row and
        # a client reading this has to get the answer they give. The field
        # below is a conjunction for the opposite reason.
        library_mode=settings_store.library_mode(db),
        # The conjunction, never the raw row: this is the flag a browser with
        # no token reads to decide whether there is a public catalogue to
        # offer, and it has to give the same answer the routes do.
        public_catalogue_published=settings_store.public_catalogue_is_published(db),
    )


@router.get("", response_model=SettingsOut)
def get_settings(
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> SettingsOut:
    return _read_settings(db)


@router.get("/sender-health", response_model=list[SenderHealth])
def get_sender_health(
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> list[SenderHealth]:
    """What each switched-on reminder channel last did.

    Declared **before** nothing, and that is worth saying: this prefix has no
    path parameter, so the route order rule has no work to do here. It is a
    separate endpoint rather than a field on `SettingsOut` because the banner
    that reads it lives on the library page, and pulling the whole admin
    settings record, four secrets' previews included, to render one line would
    be the wrong payload on the wrong screen.

    Admin only, like the settings it reports on and for the same reason: it
    names channels, their failures and the sentences those failures produced.
    An ordinary member can do nothing with any of it, since only an admin can
    reach the screen that fixes it.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    return [SenderHealth(**entry) for entry in notifications.health(db, now)]


@router.put("", response_model=SettingsOut)
def update_settings(
    payload: SettingsUpdate,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> SettingsOut:
    """Apply a partial update.

    Only fields actually present are written. That is what lets the admin form
    submit without the API key: the browser never received the real value, so
    sending the field back would blank it.
    """
    if payload.google_books_enabled is not None:
        _store(
            db,
            SettingKey.GOOGLE_BOOKS_ENABLED,
            "true" if payload.google_books_enabled else "false",
        )

    if payload.google_books_api_key is not None:
        if config.google_books_api_key_from_env():
            raise HTTPException(
                status_code=409,
                detail=(
                    "The Google Books key is supplied by this deployment's "
                    "environment and cannot be changed here. Change "
                    "GOOGLE_BOOKS_API_KEY where the app is configured."
                ),
            )
        # An empty string is a deliberate clear; None never reaches here.
        _store(
            db, SettingKey.GOOGLE_BOOKS_API_KEY, payload.google_books_api_key.strip()
        )

    if payload.goodreads_lookup_enabled is not None:
        _store(
            db,
            SettingKey.GOODREADS_LOOKUP_ENABLED,
            "true" if payload.goodreads_lookup_enabled else "false",
        )

    if payload.default_locale is not None:
        _store(db, SettingKey.DEFAULT_LOCALE, payload.default_locale.value)

    if payload.overdue_webhook_enabled is not None:
        _store(
            db,
            SettingKey.OVERDUE_WEBHOOK_ENABLED,
            "true" if payload.overdue_webhook_enabled else "false",
        )

    if payload.overdue_webhook_url is not None:
        # Already scheme-checked by `SettingsUpdate.http_or_https`, which
        # answers a 422 naming the field. `notifications.checked_url` checks it
        # again before every send, for the row a restore wrote.
        _store(db, SettingKey.OVERDUE_WEBHOOK_URL, payload.overdue_webhook_url)

    if payload.overdue_webhook_secret is not None:
        # An empty string is a deliberate clear, like the Google key.
        _store(
            db, SettingKey.OVERDUE_WEBHOOK_SECRET, payload.overdue_webhook_secret.strip()
        )

    if payload.overdue_reminder_days is not None:
        # Not a channel's configuration: it says how often a loan is chased, so
        # `sender_for` answers None and no health record is dropped.
        _store(
            db, SettingKey.OVERDUE_REMINDER_DAYS, str(payload.overdue_reminder_days)
        )

    for field, key in _SENDER_TEXT.items():
        value = getattr(payload, field)
        if value is None:
            continue
        _refuse_if_pinned(key)
        # An empty string is a deliberate clear, like the Google key and the
        # webhook secret. `None` never reaches here.
        _store(db, key, value.strip())

    if payload.catalogue_sources is not None:
        # Merged against what is stored rather than taken whole: a payload that
        # names one source must not be read as switching the other eight on. See
        # `sources.from_wire`.
        _store(
            db,
            SettingKey.CATALOGUE_SOURCES,
            sources.serialise(
                sources.from_wire(
                    [
                        sources.Preference(entry.source, entry.enabled)
                        for entry in payload.catalogue_sources
                    ],
                    settings_store.stored_catalogue_sources(db),
                )
            ),
        )

    for field, key in _LIBRARY_MODE_BOOL.items():
        value = getattr(payload, field)
        if value is None:
            continue
        _store(db, key, "true" if value else "false")

    for field, key in _SENDER_BOOL.items():
        value = getattr(payload, field)
        if value is None:
            continue
        _refuse_if_pinned(key)
        _store(db, key, "true" if value else "false")

    # **Every write that can change which catalogues are asked drops the lookup
    # cache**, and there are three rather than one: the provider list, and the
    # two Google Books rows that `settings_store.ready_sources` reads. Clearing
    # on only the first was the shape of the defect it was meant to fix, since
    # switching Google off through its own card takes it out of the plan at once
    # while the records it had already supplied stayed served for another day.
    #
    # Decided from the payload rather than from what changed, because a write
    # storing the same value still means somebody looked at that switch, and a
    # needless cache drop costs one re-fetch where a missed one costs a stale
    # answer nobody can explain.
    if (
        payload.catalogue_sources is not None
        or payload.google_books_enabled is not None
        or payload.google_books_api_key is not None
    ):
        metadata.clear_cache()

    return _read_settings(db)


# ── The encryption key, and the credentials it protects ───────────────────────
#
# **Five routes, and the split between them is the show-once property.** Only
# `create_credential_key` ever returns key material, and it refuses when a key
# exists, so there is no call in this application that renders a key already in
# being. Everything else here reports *about* the key: whether one is
# configured, where it came from, and how many stored credentials it cannot
# open. Reporting where a value comes from is not reporting the value, which is
# the rule the mail and Telegram fields already run on.
#
# Not rate limited, deliberately, unlike `/auth/login` beside them. Every route
# here is admin only, and the one that takes a secret takes a 24 word phrase:
# the search space is 2^256, so a limiter would be defending an entrance nobody
# can walk through against callers who are already inside.


def _known_source(source: str) -> CatalogueSource:
    """The roster row this path names, or 404.

    **404 rather than 422**, because a path segment that names no resource is a
    missing resource, and the enum happens to be how the roster is spelled today
    rather than what is being validated.

    **Validated against the roster, while the store is keyed on the target
    row.** The two agree on this date because every row is a `CatalogueSource`.
    They are written apart on purpose: keying storage on the closed enum would
    let the storage shape decide which rows may carry a credential, which is the
    tangle #180 reversed an earlier decision to undo. When a curated registry
    can add a row, this check moves to `catalogue_targets` and nothing below it
    changes.
    """
    try:
        return CatalogueSource(source)
    except ValueError:
        raise HTTPException(status_code=404, detail="No such catalogue source.") from None


def _read_credential_key(db: DbSession) -> CredentialKeyOut:
    """What can be said about the key, with a configuration problem said plainly.

    A deployment can configure something unusable: two stores holding different
    keys, a phrase that failed its checksum, a locked keychain. That is a
    **state to report on this screen**, not a 500 on the settings page, which is
    what `credentials.key_state` turns it into.
    """
    state = credentials.key_state()
    return CredentialKeyOut(
        configured=state.material is not None,
        location=credentials.key_location() if state.material is not None else "",
        can_generate=any(source.writable for source in credentials.KEY_SOURCES),
        problem=state.problem,
        # Off the table, not the roster. `credentials.unreadable_sources` says
        # why, and `generate_key` refuses against the same function, so the
        # refusal cannot quote a number this screen denies.
        unreadable_sources=credentials.unreadable_sources(db, state),
    )


@router.get("/credential-key", response_model=CredentialKeyOut)
def get_credential_key(
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> CredentialKeyOut:
    """Whether this deployment holds an encryption key, and where from.

    Never the key. A phrase leaves this application through exactly one route,
    the POST below, and only when there was nothing to overwrite.
    """
    return _read_credential_key(db)


@router.post("/credential-key", response_model=RecoveryPhraseOut)
def create_credential_key(
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> RecoveryPhraseOut:
    """Make an encryption key, store it, and return the phrase **once**.

    **The one response in this application that carries a secret**, and the
    exception is bounded by the route rather than by a promise: it refuses when
    a key already exists, so replaying it cannot re-display one. Write the words
    down; there is no second chance to read them, by construction.

    Where the key is kept is this machine's business: its keychain where it has
    one, otherwise a file readable only by the account the app runs as. Neither
    travels in a backup archive, which is what makes the archive safe to hand
    around and is also why the phrase matters.
    """
    try:
        phrase, _ = credentials.generate_key(db)
    except credentials.KeyConfigurationError as refusal:
        raise HTTPException(status_code=409, detail=str(refusal)) from None
    return RecoveryPhraseOut(phrase=phrase)


@router.put("/credential-key", response_model=CredentialKeyOut)
def restore_credential_key(
    payload: RecoveryPhraseIn,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> CredentialKeyOut:
    """Take a recovery phrase back in, on a new machine or after one was lost.

    **The checksum is what makes a wrong word an error rather than a different
    key.** A phrase with a word mistyped, misread off paper, or two words
    swapped is refused here; without it this route would cheerfully store a key
    that opens nothing and report success.

    Replacing a key that currently works is allowed and is not guarded against:
    it is what a person restoring a backup onto a new machine is doing, and the
    response says how many stored credentials the new key cannot open, which is
    the only honest report available.
    """
    try:
        credentials.store_key(payload.phrase)
    except credentials.BadRecoveryPhrase as refusal:
        # 422 rather than 409: a phrase somebody mistyped is a bad request, and
        # a key the deployment pinned elsewhere is a conflict with the
        # deployment. One status for both told a client nothing it could act on.
        raise HTTPException(status_code=422, detail=str(refusal)) from None
    except credentials.KeyConfigurationError as refusal:
        raise HTTPException(status_code=409, detail=str(refusal)) from None
    return _read_credential_key(db)


@router.delete("/credential-key", response_model=CredentialKeyOut)
def forget_credential_key(
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> CredentialKeyOut:
    """Drop the key this machine holds, so a new one can be made.

    **The way back from closing the tab without writing the words down.**
    Without this, `POST` refuses because a key exists, `PUT` wants a phrase
    nobody has, and the deployment is stuck behind a key protecting nothing.

    **It strands whatever the key was opening, and the response says how many**
    rather than this route hiding it: `unreadable_credentials` on the way out is
    the count of stored logins that now have to be typed again. Removing those
    logins first is the way to reach a clean state, and `DELETE` on a source's
    credential needs no key for exactly that reason.

    409 when the deployment pinned the key through the environment: a process
    cannot unset a variable for its own next start, so there is nothing here to
    clear.
    """
    try:
        credentials.forget_key()
    except credentials.KeyConfigurationError as refusal:
        raise HTTPException(status_code=409, detail=str(refusal)) from None
    return _read_credential_key(db)


@router.put("/catalogue-sources/{source}/credential", response_model=SettingsOut)
def set_source_credential(
    source: str,
    payload: SourceCredentialIn,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> SettingsOut:
    """Store a login for one catalogue, sealed.

    **Any roster source, not only one that declares it needs a credential.** A
    library may hold an account at a catalogue that also answers anonymously,
    and refusing it would be the storage deciding who may have an account
    somewhere else.

    409 when the deployment pinned this source's credential, the same rule and
    the same reason `_refuse_if_pinned` states for a settings row: a value the
    environment supplies wins, so storing a different one produces a screen that
    disagrees with what the next request actually sends.
    """
    known = _known_source(source)
    if credentials.is_from_env(known.value):
        raise HTTPException(
            status_code=409,
            detail=(
                f"{credentials.env_variable_name(known.value)} is supplied by this "
                "deployment's environment and cannot be changed here. Change it "
                "where the app is configured."
            ),
        )
    try:
        credentials.put(db, known.value, payload.username, payload.password)
    except credentials.NoKeyConfigured as refusal:
        raise HTTPException(status_code=409, detail=str(refusal)) from None
    except credentials.KeyConfigurationError as refusal:
        raise HTTPException(status_code=409, detail=str(refusal)) from None
    except credentials.CredentialError as refusal:
        raise HTTPException(status_code=400, detail=str(refusal)) from None
    # A credential can make a source ready, which changes which catalogues the
    # next lookup asks. Same reason the three writes in `update_settings` do it.
    metadata.clear_cache()
    return _read_settings(db)


@router.delete("/catalogue-sources/{source}/credential", response_model=SettingsOut)
def forget_source_credential(
    source: str,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> SettingsOut:
    """Drop a stored login for one catalogue.

    **Succeeds whether or not one was stored**, and needs no key to do it: a
    credential nobody can read is exactly the one somebody most wants to be rid
    of, and requiring the key to delete it would make a rotated key
    unrecoverable without a database edit. It is also what lets somebody who
    lost the recovery phrase reach a state where a new key may be made.

    **Reaches a row whose catalogue is no longer in the roster**, which the
    write above does not. `catalogue_credentials` carries no foreign key, on
    purpose, so that one credential for a source a later release dropped cannot
    fail an entire restore; the cost of that is an orphan, and an orphan nothing
    can delete would be a row needing a database edit to remove. Deleting sends
    nothing anywhere, so the roster check buys nothing here and costs that.

    **The pinned check fires only when nothing is stored, and that ordering is
    load bearing.** It read "there is nothing stored to remove", which stopped
    being true the moment `unreadable_sources` began counting a pinned source's
    sealed row: a login stored for a source the environment also pins **blocks
    key creation**, and refusing to delete it made that a dead end whose only
    exit was unsetting the variable, deleting, and setting it again, with
    nothing on screen saying so. An archive carries `catalogue_credentials`, so
    a restore onto a deployment that pins that source arrives there without
    anybody doing anything unusual.

    So: a row is a row, pinned or not, and deleting one sends nothing anywhere
    and does not touch the environment. With nothing stored the 409 is honest
    again, because then there really is nothing here to remove and the
    environment's is not this route's to clear.
    """
    if not credentials.stored_envelope(db, source):
        # Nothing stored, so the source has to be one this build knows; that is
        # what turns a typo into a 404 rather than a silent success.
        _known_source(source)
        if credentials.is_from_env(source):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{credentials.env_variable_name(source)} is supplied by this "
                    "deployment's environment and cannot be changed here. Change it "
                    "where the app is configured."
                ),
            )
    credentials.forget(db, source)
    metadata.clear_cache()
    return _read_settings(db)
