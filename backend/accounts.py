"""The account lifecycle: proving an address, and getting back in.

Two flows that look different from the outside and are one mechanism inside. A
member proves an address by returning a code sent to it; a member who has lost a
password gets back in by returning a code an admin read out to them. Both codes
are made here, hashed here and checked here, so there is one answer to how long
a code lives, how it is compared, and what happens when it is used.

**A code, never a link, and that is a security decision rather than a taste.** A
mailed link needs a base URL, and the only source for one on a request is the
`Host` header, which the client sets: an app that builds a link from it mails an
attacker's host to a member's mailbox. The alternatives are a setting nobody
would fill in on a household install or a link that goes to the wrong place, and
a code the member pastes needs neither. It also makes the two flows the same
shape, which is what lets the admin confirmed reset exist at all: there is no
mailbox to send anything to, so the admin reads the code out.

**What makes an admin confirmed reset a recovery flow and not a back door.**
`request_password_reset` is the only function that constructs a row, and it is
reached from one unauthenticated route, so no authenticated path creates one and
an admin approves rather than initiates. **The one exception is `backup.restore`,
which writes these rows generically from an archive**, and it is named here
rather than left for somebody to find: it widens nothing, because a restore
replaces every password hash in the library in the same transaction, so whoever
can hand one to that route already holds every account.

The residual is stated rather than hidden, here and in `docs/decisions.md`: the
request route takes a username, so an admin can post a member's name and then
approve it. Nothing in a mechanism can prevent that, because the request
deliberately requires nothing only the member has. What is prevented is doing it
quietly:

* redeeming ends every session on the account, so the member is signed out and
  their password no longer works, which is the same evening rather than the next
  time they happen to sign in;
* the request row is kept, carrying who approved it and when, and the member
  reads it back from `GET /api/users/me/security`.

**Neither flow means anything where a directory holds the credential.**
`models.app_holds_the_password` is the one predicate, and it is written as an
exclusion so an unrecognised `auth_source` fails closed.
"""

import logging
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

import mailer
import settings_store
from auth import hash_password, verify_password
from config import auth_mode
from enums import AuthMode, VerificationProvenance
from models import PasswordResetRequest, User, app_holds_the_password

logger = logging.getLogger("endpaper.auth")

#: The characters a code is drawn from.
#:
#: Base32's alphabet without `I`, `O`, `0` and `1`. A reset code is read down a
#: telephone or across a kitchen table, which is the delivery channel this whole
#: feature exists for, and those four are the pairs a listener gets wrong.
#:
#: **No lookalike folding on the way back in**, deliberately: mapping `O` to `0`
#: on a set that contains neither would be a rule with nothing to do, and one
#: that mapped onto a member of the set would let two spellings redeem one code.
#: `normalise_code` removes spacing and case and nothing else.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

#: How many characters a code carries.
#:
#: Twelve from a 32 character alphabet is 60 bits, against ten guesses an hour
#: from `ratelimit.RECOVERY_CODE_LIMIT`. Short enough to say out loud, and the
#: bound that matters is the limiter rather than the keyspace.
CODE_LENGTH = 12

#: How the code is shown to whoever has to read it out.
CODE_GROUP = 4

#: How long an unapproved request occupies the admin's queue.
#:
#: Long, because a request is not a credential: making one grants nothing and
#: asks a person to act. The cost of it being too short is a member who has to
#: ask twice, and the cost of it being too long is one row per account, which is
#: what the live unique index already bounds.
RESET_REQUEST_TTL = timedelta(days=7)

#: How long an approved code works for.
#:
#: Short, because this one **is** a credential and the admin approves at the
#: moment they are about to hand it over: the channel is the next room or a
#: telephone call, not a mailbox somebody checks tomorrow.
RESET_CODE_TTL = timedelta(hours=1)

#: How long a verification code works for.
#:
#: A day rather than an hour, because this one does travel through a mailbox and
#: a household reads mail once a day. Longer than the reset code by the
#: difference between the two delivery channels rather than by their importance.
VERIFICATION_CODE_TTL = timedelta(hours=24)


def now() -> datetime:
    """Naive UTC, which is what every `DateTime` column in this app stores."""
    return datetime.now(UTC).replace(tzinfo=None)


def generate_code() -> str:
    """A fresh one time code, grouped for reading aloud.

    `secrets.choice`, never `random`: this is a credential for the hour it
    lives.
    """
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    return "-".join(
        raw[index : index + CODE_GROUP] for index in range(0, CODE_LENGTH, CODE_GROUP)
    )


