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

import ast
from pathlib import Path

import pytest
from sqlalchemy import event

from authors import author_key
from authorship import (
    MAX_ASSERTIONS_PER_RECORD,
    AuthorNotFound,
    Authorship,
    IdentifierConflict,
)
from catalogue import AuthorityAssertion
from database import engine
from enums import AuthorityProvenance, AuthorityScheme
from models import (
    AUTHORITY_IDENTIFIER_MAX,
    AuthorAlias,
    AuthorIdentifier,
    Book,
    User,
)

KANE = AuthorityAssertion("Sean P. Kane", AuthorityScheme.GND, "1042243212")


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


class TestStoringWhatACatalogueAsserted:
    """`record_catalogue_assertions`, which is the certain half.

    Certain means the record was found by this Book's own verified ISBN. That
    is the caller's claim and not this method's, and the way an uncertain
    assertion is refused is that no search path calls it: see
    `TestACandidateIsNotStoredSilently`.
    """

    def test_an_assertion_is_stored_without_asking(self, db, user):
        shelve(db, user, "Sean P. Kane")

        Authorship.seen_by(db, user.id).record_catalogue_assertions([KANE], credited=KANE.name)

        row = db.query(AuthorIdentifier).one()
        assert (row.author_key, row.scheme, row.identifier) == (
            author_key("Sean P. Kane"),
            AuthorityScheme.GND,
            "1042243212",
        )

    def test_a_machine_written_row_names_no_person(self, db, user):
        """Provenance is the explicit value, and `created_by_user_id` is null
        by check constraint. Without both, a curated list quietly becomes a
        generated one and nothing can tell an auditor which is which."""
        Authorship.seen_by(db, user.id).record_catalogue_assertions([KANE], credited=KANE.name)

        row = db.query(AuthorIdentifier).one()
        assert row.provenance == AuthorityProvenance.CATALOGUE
        assert row.created_by_user_id is None

    def test_the_same_assertion_twice_stores_one_row(self, db, user):
        """A refresh runs whenever somebody presses the button."""
        authorship = Authorship.seen_by(db, user.id)
        authorship.record_catalogue_assertions([KANE], credited=KANE.name)
        authorship.record_catalogue_assertions([KANE], credited=KANE.name)

        assert db.query(AuthorIdentifier).count() == 1

    def test_a_catalogue_disagreeing_with_a_stored_value_changes_nothing(
        self, db, user
    ):
        """The refusal, asserted rather than assumed from the absence of a verb.

        Skipped rather than raised here: a refresh must not answer 500 because
        one catalogue disagrees, and the stored value is the one that stands.
        """
        authorship = Authorship.seen_by(db, user.id)
        authorship.record_catalogue_assertions([KANE], credited=KANE.name)

        authorship.record_catalogue_assertions(
            [AuthorityAssertion("Sean P. Kane", AuthorityScheme.GND, "9999")], credited=KANE.name
        )

        assert [row.identifier for row in db.query(AuthorIdentifier).all()] == [
            "1042243212"
        ]

    def test_a_record_may_not_deposit_more_rows_than_the_ceiling(self, db, user):
        """A catalogue response has no size cap anywhere in `metadata.py`, and
        these rows are Library wide and are deleted with no Book."""
        flood = [
            AuthorityAssertion(f"Author {index}", AuthorityScheme.GND, str(index))
            for index in range(MAX_ASSERTIONS_PER_RECORD + 40)
        ]

        Authorship.seen_by(db, user.id).record_catalogue_assertions(
            flood, credited=", ".join(row.name for row in flood)
        )

        assert db.query(AuthorIdentifier).count() == MAX_ASSERTIONS_PER_RECORD

    def test_an_identifier_the_column_cannot_hold_is_dropped_not_raised(
        self, db, user
    ):
        """Nothing in a third party record is worth failing a member's refresh
        for. The same call `classifications.bounded_headings` makes for a heading."""
        long_one = AuthorityAssertion(
            "Long", AuthorityScheme.GND, "9" * (AUTHORITY_IDENTIFIER_MAX + 1)
        )

        Authorship.seen_by(db, user.id).record_catalogue_assertions(
            [long_one, KANE], credited=f"Long, {KANE.name}"
        )

        assert [row.identifier for row in db.query(AuthorIdentifier).all()] == [
            "1042243212"
        ]

    def test_a_name_that_normalises_to_nothing_is_dropped(self, db, user):
        """An empty key matches no spelling ever, so the row would be
        unreachable and undeletable rather than merely useless."""
        punctuation = AuthorityAssertion("...", AuthorityScheme.GND, "1")

        Authorship.seen_by(db, user.id).record_catalogue_assertions([punctuation], credited="...")

        assert db.query(AuthorIdentifier).count() == 0


