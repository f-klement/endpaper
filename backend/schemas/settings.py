from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from enums import Locale, OverdueNotifyReason, OverdueSender

#: How far apart two reminders for the same loan may be, in days. The floor is
#: 1 rather than 0: a zero would mean "resend on every tick", which is an hourly
#: repeat of the same list into the library's channel.
MIN_REMINDER_DAYS = 1
MAX_REMINDER_DAYS = 365

#: Long enough for a signed webhook URL with a token in its query string.
MAX_WEBHOOK_URL = 500
MAX_WEBHOOK_SECRET = 200

#: Bounds on the mail and Telegram fields.
#:
#: Every one of these is a settings row an admin types and a restore can write
#: through Core, so the bound is what stops a settings table row becoming a
#: multi-megabyte string the hourly ticker reads on every tick.
#:
#: `MAX_MAIL_RECIPIENT_LIST` bounds the **length of the field**, not how many
#: addresses are in it. `mailer.MAX_RECIPIENTS` is what caps the count, and the
#: two are separate because a 1000 character field of one very long address is a
#: different mistake from ten thousand short ones.
MAX_MAIL_HOST = 255
MAX_MAIL_ADDRESS = 320
MAX_MAIL_RECIPIENT_LIST = 1000
MAX_MAIL_PASSWORD = 200
MAX_MAIL_USERNAME = 320
#: A bot token is `<digits>:<35 characters>` today. 300 is room for Telegram
#: changing its mind without being room for anything else.
MAX_TELEGRAM_TOKEN = 300
MAX_TELEGRAM_CHAT = 64


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

    # ── Mail ─────────────────────────────────────────────────────────────
    #: Every one of these reports the value **in force**, the environment's
    #: where it supplied one, for the reason the Google key's preview does: a
    #: screen showing a value the next send will not use is worse than one
    #: showing nothing. `mail_from_env` names which fields that applies to, so
    #: the UI disables them rather than offering an edit the server would 409.
    #: Reporting *where* a value comes from is not reporting the value, which is
    #: why that list is safe to serve beside a masked secret.
    overdue_mail_enabled: bool = False
    overdue_mail_to: str = ""
    mail_server: str = ""
    mail_port: str = ""
    mail_username: str = ""
    #: Masked, like every other secret here. `has_mail_password` is what the UI
    #: keys off, because a masked string is not a truth value.
    mail_password_preview: str = ""
    has_mail_password: bool = False
    mail_use_tls: bool = False
    mail_use_ssl: bool = False
    mail_default_sender: str = ""
    #: Which of the seven mail settings this deployment pinned. A list rather
    #: than one flag per field: the fields are uniform, and seven booleans is
    #: seven chances for one to be forgotten when an eighth arrives.
    mail_from_env: list[str] = Field(default_factory=list)

    # ── Telegram ─────────────────────────────────────────────────────────
    #: No host field, and its absence is the control rather than an omission.
    #: See `notifications.TELEGRAM_API`.
    overdue_telegram_enabled: bool = False
    telegram_bot_token_preview: str = ""
    has_telegram_bot_token: bool = False
    telegram_bot_token_from_env: bool = False
    #: In full: it is a destination an admin typed and has to be able to
    #: proofread, the same asymmetry the webhook URL has against its secret.
    telegram_chat_id: str = ""
    telegram_chat_id_from_env: bool = False


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

    overdue_mail_enabled: bool | None = None
    overdue_mail_to: str | None = Field(default=None, max_length=MAX_MAIL_RECIPIENT_LIST)
    mail_server: str | None = Field(default=None, max_length=MAX_MAIL_HOST)
    #: A string, not an `int`, so an empty field clears it back to the default
    #: the way every other text setting here does. `mailer.checked_config`
    #: refuses anything that is not a port before a socket is opened.
    mail_port: str | None = Field(default=None, max_length=5)
    mail_username: str | None = Field(default=None, max_length=MAX_MAIL_USERNAME)
    #: Write only, like the webhook secret: the browser never received the
    #: stored value, so an absent field has to mean "leave alone" or every
    #: unrelated toggle would blank it.
    mail_password: str | None = Field(default=None, max_length=MAX_MAIL_PASSWORD)
    mail_use_tls: bool | None = None
    mail_use_ssl: bool | None = None
    mail_default_sender: str | None = Field(default=None, max_length=MAX_MAIL_ADDRESS)

    overdue_telegram_enabled: bool | None = None
    #: Write only. It is a credential, and Telegram puts it in the URL path.
    telegram_bot_token: str | None = Field(default=None, max_length=MAX_TELEGRAM_TOKEN)
    telegram_chat_id: str | None = Field(default=None, max_length=MAX_TELEGRAM_CHAT)

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


class SenderOutcome(BaseModel):
    """What one channel did with the digest.

    **The withheld count is here rather than only at the top, and that is the
    point of the shape.** All three senders withhold the same private books
    today, because all three go to a channel rather than to a person, so the
    three numbers agree. They are reported per sender anyway: the moment one
    sender's audience differs, a single figure would be a lie on the other two,
    and a reader has no way to tell a shared number from a coincidence.
    """

    sender: OverdueSender
    sent: bool = False
    loans: int = Field(default=0, ge=0)
    skipped_private: int = Field(default=0, ge=0)
    #: Null exactly when `sent` is true, as at the top level.
    reason: OverdueNotifyReason | None = None
    detail: str | None = None


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
    #: One entry per sender that was switched on, in sender order. Empty when
    #: nothing was attempted at all: everything off, or nothing overdue.
    #:
    #: **`sent` at the top level is true when any of these delivered**, because
    #: that is the condition `notified_at` is stamped on: the loan was chased.
    #: A sender that failed is reported here rather than compensated for, so a
    #: broken receiver is visible on the screen that configures it instead of
    #: turning the working channels into an hourly repeat.
    senders: list[SenderOutcome] = Field(default_factory=list)


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
    #: The author merge decisions. The clearest case this field exists for: a
    #: merge writes nothing to `books`, so an archive without these rows
    #: restored a library where every merged author had split back into its
    #: spellings while every book looked perfectly intact. The table was
    #: missing from `backup._TABLES` entirely until 2026-08-26 and no count
    #: reported its absence.
    author_aliases: int = Field(default=0, ge=0)
