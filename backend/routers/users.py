from fastapi import APIRouter

from dependencies import CurrentUser, DbSession
from models import User
from schemas import AppearanceOut, AppearanceUpdate, UserOut

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(db: DbSession, current_user: CurrentUser) -> list[User]:
    """The member list.

    Readable by every member, not just admins, because the book detail page
    needs it to populate the "Loan to…" picker. `UserOut` has no password
    field, so this exposes usernames and the admin flag and nothing else.
    """
    return db.query(User).order_by(User.username).all()


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