class TestACandidateIsNotStoredSilently:
    """The behaviour is exercised end to end in
    `tests/routers/test_books_authors.py::TestWhichBranchMayWriteAnIdentifier`,
    against the two enrichment branches themselves. What is here is the module's
    own half: a Member's confirmation, and what it refuses.
    """

    def test_a_member_may_confirm_one_and_it_is_marked_as_theirs(self, db, user):
        shelve(db, user, "Sean P. Kane")

        row = Authorship.seen_by(db, user.id).confirm_identifier(
            "Sean P. Kane", AuthorityScheme.GND, "1042243212", by_user_id=user.id
        )

        assert row.provenance == AuthorityProvenance.MEMBER
        assert row.created_by_user_id == user.id

    def test_confirming_for_an_author_nobody_can_see_raises(self, db, user, other):
        shelve(db, other, "Sean P. Kane", private=True)

        with pytest.raises(AuthorNotFound):
            Authorship.seen_by(db, user.id).confirm_identifier(
                "Sean P. Kane", AuthorityScheme.GND, "1", by_user_id=user.id
            )

    def test_confirming_a_different_value_over_a_stored_one_is_refused(
        self, db, user
    ):
        """The refusal a Member meets, as opposed to the one a catalogue meets.

        Raised here because there is somebody to tell. Retyping is the only
        operation that can launder a guess into something that reads like a
        national library's assertion, so it has no verb at all.
        """
        shelve(db, user, "Sean P. Kane")
        authorship = Authorship.seen_by(db, user.id)
        authorship.record_catalogue_assertions([KANE], credited=KANE.name)

        with pytest.raises(IdentifierConflict):
            authorship.confirm_identifier(
                "Sean P. Kane", AuthorityScheme.GND, "9999", by_user_id=user.id
            )

        assert db.query(AuthorIdentifier).one().identifier == "1042243212"

    def test_confirming_the_value_already_stored_is_not_a_conflict(self, db, user):
        shelve(db, user, "Sean P. Kane")
        authorship = Authorship.seen_by(db, user.id)
        authorship.record_catalogue_assertions([KANE], credited=KANE.name)

        row = authorship.confirm_identifier(
            "Sean P. Kane", AuthorityScheme.GND, "1042243212", by_user_id=user.id
        )

        assert row.provenance == AuthorityProvenance.CATALOGUE
        assert db.query(AuthorIdentifier).count() == 1