def normalise_code(raw: str) -> str:
    """What the member typed, reduced to what was generated.

    Case and the grouping separators only. Somebody reading a code back adds
    spaces, drops the hyphens, or types it lower case, and none of those is a
    different code. Anything else is left alone so that a wrong character stays
    a wrong code.

    **`isascii()` beside `isalnum()`, at the same receiver.** `CODE_ALPHABET` is
    ASCII, so a Cyrillic or fullwidth letter is never part of a code; without the
    narrowing it would survive normalisation and travel into the comparison,
    which is the defect `isbn.normalise` already carries a test for.
    """
    return "".join(
        character for character in raw if character.isascii() and character.isalnum()
    ).upper()


def _code_matches(supplied: str, stored: str | None) -> bool:
    """Compare a typed code against a stored hash, in the ungrouped spelling."""
    if not stored:
        return False
    return verify_password(normalise_code(supplied), stored)


def _hash_code(code: str) -> str:
    """Store the ungrouped spelling, so the grouping is presentation only."""
    return hash_password(normalise_code(code))


# ── Verification ──────────────────────────────────────────────────────────────


def verification_is_required(db: Session, user: User) -> bool:
    """Whether this account has to prove its address before it may do anything.

    Two conditions, and neither is derived from the other. The deployment has to
    have said its accounts are held by people outside the household, and this app
    has to be the one holding the account's credential.
    """
    return app_holds_the_password(user) and settings_store.accounts_are_open_to_outsiders(
        db
    )


def verification_blocks(db: Session, user: User) -> bool:
    """Whether this account is refused right now for want of verification.

    **The single rule, asked at both doors that can produce a session**: the
    sign in route, where it becomes a 403 that says why, and `_user_from_token`,
    where it becomes an ordinary 401. Two call sites and one rule, which is not
    the third account state the owner refused: nothing downstream of a session
    asks this question, because an account it refuses never holds one.

    The setting is read only for an account that is actually unverified, so the
    ordinary request pays no extra row read.
    """
    if user.email_verified_at is not None:
        return False
    return verification_is_required(db, user)


def record_verification(
    user: User,
    source: VerificationProvenance,
    *,
    by: User | None = None,
) -> None:
    """Settle this account's verification, and say who settled it.

    **The one writer of the three columns**, which is what keeps
    `email_verified_by_user_id` set on an `ADMIN` assertion and null on every
    other. There is no check constraint pairing them: adding one to `users`
    forces a batch rewrite of a table that now carries a self referential
    foreign key. `models.User.email_verification_source` says so at the columns
    and `tests/test_accounts.py::TestOnlyAnAdminAssertionNamesAnAdmin` is the
    enforcement.

    Clears any live code, because a settled account has nothing left to prove
    and a code that outlives its purpose is a credential nobody is watching.
    """
    if (source is VerificationProvenance.ADMIN) != (by is not None):
        raise ValueError(
            "An admin assertion names the admin, and no other assertion names "
            f"anybody: {source.value} with by={by!r}"
        )
    user.email_verified_at = now()
    user.email_verification_source = source.value
    user.email_verified_by_user_id = by.id if by is not None else None
    user.verification_code_hash = None
    user.verification_code_expires_at = None


def start_verification(db: Session, user: User) -> str:
    """Mint a fresh verification code for this account and return the plaintext.

    Replaces whatever was outstanding rather than adding to it, so "send it
    again" means send it again. The plaintext is returned once and never stored.
    """
    code = generate_code()
    user.verification_code_hash = _hash_code(code)
    user.verification_code_expires_at = now() + VERIFICATION_CODE_TTL
    db.commit()
    return code


def redeem_verification(db: Session, username: str, code: str) -> bool:
    """Mark an account verified if it was that account's live code.

    False for every failure, with no distinction between them: whether the
    account exists, whether it was awaiting anything, whether the code was wrong
    and whether it had expired are four answers the caller must not be able to
    tell apart. The caller holds no session, so an endpoint that separated them
    would be a roster oracle.
    """
    user = db.query(User).filter(User.username == username).first()
    if user is None or not app_holds_the_password(user):
        spend_a_comparison(code)
        return False
    expires = user.verification_code_expires_at
    if expires is None or expires <= now():
        spend_a_comparison(code)
        return False
    if not _code_matches(code, user.verification_code_hash):
        return False
    record_verification(user, VerificationProvenance.EMAIL)
    db.commit()
    logger.info("Account %r verified its address", user.username)
    return True


