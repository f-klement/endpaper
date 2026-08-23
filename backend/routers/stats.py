from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import func

from dependencies import CurrentUser, DbSession
from models import Book, Collection, ReadingProgress, Tag, User, UserBook, book_tags, visible_to
from schemas import CollectionStat, MonthStat, PerUserStat, StatsOut, TagStat

router = APIRouter(prefix="/api/stats", tags=["stats"])


def _pages_by_month(rows: list[tuple[int, datetime, int]]) -> list[MonthStat]:
    """Pages read per month, from a member's own page-unit entries.

    In Python rather than SQL because the figure is a difference between
    *consecutive* rows per book, and SQL that expresses that (a window
    function feeding a conditional sum feeding a group) is a query nobody will
    be able to check against this description a year from now.

    What bounds it: one row per sitting per member, so the input is the size of
    one person's reading, not of the library. A member who logs a page every
    day for five years is 1,825 rows.

    `rows` must arrive ordered by `(book_id, recorded_at, id)`, which is what
    makes "the previous row" mean "the previous entry on this book".

    Two rules, and each drops something on purpose:

    * The **first** entry on a book counts in full. Reaching page 80 means
      eighty pages were read, and crediting nothing would mean a single sitting
      per book never appears at all.
    * A **backwards** step counts nothing. That covers both a re-read and a
      corrected typo, and the two are indistinguishable from here. Crediting
      the lower page in full would let a typo of 400 followed by its correction
      to 40 report 440 pages read, which is the worse of the two errors: this
      way a re-read's first sitting is missed, rather than a mistake inventing
      reading that never happened.
    """
    totals: dict[str, int] = {}
    current_book: int | None = None
    previous_page = 0

    for book_id, recorded_at, page in rows:
        delta = page if book_id != current_book else page - previous_page
        current_book = book_id
        previous_page = page
        if delta > 0:
            month = recorded_at.strftime("%Y-%m")
            totals[month] = totals.get(month, 0) + delta

    return [MonthStat(month=month, count=totals[month]) for month in sorted(totals)]


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

    # Named collections only, and joined to Book so the same privacy predicate
    # applies: a shelf holding one member's private books must not report them
    # as a number to everybody else. Unfiled books are deliberately not a row
    # here; `total` minus the sum of these is how many there are.
    by_collection = (
        db.query(Collection.name, func.count(Book.id).label("count"))
        .join(Book, Book.collection_id == Collection.id)
        .filter(visible)
        .group_by(Collection.id)
        .order_by(func.count(Book.id).desc(), Collection.name)
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

    # Joined to Book for the privacy predicate, like the aggregation above.
    # Page-unit entries only: a percent cannot be added to a page count.
    progress_rows = (
        db.query(ReadingProgress.book_id, ReadingProgress.recorded_at, ReadingProgress.page)
        .join(Book, ReadingProgress.book_id == Book.id)
        .filter(
            visible,
            ReadingProgress.user_id == current_user.id,
            ReadingProgress.page.isnot(None),
        )
        .order_by(
            ReadingProgress.book_id,
            ReadingProgress.recorded_at,
            # Two entries recorded in the same second would otherwise tie, and
            # SQLite's CURRENT_TIMESTAMP has only second resolution.
            ReadingProgress.id,
        )
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
        by_collection=[
            CollectionStat(name=name, count=count) for name, count in by_collection
        ],
        by_month=[MonthStat(month=month, count=count) for month, count in by_month],
        finished_by_month=[
            MonthStat(month=month, count=count) for month, count in finished_by_month
        ],
        # The comprehension narrows `page`, which is nullable on the column
        # and non-null in these rows because the query filters on it. Written
        # out rather than cast, so a query that stops filtering drops the rows
        # instead of adding None to an integer.
        pages_by_month=_pages_by_month(
            [
                (book_id, recorded_at, page)
                for book_id, recorded_at, page in progress_rows
                if page is not None
            ]
        ),
        # Rounded here rather than in the client: it is one number with one
        # sensible precision, and every client would round it the same way.
        average_rating=round(float(average), 2) if average is not None else None,
        rated_count=rated_count or 0,
    )