class TestAnIdentifierIsRemovableAndNeverEditable:
    def test_there_is_no_operation_that_retypes_an_identifier(self):
        """The counterpart of `test_there_is_no_operation_that_retypes_an_alias_key`.

        **This guard has been rewritten four times and been substantially wrong
        every time, including the rewrite that was itself billed as the
        simplification.** That history is the most useful thing about it and is
        why it is written down rather than tidied away:

        1. a substring search, `".identifier =" not in source`. Four ordinary
           spellings walked past: no space, augmented, tuple target, `setattr`.
        2. hand walked `Assign`, `AugAssign` and `AnnAssign`. Three more walked
           past: a bulk `update({...})`, an aliased `setattr`, and
           `row.__dict__[...] = v`.
        3. store context, which is structurally complete for assignment. But it
           kept a **fourth arm that matched the text of SQL strings**, and that
           arm both false-positived on this module's own docstring ("updated"
           uppercases to contain "UPDATE") and missed every f-string, because an
           f-string is a `JoinedStr` and no single `Constant` in it carries both
           the verb and the column.
        4. the payload matcher deleted. A raw SQL write's invariant is **the
           call, not the string**, so the call arm covers it however the string
           is built, and the docstring exclusion went with the scan it existed
           to patch.

        **The lesson, and it generalises past this file: an arm that matches a
        payload is a defect, an arm that matches structure is not.** Rounds 1
        and 2 taught this guard to stop matching payloads and round 3
        reintroduced it in the one arm nobody re-derived.

        Four arms, each structural, each present because something got past
        without it:

        1. **store context** on an attribute, which is every assignment form
           there is, including tuple targets, `for` targets, `with ... as`
           targets and comprehension targets;
        2. **store context** on a subscript with a literal key, for
           `row.__dict__["identifier"] = v`;
        3. **any call named as a bulk writer**, however bound, for the ORM and
           Core writes that touch no Python attribute: matching only
           `ast.Attribute` missed `update(...)` imported as a bare name, and
           `bulk_update_mappings` is a documented Session method whose whole
           purpose is this;
        4. **any mention of a dynamic setter**, as a `Name`, an `Attribute` or a
           **string constant**, for `getattr(row, "__setattr__")(...)` and for
           `AuthorIdentifier.identifier.__set__(row, v)`.

        **Where the boundary is, stated rather than left to be discovered, and
        stated accurately this time.** The previous version claimed the arms
        catch "all the cheap spellings", and that was false when written: an
        f-string is the ordinary way to write SQL in Python and it survived, as
        did a documented bulk-update method. What is true is narrower. These
        arms catch every spelling either reviewing seat has found, and the one
        acknowledged survivor is a **subscript key assembled at runtime**, which
        needs a line whose only purpose is to hide a write from a reader.
        `__import__("database")` is likewise a `Call` on a string rather than an
        import node, and `eval`/`exec` are outside static analysis entirely.

        **The closed form, for whoever needs a fifth arm: do not add one.** The
        arms enumerate an open set, so arm five is already implied by arm four.
        Every shape either seat has found names `AuthorIdentifier` or
        `author_identifiers`, so an allowlist of the functions permitted to name
        that model closes all of them at once, the way
        `TestTheShelfIsTheOnlyWayIn` does for `Book`. That turns this from "no
        spelling I thought of" into "these are the whole write surface". See
        `docs/decisions.md`.

        The absence of a route or a UI control is deliberately **not** what is
        claimed here: the module itself must have no way to do it.
        """
        source = (Path(__file__).resolve().parent.parent / "authorship.py").read_text()
        tree = ast.parse(source)
        guarded = {"identifier", "provenance"}
        dynamic_setters = {"setattr", "__setattr__", "__set__"}
        # **`merge` is deliberately absent**: this module has a method by that
        # name, so adding it would fail on clean source. None of the names below
        # appears in `authorship.py`, so the list costs nothing today.
        bulk_writers = {
            "update",
            "values",
            "execute",
            "exec_driver_sql",
            "scalar",
            "scalars",
            "bulk_update_mappings",
            "bulk_save_objects",
        }

        written: set[str] = set()
        dynamic = 0
        bulk = 0
        for node in ast.walk(tree):
            # 1 and 2: any store, in any statement form.
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
                written.add(node.attr)
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.ctx, ast.Store)
                and isinstance(node.slice, ast.Constant)
            ):
                written.add(str(node.slice.value))
            # 4: a dynamic setter named any way at all.
            if isinstance(node, ast.Name) and node.id in dynamic_setters:
                dynamic += 1
            if isinstance(node, ast.Attribute) and node.attr in dynamic_setters:
                dynamic += 1
            if isinstance(node, ast.Constant) and node.value in dynamic_setters:
                dynamic += 1
            # 3: a bulk write, however the callable was bound.
            if isinstance(node, ast.Call):
                called = node.func
                name = (
                    called.attr
                    if isinstance(called, ast.Attribute)
                    else called.id
                    if isinstance(called, ast.Name)
                    else ""
                )
                if name in bulk_writers:
                    bulk += 1

        assert not (written & guarded), sorted(written & guarded)
        assert dynamic == 0
        assert bulk == 0
        # The field a merge does rewrite, kept beside these so the asymmetry
        # reads as deliberate rather than as an omission.
        assert "canonical_name" in written

    def test_a_member_may_remove_one(self, db, user):
        shelve(db, user, "Sean P. Kane")
        authorship = Authorship.seen_by(db, user.id)
        [row] = authorship.record_catalogue_assertions([KANE], credited=KANE.name).stored
        row_id = row.id

        authorship.forget_identifier(row_id)

        assert db.get(AuthorIdentifier, row_id) is None

    def test_re_import_puts_it_back(self, db, user):
        """Removal is the correction and re-import is the undo, so nothing is
        lost that a catalogue cannot say again."""
        shelve(db, user, "Sean P. Kane")
        authorship = Authorship.seen_by(db, user.id)
        [row] = authorship.record_catalogue_assertions([KANE], credited=KANE.name).stored
        authorship.forget_identifier(row.id)

        authorship.record_catalogue_assertions([KANE], credited=KANE.name)

        assert db.query(AuthorIdentifier).one().identifier == "1042243212"

    def test_removing_a_row_you_cannot_see_the_effect_of_raises(
        self, db, user, other
    ):
        """Authority rather than secrecy, the same rule `unmerge` applies: the
        page offers this beside the spelling it names, and a row with no such
        spelling on your shelf has no meaning here."""
        shelve(db, other, "Sean P. Kane", private=True)
        Authorship.seen_by(db, other.id).record_catalogue_assertions([KANE], credited=KANE.name)
        row_id = db.query(AuthorIdentifier).one().id

        with pytest.raises(AuthorNotFound):
            Authorship.seen_by(db, user.id).forget_identifier(row_id)

        assert db.get(AuthorIdentifier, row_id) is not None

    def test_removing_a_row_that_does_not_exist_raises(self, db, user):
        with pytest.raises(AuthorNotFound):
            Authorship.seen_by(db, user.id).forget_identifier(9999)