def override_verification(db: Session, user: User, admin: User) -> None:
    """An admin asserting that this account belongs to who it says.

    Loud, because it is the one way past a policy the deployment turned on, and
    because it is what makes "an unverified account may do nothing" survivable
    on an install with no mail server. See `docs/decisions.md`.
    """
    record_verification(user, VerificationProvenance.ADMIN, by=admin)
    db.commit()
    logger.warning(
        "Admin %r marked the account %r verified", admin.username, user.username
    )


def verification_mail(
    db: Session, user: User, code: str
) -> tuple[mailer.MailConfig, str, str] | None:
    """The message that carries a verification code, or None if it cannot be sent.

    None for both reasons it might not go: no address on the account, and no
    mail server configured. Neither is an error the member should be told about
    in a way that distinguishes them, and neither stops the account existing:
    the admin override is the path for an install with no mailbox, which is the
    ordinary one here.

    **This is the only place outside `routers/users.py` and `auth_backends.py`
    that reads a member's address**, and `tests/test_house_rules.py` names it.
    Issue #80 kept the mailer off `users.email` because a reminder goes to the
    household; a verification code goes to the person being verified, and there
    is no other address it could go to.

    Returns the parts rather than sending, so the caller can hand them to a
    background task: SMTP is blocking, and a member registering must not wait on
    somebody else's mail server.
    """
    address = user.email
    if not address:
        return None
    try:
        config = mailer.checked_config(db, recipients=(address,))
    except mailer.MailRefused as refusal:
        logger.info("No verification mail for %r: %s", user.username, refusal)
        return None
    body = (
        "Someone asked to confirm this address for the account "
        f"{user.username}.\n\n"
        f"Your confirmation code is: {code}\n\n"
        "Enter it on the sign in screen. It stops working in "
        f"{int(VERIFICATION_CODE_TTL.total_seconds() // 3600)} hours.\n\n"
        "If this was not you, nothing has happened and you can ignore this."
    )
    return config, "Confirm your address", body


# ── Password reset ────────────────────────────────────────────────────────────


def live_request(db: Session, user_id: int) -> PasswordResetRequest | None:
    """This account's request that has not been redeemed, if it has one."""
    return db.scalars(
        select(PasswordResetRequest).where(
            PasswordResetRequest.user_id == user_id,
            PasswordResetRequest.completed_at.is_(None),
        )
    ).first()


def request_password_reset(db: Session, username: str) -> None:
    """Record that whoever holds this account is asking to be let back in.

    **The only function that constructs a `PasswordResetRequest`**, and the
    property the design rests on. It is called from one unauthenticated route,
    so there is no authenticated path by which an admin starts a reset on
    somebody else's account: an admin approves a request and never makes one.
    `backup.restore` writes these rows generically from an archive and is the
    stated exception; see this module's docstring for why it widens nothing.

    Answers nothing. The caller returns the same response whatever happened
    here, because the route is reachable without a session and one that said "no
    such member" would be a roster for anybody who wanted the household's.

    A live request that has expired is replaced rather than blocking a new one,
    which is what keeps the queue bounded without a sweeper: at most one row per
    account is ever pending, and an abandoned one costs its account one retry.
    An approved request whose code has not expired is left alone, so asking again
    cannot cancel a code the admin has already read out.

    **This one is not equalised the way the confirmation resend is**, and the
    shape is stated rather than measured: a name nobody holds costs one SELECT,
    and a local account costs two plus an insert and a commit. Neither branch
    performs a bcrypt, so the difference is one SQLite commit rather than the cost
    of a hash, which `spend_a_comparison` measures and this deliberately does not
    restate. It falls to zero on every later request inside the request's
    lifetime, since a live row makes the real branch return early too.
    Not measured, because a duration taken on a development checkout's storage
    says nothing about the deployment's.
    """
    user = db.query(User).filter(User.username == username).first()
    if user is None or not app_holds_the_password(user):
        return
    existing = live_request(db, user.id)
    if existing is not None:
        if not _request_has_lapsed(existing):
            return
        db.delete(existing)
        db.flush()
    db.add(
        PasswordResetRequest(
            user_id=user.id,
            requested_at=now(),
            expires_at=now() + RESET_REQUEST_TTL,
        )
    )
    db.commit()
    # WARNING, and it names the account. A reset request is the first step of the
    # one flow in this app that puts a member's library in somebody else's hands,
    # and `auth_backends` sets the precedent: the consequential things are logged
    # loudly, because the record of the last incident was an INFO line nobody read.
    logger.warning("The account %r asked for a password reset", user.username)


