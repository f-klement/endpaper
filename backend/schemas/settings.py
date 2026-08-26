from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from enums import Locale, OverdueNotifyReason

#: How far apart two reminders for the same loan may be, in days. The floor is
#: 1 rather than 0: a zero would mean "resend on every tick", which is an hourly
#: repeat of the same list into the library's channel.
MIN_REMINDER_DAYS = 1
MAX_REMINDER_DAYS = 365

#: Long enough for a signed webhook URL with a token in its query string.
MAX_WEBHOOK_URL = 500
MAX_WEBHOOK_SECRET = 200


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

    # ── Overdue reminders ────────────────────────────────────────────────
    overdue_webhook_enabled: bool = False
    #: Returned in full, unlike the secret beside it. It is a destination the
    #: admin typed and has to be able to check; a masked URL cannot be
    #: proofread, and the whole point of the field is spotting a wrong one.
    #: An admin who can read this is an admin who can change it.
    overdue_webhook_url: str = ""
    #: Masked, like the Google key, for the same reason: the browser has no use
    #: for the signing secret and every reason not to hold it.
    overdue_webhook_secret_preview: str = ""
    has_overdue_webhook_secret: bool = False
    overdue_reminder_days: int = Field(
        default=7, ge=MIN_REMINDER_DAYS, le=MAX_REMINDER_DAYS
    )


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

    overdue_webhook_enabled: bool | None = None
    #: An empty string clears the destination. `None` leaves it untouched.
    overdue_webhook_url: str | None = Field(default=None, max_length=MAX_WEBHOOK_URL)
    #: Write only, like the Google key: the browser never received the stored
    #: value, so an absent field has to mean "leave alone" or every unrelated
    #: toggle would blank the secret.
    overdue_webhook_secret: str | None = Field(
        default=None, max_length=MAX_WEBHOOK_SECRET
    )
    overdue_reminder_days: int | None = Field(
        default=None, ge=MIN_REMINDER_DAYS, le=MAX_REMINDER_DAYS
    )

    @field_validator("overdue_webhook_url")
    @classmethod
    def http_or_https(cls, value: str | None) -> str | None:
        """Refuse a destination that is not an http(s) URL.

        Checked here **and** again in `notifications.py` before the request is
        made. Two checks rather than one because they answer different
        questions: this one refuses the save with a 422 naming the field, and
        the other one refuses to send at all, which covers a row written by a
        restore or edited by hand. A `file:` or `gopher:` destination is not a
        typo worth guessing at.

        This does **not** try to keep an admin off the cluster's own network.
        See `docs/security.md`: the URL is admin-set, and a blocklist of
        private ranges is a thing that looks like a control and is not one.
        """
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            return ""
        parsed = urlparse(trimmed)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("The webhook URL must start with http:// or https://")
        return trimmed


class OverdueNotifyResult(BaseModel):
    """What one run of the overdue digest did.

    Reported rather than logged, because "send now" exists so a person can see
    the thing work. `skipped_private` is here for the same reason the exclusion
    exists: a library that expects five entries and gets four should be able
    to see why without reading the source.
    """

    #: True when a request was actually made and the receiver accepted it.
    sent: bool = False
    #: Loans in the digest that was sent, or that would have been.
    loans: int = Field(default=0, ge=0)
    #: Overdue loans left out because the book is private. See decisions.md.
    skipped_private: int = Field(default=0, ge=0)
    #: Which of the four ways nothing was sent. **Null exactly when `sent` is
    #: true**, and set in every other case: `_outcome` in `notifications.py` is
    #: the only thing that builds a not-sent result, so a new exit cannot omit
    #: it.
    #:
    #: A closed set rather than only the sentence below, because the client has
    #: to render the difference and cannot branch on prose. Without it a refused
    #: webhook and a quiet week were the same line on the screen.
    reason: OverdueNotifyReason | None = None
    #: The same outcome as a sentence, for a log or for an API caller with no
    #: message catalogue. Null on a successful send.
    detail: str | None = None


class RestoreResult(BaseModel):
    """What a restore actually put back.

    Counted per table rather than reported as "done", so a backup that was
    missing its covers or its loans says so instead of looking successful.

    The list is the tables whose absence a library would notice: their books,
    their accounts, what they wrote, who has what, and what they have read. It
    is not every table, and the two it leaves out are the two nobody counts:
    `tags` and `book_tags` come back with the books, and `settings` is one row
    per toggle. A table added to `backup._TABLES` belongs here if losing it
    silently would look like a successful restore.
    """

    books: int = Field(ge=0)
    users: int = Field(ge=0)
    notes: int = Field(ge=0)
    loans: int = Field(ge=0)
    covers: int = Field(ge=0)
    #: Every member's reading status, rating and reading dates. Absent from
    #: this report until reading progress was added, so a restore that dropped
    #: the library's entire reading history read as a clean one.
    user_books: int = Field(default=0, ge=0)
    reading_progress: int = Field(default=0, ge=0)
    #: The library's shelf labels. Here for the reason above: losing them
    #: silently restores every book unfiled, which reads as a clean restore
    #: until somebody opens the library and finds their shelves gone.
    collections: int = Field(default=0, ge=0)
    #: Passages members typed out by hand. They exist nowhere else: a book can
    #: be rescanned and a cover refetched, and a quote cannot, so a restore
    #: that silently dropped them is the worst case this field guards against.
    quotes: int = Field(default=0, ge=0)
