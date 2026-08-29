"""Runtime configuration, resolved from the environment.

Every setting is read through a function rather than a module-level constant so
that tests can monkeypatch the environment and see the change, and so that a
change like closing registration takes effect without a restart. The exception
is DATA_DIR, which is resolved once at import because the directory has to
exist before the app starts serving from it.
"""

import os
from pathlib import Path
from typing import Final

from enums import AppEnv, AuthMode, SettingKey

# Where the SQLite database and uploaded images live. In the container this is
# the bind-mounted volume at /app/data; locally it defaults to ./data so the
# backend can be run and tested without a container.
DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data" if Path("/app").is_dir() else "./data")).resolve()

COVERS_DIR = DATA_DIR / "covers"

# Image formats accepted for book covers and the login background. SVG is
# deliberately absent: these files are served back from the app's own origin,
# and an SVG can carry script, which would make it a stored-XSS vector.
ALLOWED_IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp"})

# Uploads are read fully into memory before being written, so this cap is also
# what stops a large request exhausting the container's memory.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

# The placeholder shipped in .env.example and docker-compose.yml. Booting with
# it in production means every session token is forgeable by anyone who has
# read the repository.
_PLACEHOLDER_SECRETS = frozenset(
    {
        "dev-secret-change-in-production",
        "change-this-in-production",
        "replace-with-at-least-32-random-characters",
        "REPLACE_WITH_A_LONG_RANDOM_STRING",
    }
)

# HS256 keys shorter than the hash output add no security beyond their length.
MIN_SECRET_KEY_LENGTH = 32


def app_env() -> AppEnv:
    """Deployment posture. Anything that is not exactly "dev" is treated as
    production, so a typo fails safe rather than silently relaxing the checks."""
    return AppEnv.DEV if os.getenv("APP_ENV", "").strip().lower() == "dev" else AppEnv.PROD


def database_url() -> str:
    """SQLAlchemy URL. Defaults to a SQLite file inside DATA_DIR."""
    return os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'library.db'}")


def secret_key() -> str:
    """HMAC key for signing JWTs."""
    return os.getenv("SECRET_KEY", "dev-secret-change-in-production")


def registration_enabled() -> bool:
    """Whether /auth/register accepts new signups."""
    return os.getenv("ALLOW_REGISTRATION", "true").strip().lower() != "false"


def overdue_ticker_enabled() -> bool:
    """Whether the in-process hourly overdue digest runs.

    On by default, because the feature is worthless if it only fires when
    somebody presses a button. Set `ENABLE_OVERDUE_TICKER=false` to run it from
    an external cron against `POST /api/loans/overdue/notify` instead, which is
    also what a deployment with more than one web process has to do: the ticker
    assumes exactly one, and the Dockerfile's single uvicorn is what makes that
    true. See `notifications.ticker`.

    The test suite sets it false. A background task that wakes on a timer in a
    suite that manipulates the clock is a source of failures that depend on how
    long the run took.
    """
    return os.getenv("ENABLE_OVERDUE_TICKER", "true").strip().lower() != "false"


def serve_frontend() -> bool:
    """Whether the compiled SPA is mounted at `/`.

    On by default, because an ordinary deployment is one container serving the
    API and the bundle from one origin. `SERVE_FRONTEND=false` is for a host
    with no reader: a relay stores sealed envelopes and has no members, no
    library and nobody to show a page to, so the shell, the asset routes, the
    SPA fallback and the cache policy that goes with them are attack surface
    with no user.

    With it false an unmatched path is a plain 404 rather than the shell. That
    is correct, not a regression: the fallback exists so a client route
    survives a refresh, and a headless instance has no client routes.

    One image, one flag. The frontend files stay on disk unused.
    """
    return os.getenv("SERVE_FRONTEND", "true").strip().lower() != "false"