def _request_has_lapsed(request: PasswordResetRequest) -> bool:
    """Whether this request no longer holds anything worth keeping.

    An unapproved request lapses at `expires_at`. An approved one lapses when its
    code does, and not before: the admin has already read that code out, and
    replacing the row underneath them would answer a member's second click by
    silently invalidating what they were just told.
    """
    if request.code_expires_at is not None:
        return request.code_expires_at <= now()
    return request.expires_at <= now()


def approve_reset(db: Session, request: PasswordResetRequest, admin: User) -> str:
    """Grant a request and return the one time code, once.

    The plaintext exists in this return value and nowhere else: what is stored
    is a bcrypt hash, and no schema in the application carries a code except the
    one this is returned in.

    Re-approving a request that already carries a live code mints a new one,
    which is the honest behaviour for a screen that shows a code once: an admin
    who lost the paper has not gained anything they did not already have, and the
    previous code stops working.
    """
    code = generate_code()
    request.code_hash = _hash_code(code)
    request.code_expires_at = now() + RESET_CODE_TTL
    request.approved_by_user_id = admin.id
    request.approved_at = now()
    db.commit()
    logger.warning(
        "Admin %r approved a password reset for user id %d",
        admin.username,
        request.user_id,
    )
    return code


def dismiss_reset(db: Session, request: PasswordResetRequest, admin: User) -> None:
    """Decline a request.

    Deleted rather than marked, because a declined request is not an assertion
    about anybody and there is nothing for the member to read back. The log line
    is the record of it.
    """
    db.delete(request)
    db.commit()
    logger.warning(
        "Admin %r declined a password reset for user id %d",
        admin.username,
        request.user_id,
    )


def redeem_reset(db: Session, username: str, code: str, new_password: str) -> bool:
    """Set a new password if the code was this account's live approved one.

    False for every failure and for the same reason `redeem_verification`
    answers that way: this route is reachable without a session.

    Three writes, and all three are the point:

    * the password becomes the one the member just chose;
    * `sessions_valid_from` moves to now, so **every** token on the account stops
      working, including one an admin minted for themselves after resetting it,
      and including the member's own, which is what makes the reset impossible to
      miss;
    * the request is marked complete rather than deleted, so the account keeps
      the record of when it happened and which admin approved it.

    No token is issued. The code is not a session and never becomes one: the
    member signs in with the password they just set, which is also the check that
    it works.
    """
    user = db.query(User).filter(User.username == username).first()
    if user is None or not app_holds_the_password(user):
        spend_a_comparison(code)
        return False
    request = live_request(db, user.id)
    if request is None or request.approved_at is None:
        spend_a_comparison(code)
        return False
    if request.code_expires_at is None or request.code_expires_at <= now():
        spend_a_comparison(code)
        return False
    if not _code_matches(code, request.code_hash):
        return False

    user.password_hash = hash_password(new_password)
    user.sessions_valid_from = now()
    request.completed_at = now()
    # A single use code, gone the moment it is spent: without this the row still
    # carries a working hash until its hour is up.
    request.code_hash = None
    db.commit()
    logger.warning(
        "The account %r completed a password reset approved by user id %s",
        user.username,
        request.approved_by_user_id,
    )
    return True


def last_completed_reset(db: Session, user_id: int) -> PasswordResetRequest | None:
    """The most recent reset this account actually went through.

    What `GET /api/users/me/security` serves, and the reason completed rows are
    kept: a reset that left no mark on the account would be indistinguishable
    from a quiet takeover, which is the property the whole flow exists to keep.
    """
    return db.scalars(
        select(PasswordResetRequest)
        .where(
            PasswordResetRequest.user_id == user_id,
            PasswordResetRequest.completed_at.is_not(None),
        )
        .order_by(PasswordResetRequest.completed_at.desc())
    ).first()


def pending_requests(db: Session) -> list[PasswordResetRequest]:
    """Every request an admin has not finished with, oldest first.

    Expired rows are filtered here rather than swept, so the queue an admin reads
    holds only what they can still act on and no background task has to exist.
    The row itself is left for `request_password_reset` to replace.
    """
    rows = db.scalars(
        select(PasswordResetRequest)
        .where(PasswordResetRequest.completed_at.is_(None))
        .order_by(PasswordResetRequest.requested_at)
    ).all()
    return [row for row in rows if not _request_has_lapsed(row)]


