from fastapi import APIRouter

from dependencies import CurrentUser, DbSession
from models import User
from schemas import UserOut

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(db: DbSession, current_user: CurrentUser) -> list[User]:
    """The member list.

    Readable by every member, not just admins, because the book detail page
    needs it to populate the "Loan to…" picker. `UserOut` has no password
    field, so this exposes usernames and the admin flag and nothing else.
    """
    return db.query(User).order_by(User.username).all()
