from fastapi import APIRouter
from sqlalchemy import func

from dependencies import CurrentUser, DbSession
from models import Book, Tag, User, UserBook, book_tags, visible_to
from schemas import MonthStat, PerUserStat, StatsOut, TagStat

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("", response_model=StatsOut)
def get_stats(db: DbSession, current_user: CurrentUser) -> StatsOut:
    """Collection statistics, scoped to what this member may see.

    Every aggregation applies `visible_to` independently. Omitting it from any
    one of them would leak another member's private books as a count, which is
    quieter than leaking a title but leaks all the same.
    """
    visible = visible_to(current_user.id)

    total = db.query(func.count(Book.id)).filter(visible).scalar() or 0

    per_user = (
        db.query(User.username, func.count(Book.id).label("count"))
        .join(Book, Book.added_by_user_id == User.id)
        .filter(visible)
        .group_by(User.id)
        .order_by(func.count(Book.id).desc(), User.username)
        .all()
    )

    by_tag = (
        db.query(Tag.name, Tag.category, func.count(book_tags.c.book_id).label("count"))
        .join(book_tags, Tag.id == book_tags.c.tag_id)
        .join(Book, Book.id == book_tags.c.book_id)
        .filter(visible)
        .group_by(Tag.id)
        .order_by(Tag.category, func.count(book_tags.c.book_id).desc(), Tag.name)
        .all()
    )

    by_month = (
        db.query(
            func.strftime("%Y-%m", Book.added_at).label("month"),
            func.count(Book.id).label("count"),
        )
        .filter(visible)
        .group_by("month")
        .order_by("month")
        .all()
    )

    # Joined to Book so the privacy predicate still applies: a finished private
    # book of somebody else's must not appear even as an anonymous count.
    finished_by_month = (
        db.query(
            func.strftime("%Y-%m", UserBook.finished_at).label("month"),
            func.count(UserBook.id).label("count"),
        )
        .join(Book, UserBook.book_id == Book.id)
        .filter(visible, UserBook.user_id == current_user.id, UserBook.finished_at.isnot(None))
        .group_by("month")
        .order_by("month")
        .all()
    )

    rating_row = (
        db.query(func.avg(UserBook.rating), func.count(UserBook.id))
        .join(Book, UserBook.book_id == Book.id)
        .filter(visible, UserBook.user_id == current_user.id, UserBook.rating.isnot(None))
        .one()
    )
    average, rated_count = rating_row

    return StatsOut(
        total=total,
        per_user=[PerUserStat(username=username, count=count) for username, count in per_user],
        by_tag=[
            TagStat(name=name, category=category, count=count) for name, category, count in by_tag
        ],
        by_month=[MonthStat(month=month, count=count) for month, count in by_month],
        finished_by_month=[
            MonthStat(month=month, count=count) for month, count in finished_by_month
        ],
        # Rounded here rather than in the client: it is one number with one
        # sensible precision, and every client would round it the same way.
        average_rating=round(float(average), 2) if average is not None else None,
        rated_count=rated_count or 0,
    )
