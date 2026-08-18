from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

import config
import settings_store
from auth import require_admin
from config import ALLOWED_IMAGE_EXTENSIONS, COVERS_DIR
from dependencies import DbSession
from enums import SettingKey
from models import User
from schemas import FeatureFlagsOut, LoginImageOut, SettingsOut, SettingsUpdate
from uploads import read_image_upload

LOGIN_BG_BASE = "login_bg"

router = APIRouter(prefix="/api/settings", tags=["settings"])


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

    # Remove any existing background first: two formats of login_bg would both
    # exist and _find_login_bg would pick whichever it saw first.
    for old_extension in ALLOWED_IMAGE_EXTENSIONS:
        old_path = COVERS_DIR / f"{LOGIN_BG_BASE}.{old_extension}"
        if old_path.exists():
            old_path.unlink()

    destination = COVERS_DIR / f"{LOGIN_BG_BASE}.{extension}"
    destination.write_bytes(data)
    return LoginImageOut(url=f"/covers/{destination.name}")


# ── Runtime settings ──────────────────────────────────────────────────────────


def _read_settings(db: DbSession) -> SettingsOut:
    from_env = config.google_books_api_key_from_env()
    # The one in force, which is the environment's when it has one. Showing the
    # stored key's preview while a different key is actually being used would
    # be worse than showing nothing.
    key = from_env or settings_store.get_raw(db, SettingKey.GOOGLE_BOOKS_API_KEY)

    return SettingsOut(
        google_books_enabled=settings_store.get_bool(db, SettingKey.GOOGLE_BOOKS_ENABLED),
        google_books_api_key_preview=settings_store.mask(key),
        has_google_books_api_key=bool(key),
        google_books_api_key_from_env=bool(from_env),
        goodreads_lookup_enabled=settings_store.get_bool(
            db, SettingKey.GOODREADS_LOOKUP_ENABLED
        ),
        default_locale=settings_store.get_locale(db, SettingKey.DEFAULT_LOCALE),
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
    )


@router.get("", response_model=SettingsOut)
def get_settings(
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> SettingsOut:
    return _read_settings(db)


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
        settings_store.set_value(
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
        settings_store.set_value(
            db, SettingKey.GOOGLE_BOOKS_API_KEY, payload.google_books_api_key.strip()
        )

    if payload.goodreads_lookup_enabled is not None:
        settings_store.set_value(
            db,
            SettingKey.GOODREADS_LOOKUP_ENABLED,
            "true" if payload.goodreads_lookup_enabled else "false",
        )

    if payload.default_locale is not None:
        settings_store.set_value(db, SettingKey.DEFAULT_LOCALE, payload.default_locale.value)

    return _read_settings(db)
