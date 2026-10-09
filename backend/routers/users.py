import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import accounts
from auth import hash_password, require_admin
from auth_backends import directory_owns_email
from dependencies import CurrentUser, DbSession, RowId
from enums import AuthMode, VerificationProvenance
from models import User, app_holds_the_password, switch_targets
from schemas import (
    AppearanceOut,
    AppearanceUpdate,
    EmailUpdate,
    MemberEmailOut,
    MemberVerificationOut,
    MySecurityOut,
    ResetCodeOut,
    ResetRequestOut,
    UserCreate,
    UserOut,
)

logger = logging.getLogger("endpaper.auth")

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(db: DbSession, current_user: CurrentUser) -> list[User]:
    """The member list.

    Readable by every member, not just admins, because the book detail page
    needs it to populate the "Loan to…" picker. `UserOut` has no password
    field, so this exposes usernames and the admin flag and nothing else.
    """
    return db.query(User).order_by(User.username).all()


# ── Test accounts ─────────────────────────────────────────────────────────────
#
# Under `ldap` or `proxy` an admin has no way to see what an ordinary member
# sees: registration is refused, and signing in as somebody else means knowing
# their directory password. These two routes are that way in, and they are
# admin only.
#
# **Every route with a `/{user_id}` first segment is declared last**, at the
# bottom of this file. FastAPI matches in declaration order, so one of them above
# these would make `/test-accounts` a request for the member with that id, and
# `/me/email` a request for the member with id "me" (a 422, since `RowId` is an
# int). `/password-resets/{user_id}/approve` is not one of them: its first
# segment is a literal, so it collides with nothing.


@router.get("/test-accounts", response_model=list[UserOut])
def list_test_accounts(
    db: DbSession, current_user: Annotated[User, Depends(require_admin)]
) -> list[User]:
    """The accounts an admin may switch into, and no others.

    `switch_targets()`, not the flag alone, so that sentence is true of every
    row returned. The two differ only for a row nothing here writes (a flagged
    account whose `auth_source` was edited to a directory, or whose hash was
    cleared), and on that row the flag alone would put a Switch button in front
    of an admin that `/auth/switch` then answers 404 to, with nothing the UI
    could usefully say.

    Filtering is presentation either way: `/auth/switch` refuses a bad target
    whatever the client sends. Admin only because who exists for testing is
    nobody else's business, and because every account on this list is one
    somebody holds the password to.
    """
    return db.query(User).filter(switch_targets()).order_by(User.username).all()


