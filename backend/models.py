from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    func,
    or_,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.elements import ColumnElement

from database import Base
from enums import AuthMode, OwnershipStatus, ReadStatus, TagCategory

# Many-to-many association table for books <-> tags
book_tags = Table(
    "book_tags",
    Base.metadata,
    Column("book_id", Integer, ForeignKey("books.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    category: Mapped[TagCategory] = mapped_column(String(50), nullable=False)


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
    # family chooses from, these are whatever the publisher supplied.
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

    added_by_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    # Indexed for the "Recently Added" sort and the per-month statistic.
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    is_private: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

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
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("books.id"), nullable=False)
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

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("books.id"), nullable=False)
    loaned_to_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    loaned_by_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    loaned_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    returned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Optional. A loan with no due date is still a loan, and most family lending
    # has no deadline. It exists so an open loan can be called overdue by
    # something other than a person remembering, which is the only reason to
    # record a loan in the first place.
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    book: Mapped[Book] = relationship("Book", back_populates="loans")
    loaned_to: Mapped[User] = relationship(
        "User", foreign_keys=[loaned_to_user_id], back_populates="loans_received"
    )
    loaned_by: Mapped[User] = relationship(
        "User", foreign_keys=[loaned_by_user_id], back_populates="loans_given"
    )


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("books.id"), nullable=False)
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

    A book is visible when it is public, or when this account is the one that
    added it. Every listing, search, export and statistic must apply this or
    it leaks other people's private books, so it lives here rather than being
    retyped at each call site.

    Note the `.is_(False)` rather than `not Book.is_private`: the latter would
    evaluate the Column's Python truthiness and collapse to a constant, quietly
    matching every row.
    """
    return or_(Book.is_private.is_(False), Book.added_by_user_id == user_id)
