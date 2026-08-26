"""Tests for backend/authorship.py: the database half of author identity.

`tests/routers/test_books_authors.py` already covers the four endpoints through
the API, and it stays the place for anything about status codes, payloads and
the privacy rule as a caller experiences it. This file tests what that one
structurally cannot reach: the module's own seam.

Three things live here and nowhere else.

**That the index is read fresh.** One read costs two statements, and a read after
a write is not stale. Together they are what says there is no cache: an earlier
version held one per instance, it saved nothing on any path, and these two are
what a cache coming back would have to keep true. See `TestTheIndexIsReadFresh`.

**`AuthorNotFound` rather than `HTTPException`.** The module does not know what
HTTP is. The router maps the exception to 404, and that mapping is tested
through the API; that the module raises the domain error at all is tested here.

**The three rules the plan names as the design.** A key is written by the system
and never chosen by a caller; removing one is allowed and retyping it is not;
and a key is per spelling rather than per person, so two rows may disagree.
"""

import pytest
from sqlalchemy import event

from authors import author_key
from authorship import AuthorNotFound, Authorship
from database import engine
from models import AuthorAlias, Book, User


@pytest.fixture
def user(db) -> User:
    u = User(username="reader", password_hash="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def other(db, user) -> User:
    u = User(username="stranger", password_hash="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def shelve(db, user, *credits: str, private: bool = False) -> list[Book]:
    books = [
        Book(title=f"Book {n}", author=credit, added_by_user_id=user.id, is_private=private)
        for n, credit in enumerate(credits)
    ]
    db.add_all(books)
    db.commit()
    return books


def selects(fn) -> list[str]:
    """Every SELECT one call issues, in order."""
    statements: list[str] = []

    def record(conn, cursor, statement, *args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return statements


class TestTheIndexIsReadFresh:
    """There is no cache, and these are what say so.

    An earlier version cached the index per instance. It saved nothing: no path
    reads it twice without a write between the two reads, and every route builds
    a fresh instance for one call. The two tests that measured the cache went
    with it; the two below stayed, because "a read after a write is not stale"
    still has to hold and they now fail if the cache comes back.
    """

    def test_one_read_costs_two_statements(self, db, user):
        """The visible credit lines, and the alias table. Whatever the shelf
        holds: `test_books_authors.py` asserts the same number at 1 book and at
        40."""
        shelve(db, user, "Ursula K. Le Guin", "Terry Pratchett")
        # Read outside the measured window. `shelve` commits, which expires the
        # fixture's row, so reading `user.id` inside the window would count the
        # reload as a third statement. The same gotcha `test_serialisation.py`
        # records about a commit inside a measurement.
        viewer_id = user.id

        assert len(selects(lambda: Authorship.seen_by(db, viewer_id).entries)) == 2

    def test_a_read_after_a_merge_is_not_stale(self, db, user):
        """The instance must not answer from an index built before its own
        write. True by construction now, and pinned so it stays true."""
        shelve(db, user, "Le Guin", "Ursula K. Le Guin")
        authorship = Authorship.seen_by(db, user.id)
        assert len(authorship.entries) == 2

        authorship.merge(
            [author_key("Le Guin"), author_key("Ursula K. Le Guin")],
            "Ursula K. Le Guin",
            by_user_id=user.id,
        )

        assert len(authorship.entries) == 1

    def test_a_read_after_an_unmerge_is_not_stale(self, db, user):
        shelve(db, user, "Le Guin", "Ursula K. Le Guin")
        authorship = Authorship.seen_by(db, user.id)
        authorship.merge(
            [author_key("Le Guin"), author_key("Ursula K. Le Guin")],
            "Ursula K. Le Guin",
            by_user_id=user.id,
        )
        assert len(authorship.entries) == 1

        alias = db.query(AuthorAlias).filter_by(alias_key=author_key("Le Guin")).one()
        authorship.unmerge(alias.id)

        assert len(authorship.entries) == 2


class TestTheModuleDoesNotKnowWhatHttpIs:
    """It raises a domain error. The router turns it into 404, and that mapping
    is tested through the API."""

    def test_merging_an_author_nobody_can_see_raises(self, db, user, other):
        shelve(db, user, "Ursula K. Le Guin", private=True)

        with pytest.raises(AuthorNotFound):
            Authorship.seen_by(db, other.id).merge(
                [author_key("Ursula K. Le Guin")], "U. K. Le Guin", by_user_id=other.id
            )

    def test_unmerging_a_row_that_does_not_exist_raises(self, db, user):
        with pytest.raises(AuthorNotFound):
            Authorship.seen_by(db, user.id).unmerge(999)

    def test_unmerging_a_row_you_cannot_see_the_effect_of_raises(self, db, user, other):
        """Authority rather than secrecy: undo what you can see the effect of."""
        shelve(db, user, "Le Guin", "Ursula K. Le Guin", private=True)
        mine = Authorship.seen_by(db, user.id)
        mine.merge(
            [author_key("Le Guin"), author_key("Ursula K. Le Guin")],
            "Ursula K. Le Guin",
            by_user_id=user.id,
        )
        alias = db.query(AuthorAlias).filter_by(alias_key=author_key("Le Guin")).one()

        with pytest.raises(AuthorNotFound):
            Authorship.seen_by(db, other.id).unmerge(alias.id)


class TestAKeyIsWrittenByTheSystem:
    """The identifier is derived from the name and never chosen by a caller;
    the display name is the opposite. That asymmetry is the design."""

    def test_the_key_is_derived_from_the_name(self, db, user):
        shelve(db, user, "J. R. R. Tolkien")
        entry = Authorship.seen_by(db, user.id).entries[0]

        assert entry.key == author_key(entry.name)

    def test_spellings_that_fold_automatically_share_one_key(self, db, user):
        """Case, accents and punctuation fold with nobody asked, which is what
        makes `author_key` idempotent on a key this API issued."""
        shelve(db, user, "J.R.R. Tolkien", "J. R. R. Tolkien")
        entries = Authorship.seen_by(db, user.id).entries

        assert len(entries) == 1
        assert len(entries[0].spellings) == 2

    def test_a_merge_moves_the_key_with_the_name(self, db, user):
        """A key is not an identity behind the name: a merge retires the keys it
        folds exactly as it retires the spellings."""
        shelve(db, user, "Le Guin", "Ursula K. Le Guin")
        authorship = Authorship.seen_by(db, user.id)

        out = authorship.merge(
            [author_key("Le Guin"), author_key("Ursula K. Le Guin")],
            "U. K. Le Guin",
            by_user_id=user.id,
        )

        assert out.key == author_key("U. K. Le Guin")
        assert out.name == "U. K. Le Guin"


class TestRemovingAKeyIsAllowedAndRetypingIsNot:
    def test_unmerge_deletes_the_row_and_restores_the_author(self, db, user):
        shelve(db, user, "Le Guin", "Ursula K. Le Guin")
        authorship = Authorship.seen_by(db, user.id)
        authorship.merge(
            [author_key("Le Guin"), author_key("Ursula K. Le Guin")],
            "Ursula K. Le Guin",
            by_user_id=user.id,
        )
        alias = db.query(AuthorAlias).filter_by(alias_key=author_key("Le Guin")).one()

        authorship.unmerge(alias.id)

        assert db.get(AuthorAlias, alias.id) is None
        assert {entry.name for entry in authorship.entries} == {"Le Guin", "Ursula K. Le Guin"}

    def test_there_is_no_operation_that_retypes_an_alias_key(self):
        """Counted rather than asserted in prose. An operation that changed an
        `alias_key` in place would silently reassign every book carrying that
        spelling, which is not an undo of anything."""
        from pathlib import Path

        source = (Path(__file__).resolve().parent.parent / "authorship.py").read_text()
        assert ".alias_key =" not in source
        # `canonical_name` is the field a merge does rewrite, which is the
        # display-name half of the asymmetry.
        assert ".canonical_name = keep_name" in source

    def test_a_merge_never_writes_to_books(self, db, user):
        """The whole reason the decision is stored rather than the strings
        rewritten: nothing here is irreversible."""
        books = shelve(db, user, "Le Guin", "Ursula K. Le Guin")
        before = [book.author for book in books]

        Authorship.seen_by(db, user.id).merge(
            [author_key("Le Guin"), author_key("Ursula K. Le Guin")],
            "Ursula K. Le Guin",
            by_user_id=user.id,
        )

        for book in books:
            db.refresh(book)
        assert [book.author for book in books] == before


class TestAKeyIsPerSpellingNotPerPerson:
    def test_one_merge_writes_a_row_per_spelling_including_the_kept_one(self, db, user):
        """The kept key gets a row too, and that is what pins the display name
        against the most-used-spelling default."""
        shelve(db, user, "Le Guin", "Ursula K. Le Guin")

        Authorship.seen_by(db, user.id).merge(
            [author_key("Le Guin"), author_key("Ursula K. Le Guin")],
            "Ursula K. Le Guin",
            by_user_id=user.id,
        )

        keys = {row.alias_key for row in db.query(AuthorAlias).all()}
        assert keys == {author_key("Le Guin"), author_key("Ursula K. Le Guin")}

    def test_the_kept_spelling_is_not_listed_as_folded_into_itself(self, db, user):
        """It put "Folded in: Ursula K. Le Guin" under the heading "Ursula K.
        Le Guin", with an undo beside it."""
        shelve(db, user, "Le Guin", "Ursula K. Le Guin")
        authorship = Authorship.seen_by(db, user.id)

        out = authorship.merge(
            [author_key("Le Guin"), author_key("Ursula K. Le Guin")],
            "Ursula K. Le Guin",
            by_user_id=user.id,
        )

        assert [merged.spelling for merged in out.merged] == ["Le Guin"]


class TestResolvingAName:
    def test_a_folded_spelling_resolves_to_the_person_it_was_folded_into(self, db, user):
        """What makes an old link keep working after a tidy-up."""
        shelve(db, user, "Le Guin", "Ursula K. Le Guin")
        authorship = Authorship.seen_by(db, user.id)
        authorship.merge(
            [author_key("Le Guin"), author_key("Ursula K. Le Guin")],
            "Ursula K. Le Guin",
            by_user_id=user.id,
        )

        assert len(authorship.book_ids_for("Le Guin")) == 2

    def test_a_spelling_no_book_carries_still_resolves(self, db, user):
        """Resolved through the **whole** alias map, not through the spellings
        on this shelf. Fold A into B, then B into C, and the middle name is on
        nothing: resolving through the shelf answered "we own nothing by her".
        """
        shelve(db, user, "Le Guin")
        authorship = Authorship.seen_by(db, user.id)
        authorship.merge([author_key("Le Guin")], "Ursula K. Le Guin", by_user_id=user.id)
        authorship.merge(
            [author_key("Ursula K. Le Guin")], "U. K. Le Guin", by_user_id=user.id
        )

        assert len(authorship.book_ids_for("Ursula K. Le Guin")) == 1

    def test_an_unknown_name_is_empty_rather_than_an_error(self, db, user):
        """A filter on a listing that matches nothing is empty. The alternative
        turns a stale bookmark into an error page."""
        shelve(db, user, "Terry Pratchett")

        assert Authorship.seen_by(db, user.id).book_ids_for("nobody at all") == []

    def test_resolution_is_scoped_to_the_viewer(self, db, user, other):
        """The book ids come out of a shelf, so a private book cannot reach a
        filter through an author name."""
        shelve(db, user, "Ursula K. Le Guin", private=True)

        assert Authorship.seen_by(db, user.id).book_ids_for("Ursula K. Le Guin") != []
        assert Authorship.seen_by(db, other.id).book_ids_for("Ursula K. Le Guin") == []


class TestThePrivacyLineOnTheAliasTable:
    def test_the_index_is_scoped_to_the_viewer(self, db, user, other):
        shelve(db, user, "Ursula K. Le Guin", private=True)

        assert Authorship.seen_by(db, user.id).entries != []
        assert Authorship.seen_by(db, other.id).entries == []

    def test_the_alias_rows_themselves_are_library_wide(self, db, user, other):
        """A row says who a name means; it never says a book exists. Filtering
        the mapping per caller was built, reviewed and withdrawn: it made
        identity itself differ between members."""
        shelve(db, user, "Le Guin", private=True)
        shelve(db, other, "Ursula K. Le Guin")
        Authorship.seen_by(db, user.id).merge(
            [author_key("Le Guin"), author_key("Ursula K. Le Guin")],
            "Ursula K. Le Guin",
            by_user_id=user.id,
        )

        # Observed through the module rather than by counting rows, which is
        # what makes this discriminating. The stranger resolves a spelling that
        # is on nothing they can see, and gets the person it was folded into.
        # Filtering the mapping per caller at `_load` returns [] here, so the
        # withdrawn design fails on this line.
        assert len(Authorship.seen_by(db, other.id).book_ids_for("Le Guin")) == 1

    def test_a_folded_spelling_only_on_a_private_book_is_not_listed(self, db, user, other):
        """The privacy line for the alias table. `build_index` fills
        `alias_keys` only for a spelling on a book this member can see, so a row
        whose spelling survives only on somebody else's private book would
        otherwise announce that the book exists."""
        shelve(db, user, "Le Guin", private=True)
        shelve(db, other, "Ursula K. Le Guin")
        Authorship.seen_by(db, user.id).merge(
            [author_key("Le Guin"), author_key("Ursula K. Le Guin")],
            "Ursula K. Le Guin",
            by_user_id=user.id,
        )

        listing = Authorship.seen_by(db, other.id).listing()
        entry = next(row for row in listing if row.name == "Ursula K. Le Guin")
        assert [merged.spelling for merged in entry.merged] == []
        assert entry.book_count == 1