def cors_origins() -> list[str]:
    """Browser origins allowed to make credentialed calls.

    Empty by default, which is correct for the normal deployment: FastAPI
    serves the API and the compiled frontend from the same origin, so no
    cross-origin request happens at all. Set CORS_ORIGINS (comma-separated)
    only when the frontend is genuinely served from somewhere else.
    """
    raw = os.getenv("CORS_ORIGINS", "").strip()
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def validate_secret_key() -> None:
    """Fail startup rather than run production with a guessable signing key.

    Called from init_db(). Raising here stops the container, which is loud and
    fixable; the alternative is an app that looks healthy while every token it
    issues can be forged.
    """
    if app_env() is AppEnv.DEV:
        return

    key = secret_key()
    if key in _PLACEHOLDER_SECRETS:
        raise RuntimeError(
            "SECRET_KEY is still the example placeholder. Generate one with "
            "`python -c 'import secrets; print(secrets.token_urlsafe(48))'` and set it, "
            "or set APP_ENV=dev for local work."
        )
    if len(key.encode("utf-8")) < MIN_SECRET_KEY_LENGTH:
        raise RuntimeError(
            f"SECRET_KEY must be at least {MIN_SECRET_KEY_LENGTH} bytes; "
            f"got {len(key.encode('utf-8'))}. Set APP_ENV=dev for local work."
        )


# ── Authentication ────────────────────────────────────────────────────────────


def auth_mode() -> AuthMode:
    """Which backend authenticates members.

    An unrecognised value is a configuration mistake, and falling back to
    `local` would quietly hand out local signups on a deployment meant to be
    directory-only. So it fails loudly instead.
    """
    raw = os.getenv("AUTH_MODE", AuthMode.LOCAL.value).strip().lower()
    try:
        return AuthMode(raw)
    except ValueError:
        raise RuntimeError(
            f"AUTH_MODE={raw!r} is not one of: "
            f"{', '.join(mode.value for mode in AuthMode)}"
        ) from None


def ldap_url() -> str:
    return os.getenv("LDAP_URL", "").strip()


def ldap_bind_dn() -> str:
    """Service account used to search the directory. Empty means anonymous."""
    return os.getenv("LDAP_BIND_DN", "").strip()


def ldap_bind_password() -> str:
    return os.getenv("LDAP_BIND_PASSWORD", "")


def ldap_user_base_dn() -> str:
    return os.getenv("LDAP_USER_BASE_DN", "").strip()


def ldap_user_filter() -> str:
    """Search filter for one member. `{username}` is substituted.

    The default matches the common case. Note the app escapes the username
    before substitution, so a filter is not an injection point.
    """
    return os.getenv("LDAP_USER_FILTER", "(&(objectClass=person)(uid={username}))").strip()


def ldap_username_attribute() -> str:
    return os.getenv("LDAP_USERNAME_ATTRIBUTE", "uid").strip()


def ldap_admin_group() -> str:
    """DN or name of the group whose members are admins here. Empty disables."""
    return os.getenv("LDAP_ADMIN_GROUP", "").strip()


def ldap_email_attribute() -> str:
    """Attribute carrying a member's address. Empty means the directory has none.

    **Empty by default, and the default is the load-bearing part.** It is the
    same shape as `LDAP_ADMIN_GROUP`: unset, the directory has no opinion about
    addresses, so the app does not ask for one, does not overwrite one and lets
    the member keep their own. Set (`mail` in most directories), the directory
    owns the value and re-applies it on every sign in, which is the rule
    `upsert_directory_user` already runs for admin status.

    Defaulting this to `mail` instead would add an attribute to every search
    this app makes and silently start overwriting locally typed addresses on an
    upgrade nobody configured.
    """
    return os.getenv("LDAP_EMAIL_ATTRIBUTE", "").strip()


def ldap_start_tls() -> bool:
    return os.getenv("LDAP_START_TLS", "false").strip().lower() == "true"


def proxy_user_header() -> str:
    """Header naming the authenticated member. Authelia sends Remote-User."""
    return os.getenv("PROXY_USER_HEADER", "Remote-User").strip()


def proxy_groups_header() -> str:
    return os.getenv("PROXY_GROUPS_HEADER", "Remote-Groups").strip()


def proxy_admin_group() -> str:
    """Group that grants admin. Empty means nobody is admin via the proxy."""
    return os.getenv("PROXY_ADMIN_GROUP", "").strip()


def proxy_email_header() -> str:
    """Header asserting the member's address. Empty means the upstream sends none.

    Empty by default for the reason `ldap_email_attribute` carries in full: an
    upstream that does not send this must not be read as saying a member has no
    address. Authelia's spelling is `Remote-Email`, which is what to set it to.

    Unlike `PROXY_USER_HEADER` this is not validated at startup, because an
    absent address is a supported state and an empty header is how you say so.
    """
    return os.getenv("PROXY_EMAIL_HEADER", "").strip()