@router.post("/test-accounts", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_test_account(
    payload: UserCreate,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> User:
    """Create a local account with a password, in any auth mode.

    `UserCreate`, so the registration policy applies unchanged: the 8 character
    floor and the 72 byte bcrypt ceiling the schema already documents.

    Never an admin. A test account exists to see the library as an ordinary
    member sees it, and an admin can already see the admin view. Nothing else
    in this app grants the flag either, so there is no path that turns one into
    an admin later.
    """
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        is_admin=False,
        auth_source=AuthMode.LOCAL.value,
        is_test_account=True,
        email=payload.email,
    )
    # Nobody was asked, which is what `NOT_REQUIRED` says. Deliberately not
    # `ADMIN`: that value names the admin who asserted an address belongs to a
    # person, and this account is the admin's own, made to look at the library
    # from the other side. Recording a name here would put a confirmation in
    # front of a reader that nobody made.
    accounts.record_verification(user, VerificationProvenance.NOT_REQUIRED)
    db.add(user)
    db.commit()
    db.refresh(user)
    # WARNING for the same reason `auth_backends` logs account creation there:
    # a new account with a password on it is the most consequential thing this
    # app writes, and this one is reachable in a mode where no other route can
    # create an account at all.
    logger.warning(
        "Admin %r created the test account %r", current_user.username, user.username
    )
    return user


def _appearance(user: User) -> AppearanceOut:
    """Map the three columns onto the schema.

    Written out rather than `from_attributes`: the columns carry an
    `appearance_` prefix because they sit on a table with `username` and
    `is_admin` beside them, and the schema does not, because it is already
    named for what it holds.
    """
    return AppearanceOut(
        palette=user.appearance_palette,
        mode=user.appearance_mode,
        wallpaper=user.appearance_wallpaper,
    )


@router.get("/me/appearance", response_model=AppearanceOut)
def get_my_appearance(current_user: CurrentUser) -> AppearanceOut:
    """The caller's own appearance.

    There is no path parameter and no route that takes a member id, so there
    is no object to authorize: the only appearance reachable here is the
    caller's. That is the point, and it is why this is not a field on
    `UserOut`, which every member can read for every other member.
    """
    return _appearance(current_user)


@router.put("/me/appearance", response_model=AppearanceOut)
def set_my_appearance(
    payload: AppearanceUpdate, current_user: CurrentUser, db: DbSession
) -> AppearanceOut:
    """Replace the caller's own appearance.

    No admin check and no member check, deliberately: a preference about what
    a person's own screen looks like needs no permission beyond being signed
    in, and the row written is the one the token names.
    """
    current_user.appearance_palette = payload.palette
    current_user.appearance_mode = payload.mode
    current_user.appearance_wallpaper = payload.wallpaper
    db.commit()
    db.refresh(current_user)
    return _appearance(current_user)


# ── Addresses ─────────────────────────────────────────────────────────────────
#
# Where a reminder addressed to a member would go, and the **only** four routes
# that serve or take one. `UserOut` deliberately has no address on it, so no
# book payload and no member list carries one; the rule and what enforces it are
# in `schemas/user.py` and `models.User.email`.
#
# Who may write is two sentences. A member writes their own; an admin writes
# anybody's. Both are refused where the deployment's directory owns the value,
# because there the next sign in would overwrite whatever was typed:
# `auth_backends.directory_owns_email` is the one place that decides it.


def _member_email(user: User) -> MemberEmailOut:
    """One row as the schema, including whether it is that row's to change.

    **Two flags rather than one**, because "may I type here" and "why is this
    empty" are different questions and only the second can explain a directory
    account that nobody ever asked for an address. See `MemberEmailOut`.
    """
    return MemberEmailOut(
        id=user.id,
        username=user.username,
        email=user.email,
        editable=not directory_owns_email(user.auth_source),
        # **Named directories, never "not local".** `users.auth_source` carries
        # no `CheckConstraint`, which `directory_owns_email` states and relies
        # on: an unknown spelling is a row no directory is configured for, and
        # it answers False for one. `!= LOCAL` took the opposite stance on the
        # same column, so `''`, `'LOCAL'` and a restored row of junk all came
        # back as directory accounts and their owners were told a directory
        # they do not have supplies no address. Measured over seven spellings by
        # a design critic.
        from_directory=user.auth_source in (AuthMode.LDAP.value, AuthMode.PROXY.value),
    )


def _refuse_if_the_directory_owns_it(user: User) -> None:
    """409 on a write the next sign in would silently revert.

    **409 rather than 403.** Nothing about the caller's rights is wrong: an
    admin has every right here and still cannot write this field, because the
    directory is the one that decides it. A 403 would send an admin looking for
    a permission to grant themselves, and there is none.

    The detail names the variable to unset, because the remedy is a deployment
    change and the person reading this is the one who made it.
    """
    if not directory_owns_email(user.auth_source):
        return
    setting = (
        "PROXY_EMAIL_HEADER"
        if user.auth_source == AuthMode.PROXY.value
        else "LDAP_EMAIL_ATTRIBUTE"
    )
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            f"This address comes from the directory. Change it there, or clear "
            f"{setting} to let it be set here."
        ),
    )


@router.get("/me/email", response_model=MemberEmailOut)
def get_my_email(current_user: CurrentUser) -> MemberEmailOut:
    """The caller's own address.

    No path parameter and no member id, so there is no object to authorize: the
    only address reachable here is the caller's. That is the same shape as
    `/me/appearance` and it is the reason neither is a field on `UserOut`.
    """
    return _member_email(current_user)


@router.put("/me/email", response_model=MemberEmailOut)
def set_my_email(
    payload: EmailUpdate, current_user: CurrentUser, db: DbSession
) -> MemberEmailOut:
    """Set or clear the caller's own address."""
    _refuse_if_the_directory_owns_it(current_user)
    current_user.email = payload.email
    db.commit()
    db.refresh(current_user)
    return _member_email(current_user)