class TestAnIdentifierIsPerSpellingNotPerPerson:
    def test_two_folded_spellings_may_carry_different_identifiers(self, db, user):
        """Both persist. Either the local merge is wrong or the upstream
        cluster is, and nothing here can tell which."""
        shelve(db, user, "Sean P. Kane", "S. Kane")
        authorship = Authorship.seen_by(db, user.id)
        authorship.record_catalogue_assertions(
            [KANE, AuthorityAssertion("S. Kane", AuthorityScheme.GND, "9999")],
            credited=f"{KANE.name}, S. Kane",
        )

        authorship.merge(
            [author_key("Sean P. Kane"), author_key("S. Kane")],
            "Sean P. Kane",
            by_user_id=user.id,
        )

        assert db.query(AuthorIdentifier).count() == 2

    def test_the_disagreement_is_reported_on_the_author(self, db, user):
        shelve(db, user, "Sean P. Kane", "S. Kane")
        authorship = Authorship.seen_by(db, user.id)
        authorship.record_catalogue_assertions(
            [KANE, AuthorityAssertion("S. Kane", AuthorityScheme.GND, "9999")],
            credited=f"{KANE.name}, S. Kane",
        )
        authorship.merge(
            [author_key("Sean P. Kane"), author_key("S. Kane")],
            "Sean P. Kane",
            by_user_id=user.id,
        )

        [author] = authorship.listing()

        assert author.identifier_conflicts == [AuthorityScheme.GND]
        assert {row.identifier for row in author.identifiers} == {
            "1042243212",
            "9999",
        }

    def test_two_spellings_agreeing_is_not_a_conflict(self, db, user):
        """The case a merge is usually made from. Not unique on the identifier,
        for exactly this reason."""
        shelve(db, user, "Sean P. Kane", "S. Kane")
        authorship = Authorship.seen_by(db, user.id)
        authorship.record_catalogue_assertions(
            [KANE, AuthorityAssertion("S. Kane", AuthorityScheme.GND, "1042243212")],
            credited=f"{KANE.name}, S. Kane",
        )
        authorship.merge(
            [author_key("Sean P. Kane"), author_key("S. Kane")],
            "Sean P. Kane",
            by_user_id=user.id,
        )

        [author] = authorship.listing()

        assert author.identifier_conflicts == []
        assert len(author.identifiers) == 2

    def test_an_author_with_no_identifier_reports_no_conflict(self, db, user):
        shelve(db, user, "Terry Pratchett")

        [author] = Authorship.seen_by(db, user.id).listing()

        assert author.identifiers == []
        assert author.identifier_conflicts == []


