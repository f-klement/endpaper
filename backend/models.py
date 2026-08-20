import logging
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    and_,
    func,
    or_,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from sqlalchemy.sql.elements import ColumnElement

import covers
from database import Base
from enums import AuthMode, BookCondition, BookFormat, OwnershipStatus, ReadStatus, TagCategory

logger = logging.getLogger("endpaper.models")

# Many-to-many association table for books <-> tags
book_tags = Table(
    "book_tags",
    Base.metadata,
    Column("book_id", Integer, ForeignKey("books.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    Index("ix_book_tags_tag_id", "tag_id"),
)


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    category: Mapped[TagCategory] = mapped_column(String(50), nullable=False)

    # Whether `seed_tags()` owns this row.
    #
    # A stored flag rather than "is the name in PREDEFINED_TAGS": that test
    # would silently reclassify every tag the moment somebody renamed one in
    # the seed list, and renaming a seeded tag is a thing that has already
    # happened once here (migration 95b6a61d6668).
    #
    # It decides two things. A predefined tag cannot be deleted, because
    # `seed_tags()` would put it back at the next restart and the delete would
    # look like it silently failed. And the picker groups by it, so the
    # household's own tags do not scatter through a curated genre list.
    is_predefined: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    # Nullable since accounts authenticated by LDAP or by an upstream proxy
    # have no local password. Storing a dummy hash instead would leave a
    # credential that looks usable and is not.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # Which backend vouched for this account. Kept so a directory account is
    # never accidentally treated as one with a local password, and so the
    # member list can show where people come from.
    auth_source: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AuthMode.LOCAL, server_default=AuthMode.LOCAL.value
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    books_added: Mapped[list[Book]] = relationship("Book", back_populates="added_by")
    user_books: Mapped[list[UserBook]] = relationship("UserBook", back_populates="user")
    loans_received: Mapped[list[Loan]] = relationship(
        "Loan", foreign_keys="Loan.loaned_to_user_id", back_populates="loaned_to"
    )
    loans_given: Mapped[list[Loan]] = relationship(
        "Loan", foreign_keys="Loan.loaned_by_user_id", back_populates="loaned_by"
    )


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    isbn: Mapped[str | None] = mapped_column(String(20), unique=True, index=True, nullable=True)
    # Indexed because it is the default sort for every listing and export.
    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    subtitle: Mapped[str | None] = mapped_column(String(500), nullable=True)
    author: Mapped[str | None] = mapped_column(String(500), nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Enrichment fields. Left empty by the ordinary scan flow and filled on
    # demand from Google Books, which carries them far more often than Open
    # Library does. `categories` is Google's own subject list and is
    # deliberately NOT the Tag system: tags are a small curated vocabulary the
    # household chooses from, these are whatever the publisher supplied.
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    categories: Mapped[str | None] = mapped_column(Text, nullable=True)
    google_books_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Series membership. Two columns rather than a `series` table: a series has
    # no attributes of its own here beyond a name, and the questions asked of it
    # ("what else is in this one", "which numbers are missing") are answered by
    # grouping on the name. A table would add a join and an orphan-cleanup
    # problem to buy nothing.
    #
    # Indexed because "everything in this series" is a browse action, not a
    # search. `series_index` is a float: omnibus editions and novellas really are
    # numbered 2.5.
    series_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    series_index: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Where the copy physically is: "living room shelf 3", "loft box 2".
    # Deliberately free text rather than an enum or a table. Nobody knows their
    # own shelf taxonomy before they start, and a wrong vocabulary imposed up
    # front is worse than a slightly untidy one that grows. Indexed so the
    # filter and the distinct-values list stay cheap.
    location: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)

    # What kind of object this copy is. Nullable rather than defaulted to
    # paperback: a scan cannot tell, and guessing wrong on every imported book
    # is worse than admitting the answer is not known. Indexed because "have we
    # got this on audio" is a filter, not a search.
    format: Mapped[BookFormat | None] = mapped_column(String(20), nullable=True, index=True)

    # ── Collector details ────────────────────────────────────────────────
    #
    # Everything below is about this copy as an object rather than about the
    # work, and none of it is ever filled in by a lookup. They live behind a
    # disclosure in the UI so the ordinary add flow stays four fields long.
    #
    # Goodreads is criticised in review after review for having nowhere to put
    # condition or where a book is; the shelf location was already here, this
    # is the other half.

    condition: Mapped[BookCondition | None] = mapped_column(String(20), nullable=True)

    # **Minor units** (cents), not a decimal. SQLite has no decimal type, and
    # SQLAlchemy's Numeric over it round-trips through a float, which is how a
    # price becomes 12.989999999999999. An integer count of cents cannot do
    # that. The client divides by 100 to display; nothing else knows.
    purchase_price_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Stored per book rather than as one setting, because a book bought on
    # holiday really does have a different currency, and a single household
    # currency would silently relabel it.
    purchase_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)

    # A date, not a datetime: nobody knows what time they bought a book.
    purchased_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Free text, like `location`, and for the same reason: "the Oxfam on
    # Cowley Road" is a real answer and no vocabulary chosen up front contains
    # it.
    purchase_source: Mapped[str | None] = mapped_column(String(120), nullable=True)

    added_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )
    # Indexed for the "Recently Added" sort and the per-month statistic.
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    is_private: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    # When this book was moved to the trash, or null while it is on the shelf.
    #
    # A delete is the one action in this app that cannot be undone by repeating
    # it, and it is one tap away from every book. Reviews of every competitor
    # here say the same thing: the app does not say what was deleted and offers
    # no way to put it back. So a delete parks the row instead of dropping it,
    # and `visible_to()` is what keeps it out of everything else.
    #
    # Indexed because the trash listing filters on it and the ordinary case
    # (`IS NULL`) is every other query in the app.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    # Whether a copy is physically here. Defaults to OWNED because the ordinary
    # way a book arrives is somebody scanning the barcode on its back cover,
    # which means they were holding it. Rows created by an import default to
    # UNKNOWN instead, since an export proves nothing about the shelf.
    # Indexed: "show me the ones I have not confirmed yet" is the query the
    # whole bulk-confirmation flow is built around.
    ownership: Mapped[OwnershipStatus] = mapped_column(
        String(20),
        nullable=False,
        default=OwnershipStatus.OWNED,
        server_default=OwnershipStatus.OWNED.value,
        index=True,
    )

    added_by: Mapped[User | None] = relationship("User", back_populates="books_added")
    user_books: Mapped[list[UserBook]] = relationship(
        "UserBook", back_populates="book", cascade="all, delete-orphan"
    )
    loans: Mapped[list[Loan]] = relationship("Loan", back_populates="book", cascade="all, delete-orphan")
    tags: Mapped[list[Tag]] = relationship("Tag", secondary=book_tags)
    notes: Mapped[list[Note]] = relationship("Note", back_populates="book", cascade="all, delete-orphan")

    @validates("cover_url")
    def _store_covers_over_https(self, _key: str, url: str | None) -> str | None:
        """Every write of this column passes through here, which is the point.

        Google Books serves `imageLinks.thumbnail` over plain http, and an http
        image on an https page is mixed content: blocked by the browser
        whatever the CSP says, so the book gets a cover that is correct in the
        database and invisible in the app. Five paths write this column
        (adding a book, uploading a cover, refreshing metadata, Google
        enrichment, and a merge absorbing the loser's), and fixing it at one of
        them fixes it at one of them.

        **The sixth does not reach here.** `backup.restore` inserts through
        Core rather than the ORM, and `@validates` does not fire on a Core
        insert, so it calls `covers.storable` itself. Anything else that learns
        to bulk-insert books has to do the same.

        Both rules live in `covers.storable`, in the order they have to run.
        See `covers.https_url` for why the upgrade is safe and
        `covers.is_renderable` for what is refused.

        A value that is neither https nor one of our own uploads is dropped
        rather than stored. Silently, and that is the right trade here: there
        is no caller to tell (`BookCreate` already answers one with a 422), and
        the alternative is a column that reaches an `<img src>` holding
        whatever an archive put in it. Logged at WARNING so it is not
        invisible.
        """
        stored = covers.storable(url)
        if url and stored is None:
            logger.warning("Discarded a cover URL that is not renderable: %r", url[:120])
        return stored