@router.get("/emails", response_model=list[MemberEmailOut])
def list_emails(
    db: DbSession, current_user: Annotated[User, Depends(require_admin)]
) -> list[MemberEmailOut]:
    """Every member's address. Admin only.

    **Reading was the half of this that was argued about**, and the refused
    alternative was write only, where nobody sees an address including an admin.
    It was refused because a household whose reminders silently go nowhere needs
    somebody able to see the typo, and a per sender delivery record tells you a
    send failed rather than that the address is wrong. Recorded on issue #80.

    A whole list rather than one member at a time, because the screen behind it
    is a list: a household has a handful of accounts and the admin is looking
    for the empty row.
    """
    return [
        _member_email(user) for user in db.query(User).order_by(User.username).all()
    ]


# ── Account recovery, and confirming an address ───────────────────────────────
#
# The admin's half of both flows. What an admin may do here is bounded by what
# the routes are: **approve** a request a member made, and **assert** that an
# account's address is that person's. Neither creates a request, and no route
# reachable with a session does: `backup.restore` writes the rows generically
# from an archive and is the named exception, for the reason `accounts` gives.


def _username(db: Session, user_id: int | None) -> str | None:
    """One name for a row this screen is about to show, or None."""
    if user_id is None:
        return None
    user = db.get(User, user_id)
    return user.username if user is not None else None


@router.get("/password-resets", response_model=list[ResetRequestOut])
def list_password_resets(
    db: DbSession, current_user: Annotated[User, Depends(require_admin)]
) -> list[ResetRequestOut]:
    """The requests waiting on an admin, oldest first. Admin only.

    Carries no code and never has: an approval's code exists once, in the
    response to the approval, and is stored as a bcrypt hash. `approved_at` is
    here so the queue can say a request has already been granted, which is the
    one thing a screen that cannot show the code again has to be able to say.
    """
    rows = accounts.pending_requests(db)
    return [
        ResetRequestOut(
            user_id=row.user_id,
            username=_username(db, row.user_id) or "",
            requested_at=row.requested_at,
            expires_at=row.expires_at,
            approved_at=row.approved_at,
            approved_by=_username(db, row.approved_by_user_id),
            code_expires_at=row.code_expires_at,
        )
        for row in rows
    ]


