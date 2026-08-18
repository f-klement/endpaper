from pydantic import BaseModel, Field

from enums import Locale


class LoginImageOut(BaseModel):
    """Where the login background lives, as a path under the /covers mount."""

    url: str


class FeatureFlagsOut(BaseModel):
    """What the frontend needs in order to decide what to render.

    Readable by anyone, deliberately: the login page is localised, so the
    default language has to be known before a token exists. It carries no
    secrets and nothing about the catalogue.
    """

    google_books_enabled: bool
    # Whether the lookup will actually work: the toggle is on AND a key is
    # stored. `google_books_enabled` alone is not enough to decide what to
    # render, because a toggle with no key behind it produces a button that
    # can only ever 400. Not a secret: any member could learn the same thing
    # by pressing that button once.
    google_books_ready: bool = False
    goodreads_lookup_enabled: bool
    default_locale: Locale


class SettingsOut(BaseModel):
    """The admin view. The API key is masked, never returned in full."""

    google_books_enabled: bool
    # Masked: enough to see a key is present and tell one from another, and
    # nothing a browser could use. `has_google_books_api_key` is what the UI
    # keys off, because a masked string is not a truth value.
    google_books_api_key_preview: str
    has_google_books_api_key: bool
    # True when the deployment supplied the key through the environment. It then
    # wins over anything stored and cannot be changed here, so the UI disables
    # the field rather than offering an edit that would be refused. Reporting
    # *where* a secret comes from is not reporting the secret.
    google_books_api_key_from_env: bool = False
    goodreads_lookup_enabled: bool
    default_locale: Locale


class SettingsUpdate(BaseModel):
    """A partial update. Every field is optional; absent means "leave alone".

    That matters for the API key: a form that always submitted every field
    would blank the key whenever an admin toggled something else, since the
    browser never received the real value to send back.
    """

    google_books_enabled: bool | None = None
    # An empty string clears the key deliberately. `None` leaves it untouched.
    google_books_api_key: str | None = Field(default=None, max_length=200)
    goodreads_lookup_enabled: bool | None = None
    default_locale: Locale | None = None