class UserBook(Base):
    """One member's reading status for one book.

    A row only exists once someone sets a status, so **absence means unread**:
    every query that filters on status has to treat a missing row as unread.
    """

    __tablename__ = "user_books"

    # A unique index rather than a UniqueConstraint: SQLite cannot add a
    # constraint to an existing table without rebuilding it, but it can create
    # an index. That lets migrate_schema() apply this to a live database.
    # Nothing enforced one-row-per-(member, book) before, so duplicates were
    # possible and whichever row .first() returned decided the displayed status.
    __table_args__ = (
        Index("uq_user_books_user_book", "user_id", "book_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("books.id"), nullable=False, index=True
    )
    status: Mapped[ReadStatus] = mapped_column(String(20), default=ReadStatus.UNREAD)

    # 1 to 5, or absent. Per person for the same reason status is: a shared
    # shelf does not mean a shared opinion of what is on it. Goodreads exports
    # carry this and the importer used to parse it and throw it away, because
    # there was nowhere to put it.
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # When this person started and finished. Set from status transitions rather
    # than typed: moving to READING stamps the start, moving to READ stamps the
    # finish. Without them a status is a state with no history, and "what did we
    # read in 2026" cannot be asked at all.
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Indexed: it drives the per-month "books finished" statistic.
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    user: Mapped[User] = relationship("User", back_populates="user_books")
    book: Mapped[Book] = relationship("Book", back_populates="user_books")


class Loan(Base):
    __tablename__ = "loans"

    # A book is in one person's hands at a time. Three code paths had to agree
    # on that (lending, merging two records, trashing one), and one of them
    # historically did not: a merge left both books' open loans open, so the
    # merged book was out with two people at once and the UI showed whichever
    # the query returned first.
    #
    # A partial unique index, which SQLite supports, so the rule holds even if
    # a fourth path is added later and forgets. Partial rather than plain,
    # because a book returned and lent again is two rows with the same
    # `book_id`, and only the open ones are exclusive.
    #
    # The second constraint is the borrower rule: a loan names **either** a
    # member **or** a free-text name, never both and never neither. In the
    # database rather than only in `LoanCreate`, for the same reason as the
    # index above: the schema guards one writer, and a restore, an import or
    # the next endpoint added does not go through it.
    #
    # The trim clause is not decoration. `''` and `'   '` both satisfy
    # `IS NOT NULL`, so without it the constraint admits a loan whose borrower
    # is a run of spaces: a book that is out, with nobody to ask for it back.
    # `LoanCreate` strips whitespace, and `LoanCreate` is the writer this
    # constraint exists because you cannot rely on.
    __table_args__ = (
        Index(
            "uq_loans_one_open_per_book",
            "book_id",
            unique=True,
            sqlite_where=text("returned_at IS NULL"),
        ),
        CheckConstraint(
            "(loaned_to_user_id IS NULL) <> (loaned_to_name IS NULL) "
            "AND (loaned_to_name IS NULL OR length(trim(loaned_to_name)) > 0)",
            name="ck_loans_one_borrower",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("books.id"), nullable=False, index=True
    )
    # Null when the book went to somebody with no account. See loaned_to_name.
    loaned_to_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )
    # A borrower who is not a member: a neighbour, a colleague, a book club.
    # The whole point of recording a loan is remembering who has the book, and
    # the people most likely to keep one are exactly those who will never have
    # an account here. Free text, capped, and never joined on.
    loaned_to_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    loaned_by_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    loaned_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    returned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Optional. A loan with no due date is still a loan, and most household lending
    # has no deadline. It exists so an open loan can be called overdue by
    # something other than a person remembering, which is the only reason to
    # record a loan in the first place.
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    book: Mapped[Book] = relationship("Book", back_populates="loans")
    loaned_to: Mapped[User | None] = relationship(
        "User", foreign_keys=[loaned_to_user_id], back_populates="loans_received"
    )
    loaned_by: Mapped[User] = relationship(
        "User", foreign_keys=[loaned_by_user_id], back_populates="loans_given"
    )


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("books.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    book: Mapped[Book] = relationship("Book", back_populates="notes")
    author: Mapped[User] = relationship("User")


class Setting(Base):
    """One admin-editable setting, stored as text.

    A single key/value table rather than a column per setting: these are read
    rarely, written rarely, and adding one should not need a migration. Values
    are text and parsed by `settings_store`, which owns the typing.
    """

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


def visible_to(user_id: int) -> ColumnElement[bool]:
    """Filter predicate for the books a given account is allowed to see.

    A book is visible when it is **on the shelf** and either public or added by
    this account. Every listing, search, export and statistic must apply this
    or it leaks other people's private books, so it lives here rather than
    being retyped at each call site.

    The trashed check rides along here deliberately. Soft deletion needs the
    same universal reach that privacy does, and every book query in this app
    already calls this function, which is the only reason a delete does not
    have to be chased through twenty call sites. Adding a second rule that
    every query must remember would be the thing that eventually gets
    forgotten. The trash view opts out by using `in_trash_for()` instead.

    Note the `.is_(False)` rather than `not Book.is_private`: the latter would
    evaluate the Column's Python truthiness and collapse to a constant, quietly
    matching every row.
    """
    return and_(
        Book.deleted_at.is_(None),
        or_(Book.is_private.is_(False), Book.added_by_user_id == user_id),
    )


def in_trash_for(user_id: int) -> ColumnElement[bool]:
    """The mirror image: books this account may see **and** has trashed away.

    Deliberately a separate function rather than a flag on `visible_to`. A
    predicate that sometimes means "on the shelf" and sometimes means "in the
    trash" depending on an argument is one a caller can get backwards, and
    getting it backwards here would show every deleted book in the library.
    """
    return and_(
        Book.deleted_at.isnot(None),
        or_(Book.is_private.is_(False), Book.added_by_user_id == user_id),
    )
