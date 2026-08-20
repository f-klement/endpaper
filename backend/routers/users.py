import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from auth import hash_password, require_admin
from dependencies import CurrentUser, DbSession
from enums import AuthMode
from models import User, switch_targets
from schemas import AppearanceOut, AppearanceUpdate, UserCreate, UserOut

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
# Nothing shadows them today because this router has no `/{user_id}` route.
# One added above these would: FastAPI matches in declaration order, so
# `/test-accounts` would become a request for the member with that id.


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
