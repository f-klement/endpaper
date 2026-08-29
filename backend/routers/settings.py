from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Final

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

import config
import covers
import notifications
import settings_store
from auth import require_admin
from config import ALLOWED_IMAGE_EXTENSIONS, COVERS_DIR
from dependencies import DbSession
from enums import SettingKey
from models import User
from schemas import (
    FeatureFlagsOut,
    LoginImageOut,
    SenderHealth,
    SettingsOut,
    SettingsUpdate,
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

def _store(db: DbSession, key: SettingKey, value: str) -> None:
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
    """
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


def _read_settings(db: DbSession) -> SettingsOut:
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

    return _read_settings(db)