class TestThePrivacyLineOnTheIdentifierTable:
    def test_a_row_for_a_spelling_only_on_a_private_book_is_not_listed(
        self, db, user, other
    ):
        """The rows are Library wide, like the aliases, and listing one whose
        spelling survives only on somebody else's Private Book would announce
        that the Book exists."""
        shelve(db, other, "Sean P. Kane", private=True)
        Authorship.seen_by(db, other.id).record_catalogue_assertions([KANE], credited=KANE.name)
        shelve(db, user, "Terry Pratchett")

        listing = Authorship.seen_by(db, user.id).listing()

        assert all(author.identifiers == [] for author in listing)

    def test_the_listing_costs_one_statement_more_than_the_index(self, db, user):
        """`_load` is unchanged at two, and only the listing pays for the third.

        Measured at both ends rather than at one: a claim that the cost does not
        grow is a claim about two shelf sizes.
        """
        shelve(db, user, "Sean P. Kane")
        viewer_id = user.id
        one = len(selects(lambda: Authorship.seen_by(db, viewer_id).listing()))

        shelve(db, user, *[f"Author {index}" for index in range(40)])
        many = len(selects(lambda: Authorship.seen_by(db, viewer_id).listing()))

        assert one == many == 3


class TestAMergedNameIsNotEvidenceOfAnything:
    """A `keep_name` is typed by a person, so it proves no Book exists.

    The reachable key set used to include `entry.key`, which is derived from
    that typed name. `merge` accepts a `keep_name` no Book carries by design, so
    a member could guess a spelling and reach rows derived from somebody else's
    Private Book. `_evidenced_keys` carries the measurement.
    """

    @staticmethod
    def _strangers_private_identifier(db, other) -> int:
        shelve(db, other, "Sean P. Kane", private=True)
        Authorship.seen_by(db, other.id).record_catalogue_assertions([KANE], credited=KANE.name)
        return db.query(AuthorIdentifier).one().id

    def test_guessing_a_name_does_not_reveal_a_private_books_identifier(
        self, db, user, other
    ):
        self._strangers_private_identifier(db, other)
        shelve(db, user, "Terry Pratchett")
        authorship = Authorship.seen_by(db, user.id)

        authorship.merge(
            [author_key("Terry Pratchett")], "Sean P. Kane", by_user_id=user.id
        )

        assert all(author.identifiers == [] for author in authorship.listing())

    def test_guessing_a_name_does_not_reach_the_authority_lookups_door(
        self, db, user, other
    ):
        """`identifiers_for` is what `GET /authors/authority` asks, so it is a
        second door onto the same rows and needs the same rule."""
        self._strangers_private_identifier(db, other)
        shelve(db, user, "Terry Pratchett")
        authorship = Authorship.seen_by(db, user.id)
        authorship.merge(
            [author_key("Terry Pratchett")], "Sean P. Kane", by_user_id=user.id
        )

        assert authorship.identifiers_for("Sean P. Kane") == []

    def test_guessing_a_name_does_not_let_a_member_delete_the_row(
        self, db, user, other
    ):
        """The worse half: a destructive write against data derived from a Book
        the caller cannot see."""
        row_id = self._strangers_private_identifier(db, other)
        shelve(db, user, "Terry Pratchett")
        authorship = Authorship.seen_by(db, user.id)
        authorship.merge(
            [author_key("Terry Pratchett")], "Sean P. Kane", by_user_id=user.id
        )

        with pytest.raises(AuthorNotFound):
            authorship.forget_identifier(row_id)

        assert db.get(AuthorIdentifier, row_id) is not None

    def test_an_ordinary_author_is_unaffected(self, db, user):
        """Dropping `entry.key` from the set costs nothing in the normal case:
        an unmerged author's key is the key of its own most used spelling."""
        shelve(db, user, "Sean P. Kane")
        authorship = Authorship.seen_by(db, user.id)
        authorship.record_catalogue_assertions([KANE], credited=KANE.name)

        [author] = authorship.listing()

        assert [row.identifier for row in author.identifiers] == ["1042243212"]


