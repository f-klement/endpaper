import logging
import secrets
from datetime import date, datetime
from typing import TypeGuard

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
import filing
from authors import AUTHOR_NAME_MAX
from database import Base
from enums import (
    AuthMode,
    AuthorityProvenance,
    AuthorityScheme,
    BookCondition,
    BookFormat,
    ClassificationScheme,
    CustomFieldKind,
    LendingWillingness,
    OwnershipStatus,
    ReadStatus,
    TagCategory,
)

logger = logging.getLogger("endpaper.models")

# Many-to-many association table for books <-> tags
book_tags = Table(
    "book_tags",
    Base.metadata,
    Column("book_id", Integer, ForeignKey("books.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    Index("ix_book_tags_tag_id", "tag_id"),
)


#: Longer than a shelf name and shorter than a title. A collection is a heading
#: somebody reads down a list of, so a name that does not fit on one line is
#: already the wrong name.
COLLECTION_NAME_MAX = 80

#: Room for `Collection.name_folded`, which is `name.lower()` and can be longer
#: than the name it came from.
#:
#: Exactly one code point in Unicode grows under `str.lower()`: U+0130, the
#: Turkish dotted capital I, which folds to two code points. Measured by
#: folding every code point from 0 to 0x10FFFF, so twice the name's bound is
#: the worst case rather than a guess. SQLite does not enforce a VARCHAR
#: length, so this documents the column rather than policing it, which is the
#: same job `AUTHOR_KEY_MAX` does for NFKD expansion.
COLLECTION_KEY_MAX = COLLECTION_NAME_MAX * 2


def fold_collection_name(name: str) -> str:
    """The value `Collection.name_folded` holds, wherever it is derived.

    Three callers need it and only one of them can use the validator below:
    the ORM write path, `routers/collections._named`, which has to fold the
    incoming name to compare against the stored column, and `backup._parse_row`,
    whose Core insert never fires a validator. A derivation copied into three
    places is a derivation that drifts, and the note on `.lower()` versus
    `.casefold()` in `_fold_the_name` is precisely the change that would
    split them.

    **`.lower()`, not `.casefold()`.** Casefold makes `Straße` and `STRASSE`
    the same shelf, which may even be the better answer, but
    `routers/books.py::create_tag` and `importing.Import` both fold tag names
    with `.lower()`. A library where tags and collections fold differently is
    a worse defect than either rule on its own, so changing this is a decision
    that changes tags too, and it is changed here or nowhere.
    """
    return name.lower()


#: The highest volume number a series is reasoned about up to.
#:
#: Read by the three request bodies that write `books.series_index`
#: (`BookCreate`, `BookMatch`, `BookDetailsUpdate`) **and** by
#: `routers/books.list_series`, which is the reason it is a name here rather
#: than a literal in each. The bound and its consumer have to agree: that
#: handler computes `set(range(1, max(held) + 1))` over the column under
#: `Shelf.seen_by`, so the ceiling on what may be stored is also the ceiling on
#: how much work one stored row can make every member's request do.
#:
#: **Bounding the writers was not enough, and this is the half that covers the
#: rows already written.** Every API path now refuses a larger value, but
#: `backup.restore` inserts through Core, where neither pydantic nor a
#: `@validates` fires, and an instance upgraded from a release before
#: 2026-09-03 carries whatever its enrichment route stored. Measured on one row
#: at 2,000,000, which is 2,000x this number: `GET /api/books/series` answered
#: **14,888,944 bytes** carrying 1,999,999 missing indexes. So the handler
#: truncates the range at this ceiling, which loses nothing a member could have
#: entered and keeps the gaps below it, rather than answering with a series
#: nobody can read or with nothing at all.
#:
#: 1000 rather than a rounder or tighter number is inherited: it is the `le` the
#: three bodies already carried as a literal, and moving it here changed no
#: value. `tests/schemas/test_book.py` keeps the three from drifting apart and
#: cannot see this fourth reader, which is the second reason for the name.
MAX_SERIES_INDEX = 1000

#: The highest page a book is allowed to have, in the database's own words.
#:
#: The same number `schemas/progress.py` calls `MAX_PAGE` and `BookCreate`
#: bounds `page_count` by. It lives here because `ck_quotes_page_bounds`
#: interpolates it into SQL, and a CHECK constraint that disagreed with the
#: schema would turn a 422 into a 500 for exactly the values in between.
MAX_PAGE_NUMBER_IN_A_BOOK = 100_000


class Collection(Base):
    """A named part of the library's shelf.

    What it is for is the three splits the field sells it for: physical from
    ebook, kept from sold, one person's shelf from another's. All three are
    **partitions**, which is why a book carries one collection rather than a
    list of them: see `Book.collection_id`.

    **Library wide, and never a privacy boundary.** Any member may make one,
    rename it or delete it, and filing a book into one changes nothing about
    who can see it. `visible_to()` remains the only access control on content,
    and this is deliberately not a second scoping axis beside it: a label that
    sometimes hides rows is a label somebody will eventually mistake for
    permission, and the mistake is silent. `docs/decisions.md` records the
    argument.

    `created_by_user_id` is provenance and nothing else. No query consults it,
    which is what keeps the previous paragraph true rather than merely
    intended. Nullable, so deleting an account does not cascade away the
    library's shelving.
    """

    __tablename__ = "collections"

    # Case-insensitively unique. "Ebooks" and "ebooks" as two separate shelves
    # is a typo rather than an intention, and a library that acquires both has
    # no way to tell them apart in a picker.
    #
    # **On a stored fold, not on `lower(name)`, and that reversal is the whole
    # of issue #77.** This index used to be functional, `lower(name)`, on the
    # argument that a stored column is the same name twice and can fall out of
    # step. What that bought was a rule that held for ASCII and for nothing
    # else: SQLite's `lower()` folds the 26 ASCII letters and leaves every
    # other letter alone, so `Ästhetik` and `ästhetik` were two shelves while
    # `Fiction` and `fiction` were one. `COLLATE NOCASE` is the same 26 letters
    # in different words and fixes nothing: measured,
    # `'Ästhetik' = 'ästhetik' COLLATE NOCASE` is 0. A Unicode aware `lower()`
    # in SQLite needs the ICU extension, which this image does not build.
    #
    # So the fold happens in Python, where it is correct, and is stored. The
    # derivation lives in `fold_collection_name` and nowhere else: the ORM
    # reaches it through `_fold_the_name` below, and the two writers that
    # cannot (`routers/collections._named`, which folds an incoming name to
    # compare, and `backup._parse_row`, whose Core insert fires no validator)
    # call it directly.
    __table_args__ = (
        Index("uq_collections_name_folded", "name_folded", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(COLLECTION_NAME_MAX), nullable=False)
    # Derived, never typed. `name` stays exactly what somebody wrote, because
    # that is what a picker shows; this is what the database compares.
    name_folded: Mapped[str] = mapped_column(String(COLLECTION_KEY_MAX), nullable=False)
    # Deliberately **not** indexed, like `loans.loaned_by_user_id`: nothing
    # queries by it, and there is no delete-account path whose child check it
    # would speed up. An index is a write cost, and this one would have no read
    # behind it.
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    books: Mapped[list[Book]] = relationship("Book", back_populates="collection")

    @validates("name")
    def _fold_the_name(self, _key: str, name: str) -> str:
        """Keep `name_folded` in step with every ORM write of `name`.

        Two callers write this column, `create_collection` and
        `rename_collection`, and a derivation either of them could forget is a
        derivation that will eventually be forgotten. The unique index then
        catches what slips past the ORM, which is the half a Python-only check
        does not have.

        The derivation itself is `fold_collection_name`, which the two writers
        that cannot reach this validator also call.
        """
        self.name_folded = fold_collection_name(name)
        return name


#: The longest key an alias row files a spelling under.
#:
#: `authors.author_key` never lengthens a name except through NFKD (a ligature
#: becomes two letters), and the longest spelling it can be given is the whole
#: of `books.author`, so this is that column's 500 with room for the expansion.
#: `AUTHOR_NAME_MAX` bounds the other end: what somebody may *type* as the name
#: to keep.
AUTHOR_KEY_MAX = 500


class AuthorAlias(Base):
    """One spelling of a name, and the person a member said it means.

    **The whole author feature is derived except for this table.** Authors are
    not rows: `books.author` stays the free text credit line it has always
    been, and an author page is a `GROUP BY` over it, exactly as a series page
    is a `GROUP BY` over `series_name`. What that cannot do is record a
    decision, and "Le Guin, Ursula K. is Ursula K. Le Guin" is a decision:
    there is no spelling difference a machine can be trusted to fold on its
    own, no place to put the answer, and nothing to stop the next import
    splitting the name again. So the decision is stored, and the books are not
    touched. `docs/decisions.md` records the rewrite-the-strings alternative
    and why it was refused.

    **Nothing here is a foreign key, and that is the design rather than an
    omission.** An author has no row to point at. A spelling that no book
    carries any more leaves an alias that matches nothing, which costs a row
    and breaks nothing, and the same alias starts working again by itself the
    day an import re-creates that spelling. That is the property a rewrite of
    `books.author` cannot have: it repairs the split once, and the next import
    of the same file makes it again.

    **One lookup is always enough.** Following a row's `canonical_name` one hop
    further never changes it: the merge handler repoints every row that pointed
    at a name it is folding away, and resolves a name that is itself folded
    before storing it. A row naming **itself** satisfies that too, and is the
    ordinary way a display name is pinned against the most-used-spelling
    default. `authors.resolve_alias_map` still flattens what it is given,
    because a hand-edited database is not bound by a handler, and
    `tests/routers/test_books_authors.py::test_one_lookup_is_always_enough`
    asserts the invariant after three merges in a ring.

    **The mapping is library wide and so are the names in it**, exactly like
    a collection's name: every member resolves a spelling to the same person,
    and `canonical_name` is not withheld from anybody. What is filtered is the
    shelf, not the mapping. An author appears for a member only because that
    member can see a book credited to a spelling resolving to them, so an
    author whose every book is private appears for nobody else, and a row here
    proves no book exists: it outlives the book it was created for.
    """

    __tablename__ = "author_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Unique, because a spelling means one person. Re-merging a spelling
    # somewhere else replaces the row rather than adding a second one, which is
    # what keeps a lookup a lookup instead of a decision about which row wins.
    #
    # The key rather than the spelling as written: `authors.author_key` already
    # folds case, accents and punctuation, so storing "Le Guin, Ursula K." as
    # typed would leave "LE GUIN, URSULA K." unfolded on the next import.
    alias_key: Mapped[str] = mapped_column(
        String(AUTHOR_KEY_MAX), unique=True, nullable=False
    )

    # The name to show, as a member typed or picked it. Not a key: this is the
    # one string in the feature that is a choice rather than a derivation, and
    # it is what an author page is headed with.
    #
    # It need not be a name any book carries. Merging two fragments into a name
    # that appears nowhere is how a credit line stored in catalogue order gets
    # repaired without editing the book.
    canonical_name: Mapped[str] = mapped_column(String(AUTHOR_NAME_MAX), nullable=False)

    # Provenance, like `Collection.created_by_user_id`, and read by nothing.
    # Deliberately not indexed: no query consults it and there is no
    # delete-account path whose child check it would speed up.
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


#: The longest identifier an authority file gives one person.
#:
#: A GND number is at most 11 characters (`118181505`, `4203576-4`). The longest
#: identifier any authority file in scope issues is a **Biblioteca Nacional de
#: Chile control number, 23 digits**: `10000000000000000011923`, measured
#: 2026-08-28 in the VIAF cluster for Clarice Lispector. That sentence used to
#: name a VIAF cluster id at 9 digits, and the six national schemes retired it.
#: 60 is far past both and is not a guess about a
#: format: it is a **stored denial of service bound**, the same job
#: `CUSTOM_FIELD_VALUE_MAX` does. A catalogue response has no size cap anywhere
#: in `metadata.py`, so without a bound here a hostile `$0` writes as many bytes
#: into this column as the record holds.
AUTHORITY_IDENTIFIER_MAX = 60


def _scheme_check(members: type[AuthorityScheme]) -> str:
    """A SQL `IN` list holding every member of an enum, in declaration order.

    **Not sorted, and the order is a readability property rather than a
    correctness one.** `StrEnum` iterates in declaration order, so the text this
    renders reads in the same order as the enum above it and as the literal the
    migration spells out. Nothing checks that the two texts match: the guard
    that exists,
    `tests/test_schema.py::TestTheAuthorityIdentifierConstraintsOnAMigratedDatabase
    ::test_every_scheme_the_enum_offers_is_storable`, asks the migrated database
    whether each member is **storable**, which is the question that matters and
    is indifferent to the order. Keeping them in step is for whoever reads the
    two files against each other.
    """
    return "scheme IN (" + ", ".join(f"'{member.value}'" for member in members) + ")"


class AuthorIdentifier(Base):
    """Which record in an authority file one spelling of a name means.

    **Per spelling, not per person, and that is the design rather than a
    simplification.** Two spellings a member folded into one author may carry
    different GND numbers, and that disagreement is evidence: either the local
    merge is wrong or the upstream cluster is. Storing one row per person would
    have to choose between them at write time, silently, with nothing left to
    look at. So both are stored, `Authorship.listing` reports the conflict, and
    nothing here adjudicates.

    **Not a column on `author_aliases`**, though that table is also keyed on a
    spelling. An alias row is a **decision** somebody made about two names, and
    most spellings have none: an author nobody has ever merged has no alias row,
    so an identifier column there would have nowhere to put the ordinary case
    and would make the DNB's assertion depend on whether a member had happened
    to tidy the name. The two tables answer different questions about the same
    key.

    **Nothing here is a foreign key to an author, for the reason `AuthorAlias`
    gives**: an author has no row to point at. A row whose spelling no book
    carries any more costs a row and breaks nothing, and it starts meaning
    something again by itself the day an import re-creates that spelling.

    **The display name and the identifier have deliberately different
    mutability, and the asymmetry is the whole feature.**
    `author_aliases.canonical_name` is how this Household wants a name to read,
    so a member may overwrite it: a national library is entitled to be overruled
    about spelling. This is a claim about *which record in an external file* an
    author is, which is a fact rather than a preference, so there is no
    operation that changes `identifier` in place. `Authorship` refuses a second,
    differing assertion rather than updating the row, and
    `uq_author_identifiers_key_scheme` makes a second row impossible besides.

    **Removable, though.** An upstream cluster can be wrong, and a fact that
    cannot be corrected is a trap rather than an invariant, so a member may
    delete a row and a later import may write it again. What is refused is
    retyping it to a different value, which is the only operation that can
    launder a guess into a fact.
    """

    __tablename__ = "author_identifiers"

    __table_args__ = (
        # One identifier per spelling per scheme. This is what makes "refuse a
        # retype" enforceable below the application: a differing assertion has
        # no second row to land in, so a writer that forgot to check gets an
        # IntegrityError rather than two answers.
        #
        # Not unique on the identifier alone: two spellings legitimately share
        # one GND number, which is precisely the case a merge is made from.
        Index(
            "uq_author_identifiers_key_scheme",
            "author_key",
            "scheme",
            unique=True,
        ),
        # **Built from the enum rather than written out, and that is a fix for a
        # drift that had nowhere to be caught.** The list used to be the literal
        # `('gnd')`, so adding a member to `AuthorityScheme` left a value the
        # application accepts and the database rejects, with the failure landing
        # as an `IntegrityError` at the first write rather than at import. The
        # migration still spells the list out, because a revision has to say
        # what it did on the day it ran, and
        # `tests/test_schema.py::TestTheAuthorityIdentifierConstraintsOnAMigrated
        # Database::test_every_scheme_the_enum_offers_is_storable` is what keeps
        # the two from separating again: it asks the **migrated** database
        # whether each member is storable, which a model built one cannot,
        # because this function derives that constraint from the same enum and
        # so can only ever agree with itself.
        CheckConstraint(
            _scheme_check(AuthorityScheme),
            name="ck_author_identifiers_scheme",
        ),
        CheckConstraint(
            "provenance IN ('catalogue', 'member')",
            name="ck_author_identifiers_provenance",
        ),
        # A machine assertion never names a person. The other direction is
        # deliberately not constrained, so that a member written row whose
        # author is gone still reads `member`: that is the value somebody
        # auditing the list reads, and a stricter check would make the two
        # indistinguishable exactly when the audit matters. Nothing deletes an
        # account today (counted 2026-08-27 over `routers/` and `backend/*.py`:
        # no `db.delete(user)` anywhere), so this is slack for a change not yet
        # made rather than a case in flight.
        CheckConstraint(
            "provenance <> 'catalogue' OR created_by_user_id IS NULL",
            name="ck_author_identifiers_asserter",
        ),
        CheckConstraint(
            f"length(identifier) > 0 AND length(identifier) <= {AUTHORITY_IDENTIFIER_MAX}",
            name="ck_author_identifiers_bounds",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # The key rather than the spelling as written, for the reason
    # `author_aliases.alias_key` gives: `authors.author_key` folds case,
    # accents and punctuation, so the DNB's decomposed `Müller` and a member's
    # composed one are one spelling here.
    #
    # No standalone index: `uq_author_identifiers_key_scheme` leads with this
    # column, and every read of this table is either the whole of it or a
    # lookup by key.
    author_key: Mapped[str] = mapped_column(String(AUTHOR_KEY_MAX), nullable=False)

    scheme: Mapped[AuthorityScheme] = mapped_column(String(20), nullable=False)

    # Stored bare, without MARC's `(DE-588)` wrapper: the scheme is already a
    # column, and keeping the prefix would let one identifier arrive under two
    # spellings that `uq_author_identifiers_key_scheme` cannot collapse. The
    # same rule `metadata._gnd_identifier` applies to a subject heading.
    identifier: Mapped[str] = mapped_column(
        String(AUTHORITY_IDENTIFIER_MAX), nullable=False
    )

    provenance: Mapped[AuthorityProvenance] = mapped_column(String(20), nullable=False)

    # Set only on a `MEMBER` row, and null on a `CATALOGUE` one by check
    # constraint. Deliberately not indexed, like `author_aliases`: no query
    # consults it.
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Tag(Base):
    __tablename__ = "tags"

    # Declared here and not as `unique=True` on the column, so that the index
    # `create_all` builds is the one migration c1f8a7e3d240 creates, by name.
    # A uniqueness rule that lives only in a revision is absent from every
    # database built from the metadata and `--autogenerate` proposes dropping
    # it: `tests/test_custom_fields.py` records that happening to a CHECK.
    __table_args__ = (Index("uq_tags_key", "key", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    category: Mapped[TagCategory] = mapped_column(String(50), nullable=False)

    # Which seeded tag this row **is**, independent of what it is called, and
    # the only thing a translated name is looked up by. `TagKey` carries why
    # that is not `name` and not `is_predefined`.
    #
    # Null for a tag the library invented, and null for a seeded row somebody
    # renamed: migration c1f8a7e3d240 sets it only where the name still matched
    # the English seed name exactly, so a renamed row is theirs from then on
    # and is shown as typed. A rename through the ORM clears it, and that is
    # enforced rather than asked for: `_drop_the_key_on_a_rename` below.
    #
    # Typed `str | None` rather than `TagKey | None` on purpose: a row written
    # by a later version carrying a key this one has never heard of must still
    # load. `TagOut` is where an unrecognised value is forgotten, so it costs a
    # translation rather than a 500 on the whole tag list.
    key: Mapped[str | None] = mapped_column(String(50), nullable=True)

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
    # library's own tags do not scatter through a curated genre list.
    is_predefined: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    @validates("name")
    def _drop_the_key_on_a_rename(self, _key: str, name: str) -> str:
        """A renamed tag stops being a seeded one, enforced rather than asked for.

        The rule this guards is the whole feature: a row keeps its key only
        while it still carries the seeded name, so a household that renamed one
        is shown their word and not the curated one. Migration `c1f8a7e3d240`
        applies it to a database being upgraded and `backup._repair_seeded_tags`
        applies it to one being restored. Nothing renames a tag through the ORM
        today, and this is here so that whoever adds that route does not have to
        know: `Collection._fold_the_name` is the same shape, for the reason its
        docstring gives, that a derivation either writer could forget is a
        derivation that will eventually be forgotten.

        **`self.name is not None` is what makes this safe on an insert, not
        defensive noise.** SQLAlchemy assigns constructor kwargs in the order
        given, and `seed_tags()` writes `Tag(key=..., name=...)`, so the key is
        already set when the name is first assigned. Without that clause this
        validator would clear the key off every seeded row as it was created,
        and the vocabulary would ship unkeyed.

        A Core insert never fires this. Both of them (`backup.restore` and the
        migration) decide the key themselves, which is why that is correct here
        rather than a gap.

        **Three paths skip it, not one, and the other two have no backstop.**
        `Query.update()` and `Session.bulk_update_mappings` write straight to
        the table without instantiating the row, so a bulk rename through either
        would leave a key describing the name the tag used to have, and the
        display would put the seeded word back over the one the member chose.
        `Collection._fold_the_name` has `uq_collections_name_folded` catching
        what slips past it; this has nothing equivalent, because `uq_tags_key`
        enforces one row per key and cannot enforce that the key matches the
        name: that is a fact about `PREDEFINED_TAGS`, which is a list only the
        app has. Neither caller exists today (grepped). Whoever writes the first
        one clears the key in the same statement.
        """
        if self.key is not None and self.name is not None and name != self.name:
            self.key = None
        return name


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
    # An account an admin created for testing, with a password the admin set.
    #
    # Two rules hang off this flag, and neither is expressible any other way.
    # It is the **only** thing an admin may exchange a password for a session
    # on (`is_switch_target`), so a directory-backed member can never be one.
    # And `upsert_directory_user` refuses to adopt a row carrying it: matching
    # on username alone, a directory identity named like a test account would
    # otherwise inherit its books, loans and notes.
    #
    # A column rather than "auth_source is local", because a local account
    # from before this deployment moved to a directory is also local, belongs
    # to a real person, and must not become either of those things.
    is_test_account: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Where a reminder addressed to this member would go. Nullable, and NULL is
    # every row on upgrade: no address means the household mailbox, which is the
    # only mode the mail sender has, so the column changes nothing until
    # somebody fills a field in.
    #
    # **Deliberately NOT on `UserOut`**, for the same reason the three
    # appearance columns are not: that schema is served inside every book
    # payload and the member list, so a field on it is disclosed to every member
    # who can see a book. An address reaches the four routes named in
    # `routers/users.py` and nothing else: **not the mailer**, which still takes
    # its recipients from `overdue_mail_to`, so filling this in changes no
    # behaviour. `tests/test_house_rules.py::TestAnAddressIsServedOnlyWhereItIsNamed`
    # is what keeps that true rather than intended, and its reader pass is what
    # would fail the moment the mailer did read it.
    #
    # 320 is the RFC 5321 maximum for a path, and `mailer.MAX_ADDRESS` is the
    # same number. A literal rather than that constant because importing it
    # here is an import cycle: `mailer` imports `settings_store`, which imports
    # this module. So the two are tied by a test instead,
    # `tests/test_schema.py::TestAnAddressPerMember::test_the_column_is_as_wide_as_the_rule_allows`,
    # and SQLite enforces neither: the width is applied before the write, at
    # `schemas/user.py` and `auth_backends._directory_email`.
    #
    # Who owns the value is `auth_backends.directory_owns_email`, not this
    # column: under a directory configured to carry an address the directory
    # writes it on every sign in, exactly as it re-applies `is_admin`. That
    # function is the one place the question is answered; three call sites in
    # two modules ask it.
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)

    # ── Appearance ────────────────────────────────────────────────────────
    # Three columns here rather than a `user_preferences` table. They are a
    # one-to-one with no history, no cardinality and no lifecycle of their
    # own: a side table would buy a join on every read and a nullable row that
    # every account creation path has to remember to make, including the two
    # that create shadow accounts on the fly. Columns default to NULL, so a
    # directory account gets them for free.
    #
    # NULL means "this member has not chosen", not a value. The frontend then
    # follows the system for the mode, uses the house palette, and picks a
    # different wallpaper every visit, which is the behaviour this app had
    # before anything was stored at all.
    #
    # Deliberately NOT on `UserOut`. That schema is served inside book
    # payloads and the member list, so putting appearance on it would show
    # every member what every other member's library looks like.
    appearance_palette: Mapped[str | None] = mapped_column(String(30), nullable=True)
    appearance_mode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    appearance_wallpaper: Mapped[str | None] = mapped_column(String(30), nullable=True)

    books_added: Mapped[list[Book]] = relationship("Book", back_populates="added_by")
    user_books: Mapped[list[UserBook]] = relationship("UserBook", back_populates="user")
    loans_received: Mapped[list[Loan]] = relationship(
        "Loan", foreign_keys="Loan.loaned_to_user_id", back_populates="loaned_to"
    )
    loans_given: Mapped[list[Loan]] = relationship(
        "Loan", foreign_keys="Loan.loaned_by_user_id", back_populates="loaned_by"
    )


#: How wide each of the Book's own text columns is.
#:
#: Named rather than written as a literal inside `String(...)` because a second
#: module now has to agree with them. `catalogue.Record` bounds what a catalogue
#: asserted against the column that will store it, and a ceiling it derived from
#: a literal it could not see would be a fact stored twice.
#: `tests/test_catalogue.py::TestARecordAgreesWithTheColumnsItFeeds` recomputes
#: each one from `Book.__table__` rather than restating it.
#:
#: **`AUTHOR_LINE_MAX` is not `authors.AUTHOR_NAME_MAX`.** That one bounds a
#: single person's name (300); this bounds the whole credit line, which is every
#: person `authors.split_authors` will later separate.
TITLE_MAX = 500
SUBTITLE_MAX = 500
AUTHOR_LINE_MAX = 500
PUBLISHER_MAX = 255
LANGUAGE_MAX = 10
COVER_URL_MAX = 500
SERIES_NAME_MAX = 255
GOOGLE_BOOKS_ID_MAX = 50
ISBN_MAX = 20


class Book(Base):
    __tablename__ = "books"

    # The ISBN is unique **only among rows that are not copies of each other**.
    #
    # A library that holds two paperbacks of one title has two objects, and
    # every per-object fact in this table (location, condition, what was paid,
    # who has it) is already written per row. So a second copy is a second row,
    # and a plain UNIQUE on `isbn` is what made that impossible.
    #
    # Partial rather than dropped, because the constraint was doing real work:
    # it is what turns a re-scan of a book already on the shelf into a 409
    # instead of a silent second row, and that is the commonest mistake in this
    # app. Rows carrying a `copy_group` have been declared deliberate copies by
    # a member pressing a button that says so; rows without one have not, and
    # stay exclusive. `deleted_at` is deliberately NOT in the predicate: a
    # trashed row keeps its claim on the ISBN, which is the trap
    # `_create_book` frees the holders to resolve, and excluding trashed rows would
    # move that trap rather than remove it.
    __table_args__ = (
        Index(
            "uq_books_isbn_single_copy",
            "isbn",
            unique=True,
            sqlite_where=text("copy_group IS NULL"),
        ),
        # `backup.restore` inserts through Core, where no Pydantic model and no
        # `@validates` fires, so an archive decides this value. A value outside
        # the enum then raises in `OwnershipStatus(...)` at every read.
        #
        # Constrained rather than degraded because this enum is **closed**: owned,
        # not owned, unknown is the whole of the question. SQLite cannot ALTER a
        # CHECK, so a constraint costs a table rebuild every time the enum grows,
        # and this one will not. `user_books.status` and `classifications.scheme`
        # are the other way round and are exempt in `test_house_rules.py`.
        CheckConstraint(
            "ownership IN ('owned', 'not_owned', 'unknown')",
            name="ck_books_ownership",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    isbn: Mapped[str | None] = mapped_column(String(ISBN_MAX), index=True, nullable=True)
    # Indexed because it is the default sort for every listing and export.
    title: Mapped[str] = mapped_column(String(TITLE_MAX), nullable=False, index=True)
    subtitle: Mapped[str | None] = mapped_column(String(SUBTITLE_MAX), nullable=True)
    author: Mapped[str | None] = mapped_column(String(AUTHOR_LINE_MAX), nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(PUBLISHER_MAX), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(String(COVER_URL_MAX), nullable=True)

    # Enrichment fields. Left empty by the ordinary scan flow and filled on
    # demand from Google Books, which carries them far more often than Open
    # Library does. `categories` is Google's own subject list and is
    # deliberately NOT the Tag system: tags are a small curated vocabulary the
    # library chooses from, these are whatever the publisher supplied.
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str | None] = mapped_column(String(LANGUAGE_MAX), nullable=True)
    categories: Mapped[str | None] = mapped_column(Text, nullable=True)
    google_books_id: Mapped[str | None] = mapped_column(String(GOOGLE_BOOKS_ID_MAX), nullable=True)

    # Series membership. Two columns rather than a `series` table: a series has
    # no attributes of its own here beyond a name, and the questions asked of it
    # ("what else is in this one", "which numbers are missing") are answered by
    # grouping on the name. A table would add a join and an orphan-cleanup
    # problem to buy nothing.
    #
    # Indexed because "everything in this series" is a browse action, not a
    # search. `series_index` is a float: omnibus editions and novellas really are
    # numbered 2.5.
    series_name: Mapped[str | None] = mapped_column(String(SERIES_NAME_MAX), nullable=True, index=True)
    series_index: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Where the copy physically is: "living room shelf 3", "loft box 2".
    # Deliberately free text rather than an enum or a table. Nobody knows their
    # own shelf taxonomy before they start, and a wrong vocabulary imposed up
    # front is worse than a slightly untidy one that grows. Indexed so the
    # filter and the distinct-values list stay cheap.
    location: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)

    # Which named part of the shelf this **object** belongs to, or null while
    # it belongs to none.
    #
    # One collection, not many, and that is a product decision rather than a
    # storage one. The splits collections exist for (physical from ebook, kept
    # from sold, one person's shelf from another's) are partitions: a book is
    # in exactly one of each. A join table would answer "which collection is
    # this in" with a list, which every filter, export cell and sort would then
    # need a rule for, and it would be a second tag system with a worse picker.
    # Tags are already the many-to-many axis, and they are where an overlapping
    # label belongs.
    #
    # Per row rather than per copy group, for the same reason `location` is:
    # two copies of one title are two objects, and which shelf each lives on is
    # exactly the kind of fact that differs between them. A library with an
    # Ebooks collection and a physical copy of the same title wants them apart,
    # not together.
    #
    # Nullable, with no default collection invented by the migration. An
    # unfiled book is a real and permanent state, like `format` and `lending`
    # being null: a name chosen for somebody by an upgrade is a name in one
    # language that nobody picked, and every library that never wanted the
    # feature would carry it forever.
    #
    # `SET NULL`, never a cascade. Deleting a shelf label must not delete the
    # books on it, and the database is where that is settled: three delete
    # paths would otherwise each have to remember.
    #
    # Indexed because filtering the library by collection is a browse action
    # over the whole catalogue rather than a search.
    collection_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("collections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # What kind of object this copy is. Nullable rather than defaulted to
    # paperback: a scan cannot tell, and guessing wrong on every imported book
    # is worse than admitting the answer is not known. Indexed because "have we
    # got this on audio" is a filter, not a search.
    format: Mapped[BookFormat | None] = mapped_column(String(20), nullable=True, index=True)

    # Whether the library will lend this copy out, or null while nobody has
    # been asked. A standing intention rather than a state: the open `Loan`
    # answers "is it out", and a book can be marked happy to lend while it is
    # at somebody's house. Storing the answer on the loan would mean it only
    # existed while the book was somewhere else.
    #
    # Nullable rather than defaulted, for the reason `format` is: a guess
    # written into every imported book at once is worse than a blank, because
    # nobody re-checks a field that looks filled in. Indexed because "what
    # could we lend the book club" is a filter over the whole catalogue, which
    # is a browse action rather than a search.
    lending: Mapped[LendingWillingness | None] = mapped_column(
        String(20), nullable=True, index=True
    )

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
    # holiday really does have a different currency, and a single library
    # currency would silently relabel it.
    purchase_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)

    # A date, not a datetime: nobody knows what time they bought a book.
    purchased_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Free text, like `location`, and for the same reason: "the Oxfam on
    # Cowley Road" is a real answer and no vocabulary chosen up front contains
    # it.
    purchase_source: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Which set of deliberate copies this row belongs to, or null while the
    # library holds one of it.
    #
    # An opaque shared token rather than a self-referencing foreign key, and
    # that is the whole design. "Is a copy of" is **symmetric**: two paperbacks
    # of one title are peers and neither is the original. A self-FK would
    # invent a distinguished row, and every distinguished row needs a rule for
    # what happens when it is purged, which is a promote-a-sibling step that
    # five delete paths would each have to remember. A shared label has no such
    # row and therefore needs no such rule: purging any member leaves the rest
    # exactly as they were.
    #
    # Not a foreign key for the same reason, so nothing dangles when a member
    # of the group is destroyed. `copy_group_token()` makes them.
    #
    # Indexed because "the other copies of this one" is the only question ever
    # asked of it, and it is asked on every book detail page.
    copy_group: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

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
    collection: Mapped[Collection | None] = relationship("Collection", back_populates="books")
    user_books: Mapped[list[UserBook]] = relationship(
        "UserBook", back_populates="book", cascade="all, delete-orphan"
    )
    # Cascaded like the rest, so purging a book from the trash takes its
    # progress with it rather than leaving rows pointing at nothing.
    progress: Mapped[list[ReadingProgress]] = relationship(
        "ReadingProgress", back_populates="book", cascade="all, delete-orphan"
    )
    loans: Mapped[list[Loan]] = relationship("Loan", back_populates="book", cascade="all, delete-orphan")
    tags: Mapped[list[Tag]] = relationship("Tag", secondary=book_tags)
    notes: Mapped[list[Note]] = relationship("Note", back_populates="book", cascade="all, delete-orphan")
    # Cascaded like the notes beside them: purging a book from the trash takes
    # the passages copied out of it, which have no meaning without it.
    quotes: Mapped[list[Quote]] = relationship(
        "Quote", back_populates="book", cascade="all, delete-orphan"
    )
    # Ordered by id, which is insertion order, so a book classified by two
    # catalogues reads the same way twice. Cascaded like the notes and the
    # quotes: a purged book's headings describe nothing.
    classifications: Mapped[list[Classification]] = relationship(
        "Classification",
        back_populates="book",
        cascade="all, delete-orphan",
        order_by="Classification.id",
    )
    # Cascaded like the notes and the quotes, and ordered by the definition
    # rather than by this row: a Book reads its fields in the order the Library
    # defined them, so two Books list the same fields the same way.
    custom_field_values: Mapped[list[CustomFieldValue]] = relationship(
        "CustomFieldValue",
        back_populates="book",
        cascade="all, delete-orphan",
        order_by="CustomFieldValue.field_id",
    )

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

    # "Ask me about this book", and the one column on this table meant to be
    # read by other people. The status, the rating and both dates are private
    # to the member who set them and reach the API only as the caller's own
    # `my_*` fields; this one is served as `discuss_with` on every book the
    # caller can see, which is the whole point of the flag. It discloses the
    # usernames and nothing else, in particular not whether those members have
    # read the book.
    #
    # NOT NULL with a default of false rather than nullable, unlike
    # `books.lending`. There is nothing between yes and no here, and absence of
    # the row already means "has not said" for every member who never touched
    # the book, so a nullable column would be a second, weaker spelling of it.
    wants_to_discuss: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    user: Mapped[User] = relationship("User", back_populates="user_books")
    book: Mapped[Book] = relationship("Book", back_populates="user_books")


class ReadingProgress(Base):
    """One moment a member recorded where they were in one book.

    **Append-only.** A row is a fact about the past, so nothing updates one;
    recording a new position inserts. That is the difference between this and a
    `current_page` column, which answers "where am I" and destroys the answer
    to "how much did I read in March" every time it is written.

    It is also why a status change does not touch this table, while
    `started_at` and `finished_at` are cleared on the way back to UNREAD. Those
    two are *derived* from the current status and would otherwise claim
    something false about now; these rows claim nothing about now, and a re-read
    is a real thing whose earlier passes are worth keeping.
    """

    __tablename__ = "reading_progress"

    # Two constraints and one index, all three load bearing.
    #
    # The unit rule is a CHECK rather than only a schema validator, for the
    # same reason `ck_loans_one_borrower` is: a restore inserts through Core
    # and never sees a Pydantic model. Exactly one unit per row means no
    # tie-break rule is needed for a row carrying both, and no such rule can
    # therefore be got wrong. An audiobook has no pages, and neither has a book
    # whose `page_count` no provider supplied.
    #
    # The bounds clause exists because `page = 0` and `percent = 140` are both
    # storable otherwise, and both make the derived percent nonsense.
    #
    # The index matches the only question asked of this table: this member,
    # this book, in order.
    __table_args__ = (
        Index("ix_reading_progress_user_book_time", "user_id", "book_id", "recorded_at"),
        CheckConstraint(
            "(page IS NULL) <> (percent IS NULL)",
            name="ck_reading_progress_one_unit",
        ),
        CheckConstraint(
            "(page IS NULL OR page > 0) "
            "AND (percent IS NULL OR (percent >= 0 AND percent <= 100)) "
            "AND (minutes IS NULL OR minutes > 0)",
            name="ck_reading_progress_bounds",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("books.id"), nullable=False, index=True
    )
    #: When the position was recorded. **Deliberately not indexed on its own.**
    #: Nothing filters or orders on it alone: the history reads it under
    #: `(user_id, book_id)` and the per-month statistic reads it under
    #: `user_id`, so the composite above serves both and a second index would
    #: be a write cost on an append-only table for no read.
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    #: The page reached, not the pages read. A position can be reconciled with
    #: the book; a delta cannot, so a mistyped delta is uncorrectable and a
    #: re-read looks like twice the reading.
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: 0 to 100, for anything with no page count. Never stored beside a page:
    #: the displayed percent is derived from `page / book.page_count` when that
    #: is known, so storing both would be the same fact twice.
    percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: How long this sitting was. Optional, and nothing derives from it.
    minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user: Mapped[User] = relationship("User")
    book: Mapped[Book] = relationship("Book", back_populates="progress")


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

    # Optional. A loan with no due date is still a loan, and most library lending
    # has no deadline. It exists so an open loan can be called overdue by
    # something other than a person remembering, which is the only reason to
    # record a loan in the first place.
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # When an overdue reminder last went out for this loan, or null if none
    # ever has. The whole state the digest keeps, and it is what makes the
    # difference between the two ways this feature goes wrong: without it the
    # digest either sends once and forgets a loan that is still out, or repeats
    # the same list into the library's channel every single run.
    #
    # Stamped only on a delivery that succeeded. A failure leaves it alone so
    # the next tick retries, which is why it is a timestamp on the loan rather
    # than a "sent" flag set before the request.
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

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


#: A quote is a **verbatim excerpt of somebody else's copyrighted words**, so
#: the ceiling is lower than `MAX_NOTE_LENGTH` (10,000) on purpose and is the
#: one place that concern has a mechanical consequence. 2,000 characters is
#: roughly 300 words of prose, about one printed page: enough for the longest
#: passage anybody copies out by hand, and short enough that the table cannot
#: be used to hold a chapter. It is also the stored-denial-of-service bound,
#: which is why an unbounded Text column is not the answer. Enforced by
#: `ck_quotes_text_bounds`, not by the column width: SQLite ignores that.
#: The longest description a client may write.
#:
#: **The column is `Text` and stays `Text`**, so this bounds new writes and
#: leaves every stored row readable: a `max_length` on the schema needs no
#: migration and cannot make an existing book uneditable, which a `CheckConstraint`
#: would.
#:
#: It exists because there was no bound at all, and both critic seats found the
#: same hole from opposite ends on 2026-08-30. `description` is on the **list**
#: payload, so one oversized value is paid for on every page of every listing:
#: measured, a single 3,000,256 byte upload through MARC import made
#: `GET /api/books` answer with 3,203,366 bytes. `POST /api/books` accepted a
#: 200,000 character description with a 201, so this was never a MARC hole; the
#: importer honouring the API's contract is what made the contract's absence
#: visible.
#:
#: **10,000 is argued rather than measured, and the arithmetic is the honest
#: half.** No real population was available to measure: the captured catalogue
#: fixtures in this tree hold descriptions of 8 to 23 characters. What the
#: number has to do is bound a page rather than describe a blurb, and 25 books
#: at 10,000 is 250 KB against the 3.2 MB above. Roughly 1,500 words is past any
#: publisher's blurb and past a MARC `520` summary note, which is one paragraph
#: in every record this app has parsed.
DESCRIPTION_MAX = 10_000

QUOTE_TEXT_MAX = 2_000

#: What the member wants to say *about* the passage. Half the excerpt's
#: ceiling, because a remark longer than the thing it remarks on is a note, and
#: notes already exist.
QUOTE_NOTE_MAX = 1_000


class Quote(Base):
    """A passage a member copied out of a book, and optionally why.

    Shaped after `Note`, which is the closest thing here: the same book and
    author columns, the same edit rule, the same visibility. Three things
    differ, and each was decided rather than inherited.

    **`text` is verbatim and `note` is not.** BookWyrm keeps the excerpt and
    the commentary in separate columns for this reason and it is the right
    call: fold them together and the one field that is supposed to be a
    faithful transcription is where people put their own words. BookLogr takes
    the other route, a `quote_page` column on its notes table, and pays for it:
    nothing there can tell a quote from a note that happened to remember a
    page.

    The two length ceilings are enforced by `ck_quotes_text_bounds` rather than
    by the `String(n)` widths, because SQLite ignores VARCHAR width: the widths
    generate the DDL and document the intent, the CHECK is the rule.

    **`page` is an integer, not free text.** BookWyrm stores a position as text
    because it also carries percentages and ebook locations. This app has no
    reader and no percentage mode, and an integer is what lets the list come
    back in reading order. The cost is real and accepted: a passage from a
    roman-numbered preface has no page here, and goes in unpaged.

    **It hangs off the book row, not off `copy_group`.** A page number is a
    fact about an edition: page 214 of the paperback is not page 214 of the
    hardback. Everything else per copy already lives this way (notes, loans,
    progress), and `_repoint_relations` moves these across on a merge exactly
    as it moves notes.

    Deliberately absent, each because a reference implementation has one and
    this app has no use for it: an end position and a position mode (BookWyrm
    needs both for percentages and federated rendering), a per-row visibility
    (BookLogr needs it for its public profile; nothing here is public), a
    favourite flag, and a title.
    """

    __tablename__ = "quotes"

    __table_args__ = (
        # Both questions asked of this table start with the book: the book page
        # reads its quotes in page order, and the cross-book listing joins on
        # `book_id`. So this is the **only** index on the pair, and `book_id`
        # deliberately carries no `index=True` of its own: a composite leading
        # with the same column already serves every lookup a standalone one
        # would, and shipping both is a second B-tree written on every insert
        # for nothing. `reading_progress`, `user_books` and `loans` each keep a
        # standalone `book_id` index because their composite leads with a
        # different column or is partial; none of those reasons applies here.
        #
        # The listing's own ordering is by `created_at` and is deliberately not
        # indexed: it sorts one page of a library's quotes.
        Index("ix_quotes_book_page", "book_id", "page"),
        # Mirrors `ck_reading_progress_bounds`. The schema bounds `page` too,
        # and both are needed: a restore inserts through Core and never sees a
        # Pydantic model.
        CheckConstraint(
            f"page IS NULL OR (page > 0 AND page <= {MAX_PAGE_NUMBER_IN_A_BOOK})",
            name="ck_quotes_page_bounds",
        ),
        # **`String(n)` is not a bound in SQLite**, which ignores VARCHAR width
        # entirely: a Core insert of 50,000 characters into `text` stores
        # 50,000, measured. So the length rule is stated the only way the
        # database will actually enforce it, beside the page rule and for the
        # same reason. Without this, "the ceiling is in the database" was a
        # false claim about the one column whose ceiling is the argument for
        # the whole table existing separately.
        CheckConstraint(
            f"length(text) <= {QUOTE_TEXT_MAX} "
            f"AND (note IS NULL OR length(note) <= {QUOTE_NOTE_MAX})",
            name="ck_quotes_text_bounds",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # No `index=True`: `ix_quotes_book_page` leads with this column. See above.
    book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("books.id"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    # `String(n)` documents the intent and generates the DDL; `ck_quotes_text_bounds`
    # is what actually refuses an over-long value. See the constraint.
    text: Mapped[str] = mapped_column(String(QUOTE_TEXT_MAX), nullable=False)
    # Null is "I did not note the page", which is the ordinary case for
    # somebody typing a line they liked from memory. It is not zero: a book has
    # no page zero, and the CHECK says so.
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(String(QUOTE_NOTE_MAX), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    book: Mapped[Book] = relationship("Book", back_populates="quotes")
    author: Mapped[User] = relationship("User")


#: A classification number, as text. `005.133` and `QA76.73.P98 V53 2021` are
#: both one, so this is a string and not a number.
#:
#: **120 rather than 40, and the widening is LCSH's.** The other three schemes
#: put a notation or an authority number here and none of them approaches 40.
#: LCSH has no identifier in the record at all (measured: no `valueURI` on any
#: of 2,280 `<subject>` elements in 900 live MODS records, 2026-08-24), so its
#: access point is the authorised heading string, subdivisions and all:
#: `University of Nebraska (Lincoln campus). University Galleries --
#: Exhibitions -- Periodicals` is 91 characters. Measured over the 1,559 LCSH
#: headings in those records, a bound of 40 refuses **399 of them, 25.6%**, and
#: it refuses exactly the subdivided ones, which are the informative ones. 80
#: still refuses 5; 100 and 120 refuse none.
#:
#: Widening it costs the row nothing that matters: `CLASSIFICATION_LABEL_MAX`
#: is 200 on the same table, so a heading row was already allowed 240 **characters**
#: of text and is now allowed 320. Characters rather than bytes matters here: an
#: LCSH heading is routinely non-ASCII, so the per book ceiling of 2,560
#: characters can be up to about 10 KB. Against a per book ceiling of eight rows
#: (`MAX_CLASSIFICATIONS_PER_BOOK`) that did not move.
CLASSIFICATION_NUMBER_MAX = 120

#: The caption a catalogue supplied for that number, in whatever language it
#: catalogues in. Longer than a tag name (100) because a DDC caption is a
#: sentence fragment: "Soziale Probleme, Sozialdienste, Versicherungen" is 47
#: characters and is not the longest.
CLASSIFICATION_LABEL_MAX = 200

#: The longest subject list a client may write into `books.categories`.
#:
#: The second `Text` column on this table and on the **list** payload, so it
#: inherits `DESCRIPTION_MAX`'s argument whole: an oversized value is paid for on
#: every page of every listing, and the column stays `Text` so this bounds new
#: writes without making a stored row unreadable.
#:
#: **Computed rather than chosen, so the arithmetic cannot drift from the
#: sentence**: 32 headings at `CLASSIFICATION_NUMBER_MAX` plus their separators.
#: 32 because the failure modes are asymmetric: too loose costs page weight, too
#: tight drops a whole search result silently, since a row is dropped rather than
#: a field. The widest shape measured here is 14 headings, so it clears 3x.
CATEGORIES_MAX = 32 * CLASSIFICATION_NUMBER_MAX + 31 * 2

#: How wide the stored shelf key has to be to hold any number the column takes.
#:
#: **Wider than the number, which is the whole trap.** A filing rule pads, so a
#: key is longer than the value it files: `Q1` is two characters and files as
#: thirteen. `filing.MAX_KEY_GROWTH` is the most a rule can add and is derived
#: from the three widths that add it, so this bound moves when they do rather
#: than being a number somebody remembered to update.
#:
#: SQLite does not enforce a `VARCHAR` length, so nothing truncates here today.
#: `tests/test_models.py::TestTheShelfKeyFitsItsColumn` is the enforcement, and
#: it measures rather than asserts: the longest key the longest admissible
#: number can produce, against this bound.
CLASSIFICATION_SORT_KEY_MAX = CLASSIFICATION_NUMBER_MAX + filing.MAX_KEY_GROWTH


class Classification(Base):
    """One published scheme's assertion about what a book is about.

    `GND`, `4203576-4`, `Schatz`: a scheme, a number and the caption that scheme
    gave the number. Three columns rather than the one string
    `"004 Informatik"` a catalogue used to hand over, because that string cannot
    be sorted, cannot be matched across languages and does not say which scheme
    it came from.

    **A Dewey row has no caption at all today**, and that is the shape rather
    than a gap: MARC 082 carries the notation and the printed schedule carries
    the words, and every live supplier of a Dewey number here is MARC.

    **`number` is the scheme's own identifier for the heading**, which is a
    shelf notation in DDC and LCC, an authority record number in GND, and the
    authorised heading string itself in LCSH. What the first three have in
    common is the thing the column exists for: the identifier is stable, and
    the caption is whatever the supplying record wrote. For Dewey that was
    measured across languages in round 1; for GND it is one supplier and German
    captions, so the stability is the identifier's own property rather than
    something this catalogue has seen tested.

    **LCSH is the exception and it is stored as one rather than pretended
    away.** The record carries no identifier for a subject heading (no
    `valueURI` on any of 2,280 live `<subject>` elements, 2026-08-24), so the
    string is the access point and there is no second, stabler half to keep. An
    LCSH row as this parser writes it has `number` and no `label`: putting the same words in
    both would be one fact stored twice, and the unique index has to be on the
    half that identifies. `ClassificationScheme` says what that costs.

    **Not a tag, and not a category.** The three are one store with three jobs,
    and the difference is provenance: a tag is this library's own word, a
    category is whatever the publisher claimed, and a row here is somebody at a
    national library placing the book in a published schedule. Only the last
    means anything to another institution, which is why it is kept whole rather
    than flattened into either of the others.

    **The number is what gets matched, never the label.** `004` is Informatik
    in a German record and Computing in an English one. `ddc.tag_names`
    projects the number onto the library's vocabulary, and that projection is
    a **suggestion** offered at add time: no endpoint writes a tag from it. See
    `serialisation.suggested_tag_ids` for what the client does with it.

    Unique per book, scheme and number, so selecting the same record twice
    fills nothing in twice. Not unique on the number alone: a book carries a
    DDC and an LCC at once, and often two DDC numbers from two
    catalogues that disagree about how precise to be (K10plus returned both
    `005.133` and `004` for one ISBN, measured 2026-08-23).
    """

    __tablename__ = "classifications"

    __table_args__ = (
        Index(
            "uq_classifications_book_scheme_number",
            "book_id",
            "scheme",
            "number",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # No `index=True`: `uq_classifications_book_scheme_number` leads with this
    # column, so a second index on it would be a write cost with no read
    # behind it. The same reasoning as `quotes.book_id`.
    book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False
    )
    scheme: Mapped[ClassificationScheme] = mapped_column(String(20), nullable=False)
    number: Mapped[str] = mapped_column(
        String(CLASSIFICATION_NUMBER_MAX), nullable=False
    )
    # Null where the source carries the number alone. MARC 082 is exactly that
    # shape: the field holds the number and the printed schedule holds the
    # words, so there is nothing to store and inventing a caption from our own
    # mapping would put our word in a column that records theirs.
    label: Mapped[str | None] = mapped_column(
        String(CLASSIFICATION_LABEL_MAX), nullable=True
    )
    # Where this number stands on a shelf, under its own scheme's rule. See the
    # class docstring for why it is a column rather than an expression, and
    # `_file_the_number` for what keeps it in step.
    #
    # **NOT NULL and no default, which is the enforcement.** A writer that
    # reached this table without deriving the key would otherwise store a null,
    # and `_shelf_order` puts nulls last, so the row would file at the end of
    # every shelf with nothing red anywhere. As it stands such a write raises
    # `IntegrityError` at the flush.
    sort_key: Mapped[str] = mapped_column(
        String(CLASSIFICATION_SORT_KEY_MAX), nullable=False
    )

    book: Mapped[Book] = relationship("Book", back_populates="classifications")

    @validates("scheme", "number")
    def _file_the_number(self, key: str, value: str) -> str:
        """Keep `sort_key` in step with every ORM write of the two it derives from.

        The shape `Collection._fold_the_name` and `Tag._drop_the_key_on_a_rename`
        already use, for the reason the first of them gives: a derivation a
        writer could forget is a derivation that will eventually be forgotten.
        Here there are two columns rather than one, because the rule is chosen
        by the scheme and applied to the number.

        **Both attributes, and the order they are assigned in does not matter.**
        SQLAlchemy assigns constructor kwargs in the order given and fires this
        once per assignment, so whichever of the two is set second recomputes
        the key with the first already on the instance. `value` is used for the
        attribute being set, because the assignment has not happened yet.

        **The other one being absent is an insert in progress, not an error.**
        `Classification(scheme=...)` with no number yet leaves the key alone,
        and if the number never arrives the NOT NULL on this column and on
        `number` both refuse the row. Deriving from a `None` number would raise
        `AttributeError` from inside a constructor instead.

        A Core insert never fires this, which is `backup.restore`:
        `backup._parse_row` derives the key there, through the same
        `filing.sort_key_for`.
        """
        scheme = value if key == "scheme" else self.scheme
        number = value if key == "number" else self.number
        if number is not None:
            self.sort_key = filing.sort_key_for(scheme, number)
        return value


#: The longest name a Library may give one of its own fields.
#:
#: Shorter than a Tag's 100 because this one is a **label read beside a value**
#: rather than a word in a picker: "Calibre-web" and "Bought from" are the
#: shape, and a name that wraps has already stopped being a label.
CUSTOM_FIELD_NAME_MAX = 60

#: The longest value one may hold.
#:
#: The same 500 `books.cover_url` takes, and for the same reason: the value
#: this feature exists to store is a URL into another system, and a URL is the
#: longest thing anybody puts in a one-line field. It is a **stored denial of
#: service bound** as much as a display one, which is why the column is not
#: `Text`: see `ck_custom_field_values_bounds`.
CUSTOM_FIELD_VALUE_MAX = 500

#: How many fields the Library may define at all.
#:
#: **This is the only ceiling the feature needs**, and that is worth stating
#: rather than leaving to be re-derived. A Book holds at most one value per
#: definition (`uq_custom_field_values_book_field`), so bounding the
#: definitions bounds every Book's payload, every rename's blast radius and
#: every row this feature can add. Without it a Library could define ten
#: thousand fields and make one Book's page ten thousand rows.
#:
#: 25 rather than a rounder number because it is past what §24 describes (one
#: link to another system, plus whatever else a Household turns out to keep)
#: and small enough that `custom_fields.definitions` can scan the whole table
#: in Python to fold a name, which is what `create_tag` does and why.
MAX_CUSTOM_FIELDS = 25


class CustomField(Base):
    """A fact this Library keeps about Books that the schema does not know.

    The first concrete one, and the reason this table exists: a link to the
    Book in a calibre-web instance. There is nowhere to put that, and a column
    per Household opinion is a schema nobody can migrate.

    **Library wide, like a Tag and unlike a reading record.** Defining one is
    additive and says nothing about any Book; filling it in is the per Book
    half and lives in `CustomFieldValue`.

    **Two tables rather than a JSON column on `books`.** A JSON blob cannot be
    renamed without rewriting every row that mentions the old name, which is
    exactly what user story 5 forbids: the values must survive a rename. Here
    a rename is one UPDATE of one row and no value moves at all.

    **Never a privacy boundary**, the same promise `Collection` makes. A field
    is a shape, not an access rule: what may be read is decided by
    `visible_to()` on the Book the value hangs off, and nothing here is
    consulted by that decision.

    Ordered by `id` wherever it is listed, which is the order the Library
    defined them in. No `position` column: reordering is a feature nobody asked
    for, and insertion order is stable, which is the property a reader needs.
    """

    __tablename__ = "custom_fields"

    # SQLite ignores a VARCHAR width, so the width below documents the column
    # and this enforces it. Measured on `quotes`, not assumed: a Core insert of
    # 50,000 characters into a `String(2000)` stores 50,000. `backup.restore`
    # is the one path that reaches this table without a Pydantic model.
    __table_args__ = (
        CheckConstraint(
            f"length(name) > 0 AND length(name) <= {CUSTOM_FIELD_NAME_MAX}",
            name="ck_custom_fields_name_bounds",
        ),
        # **The enum is a plain VARCHAR, so this is what makes it closed.**
        # `CustomFieldOut.kind` is typed, so a row holding anything else makes
        # Pydantic raise while serialising the Library wide definitions route:
        # one bad row, a 500 on every read of the list, for good. That is the
        # poisoned row shape `custom_fields.link_target` is written against,
        # and the write path cannot close it, because `backup.restore` inserts
        # through Core and sees no Pydantic model and no validator. Refusing
        # the insert here makes a corrupt archive fail loudly at the restore
        # instead of quietly afterwards.
        #
        # **Declared here and not only in the migration**, which is where it
        # spent one round: `Base.metadata.create_all` builds the table from
        # this tuple, so a constraint living only in a revision is absent from
        # every database built that way and `--autogenerate` proposes dropping
        # it. `tests/test_custom_fields.py::
        # test_the_model_carries_the_kind_constraint_the_migration_declares`
        # is what caught it, twice.
        #
        # Interpolated from the enum rather than written out, so adding a kind
        # cannot leave the constraint behind. Sorted, so the DDL is stable
        # across runs and a migration diff means something.
        CheckConstraint(
            "kind IN ({})".format(
                ", ".join(f"'{kind.value}'" for kind in sorted(CustomFieldKind))
            ),
            name="ck_custom_fields_kind",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # Unique **binary**, which is the backstop rather than the rule anybody
    # meets: `custom_fields.define` folds in Python and answers the existing
    # row, because SQLite's `lower()` is ASCII only and would let `Ähnliches`
    # and `ähnliches` both exist. Same pair of mechanisms as `tags.name`, and
    # the same reason, recorded in `docs/decisions.md` under "SQLite folds case
    # in ASCII and Python does not".
    name: Mapped[str] = mapped_column(
        String(CUSTOM_FIELD_NAME_MAX), unique=True, nullable=False
    )
    kind: Mapped[CustomFieldKind] = mapped_column(String(20), nullable=False)

    # **No `values` relationship, deliberately.** It would be a way to read
    # every Book's value for a field from a definition nobody had to be allowed
    # to see, which is the one shape this feature has to not offer, and a lazy
    # relationship is invisible to any rule that reads query shapes. Deleting a
    # definition does not need it: `custom_fields.remove` deletes the rows
    # itself, for the reason `delete_tag` clears its association rows rather
    # than trusting a cascade SQLite only enforces while a pragma is on.


class CustomFieldValue(Base):
    """What one Book holds in one of those fields.

    **A row exists only when there is something in it.** Clearing a value
    deletes the row rather than storing an empty string, which is what makes
    user story 4 structural: a Book with nothing to say about a field has no
    row, so there is nothing to render and nothing to filter out. The CHECK
    below is what keeps an empty string from arriving by another door.

    **Reachable only from a Book somebody already resolved.** `custom_fields.py`
    is the only module that queries this table and every one of its readers
    takes `Book` objects rather than ids, so a caller cannot ask for the values
    on a Book it could not fetch. That is the whole answer to user story 7, and
    it is structural: `visible_to()` is applied where it always was, on the way
    to the Book, and this table needs no second copy of the rule to forget.
    """

    __tablename__ = "custom_field_values"

    __table_args__ = (
        # One value per field per Book. A second row would render twice and
        # make "the value" ambiguous for every writer.
        Index(
            "uq_custom_field_values_book_field",
            "book_id",
            "field_id",
            unique=True,
        ),
        CheckConstraint(
            f"length(value) > 0 AND length(value) <= {CUSTOM_FIELD_VALUE_MAX}",
            name="ck_custom_field_values_bounds",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # No standalone index on either column: the composite unique above leads
    # with `book_id`, which is the only lookup this table has, and `field_id`
    # is read only to delete a definition's rows, which is rare and admin only.
    # The same reasoning `quotes.book_id` records.
    book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False
    )
    field_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("custom_fields.id", ondelete="CASCADE"), nullable=False
    )
    value: Mapped[str] = mapped_column(String(CUSTOM_FIELD_VALUE_MAX), nullable=False)

    # `book` and nothing else. The relationship exists so that purging a Book
    # from the trash takes its values with it through the ORM cascade, the same
    # way it takes the notes and the quotes. There is deliberately no `field`
    # to walk in the other direction: see `CustomField`.
    book: Mapped[Book] = relationship("Book", back_populates="custom_field_values")


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


def is_switch_target(user: User | None) -> TypeGuard[User]:
    """Whether an admin may exchange a password for a session on this account.

    Four conditions, and all four have to hold, though the first implies the
    other three for every row this app creates. They are checked anyway because
    the cost of being wrong here is one member reading another's private
    books, and a hand-edited row is not a hypothesis worth being relaxed about.

    `is_admin` is in the list for a sharper reason than symmetry. Under proxy
    auth a token that names a switch target overrides the portal's own header,
    so a flagged row that is also an admin would turn a password an admin typed
    once into a seven day admin session that never passes the portal again.
    Nothing writes that row today: `create_test_account` forces the flag off,
    and `upsert_directory_user` renames a flagged row aside rather than
    applying an admin group to it. This is what keeps that true if either ever
    changes.

    **A directory-backed account is never a target, in any mode.** An admin who
    could mint a session for an LDAP or proxy member would be able to read that
    member's private books, and per-book privacy is the single promise the data
    model makes. The password check is not what stops that: the admin knows a
    test account's password because the admin set it, and a directory account
    has no local password to check at all.

    Used twice, which is why it is a function. `routers/auth.py` decides what
    may be switched to, and `auth.py` decides which tokens may override a proxy
    header, and those are the same question: under proxy auth, the only session
    this app issues itself is a switch into a test account.

    `TypeGuard` rather than `bool` so a caller that has asked the question does
    not have to assert the answer to satisfy the type checker, and deliberately
    not `TypeIs`: that one promises the predicate is true *iff* the value is a
    `User`, which is false here for every ordinary member. It would narrow the
    negative branch to `None`, so anybody who later needs to tell "no such row"
    from "exists and is not a test account" would get a bogus error out of a
    tree that passes today. This narrows the branch both callers use and says
    nothing about the other one.
    """
    return (
        user is not None
        and user.is_test_account
        and not user.is_admin
        and user.auth_source == AuthMode.LOCAL.value
        and bool(user.password_hash)
    )


def switch_targets() -> ColumnElement[bool]:
    """The same rule as a query predicate, for asking the database.

    Two spellings of one rule, which is a thing that drifts, so they are kept
    adjacent and `tests/test_models.py` asserts they select the same rows.
    Neither can be the only one: a row already loaded is a Python question,
    while "which rows are these" is a SQL question, and answering the second by
    loading every account and filtering in Python is the shortcut that is fine
    until a library has more than a handful of them.

    `routers/users.py` needs it so the list it offers as switch targets holds
    only accounts that are. `upsert_directory_user` deliberately does **not**:
    see the comment there.
    """
    return and_(
        User.is_test_account.is_(True),
        User.is_admin.is_(False),
        User.auth_source == AuthMode.LOCAL.value,
        # Both halves, because `is_switch_target` reads the hash for its
        # truthiness and an empty string is not NULL. That is the one shape
        # where the two spellings can disagree, and disagreeing here puts a
        # Switch button in front of an admin that `/auth/switch` answers 404
        # to. Nothing writes an empty hash; the equivalence test holds it.
        User.password_hash.is_not(None),
        User.password_hash != "",
    )


def copy_group_token() -> str:
    """A fresh label joining two book rows as deliberate copies of one title.

    Random rather than derived from a row id, so no member of the group is its
    owner and purging any of them leaves the label meaningful. Sixteen hex
    characters: this is a library-local label, never a secret and never
    guessed at, and it only has to not collide with the handful of others in
    one database.
    """
    return secrets.token_hex(8)


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


class CatalogueTarget(Base):
    """One catalogue source as a row: its address, transport, indexes and bounds.

    **Seeded and read by nothing at runtime.** `targets.SEEDED` is what
    `metadata` asks, and it is a module constant. That is deliberate: `fetch.py`
    and `z3950.py` both argue they need no host allowlist **because** a target's
    address is a module constant, so reading an address off this table is a
    security decision with its own ticket rather than a refactor.

    The table exists for the tickets it unblocks, each owning one column that is
    inert here: making a row editable and reading `rank`, enforcing
    `timeout_seconds`, and the institution's hard filter. **A column is kept only
    where a named ticket reads it**, so this is a schema waiting for callers
    rather than a place to park fields.
    """

    __tablename__ = "catalogue_targets"

    __table_args__ = (
        CheckConstraint(
            "requires_isbn_claim = 1 OR source = 'dnb'",
            name="ck_catalogue_targets_isbn_claim",
        ),
        CheckConstraint(
            "transport IN ('sru', 'bespoke')",
            name="ck_catalogue_targets_transport",
        ),
        CheckConstraint(
            "(isbn_index = '' OR isbn_index NOT GLOB '*[^A-Za-z0-9._]*') "
            "AND (title_index = '' OR title_index NOT GLOB '*[^A-Za-z0-9._]*')",
            name="ck_catalogue_targets_indexes",
        ),
        CheckConstraint(
            "isbn_attribute IS NULL OR (typeof(isbn_attribute) = 'integer' "
            "AND isbn_attribute IN (7))",
            name="ck_catalogue_targets_use_attribute",
        ),
    )

    #: The `CatalogueSource` this row is, and the primary key. Closed, because
    #: `sources.Plan.parse` validates a stored settings row against that enum.
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    #: Position in `sources.DEFAULT_ORDER`. #130 reads it.
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    transport: Mapped[str] = mapped_column(String(16), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    reader: Mapped[str] = mapped_column(String(32), nullable=False)
    answers_lookup: Mapped[bool] = mapped_column(Boolean, nullable=False)
    answers_search: Mapped[bool] = mapped_column(Boolean, nullable=False)
    metered: Mapped[bool] = mapped_column(Boolean, nullable=False)
    needs_key: Mapped[bool] = mapped_column(Boolean, nullable=False)
    sru_version: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    query_parameter: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    query_language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    record_schema: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    isbn_index: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    isbn_attribute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title_index: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    title_query_shape: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lookup_records: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    search_multiplier: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    search_cap: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    refuses_component_parts: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    requires_isbn_claim: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    reads_author_identifiers: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    #: NULL on every seeded row. #132 enforces it, under
    #: `metadata.SEARCH_DEADLINE_SECONDS` as the ceiling over the whole fan out.
    timeout_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Whether this row is still the application's rather than the household's.
    #:
    #: True on all nine today, because nothing can edit one yet. Read by
    #: `main.seed_catalogue_targets`, which reconciles exactly these rows against
    #: `targets.SEEDED` on every start, so a corrected constant reaches the table
    #: instead of drifting from it in silence. #130 clears it on a row somebody
    #: edits, and that row stops being reconciled.
    is_seeded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
