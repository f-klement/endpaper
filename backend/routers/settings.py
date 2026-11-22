from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Final
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

import catalogue_access
import classification_schemes
import config
import cover_store
import covers
import credentials
import harvester
import metadata
import notifications
import registry
import settings_store
import sources
import targets
import vocabulary_copy
from auth import require_admin
from dependencies import CurrentUser, DbSession
from enums import CatalogueSource, CredentialKind, RegisteredCatalogue, SettingKey
from models import ClassificationSchemeRow, User
from refusals import refuses
from schemas import (
    CatalogueRegistryOut,
    CatalogueSourceOut,
    CatalogueSourcePreference,
    ClassificationSchemeCreate,
    ClassificationSchemeOut,
    ClassificationSchemeRename,
    CredentialKeyOut,
    FeatureFlagsOut,
    LoginImageOut,
    ProbeEvidenceOut,
    RecoveryPhraseIn,
    RecoveryPhraseOut,
    RegistryEntryOut,
    SenderHealth,
    SettingsOut,
    SettingsUpdate,
    SourceCredentialIn,
    SourceTestIn,
    VocabularyOut,
    VocabularyProgressOut,
)
from uploads import read_image_upload

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

#: Every switch whose write is uniform: a boolean, stored, with no environment
#: override to refuse and no sender health to forget.
#:
#: A table for the same reason `_SENDER_BOOL` is one, and separate from it
#: because these are not senders: `notifications.sender_for` answers None for
#: every one of them, so routing them through `_SENDER_BOOL` would work and
#: would file them under a heading they do not belong to.
#:
#: **Named for the property rather than for the feature**, because it was
#: `_LIBRARY_MODE_BOOL` and the fourth entry is an account policy with nothing
#: to do with library mode: a name describing three of four members is how the
#: next one gets a second loop of its own beside this one.
#:
#: **Nothing here refuses a combination.** `public_catalogue_enabled` may be
#: stored true while `library_mode` is false; the catalogue is still not
#: published, because `settings_store.public_catalogue_is_published` reads both
#: and the routes ask it rather than reading a row. Enforcing the nesting at
#: the write instead would make the order of two toggles in one form matter.
_STORED_BOOL: Final[dict[str, SettingKey]] = {
    "library_mode": SettingKey.LIBRARY_MODE,
    "public_catalogue_enabled": SettingKey.PUBLIC_CATALOGUE_ENABLED,
    "public_catalogue_indexing_enabled": SettingKey.PUBLIC_CATALOGUE_INDEXING_ENABLED,
    # Whether accounts here belong to people outside the household, which is the
    # one switch that turns on confirming a new account's address. Stored rather
    # than pinned from the environment, like the three above and for the same
    # reason: an account policy turned on by mistake has to be correctable
    # without a redeploy.
    "accounts_open_to_outsiders": SettingKey.ACCOUNTS_OPEN_TO_OUTSIDERS,
    # The SRU server's switch. Stored whatever the publish state, like the
    # publish row: `settings_store.sru_is_served` reads both.
    "sru_server_enabled": SettingKey.SRU_SERVER_ENABLED,
    # The OAI-PMH provider's switch, stored the same way and read by
    # `settings_store.oai_is_served` with the publish state.
    "oai_provider_enabled": SettingKey.OAI_PROVIDER_ENABLED,
    # The OAI-PMH harvester's switch. Refused on without a repository by
    # `_refuse_harvest_without_a_repository`, and read by
    # `settings_store.harvest_repository` with library mode.
    "oai_harvest_enabled": SettingKey.OAI_HARVEST_ENABLED,
    # Whether a public record shows on the shelf or on loan. Stored whatever
    # the publish state: `settings_store.availability_is_shown` reads both.
    "public_availability_enabled": SettingKey.PUBLIC_AVAILABILITY_ENABLED,
    # The library page's vocabulary offer, put away for the installation.
    "vocabulary_offer_dismissed": SettingKey.VOCABULARY_OFFER_DISMISSED,
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
    try:
        if isinstance(value, dict):
            settings_store.set_json(db, key, value)
        else:
            settings_store.set_value(db, key, value)
    except credentials.NoKeyConfigured as refusal:
        # A secret with no key to seal it with: refused, never written in
        # plaintext. The message says how to make a key.
        raise HTTPException(status_code=409, detail=str(refusal)) from None
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


@router.get("/login-image", response_model=LoginImageOut)
@refuses(404)
async def get_login_image() -> LoginImageOut:
    """Public: the login page renders before anyone holds a token."""
    path = cover_store.login_background_path()
    if path is None:
        raise HTTPException(status_code=404, detail="No login background set")
    return LoginImageOut(url=covers.stored_url(path.name))


@router.post("/login-image", response_model=LoginImageOut)
async def set_login_image(
    file: Annotated[UploadFile, File()],
    current_user: Annotated[User, Depends(require_admin)],
) -> LoginImageOut:
    # Read against the size cap and refused here if it is not an image, so the
    # caller gets a 413 or a 400 rather than a 500 out of the store's own
    # refusal. What it is called, and that the other formats of it go, are
    # `cover_store`'s.
    data = await read_image_upload(file)
    destination = cover_store.save_login_background(data)
    return LoginImageOut(url=covers.stored_url(destination.name))


# ── Runtime settings ──────────────────────────────────────────────────────────


def _credential_view(db: DbSession, source: CatalogueSource, state: credentials.KeyState) -> dict[str, Any]:
    """The credential fields on one roster row, and no secret among them.

    **Built here rather than in `sources.describe`**, which is where the other
    derived fields come from. That module owns which catalogues are asked and in
    what order, holds no database by design, and a credential is neither of
    those things. Masking is here for the same reason it is here for the mail
    password: it is presentation, and `settings_store.mask` is the one rule.

    **The row's own address is handed over**, because the ladder's bottom level
    is bound to it: see `credentials.view`. `targets.SEEDED` is what the runtime
    asks, so this is the same address a lookup would use.
    """
    held = credentials.view(db, source.value, targets.SEEDED[source].base_url, state)
    return {
        "credential_provenance": held.provenance,
        "credential_username_preview": settings_store.mask(held.username),
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
    #
    # **Asked rather than spelled out.** `from_env or get_raw(...)` is
    # `in_force`'s own body, so writing it here puts precedence in two places
    # and makes this the one stored read of a key the environment can pin in the
    # whole backend: the exemption
    # `tests/test_settings_store.py::TestAnOverriddenSettingIsReadWhereItIsPinned`
    # would then need. `from_env` stays because the response also reports
    # **whether** the deployment supplied it, which is provenance rather than
    # the value.
    # Empty for a sealed secret the key cannot open, rather than a 500 on this
    # page: `unreadable_secrets` below says which to enter again.
    key = settings_store.in_force_if_readable(db, SettingKey.GOOGLE_BOOKS_API_KEY, encryption_key)
    webhook_secret = settings_store.in_force_if_readable(
        db, SettingKey.OVERDUE_WEBHOOK_SECRET, encryption_key
    )
    # The one in force for both, for the reason the Google key's preview is:
    # showing a preview of a secret that is not the one being used is worse
    # than showing none at all.
    mail_password = settings_store.in_force_if_readable(db, SettingKey.MAIL_PASSWORD, encryption_key)
    telegram_token = settings_store.in_force_if_readable(db, SettingKey.TELEGRAM_BOT_TOKEN, encryption_key)

    return SettingsOut(
        google_books_enabled=settings_store.get_bool(db, SettingKey.GOOGLE_BOOKS_ENABLED),
        google_books_api_key_preview=settings_store.mask(key),
        has_google_books_api_key=bool(key),
        google_books_api_key_from_env=bool(from_env),
        goodreads_lookup_enabled=settings_store.get_bool(db, SettingKey.GOODREADS_LOOKUP_ENABLED),
        default_locale=settings_store.get_locale(db, SettingKey.DEFAULT_LOCALE),
        overdue_webhook_enabled=settings_store.get_bool(db, SettingKey.OVERDUE_WEBHOOK_ENABLED),
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
            pinned.value for pinned in settings_store.MAIL_KEYS if settings_store.is_from_env(pinned)
        ],
        overdue_telegram_enabled=settings_store.get_bool(db, SettingKey.OVERDUE_TELEGRAM_ENABLED),
        telegram_bot_token_preview=settings_store.mask(telegram_token),
        has_telegram_bot_token=bool(telegram_token),
        telegram_bot_token_from_env=settings_store.is_from_env(SettingKey.TELEGRAM_BOT_TOKEN),
        telegram_chat_id=settings_store.in_force(db, SettingKey.TELEGRAM_CHAT_ID),
        telegram_chat_id_from_env=settings_store.is_from_env(SettingKey.TELEGRAM_CHAT_ID),
        overdue_in_app_enabled=settings_store.get_bool(db, SettingKey.OVERDUE_IN_APP_ENABLED),
        unreadable_secrets=settings_store.unreadable_secrets(db, encryption_key),
        # The two switches as stored, so the form shows what an admin typed,
        # plus the conjunction that decides whether anything is actually
        # served. See `SettingsOut` for why the screen needs all three.
        library_mode=settings_store.get_bool(db, SettingKey.LIBRARY_MODE),
        public_catalogue_enabled=settings_store.get_bool(db, SettingKey.PUBLIC_CATALOGUE_ENABLED),
        public_catalogue_indexing_enabled=settings_store.get_bool(
            db, SettingKey.PUBLIC_CATALOGUE_INDEXING_ENABLED
        ),
        public_catalogue_published=settings_store.public_catalogue_is_published(db),
        sru_server_enabled=settings_store.get_bool(db, SettingKey.SRU_SERVER_ENABLED),
        oai_provider_enabled=settings_store.get_bool(db, SettingKey.OAI_PROVIDER_ENABLED),
        oai_admin_email=settings_store.get_raw(db, SettingKey.OAI_ADMIN_EMAIL),
        oai_harvest_enabled=settings_store.get_bool(db, SettingKey.OAI_HARVEST_ENABLED),
        oai_harvest_base_url=settings_store.get_raw(db, SettingKey.OAI_HARVEST_BASE_URL),
        public_availability_enabled=settings_store.get_bool(db, SettingKey.PUBLIC_AVAILABILITY_ENABLED),
        accounts_open_to_outsiders=settings_store.accounts_are_open_to_outsiders(db),
        vocabulary_offer_dismissed=settings_store.get_bool(db, SettingKey.VOCABULARY_OFFER_DISMISSED),
        # **The stored list, not the one in force.** An admin has to see what
        # they set: a screen that hid Google Books because no key is configured
        # would be one they cannot use, since they would switch it on and watch
        # it come back off. `ready` beside it is what says it cannot answer yet.
        catalogue_sources=[
            CatalogueSourceOut(**vars(described), **_credential_view(db, described.source, encryption_key))
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
        # The conjunction alone; the raw toggle is admin-only: see
        # `FeatureFlagsOut.google_books_ready`. Public deliberately, and
        # `catalogue_access.GOOGLE_BOOKS_IS_NOT_ASKED` relies on it: that refusal tells a
        # member no more than this tells anybody. Narrowing this fails
        # `TestTheBackfillRefusalTellsAMemberOnlyWhatAnybodyCanRead`, and the refusal goes with it.
        google_books_ready=google_books_enabled and has_key,
        goodreads_lookup_enabled=settings_store.get_bool(db, SettingKey.GOODREADS_LOOKUP_ENABLED),
        default_locale=settings_store.get_locale(db, SettingKey.DEFAULT_LOCALE),
        # The raw row here, because every MARC route gates on the raw row and a
        # client reading this has to get the answer they give. The field below
        # is a conjunction for the opposite reason.
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


def _flag(value: bool) -> str:
    """How a switch is stored: the two words `settings_store` reads back."""
    return "true" if value else "false"


def _write_lookup_settings(db: DbSession, payload: SettingsUpdate) -> None:
    """The Google Books switch and key, and the Goodreads switch, in that order."""
    if payload.google_books_enabled is not None:
        _store(db, SettingKey.GOOGLE_BOOKS_ENABLED, _flag(payload.google_books_enabled))

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
        _store(db, SettingKey.GOOGLE_BOOKS_API_KEY, payload.google_books_api_key.strip())

    if payload.goodreads_lookup_enabled is not None:
        _store(db, SettingKey.GOODREADS_LOOKUP_ENABLED, _flag(payload.goodreads_lookup_enabled))


def _write_reminder_settings(db: DbSession, payload: SettingsUpdate) -> None:
    """The locale, the webhook and the reminder interval: each its own rule."""
    if payload.default_locale is not None:
        _store(db, SettingKey.DEFAULT_LOCALE, payload.default_locale.value)

    if payload.overdue_webhook_enabled is not None:
        _store(db, SettingKey.OVERDUE_WEBHOOK_ENABLED, _flag(payload.overdue_webhook_enabled))

    if payload.overdue_webhook_url is not None:
        # Already scheme-checked by `SettingsUpdate.http_or_https`, which
        # answers a 422 naming the field. `notifications.checked_url` checks it
        # again before every send, for the row a restore wrote.
        _store(db, SettingKey.OVERDUE_WEBHOOK_URL, payload.overdue_webhook_url)

    if payload.overdue_webhook_secret is not None:
        # An empty string is a deliberate clear, like the Google key.
        _store(db, SettingKey.OVERDUE_WEBHOOK_SECRET, payload.overdue_webhook_secret.strip())

    if payload.overdue_reminder_days is not None:
        # Not a channel's configuration: it says how often a loan is chased, so
        # `sender_for` answers None and no health record is dropped.
        _store(db, SettingKey.OVERDUE_REMINDER_DAYS, str(payload.overdue_reminder_days))


def _write_table[T](
    db: DbSession,
    payload: SettingsUpdate,
    table: dict[str, SettingKey],
    encode: Callable[[T], str],
    *,
    refuse_pinned: bool,
) -> None:
    """Write every field of one write table the payload carries, in table order.

    **The pinned check runs per field, before that field's write**, as it did
    when each table had its loop inline: a 409 on the second field still
    leaves the first written, and moving the check ahead of the loop would
    change which rows a refused request leaves behind.
    """
    for field, key in table.items():
        value = getattr(payload, field)
        if value is None:
            continue
        if refuse_pinned:
            _refuse_if_pinned(key)
        _store(db, key, encode(value))


#: Why the OAI-PMH switch was refused. Named in the UI's hint as well.
_OAI_NEEDS_AN_ADDRESS: Final = (
    "OAI-PMH needs a repository contact address before it can be turned on, because every "
    "harvester is told one. Enter it first."
)


def _refuse_oai_without_an_address(db: DbSession, payload: SettingsUpdate) -> None:
    """409 for a write that would leave the OAI-PMH switch on with no address.

    Owner's decision on issue #176: `Identify` must name a contact, and a role
    address chosen on purpose is the only one this app publishes. Checked
    before any field is written, so a refused request changes nothing. Only a
    write naming either field is checked: one that names neither leaves the
    pair as it was.
    """
    if payload.oai_provider_enabled is None and payload.oai_admin_email is None:
        return
    switched_on = (
        payload.oai_provider_enabled
        if payload.oai_provider_enabled is not None
        else settings_store.get_bool(db, SettingKey.OAI_PROVIDER_ENABLED)
    )
    address = (
        payload.oai_admin_email
        if payload.oai_admin_email is not None
        else settings_store.get_raw(db, SettingKey.OAI_ADMIN_EMAIL).strip()
    )
    if switched_on and not address:
        raise HTTPException(status_code=409, detail=_OAI_NEEDS_AN_ADDRESS)


#: Why the harvester's switch was refused. Named in the UI's hint as well.
_HARVEST_NEEDS_A_REPOSITORY: Final = (
    "The OAI-PMH harvester needs a repository address before it can be turned on. Enter it first."
)


def _refuse_harvest_without_a_repository(db: DbSession, payload: SettingsUpdate) -> None:
    """409 for a write that would leave the harvester on with no repository.

    The import half of issue #178: a switch with no endpoint turns on nothing,
    so it is refused where it is set rather than found broken at the harvest.
    The shape of `_refuse_oai_without_an_address`, for its reasons: checked
    before any field is written, and only for a write naming either field.
    """
    if payload.oai_harvest_enabled is None and payload.oai_harvest_base_url is None:
        return
    switched_on = (
        payload.oai_harvest_enabled
        if payload.oai_harvest_enabled is not None
        else settings_store.get_bool(db, SettingKey.OAI_HARVEST_ENABLED)
    )
    address = (
        payload.oai_harvest_base_url
        if payload.oai_harvest_base_url is not None
        else settings_store.get_raw(db, SettingKey.OAI_HARVEST_BASE_URL).strip()
    )
    if switched_on and not address:
        raise HTTPException(status_code=409, detail=_HARVEST_NEEDS_A_REPOSITORY)


#: Why a repository address was refused. **A constant sentence**: the 400 never
#: echoes what was typed.
_REPOSITORY_NOT_HARVESTABLE: Final = (
    "The repository address must be an http or https address with no username, password, query or fragment."
)


def _refuse_an_unharvestable_repository(payload: SettingsUpdate) -> None:
    """400 for a repository address `harvester.is_harvestable` refuses.

    Here rather than in `SettingsUpdate`, which only trims it: the rule reaches
    `fetch`, and a schema sits below it. The same rule
    `harvester.configured_repository` reads the stored row with, so a row this
    write accepts is never one the harvester then refuses. Checked before any
    field is written. 400 rather than 422: the schema types a 422's `detail`
    as a list of validation entries, and this one is a sentence
    (`tests/test_errors.py`).
    """
    address = payload.oai_harvest_base_url
    if address and not harvester.is_harvestable(address):
        raise HTTPException(status_code=400, detail=_REPOSITORY_NOT_HARVESTABLE)


def _write_catalogue_sources(db: DbSession, wire: list[CatalogueSourcePreference]) -> None:
    """Merged against what is stored rather than taken whole: a payload that
    names one source must not be read as switching the other eight on. See
    `sources.from_wire`."""
    _store(
        db,
        SettingKey.CATALOGUE_SOURCES,
        sources.serialise(
            sources.from_wire(
                [sources.Preference(entry.source, entry.enabled) for entry in wire],
                settings_store.stored_catalogue_sources(db),
            )
        ),
    )


def _asks_other_catalogues(payload: SettingsUpdate) -> bool:
    """Whether this write can change which catalogues are asked.

    **Every write that can drops the lookup cache**, and there are three rather
    than one: the provider list, and the two Google Books rows that
    `settings_store.ready_sources` reads. Clearing on only the first was the
    shape of the defect it was meant to fix, since switching Google off through
    its own card takes it out of the plan at once while the records it had
    already supplied stayed served for another day.

    Decided from the payload rather than from what changed, because a write
    storing the same value still means somebody looked at that switch, and a
    needless cache drop costs one re-fetch where a missed one costs a stale
    answer nobody can explain.
    """
    return (
        payload.catalogue_sources is not None
        or payload.google_books_enabled is not None
        or payload.google_books_api_key is not None
    )


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
    _refuse_oai_without_an_address(db, payload)
    _refuse_an_unharvestable_repository(payload)
    _refuse_harvest_without_a_repository(db, payload)
    _write_lookup_settings(db, payload)
    _write_reminder_settings(db, payload)
    # An empty string is a deliberate clear, like the Google key and the
    # webhook secret. `None` never reaches here.
    _write_table(db, payload, _SENDER_TEXT, str.strip, refuse_pinned=True)

    if payload.catalogue_sources is not None:
        _write_catalogue_sources(db, payload.catalogue_sources)

    if payload.oai_admin_email is not None:
        # Already checked as an address, or "", by `SettingsUpdate`.
        _store(db, SettingKey.OAI_ADMIN_EMAIL, payload.oai_admin_email)
    if payload.oai_harvest_base_url is not None:
        # Trimmed by `SettingsUpdate`, checked by `harvester.is_harvestable`
        # above unless "", and refused empty while the switch is on.
        _store(db, SettingKey.OAI_HARVEST_BASE_URL, payload.oai_harvest_base_url)
    _write_table(db, payload, _STORED_BOOL, _flag, refuse_pinned=False)
    _write_table(db, payload, _SENDER_BOOL, _flag, refuse_pinned=True)

    if _asks_other_catalogues(payload):
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
        unreadable_settings=credentials.unreadable_settings(db, state),
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
    # A secret written before there was a key is sealed now there is one.
    settings_store.seal_plaintext_secrets(db)
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
        # 400 rather than 409: a phrase somebody mistyped is a bad request, and
        # a key the deployment pinned elsewhere is a conflict with the
        # deployment. One status for both told a client nothing it could act on.
        raise HTTPException(status_code=400, detail=str(refusal)) from None
    except credentials.KeyConfigurationError as refusal:
        raise HTTPException(status_code=409, detail=str(refusal)) from None
    # As `POST` does: a secret written before there was a key is sealed now.
    settings_store.seal_plaintext_secrets(db)
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

    **It strands whatever the key was opening, and the response says which**
    rather than this route hiding it: `unreadable_sources` and
    `unreadable_settings` on the way out name the stored catalogue logins and
    settings secrets that now have to be typed again. A
    member's own Readwise token is not in that count: its member is told on
    their account page and saves it again. Removing those
    logins first is the way to reach a clean state, and `DELETE` on a source's
    credential needs no key for exactly that reason.

    409 when a store holding the key cannot be cleared from here, naming it:
    the environment, because a process cannot unset a variable for its own next
    start; a key file this process cannot remove; or a keychain that kept the
    key.
    """
    try:
        credentials.forget_key()
    except credentials.KeyConfigurationError as refusal:
        raise HTTPException(status_code=409, detail=str(refusal)) from None
    return _read_credential_key(db)


@router.put("/catalogue-sources/{source}/credential", response_model=SettingsOut)
@refuses(404)
def set_source_credential(
    source: str,
    payload: SourceCredentialIn,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> SettingsOut:
    """Store a login for one catalogue, sealed.

    **Only a source whose credential is a login**, `targets.Target.credential_kind`.
    `settings_store.catalogue_logins` resolves a login for those and no other, so
    a login stored for a catalogue that answers anonymously, or for one whose
    credential is this deployment's key, would be sealed and read by nothing.
    409 names that the source takes none.

    409 when the deployment pinned this source's credential, the same rule and
    the same reason `_refuse_if_pinned` states for a settings row: a value the
    environment supplies wins, so storing a different one produces a screen that
    disagrees with what the next request actually sends.
    """
    known = _known_source(source)
    if targets.SEEDED[known].credential_kind is not CredentialKind.LOGIN:
        raise HTTPException(
            status_code=409, detail=f"{known.value} takes no login, so none can be stored for it."
        )
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
        credentials.put(
            db,
            known.value,
            targets.SEEDED[known].base_url,
            payload.username,
            payload.password,
        )
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
@refuses(404)
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


def _registry_out(db: DbSession) -> CatalogueRegistryOut:
    chosen = registry.picked(db)
    return CatalogueRegistryOut(
        listed_by=list(registry.LISTED_BY),
        taken_on=registry.TAKEN_ON,
        aged=registry.aged(datetime.now(UTC).date()),
        entries=[_entry_out(which, entry, which in chosen) for which, entry in registry.ENTRIES.items()],
    )


def _entry_out(which: RegisteredCatalogue, entry: registry.Entry, picked: bool) -> RegistryEntryOut:
    return RegistryEntryOut(
        source=which,
        name=entry.name,
        country=entry.country,
        kind=entry.kind,
        host=urlparse(entry.target.base_url).hostname or "",
        picked=picked,
        evidence=_evidence_out(entry.evidence),
    )


def _evidence_out(evidence: registry.Evidence) -> ProbeEvidenceOut:
    return ProbeEvidenceOut(
        probed_on=evidence.probed_on, isbn=evidence.isbn, disposition=evidence.disposition
    )


def _registered(source: str) -> RegisteredCatalogue:
    """The registry entry this path names, or 404, for `_known_source`'s reason."""
    try:
        return RegisteredCatalogue(source)
    except ValueError:
        raise HTTPException(status_code=404, detail="No such catalogue in the registry.") from None


@router.get("/catalogue-registry", response_model=CatalogueRegistryOut)
def get_catalogue_registry(
    db: DbSession, current_user: Annotated[User, Depends(require_admin)]
) -> CatalogueRegistryOut:
    """The curated catalogues this build ships, each with the evidence it was
    shipped on, and which of them this library picked. **Admin only**, beside
    the pick it is read to make. `aged` says the snapshot's evidence is older
    than it is trusted; nothing is fetched to find that out."""
    return _registry_out(db)


@router.put("/catalogue-registry/{source}", response_model=CatalogueRegistryOut)
@refuses(404)
def pick_registry_catalogue(
    source: str, db: DbSession, current_user: Annotated[User, Depends(require_admin)]
) -> CatalogueRegistryOut:
    """Pick one registry catalogue. Picking it again changes nothing.

    A picked catalogue is asked when a book is added by its ISBN, after every
    catalogue in the lookup order missed, and never in a title search;
    `registry` says why.
    """
    registry.pick(db, _registered(source))
    return _registry_out(db)


@router.delete("/catalogue-registry/{source}", response_model=CatalogueRegistryOut)
@refuses(404)
def drop_registry_catalogue(
    source: str, db: DbSession, current_user: Annotated[User, Depends(require_admin)]
) -> CatalogueRegistryOut:
    """Forget a pick. Dropping one never picked changes nothing."""
    registry.drop(db, _registered(source))
    return _registry_out(db)


def _testable(source: str) -> CatalogueSource | RegisteredCatalogue:
    """A seeded source or a registry entry, or 404.

    **The only route that admits both**, because testing is the one thing a
    registry entry and a seeded source share. The credential routes stay on
    `_known_source`, so a registry entry can never be handed a login.
    """
    try:
        return CatalogueSource(source)
    except ValueError:
        return _registered(source)


@router.post("/catalogue-sources/{source}/test", response_model=ProbeEvidenceOut)
@refuses(404)
async def probe_catalogue_source(
    source: str,
    payload: SourceTestIn,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> ProbeEvidenceOut:
    """Ask one catalogue about one ISBN the way a scan would, and say how it answered.

    **A disposition and never what the catalogue returned**: answered,
    answered nothing, refused or unreachable. **Admin only and rate limited for
    the whole deployment**, a 429 past `ratelimit.SOURCE_TEST_LIMIT`, because
    each test is a request to somebody else's server. A switched off source is
    tested too. With no ISBN, a registry entry is asked the one its shipped
    evidence names, so the result compares with that evidence directly.
    """
    return _evidence_out(await catalogue_access.probe(db, _testable(source), payload.isbn))


#: The `code` of a delete refused because books quote the scheme. The client
#: reads it with the `count` beside it to word the refusal in the reader's
#: language; `SCHEME_IN_USE` in the frontend's `ClassificationSchemesSection`.
SCHEME_IN_USE: Final = "scheme_in_use"


def _scheme_out(row: ClassificationSchemeRow) -> ClassificationSchemeOut:
    return ClassificationSchemeOut(
        scheme=row.code,
        name=row.name,
        filing=row.filing,
        built_in=classification_schemes.is_built_in(row.code),
    )


@refuses(404)
def _scheme(scheme: str, db: DbSession) -> ClassificationSchemeRow:
    """The scheme whose code is `scheme`, or a 404."""
    row = db.get(ClassificationSchemeRow, scheme)
    if row is None:
        raise HTTPException(status_code=404, detail="No such classification scheme.")
    return row


@router.get("/classification-schemes", response_model=list[ClassificationSchemeOut])
def list_classification_schemes(db: DbSession, current_user: CurrentUser) -> list[ClassificationSchemeOut]:
    """Every scheme a heading may quote: the built in four, then the library's own.

    **Any member**, because a book page names each heading's scheme from this
    list. It says nothing about a book: no count, and no scheme is hidden for
    being quoted only by somebody's private one.
    """
    return [_scheme_out(row) for row in classification_schemes.listing(db)]


@router.post("/classification-schemes", response_model=ClassificationSchemeOut, status_code=201)
def define_classification_scheme(
    payload: ClassificationSchemeCreate,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> ClassificationSchemeOut:
    """Add a scheme. A code already taken is a 409.

    **Admin only**, unlike defining a custom field: a scheme's filing rule is
    fixed once defined, and what it files under orders a library's shelves.
    """
    try:
        row = classification_schemes.define(db, payload.scheme, payload.name, payload.filing)
    except classification_schemes.Refused as refusal:
        raise HTTPException(status_code=409, detail=str(refusal)) from refusal
    db.commit()
    return _scheme_out(row)


@router.patch("/classification-schemes/{scheme}", response_model=ClassificationSchemeOut)
def rename_classification_scheme(
    payload: ClassificationSchemeRename,
    row: Annotated[ClassificationSchemeRow, Depends(_scheme)],
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> ClassificationSchemeOut:
    """Rename a library's own scheme. A built in one is a 409."""
    try:
        classification_schemes.rename(db, row, payload.name)
    except classification_schemes.Refused as refusal:
        raise HTTPException(status_code=409, detail=str(refusal)) from refusal
    db.commit()
    return _scheme_out(row)


@router.delete("/classification-schemes/{scheme}", status_code=204)
def delete_classification_scheme(
    row: Annotated[ClassificationSchemeRow, Depends(_scheme)],
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> None:
    """Delete a scheme no heading quotes.

    **A 409 naming how many books still quote it**, the owner's rule: no soft
    delete and no reassignment. Its `detail` carries `code` `scheme_in_use` and
    the `count` apart from the English sentence, for a client to word;
    `classification_schemes.remove` says what the count covers. A built in
    scheme is a 409 too, with a sentence only.
    """
    try:
        classification_schemes.remove(db, row, current_user.id)
    except classification_schemes.StillQuoted as refusal:
        raise HTTPException(
            status_code=409,
            detail={"message": str(refusal), "code": SCHEME_IN_USE, "count": refusal.count},
        ) from refusal
    except classification_schemes.Refused as refusal:
        raise HTTPException(status_code=409, detail=str(refusal)) from refusal
    db.commit()


# ── The local copy of each subject vocabulary ────────────────────────────────


def _vocabulary_out(status: vocabulary_copy.Status) -> VocabularyOut:
    copy, progress = status.copy, status.progress
    return VocabularyOut(
        scheme=status.scheme.id,
        name=status.scheme.name,
        licence=status.scheme.licence,
        copyable=status.copyable,
        entries=copy.entries if copy else None,
        fetched_at=copy.fetched_at if copy else None,
        released=copy.released if copy else None,
        progress=(
            VocabularyProgressOut(
                phase=progress.phase, done=progress.done, total=progress.total, error=progress.error
            )
            if progress
            else None
        ),
    )


@router.get("/vocabularies", response_model=list[VocabularyOut])
def list_vocabularies(
    db: DbSession, current_user: Annotated[User, Depends(require_admin)]
) -> list[VocabularyOut]:
    """Every declared subject vocabulary: its licence, what is loaded of it and
    when, and any download under way. **Admin only**, beside the download it
    is read to start."""
    return [_vocabulary_out(status) for status in vocabulary_copy.statuses(db)]


@router.post("/vocabularies/{scheme}/download", response_model=VocabularyOut, status_code=202)
@refuses(404)
def download_vocabulary(
    scheme: str, db: DbSession, current_user: Annotated[User, Depends(require_admin)]
) -> VocabularyOut:
    """Fetch the vocabulary's release and load it in the background, replacing
    the copy in use only once the new one is complete. The first download and
    every refresh are this one request.

    A 404 for a vocabulary nobody declared. A 409 where its licence permits no
    local copy, or a download of it is already under way.
    """
    try:
        vocabulary_copy.start(scheme)
    except vocabulary_copy.Unknown as unknown:
        raise HTTPException(status_code=404, detail="No such vocabulary.") from unknown
    except vocabulary_copy.Refused as refusal:
        raise HTTPException(status_code=409, detail=str(refusal)) from refusal
    return next(
        _vocabulary_out(status) for status in vocabulary_copy.statuses(db) if status.scheme.id == scheme
    )