# ── Not telling an anonymous caller which failure it was ──────────────────────


def spend_a_comparison(code: str) -> None:
    """Do the work a successful lookup would have done, and discard it.

    bcrypt is slow on purpose, so a route that skips it when the account does not
    exist answers a missing username in a millisecond and a real one in a
    hundred. That difference is readable over a network and it is exactly the
    roster the identical response body exists to withhold.

    The dummy hash is built once per process, on first use rather than at import:
    one bcrypt at startup is a cost every deployment pays for a path most never
    take.

    **Public, because a route needs it too.** `POST /auth/verify/request` mints a
    code for an account that is waiting and does nothing for a name nobody holds,
    and minting one is a bcrypt.

    **The one place the figure is written down.** Measured on a worker node:
    333.3 ms median over seven hashes at this work factor, against 0.0033 ms
    median over 200 indexed SELECTs, which is five orders of magnitude. **The
    absolute numbers are one machine's and move with its CPU; the ratio is what
    the rule rests on, and that does not, because both scale together.** So this
    is a floor on the difference rather than an estimate of it, and it is
    readable over a network on any machine that runs this app. Which node is in
    the wave's notes, which do not ship.

    **What the guard on this does not watch**, recorded by the security seat
    rather than fixed: `TestNeitherBranchOfAResendIsFree` compares call counts
    and the property is cost. It holds only because the dummy hash is built
    through `hash_password` and so inherits `gensalt()`'s work factor. Hardcoding
    a cheaper precomputed dummy would keep the counts equal and restore the
    difference. An assertion on wall time would be a flake, so this is a note for
    whoever changes `_dummy_hash` rather than a second guard.
    """
    verify_password(normalise_code(code), _dummy_hash())


_DUMMY_HASH: str | None = None


def _dummy_hash() -> str:
    """A hash of something nobody knows, for comparisons that must not succeed."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(secrets.token_hex(16))
    return _DUMMY_HASH


def sign_in_refusal(db: Session, user: User) -> str | None:
    """Why this account may not have a session, or None.

    Split from `verification_blocks` so the sentence lives beside the flow that
    shows it. The token path says nothing at all, because a 401 with an
    explanation is an explanation handed to whoever stole the token.
    """
    if not verification_blocks(db, user):
        return None
    return (
        "This account has not been confirmed yet. Enter the code sent to your "
        "address, or ask an admin to confirm it."
    )


def reset_refusal() -> str | None:
    """Why this deployment will not reset a password, or None if it will.

    Named for which system owns the credential rather than saying "unavailable",
    because the member has somewhere to go and this is the sentence that says
    where. The same shape, and the same care about the proxy case, as
    `routers/auth._signup_refusal`: an upstream may be an SSO portal with no
    directory anywhere, so it is not called one.
    """
    mode = auth_mode()
    if mode is AuthMode.LOCAL:
        return None
    if mode is AuthMode.PROXY:
        return "Your password is held by whoever signs you in, not here."
    return "Your password is held by the directory, not here."


def session_is_live(db: Session, user: User, issued_at: float | None) -> bool:
    """Whether a token this old may still act as this account.

    `issued_at` is the token's `iat`. A token minted before
    `sessions_valid_from` is refused, which is how a password reset ends the
    sessions on one account without signing the household out the way
    `settings_store.bump_token_epoch` does.

    A token with no `iat` at all predates this column and is refused only once
    the column is set, so an upgrade ends nobody's session and the first reset
    after it ends every session on that account.

    **Both sides carry sub second precision, and that is not tidiness.** Rounded
    to whole seconds the rule has a hole a second wide either way, and both
    halves were measured on this tree: floor the cutoff and a token minted in the
    same second as the reset survives it, which is the session the reset exists
    to end; leave the cutoff alone and a member signing in immediately after
    their own reset presents an `iat` that floored to **before** it, and is
    refused the session the password they just set is for. `auth._encode` writes
    `iat` as a float for this reason.
    """
    cutoff = user.sessions_valid_from
    if cutoff is not None:
        if issued_at is None:
            return False
        if issued_at < cutoff.replace(tzinfo=UTC).timestamp():
            return False
    return not verification_blocks(db, user)