def validate_auth_config() -> None:
    """Fail startup on an auth mode that cannot possibly work.

    Same reasoning as the secret key: an app that starts and then rejects every
    login is worse than one that refuses to start and says why.
    """
    mode = auth_mode()

    if mode is AuthMode.LDAP:
        missing = [
            name
            for name, value in (
                ("LDAP_URL", ldap_url()),
                ("LDAP_USER_BASE_DN", ldap_user_base_dn()),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                f"AUTH_MODE=ldap requires {' and '.join(missing)} to be set."
            )

        # A bind DN with no password is an "unauthenticated bind", which the
        # directory treats as anonymous. It would appear to work while quietly
        # searching with anonymous rights, so it fails startup instead.
        if ldap_bind_dn() and not ldap_bind_password().strip():
            raise RuntimeError(
                "LDAP_BIND_DN is set but LDAP_BIND_PASSWORD is empty. The directory "
                "would treat that as an anonymous bind. Set the password, or clear "
                "LDAP_BIND_DN to search anonymously on purpose."
            )

    if mode is AuthMode.PROXY and not proxy_user_header():
        raise RuntimeError("AUTH_MODE=proxy requires PROXY_USER_HEADER to name a header.")


def ensure_data_dirs() -> None:
    """Create the data directories. Called once on app startup."""
    COVERS_DIR.mkdir(parents=True, exist_ok=True)


# ── Settings a deployment may supply instead of the admin ─────────────────────

#: The runtime settings an operator may pin from the environment, and the
#: variable that pins each.
#:
#: **The seven `MAIL_*` names are the standard ones on purpose**, matching what
#: a household `.env` and the deployment's other services already carry, so the
#: operator sets one fact once rather than learning a second spelling for it.
#: The eighth standard name, `MAIL_DEBUG`, is deliberately not here: smtplib's
#: debug output writes the AUTH exchange to stderr, so honouring it would be a
#: supported way of printing the mail password into the container log.
#:
#: **A table rather than a function per key**, so the precedence rule below has
#: one definition and adding a sender's credential is one line rather than a
#: place to forget.
_ENV_OVERRIDES: Final[dict[SettingKey, str]] = {
    SettingKey.GOOGLE_BOOKS_API_KEY: "GOOGLE_BOOKS_API_KEY",
    SettingKey.MAIL_SERVER: "MAIL_SERVER",
    SettingKey.MAIL_PORT: "MAIL_PORT",
    SettingKey.MAIL_USERNAME: "MAIL_USERNAME",
    SettingKey.MAIL_PASSWORD: "MAIL_PASSWORD",
    SettingKey.MAIL_USE_TLS: "MAIL_USE_TLS",
    SettingKey.MAIL_USE_SSL: "MAIL_USE_SSL",
    SettingKey.MAIL_DEFAULT_SENDER: "MAIL_DEFAULT_SENDER",
    SettingKey.TELEGRAM_BOT_TOKEN: "TELEGRAM_BOT_TOKEN",
    SettingKey.TELEGRAM_CHAT_ID: "TELEGRAM_CHAT_ID",
}


def env_override(key: SettingKey) -> str:
    """What the deployment supplied for this setting, or empty.

    **Empty means "the environment said nothing", and that is why every one of
    these is a string rather than its parsed type.** `MAIL_USE_TLS=false` has to
    beat a stored `true`, and a `bool` return cannot tell that apart from a
    variable nobody set. The string is parsed by `settings_store`, which parses
    the stored value the same way, so the two sources cannot disagree about what
    "on" means.

    When set, the value **wins over the stored one and cannot be changed through
    the app**. That is the point of supplying it this way: a value injected from
    a secret manager or a compose file is managed outside the application, and an
    admin editing it in a settings form would produce a setting that silently
    disagrees with the deployment on the next restart.

    A secret supplied here is never revealed through the API either, for the same
    reason a stored one is not: the app can use a secret without being able to
    show it.
    """
    name = _ENV_OVERRIDES.get(key)
    return os.getenv(name, "").strip() if name else ""


def env_variable_name(key: SettingKey) -> str:
    """Which environment variable pins this setting, for a message that says so.

    A refusal that names the variable is one an operator can act on; "supplied
    by the environment" alone sends them looking through a compose file.
    """
    return _ENV_OVERRIDES.get(key, "")


def google_books_api_key_from_env() -> str:
    """A Google Books key supplied by the deployment, or empty.

    Named rather than left to `env_override` because it predates the table and
    has callers of its own. One definition, in the table.
    """
    return env_override(SettingKey.GOOGLE_BOOKS_API_KEY)