@router.post("/password-resets/{user_id}/approve", response_model=ResetCodeOut)
def approve_password_reset(
    user_id: RowId,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> ResetCodeOut:
    """Grant a request, and show the code once.

    **An admin may approve another admin's request.** Owner's decision on issue
    #105: what makes it acceptable is the asymmetry already in the mechanism
    rather than a further rule, since the request is still member initiated. The
    case it refuses is an admin quietly acquiring a peer's account; the case it
    allows is an admin who locked themselves out being helped by the person
    beside them, which is the ordinary one in a two person archive.

    **A deployment with exactly one admin therefore has no path in this app**,
    and that case belongs to the operator: `README.md` names the command line
    recovery, which is the capability whoever runs the container already has.

    404 when there is no live request, which is true of this route: there is
    nothing here to approve, and an admin may already list every member.
    """
    request = accounts.live_request(db, user_id)
    if request is None:
        raise HTTPException(status_code=404, detail="No such reset request")
    code = accounts.approve_reset(db, request, current_user)
    # `code_expires_at` is set by the approval and is never None afterwards; the
    # narrowing is for the type checker rather than a case that can occur.
    assert request.code_expires_at is not None
    return ResetCodeOut(code=code, expires_at=request.code_expires_at)


@router.delete("/password-resets/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def decline_password_reset(
    user_id: RowId,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> None:
    """Decline a request, so it stops occupying the queue."""
    request = accounts.live_request(db, user_id)
    if request is None:
        raise HTTPException(status_code=404, detail="No such reset request")
    accounts.dismiss_reset(db, request, current_user)


@router.get("/verification", response_model=list[MemberVerificationOut])
def list_verification(
    db: DbSession, current_user: Annotated[User, Depends(require_admin)]
) -> list[MemberVerificationOut]:
    """Every member's confirmation state. Admin only.

    The whole list rather than the unconfirmed ones, for the reason
    `list_emails` serves the whole list: the screen is a list of a household's
    accounts and the admin is looking for the row that is wrong. It also lets the
    screen say which accounts this app never held a credential for, rather than
    silently omitting them and leaving somebody to wonder.
    """
    return [_verification(db, user) for user in db.query(User).order_by(User.username)]


def _verification(db: Session, user: User) -> MemberVerificationOut:
    """One row as the schema, address withheld.

    `has_address` rather than the address itself: this is not one of the four
    routes `MemberEmailOut` is served on, and what this screen needs to know is
    whether a code could have been sent at all, not where.
    """
    return MemberVerificationOut(
        id=user.id,
        username=user.username,
        verified_at=user.email_verified_at,
        verification_source=(
            VerificationProvenance(user.email_verification_source)
            if user.email_verification_source is not None
            else None
        ),
        verified_by=_username(db, user.email_verified_by_user_id),
        has_address=bool(user.email),
        applies=app_holds_the_password(user),
    )


@router.get("/me/security", response_model=MySecurityOut)
def get_my_security(db: DbSession, current_user: CurrentUser) -> MySecurityOut:
    """What has been done to the caller's own account, and by whom.

    **The member's half of an admin confirmed reset.** A reset that left no mark
    would be indistinguishable from a quiet takeover, which is the property the
    whole flow exists to keep, so the completed request is kept and read back
    here with the approver's name on it.

    No path parameter and no member id, so there is no object to authorize: the
    only account reachable here is the caller's. That is the same shape as
    `/me/email` and `/me/appearance` and it is why none of the three is a field
    on `UserOut`.
    """
    reset = accounts.last_completed_reset(db, current_user.id)
    return MySecurityOut(
        password_reset_at=reset.completed_at if reset is not None else None,
        password_reset_approved_by=(
            _username(db, reset.approved_by_user_id) if reset is not None else None
        ),
        verified_at=current_user.email_verified_at,
        verification_source=(
            VerificationProvenance(current_user.email_verification_source)
            if current_user.email_verification_source is not None
            else None
        ),
        verified_by=_username(db, current_user.email_verified_by_user_id),
    )


# ── The two routes in this file with a path parameter ─────────────────────────
#
# Declared last on purpose. See the note above `/test-accounts`.


@router.post("/{user_id}/verify", response_model=MemberVerificationOut)
def verify_member(
    user_id: RowId,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> MemberVerificationOut:
    """Assert that this account's address is that person's. Admin only.

    **The override that makes "an unverified account may do nothing" survivable.**
    A confirmation step completable only by receiving mail cannot be completed at
    all by a household with no mail server, which is the ordinary configuration
    here, so this is the primary path for some installations and the exception
    for others. Owner's decision, 2026-09-06.

    **It is an assertion about a person, so it is recorded as one.** The account
    carries that an admin confirmed it and which admin, not merely that it is
    confirmed: `AuthorityProvenance` is this codebase's precedent and
    `VerificationProvenance` is the same shape.

    409 where this app never held the credential. Nothing about the caller's
    rights is wrong, which is why it is not a 403: a directory authenticated that
    account, so confirming its address here would be an assertion this app cannot
    make. The same reasoning, and the same status, as
    `_refuse_if_the_directory_owns_it`.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="No such member")
    if not app_holds_the_password(user):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This account is authenticated elsewhere, so there is nothing "
                "here to confirm."
            ),
        )
    # **An account that is already settled is left alone**, and the row is
    # returned unchanged. Re-stamping would overwrite a member's own
    # confirmation with an admin's name, so the member's account screen would
    # afterwards say an admin confirmed an address they proved themselves. The
    # screen hides the control for such a row, and a client is not a control.
    if user.email_verified_at is None:
        accounts.override_verification(db, user, current_user)
        db.refresh(user)
    return _verification(db, user)


@router.put("/{user_id}/email", response_model=MemberEmailOut)
def set_member_email(
    user_id: RowId,
    payload: EmailUpdate,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> MemberEmailOut:
    """Set or clear any member's address. Admin only."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        # 404 for an id that does not exist, and there is nothing to withhold
        # here: an admin may already list every member.
        raise HTTPException(status_code=404, detail="No such member")
    _refuse_if_the_directory_owns_it(user)
    user.email = payload.email
    db.commit()
    db.refresh(user)
    return _member_email(user)