class TestAConfirmationIsFiledOnASpellingTheShelfCarries:
    def test_it_is_not_filed_under_a_typed_display_name(self, db, user):
        """Filed under `entry.name` it landed on a key no Book carries, which
        `_evidenced_keys` cannot reach by construction."""
        shelve(db, user, "R. L. Stevenson")
        authorship = Authorship.seen_by(db, user.id)
        authorship.merge(
            [author_key("R. L. Stevenson")],
            "Robert Louis Stevenson",
            by_user_id=user.id,
        )

        row = authorship.confirm_identifier(
            "Robert Louis Stevenson",
            AuthorityScheme.GND,
            "118753711",
            by_user_id=user.id,
        )

        assert row.author_key == author_key("R. L. Stevenson")

    def test_a_second_merge_does_not_orphan_it(self, db, user):
        """The defect this replaced: the display name moves with every merge, so
        a row filed under it became invisible and undeletable the next time
        somebody tidied the name."""
        shelve(db, user, "R. L. Stevenson")
        authorship = Authorship.seen_by(db, user.id)
        authorship.merge(
            [author_key("R. L. Stevenson")], "R.L. Stevenson", by_user_id=user.id
        )
        row = authorship.confirm_identifier(
            "R.L. Stevenson", AuthorityScheme.GND, "118753711", by_user_id=user.id
        )

        authorship.merge(
            [author_key("R. L. Stevenson")],
            "Robert Louis Stevenson",
            by_user_id=user.id,
        )

        [author] = authorship.listing()
        assert [entry.identifier for entry in author.identifiers] == ["118753711"]
        authorship.forget_identifier(row.id)
        assert db.get(AuthorIdentifier, row.id) is None


class TestALosingAssertionIsReportedRatherThanDiscarded:
    """Precedence was the defect, and it needed no column to fix.

    The store holds one value per spelling per scheme, which is what makes an
    identifier unretypeable, so a second value cannot be stored. It used to
    vanish into a `logger.info`, which is whoever wrote first winning silently.
    """

    def test_a_second_catalogue_value_comes_back_as_refused(self, db, user):
        shelve(db, user, "Sean P. Kane")
        authorship = Authorship.seen_by(db, user.id)
        authorship.record_catalogue_assertions([KANE], credited=KANE.name)

        recorded = authorship.record_catalogue_assertions(
            [AuthorityAssertion("Sean P. Kane", AuthorityScheme.GND, "9999")], credited=KANE.name
        )

        [refused] = recorded.refused
        assert (refused.asserted, refused.kept) == ("9999", "1042243212")
        assert recorded.stored == []

    def test_the_stored_value_still_stands(self, db, user):
        shelve(db, user, "Sean P. Kane")
        authorship = Authorship.seen_by(db, user.id)
        authorship.record_catalogue_assertions([KANE], credited=KANE.name)

        authorship.record_catalogue_assertions(
            [AuthorityAssertion("Sean P. Kane", AuthorityScheme.GND, "9999")], credited=KANE.name
        )

        assert db.query(AuthorIdentifier).one().identifier == "1042243212"

    def test_a_members_guess_outranking_a_catalogue_says_so(self, db, user):
        """The live case, and the one that inverts the feature's own premise: a
        person's guess beats a national library and nothing said so.
        `kept_provenance` is what makes it actionable."""
        shelve(db, user, "Sean P. Kane")
        authorship = Authorship.seen_by(db, user.id)
        authorship.confirm_identifier(
            "Sean P. Kane", AuthorityScheme.GND, "1111", by_user_id=user.id
        )

        recorded = authorship.record_catalogue_assertions([KANE], credited=KANE.name)

        [refused] = recorded.refused
        assert refused.kept_provenance == AuthorityProvenance.MEMBER
        assert (refused.asserted, refused.kept) == ("1042243212", "1111")

    def test_an_agreeing_assertion_refuses_nothing(self, db, user):
        shelve(db, user, "Sean P. Kane")
        authorship = Authorship.seen_by(db, user.id)
        authorship.record_catalogue_assertions([KANE], credited=KANE.name)

        recorded = authorship.record_catalogue_assertions([KANE], credited=KANE.name)

        assert recorded.refused == []
        assert len(recorded.stored) == 1

    def test_nothing_about_a_refusal_is_stored(self, db, user):
        """A fact about one request, not about the Library. No column, no
        migration, and nothing to clean up later."""
        shelve(db, user, "Sean P. Kane")
        authorship = Authorship.seen_by(db, user.id)
        authorship.record_catalogue_assertions([KANE], credited=KANE.name)
        authorship.record_catalogue_assertions(
            [AuthorityAssertion("Sean P. Kane", AuthorityScheme.GND, "9999")], credited=KANE.name
        )

        assert db.query(AuthorIdentifier).count() == 1


