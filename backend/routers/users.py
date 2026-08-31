import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from auth import hash_password, require_admin
from auth_backends import directory_owns_email
from dependencies import CurrentUser, DbSession, RowId
from enums import AuthMode
from models import User, switch_targets
from schemas import (
    AppearanceOut,
    AppearanceUpdate,
    EmailUpdate,
    MemberEmailOut,
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
# `PUT /{user_id}/email` is the router's only path parameter and is declared
# **last**, at the bottom of this file. FastAPI matches in declaration order, so
# a `/{user_id}` route above these would make `/test-accounts` a request for the
# member with that id, and `/me/email` a request for the member with id "me"
# (a 422, since `RowId` is an int).


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


# ── The only route in this file with a path parameter ─────────────────────────
#
# Declared last on purpose. See the note above `/test-accounts`.


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