class TestOnlyAnAssertionTheBookCreditsIsStored:
    """`credited` is the Book's own credit line, and it is required.

    Without it an assertion landed on whatever the catalogue spelled, which on
    an ordinary enrichment is a spelling the Library never adopted:
    `google_books.merge_into` skips `author` when the Book has one and
    `overwrite` is false.
    """

    def test_a_spelling_the_book_does_not_carry_is_not_stored(self, db, user):
        shelve(db, user, "S. P. Kane")

        recorded = Authorship.seen_by(db, user.id).record_catalogue_assertions(
            [KANE], credited="S. P. Kane"
        )

        assert recorded.stored == []
        assert db.query(AuthorIdentifier).count() == 0

    def test_dropping_it_is_not_reported_as_a_refusal(self, db, user):
        """A bound rather than a disagreement: nothing was overruled and there
        is nothing for a Member to act on."""
        shelve(db, user, "S. P. Kane")

        recorded = Authorship.seen_by(db, user.id).record_catalogue_assertions(
            [KANE], credited="S. P. Kane"
        )

        assert recorded.refused == []

    def test_the_spelling_the_book_carries_is_stored(self, db, user):
        shelve(db, user, "Sean P. Kane")

        recorded = Authorship.seen_by(db, user.id).record_catalogue_assertions(
            [KANE], credited="Sean P. Kane"
        )

        assert [row.author_key for row in recorded.stored] == [
            author_key("Sean P. Kane")
        ]

    def test_one_credited_author_of_several_still_qualifies(self, db, user):
        """A credit line is a comma joined list of people, and an assertion
        names one of them."""
        shelve(db, user, "Sean P. Kane, Karl Matthias")

        recorded = Authorship.seen_by(db, user.id).record_catalogue_assertions(
            [KANE], credited="Sean P. Kane, Karl Matthias"
        )

        assert len(recorded.stored) == 1

    def test_a_book_with_no_author_stores_nothing(self, db, user):
        recorded = Authorship.seen_by(db, user.id).record_catalogue_assertions(
            [KANE], credited=None
        )

        assert recorded.stored == []

    def test_everything_stored_lands_on_a_key_the_listing_can_reach(self, db, user):
        """The guarantee stated on `_evidenced_keys`, asserted rather than
        described: whatever this writes is visible and deletable."""
        shelve(db, user, "Sean P. Kane")
        authorship = Authorship.seen_by(db, user.id)

        recorded = authorship.record_catalogue_assertions(
            [KANE], credited="Sean P. Kane"
        )

        listed = {
            row.id for author in authorship.listing() for row in author.identifiers
        }
        assert {row.id for row in recorded.stored} == listed
        for row in recorded.stored:
            authorship.forget_identifier(row.id)
        assert db.query(AuthorIdentifier).count() == 0


class TestTheCrossReferencesStoredWithAConfirmation:
    """`record_cross_references`, the second half of `confirm_identifier`.

    A Member confirms a **person**, and the GND record for that person already
    carries their ISNI, LCNAF number, VIAF cluster and Wikidata item. All four
    used to be shown once and dropped.
    """

    @staticmethod
    def _references() -> dict[AuthorityScheme, str]:
        """Borges as lobid answers, measured 2026-08-28 on GND `118513532`."""
        return {
            AuthorityScheme.ISNI: "0000000121429031",
            AuthorityScheme.LCNAF: "n79007035",
            AuthorityScheme.VIAF: "88919448",
            AuthorityScheme.WIKIDATA: "Q909",
        }

    def test_every_scheme_lands_as_its_own_row(self, db, user):
        shelve(db, user, "Jorge Luis Borges")
        authorship = Authorship.seen_by(db, user.id)

        recorded = authorship.record_cross_references(
            "Jorge Luis Borges", self._references(), by_user_id=user.id
        )

        assert {(row.scheme, row.identifier) for row in recorded.stored} == {
            (scheme, value) for scheme, value in self._references().items()
        }
        assert recorded.refused == []

    def test_the_rows_say_a_person_asserted_them(self, db, user):
        """The identifier is the authority file's, but nothing tied it to this
        author until somebody said the record was theirs. `CATALOGUE` would
        claim the DNB asserted it about a Book this Library holds, which is not
        what happened, and `ck_author_identifiers_asserter` forbids naming the
        asserter on such a row anyway."""
        shelve(db, user, "Jorge Luis Borges")

        recorded = Authorship.seen_by(db, user.id).record_cross_references(
            "Jorge Luis Borges", self._references(), by_user_id=user.id
        )

        assert all(
            row.provenance == AuthorityProvenance.MEMBER for row in recorded.stored
        )
        assert all(row.created_by_user_id == user.id for row in recorded.stored)

    def test_it_files_under_the_same_key_a_confirmation_does(self, db, user):
        """Both go through `_confirmable_key`, so a confirmation and the cross
        references that came with it cannot land on two different spellings and
        make one of them unreachable from `listing()`."""
        shelve(db, user, "Jorge Luis Borges")
        authorship = Authorship.seen_by(db, user.id)
        confirmed = authorship.confirm_identifier(
            "Jorge Luis Borges", AuthorityScheme.GND, "118513532", by_user_id=user.id
        )

        recorded = authorship.record_cross_references(
            "Jorge Luis Borges", self._references(), by_user_id=user.id
        )

        assert {row.author_key for row in recorded.stored} == {confirmed.author_key}
        assert len(authorship.identifiers_for("Jorge Luis Borges")) == 5

    def test_a_collision_is_reported_and_the_stored_value_stands(self, db, user):
        """**Reported, not raised, and that is the difference from
        `confirm_identifier`.** The confirmation is what the Member asked for; a
        fact arriving alongside it must not undo one that succeeded."""
        shelve(db, user, "Jorge Luis Borges")
        authorship = Authorship.seen_by(db, user.id)
        authorship.confirm_identifier(
            "Jorge Luis Borges", AuthorityScheme.ISNI, "0000000000000001",
            by_user_id=user.id,
        )

        recorded = authorship.record_cross_references(
            "Jorge Luis Borges", self._references(), by_user_id=user.id
        )

        [refused] = recorded.refused
        assert (refused.scheme, refused.asserted, refused.kept) == (
            AuthorityScheme.ISNI,
            "0000000121429031",
            "0000000000000001",
        )
        assert refused.kept_provenance == AuthorityProvenance.MEMBER
        assert {row.scheme for row in recorded.stored} == {
            AuthorityScheme.LCNAF,
            AuthorityScheme.VIAF,
            AuthorityScheme.WIKIDATA,
        }

    def test_running_it_twice_writes_nothing_the_second_time(self, db, user):
        """A re-confirmation is an ordinary thing to do and must not produce a
        second row, which `uq_author_identifiers_key_scheme` would refuse with
        an `IntegrityError` rather than a report."""
        shelve(db, user, "Jorge Luis Borges")
        authorship = Authorship.seen_by(db, user.id)
        authorship.record_cross_references(
            "Jorge Luis Borges", self._references(), by_user_id=user.id
        )

        again = authorship.record_cross_references(
            "Jorge Luis Borges", self._references(), by_user_id=user.id
        )

        assert again.refused == []
        assert db.query(AuthorIdentifier).count() == 4

    def test_an_author_nobody_can_see_raises(self, db, user, other):
        """The same authority rule `confirm_identifier` applies: confirm what
        you can see the effect of."""
        shelve(db, user, "Jorge Luis Borges", private=True)

        with pytest.raises(AuthorNotFound):
            Authorship.seen_by(db, other.id).record_cross_references(
                "Jorge Luis Borges", self._references(), by_user_id=other.id
            )

    def test_an_unstorable_value_is_dropped_rather_than_raising(self, db, user):
        """`ck_author_identifiers_bounds` would refuse it at the database, which
        is a 500 on a request whose confirmation already succeeded."""
        shelve(db, user, "Jorge Luis Borges")

        recorded = Authorship.seen_by(db, user.id).record_cross_references(
            "Jorge Luis Borges",
            {AuthorityScheme.ISNI: "", AuthorityScheme.VIAF: "88919448"},
            by_user_id=user.id,
        )

        assert {row.scheme for row in recorded.stored} == {AuthorityScheme.VIAF}
