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

import authorship as authorship_module
from authors import DEFAULT_MATCHER, EXACT_MATCHER, author_key, resolve_alias_map
from authors import SuggestionReason as Reason
from authorship import (
    IDENTITY_SPINE,
    MAX_ASSERTIONS_PER_RECORD,
    AuthorNotFound,
    Authorship,
    DecisionStands,
    IdentifierConflict,
)
from catalogue import AuthorityAssertion
from database import Base, engine
from enums import AuthorityProvenance, AuthorityScheme
from models import (
    AUTHORITY_IDENTIFIER_MAX,
    AuthorAlias,
    AuthorIdentifier,
    Book,
    User,
)
from schemas.author import AuthorMergeGroup, AuthorSuggestionOut

KANE = AuthorityAssertion("Sean P. Kane", AuthorityScheme.GND, "1042243212")

#: Dickens' ISNI, used wherever a test needs the spine to say two spellings are
#: one person. A real number rather than an invented one, so a reader can check
#: it, and a pen name rather than a misspelling, because that is the case no rule
#: reading letters can reach.
DICKENS = "0000000121174585"

#: Two numbers bracketing it, so a contested author can be built whose lowest
#: value is `DICKENS` and another whose highest is. One of the two is enough to
#: let a rule that keeps a value rather than dropping the author pass, because
#: it files that author under the number nobody else carries.
BELOW_DICKENS = "0000000000000001"
ABOVE_DICKENS = "0000000999999999"


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


def _identify(db, user, name: str, identifier: str, scheme=IDENTITY_SPINE) -> None:
    """File one authority identifier under a spelling the shelf carries."""
    Authorship.seen_by(db, user.id).confirm_identifier(
        name, scheme, identifier, by_user_id=user.id
    )


class TestOnlyTheSpineSaysTwoSpellingsAreOnePerson:
    """Every authority file this app stores, asked whether it may decide identity.

    **The exclusion is derived from `AuthorityScheme` rather than listed**, which
    is the difference between a guard and an inclusion list: a file another
    change adds to the roster is covered here without anybody remembering to add
    an arm, and it fails loudly if that file acquires the power the spine has.

    The interesting rows are the ones that look most like an identity and are
    not. A VIAF cluster id is the one the ruling names: clusters split and merge,
    and `Stevenson, Robert Louis` was measured resolving to four personal
    clusters, so a spine built on one would offer a merge that changes when
    nothing in this database has. A GND number is a record in a national file. So
    is each of the six national numbers. All of them are stored, shown and
    fetched back from; none of them says who somebody is.
    """

    @pytest.mark.parametrize("scheme", list(AuthorityScheme))
    def test_exactly_one_scheme_groups_two_spellings_and_it_is_the_spine(
        self, db, user, scheme
    ):
        shelve(db, user, "Boz", "Charles Dickens")
        _identify(db, user, "Boz", DICKENS, scheme)
        _identify(db, user, "Charles Dickens", DICKENS, scheme)

        grouped = [
            group
            for group in Authorship.seen_by(db, user.id).suggestions()
            if Reason.IDENTITY in group.reasons
        ]

        assert bool(grouped) is (scheme is IDENTITY_SPINE), scheme

    def test_the_pair_is_reachable_by_no_other_rule(self, db, user):
        """The control the row above needs, or every arm of it could be passing
        because nothing on this shelf suggests anything at all."""
        shelve(db, user, "Boz", "Charles Dickens")

        assert Authorship.seen_by(db, user.id).suggestions() == []

    def test_the_spine_is_isni(self):
        """The only line in either test tree that pins **which** file the spine
        is, and it is load bearing rather than decorative.

        The parametrized test above reads `IDENTITY_SPINE` itself, so it
        enforces that exactly one scheme decides identity and is silent about
        which: a mutation repointing the constant at VIAF moves that guard with
        it and every arm stays green. Measured, and this test was the only
        failure. Deleting it leaves the roster's most churning identifier able
        to become the spine with nothing going red.
        """
        assert IDENTITY_SPINE is AuthorityScheme.ISNI


class TestThePrivacyLineOnTheSpine:
    """A merge suggestion is a new door onto `author_identifiers`, and it needs
    the rule the other doors have.

    `_evidenced_keys` records a measured breach: `entry.key` is derived from a
    `keep_name` a member typed, `merge` accepts one no Book carries, so a guessed
    spelling reached rows derived from somebody else's Private Book. `listing`,
    `identifiers_for` and `forget_identifier` were the three doors then. This is
    a fourth, and it leaks differently: nothing shows the row, but the merge
    offered tells the caller that some author of theirs shares an identifier with
    a name they guessed.
    """

    @staticmethod
    def _strangers_private_spine(db, other) -> None:
        shelve(db, other, "Sean P. Kane", private=True)
        _identify(db, other, "Sean P. Kane", DICKENS)

    def test_guessing_a_name_does_not_borrow_its_identity(self, db, user, other):
        self._strangers_private_spine(db, other)
        shelve(db, user, "Terry Pratchett", "Boz")
        _identify(db, user, "Boz", DICKENS)
        authorship = Authorship.seen_by(db, user.id)

        authorship.merge(
            [author_key("Terry Pratchett")], "Sean P. Kane", by_user_id=user.id
        )

        assert all(Reason.IDENTITY not in group.reasons for group in authorship.suggestions())

    def test_and_an_evidenced_spelling_carrying_it_is_grouped(self, db, user):
        """The other half of the diagonal. Without it the test above passes on a
        spine that never groups anything, which is a guard for nothing."""
        shelve(db, user, "Terry Pratchett", "Boz")
        _identify(db, user, "Boz", DICKENS)
        _identify(db, user, "Terry Pratchett", DICKENS)

        [group] = [
            group
            for group in Authorship.seen_by(db, user.id).suggestions()
            if Reason.IDENTITY in group.reasons
        ]

        assert set(group.names) == {"Boz", "Terry Pratchett"}


class TestASpineDisagreementIsReportedAndSettlesNothing:
    def test_two_folded_spellings_holding_different_isnis_are_reported(
        self, db, user
    ):
        """Reported exactly as a GND disagreement is, which is the ticket's
        second open question answered in the tree rather than in a handoff."""
        shelve(db, user, "Boz", "Charles Dickens")
        _identify(db, user, "Boz", DICKENS)
        _identify(db, user, "Charles Dickens", "0000000000000001")
        authorship = Authorship.seen_by(db, user.id)
        authorship.merge(
            [author_key("Boz"), author_key("Charles Dickens")],
            "Charles Dickens",
            by_user_id=user.id,
        )

        [author] = authorship.listing()

        assert IDENTITY_SPINE in author.identifier_conflicts

    def test_a_contested_author_pulls_nobody_else_in(self, db, user):
        """Keeping either value would be resolution by ordering, which is the
        call `authority._viaf_sources` refuses one layer up.

        Two contested authors, bracketing the shared number from both sides, for
        the reason `test_an_author_holding_two_isnis_pulls_nobody_in` records:
        one of them lets a rule that keeps `min` pass without dropping anything.
        """
        shelve(
            db, user, "Boz",
            "Charles Dickens", "C. Dickens",
            "Ellis Bell", "E. Bell",
        )
        _identify(db, user, "Boz", DICKENS)
        _identify(db, user, "Charles Dickens", DICKENS)
        _identify(db, user, "C. Dickens", ABOVE_DICKENS)
        _identify(db, user, "Ellis Bell", DICKENS)
        _identify(db, user, "E. Bell", BELOW_DICKENS)
        authorship = Authorship.seen_by(db, user.id)
        authorship.merge(
            [author_key("Charles Dickens"), author_key("C. Dickens")],
            "Charles Dickens",
            by_user_id=user.id,
        )
        authorship.merge(
            [author_key("Ellis Bell"), author_key("E. Bell")],
            "Ellis Bell",
            by_user_id=user.id,
        )

        assert all(Reason.IDENTITY not in group.reasons for group in authorship.suggestions())


class TestAnAuthorWithNoSpine:
    """The ticket's first open question, confirmed rather than assumed. It is the
    common case: a self published book carries no authority record at all."""

    def test_the_spelling_stays_the_key_and_the_suggestions_are_unchanged(
        self, db, user
    ):
        shelve(db, user, "U. K. Le Guin", "Ursula K. Le Guin")

        [group] = Authorship.seen_by(db, user.id).suggestions()

        assert group.reasons == [Reason.INITIALS]

    def test_the_author_page_is_what_it_was(self, db, user):
        shelve(db, user, "Ursula K. Le Guin")

        [author] = Authorship.seen_by(db, user.id).listing()

        assert (author.key, author.book_count, author.identifiers) == (
            author_key("Ursula K. Le Guin"),
            1,
            [],
        )


class TestIdentityIsDerivedAndNeverMinted:
    """Clause one of the ruling, enforced against the schema rather than stated.

    `AuthorAlias` says authors are not rows: `books.author` is free text, an
    author page is a `GROUP BY`, and neither identity table carries a foreign key
    to an author **because there is nothing to point at**. A table minting an id
    would make the spelling stop being the key, and every rule in `authors.py`
    reads a spelling.
    """

    def test_no_table_holds_an_author(self):
        """`Base` is imported from `database`, which declares it. `models` holds
        the tables and does not re-export it, and reaching the same registry
        through `AuthorAlias.__table__` types as a `FromClause`."""
        assert "authors" not in Base.metadata.tables

    def test_neither_identity_table_points_at_one(self):
        """Stated as the exclusion: the only thing either may reference is the
        person who wrote the row down, which is a `users` row and not an author.
        A list of the columns that are allowed to be keys is what goes stale."""
        referenced = {
            key.column.table.name
            for table in (AuthorAlias.__table__, AuthorIdentifier.__table__)
            for column in table.columns
            for key in column.foreign_keys
        }

        assert referenced <= {"users"}


def _group(suggestions, *names: str) -> AuthorSuggestionOut:
    """The suggested group holding exactly these names."""
    wanted = set(names)
    return next(group for group in suggestions if set(group.names) == wanted)


class _NoScan(dict):
    """A dict that answers a lookup and refuses to be walked.

    For asking `_would_repoint` whether it scans. `dict.get` and `in` are
    untouched; everything that iterates the whole table raises, which is what
    the alias table must never be subjected to once per group.

    **Five names, and they are the surface rather than an enumeration of it**,
    which was checked rather than assumed because a list of names is the shape
    that usually leaks. `copy()`, `dict(d)` and `{**d}` all refuse as well:
    CPython's fast path is for an exact `dict`, so a subclass falls back to
    `keys`. `__reversed__` is here because it was the one real escape, found by
    probing rather than by reading.
    """

    def _refuse(self, *args, **kwargs):
        raise AssertionError("the alias table was walked rather than looked up")

    __iter__ = _refuse
    __reversed__ = _refuse
    keys = _refuse
    values = _refuse
    items = _refuse


def _points_at(db) -> dict[str, str]:
    """Which person every alias row currently means, keyed by the spelling."""
    return {
        row.alias_key: author_key(row.canonical_name)
        for row in db.query(AuthorAlias).all()
    }


class TestWhatABatchWouldFold:
    """The preview: every group, with the name it would be folded into.

    A group with no `keep_name` is held back, and the only thing that holds one
    back is that applying it would repoint a row somebody wrote.
    """

    @staticmethod
    def _split_le_guin(db, user) -> None:
        """One person on the shelf three ways, the catalogue order split among
        them, and the whole name on the fewest Books.

        Written this way round on purpose: the most credited name is `Le Guin`,
        so a proposal naming `Ursula K. Le Guin` can only have come from a
        decision rather than from the count.
        """
        shelve(db, user, "Le Guin, Ursula K.", "Le Guin, Ursula K.", "Le Guin, Ursula K.")
        shelve(db, user, "Ursula K. Le Guin")

    def test_with_nothing_decided_the_most_credited_name_is_proposed(self, db, user):
        self._split_le_guin(db, user)

        groups = Authorship.seen_by(db, user.id).suggestions()

        assert _group(groups, "Le Guin", "Ursula K.", "Ursula K. Le Guin").keep_name == (
            "Le Guin"
        )

    def test_a_name_somebody_merged_into_wins_over_the_count(self, db, user):
        """The case a batch exists for: an import creates a spelling of somebody
        a Member established, and it is filed under the name they chose."""
        self._split_le_guin(db, user)
        authorship = Authorship.seen_by(db, user.id)
        shelve(db, user, "U. K. Le Guin")
        authorship.merge(
            [author_key("U. K. Le Guin"), author_key("Ursula K. Le Guin")],
            "Ursula K. Le Guin",
            by_user_id=user.id,
        )

        groups = authorship.suggestions()

        assert _group(
            groups, "Le Guin", "Ursula K.", "Ursula K. Le Guin"
        ).keep_name == "Ursula K. Le Guin"

    def test_two_decided_names_in_one_group_hold_it_back(self, db, user):
        """No rule here is entitled to pick between two people's decisions."""
        self._split_le_guin(db, user)
        authorship = Authorship.seen_by(db, user.id)
        shelve(db, user, "U. K. Le Guin", "Ursula Le Guin")
        authorship.merge(
            [author_key("U. K. Le Guin"), author_key("Ursula K. Le Guin")],
            "Ursula K. Le Guin",
            by_user_id=user.id,
        )
        authorship.merge(
            [author_key("Ursula Le Guin"), author_key("Le Guin")],
            "Le Guin",
            by_user_id=user.id,
        )

        held = _group(authorship.suggestions(), "Le Guin", "Ursula K.", "Ursula K. Le Guin")

        assert held.keep_name is None
        assert held.names  # still listed, so a reader knows it was considered

    def test_a_decision_only_visible_to_somebody_else_still_holds_the_name(
        self, db, user, other
    ):
        """The privacy shaped half, and it runs the other way from the usual one.

        A decision whose folded spelling is on a Private Book is invisible to
        this Member. Read off `entry.alias_keys` it would look like no decision
        at all and the batch would repoint it, so the alias table is read whole.
        What that costs is stated in `_decided_keys`; what it buys is here.
        """
        shelve(db, other, "Boz", private=True)
        Authorship.seen_by(db, other.id).merge(
            [author_key("Boz")], "Charles Dickens", by_user_id=other.id
        )
        shelve(db, user, "C. Dickens", "C. Dickens", "C. Dickens")
        shelve(db, user, "Charles Dickens")

        groups = Authorship.seen_by(db, user.id).suggestions()

        assert _group(groups, "C. Dickens", "Charles Dickens").keep_name == (
            "Charles Dickens"
        )

    def test_and_without_that_row_the_count_would_have_won(self, db, user):
        """The control the test above needs: `C. Dickens` is the more credited
        name, so the proposal is only evidence of anything if it changes."""
        shelve(db, user, "C. Dickens", "C. Dickens", "C. Dickens")
        shelve(db, user, "Charles Dickens")

        groups = Authorship.seen_by(db, user.id).suggestions()

        assert _group(groups, "C. Dickens", "Charles Dickens").keep_name == "C. Dickens"

    def test_the_preview_writes_nothing(self, db, user):
        self._split_le_guin(db, user)

        Authorship.seen_by(db, user.id).suggestions()

        assert db.query(AuthorAlias).count() == 0

    def test_a_narrower_matcher_proposes_fewer_groups(self, db, user):
        self._split_le_guin(db, user)
        authorship = Authorship.seen_by(db, user.id)

        assert authorship.suggestions(EXACT_MATCHER) == []
        assert authorship.suggestions(DEFAULT_MATCHER) != []


class TestABatchIsOneTransactionOrNothing:
    """Every confirmed group applies, or none does and the Library is untouched.

    That is what makes the preview a review: a Member who reads a refusal has
    nothing to reconstruct, because there is no half applied state to describe.
    """

    @staticmethod
    def _two_groups(db, user) -> list[AuthorMergeGroup]:
        shelve(db, user, "JRR Tolkien", "J. R. R. Tolkien")
        shelve(db, user, "U. K. Le Guin", "Ursula K. Le Guin")
        return [
            AuthorMergeGroup(
                keys=[author_key("JRR Tolkien"), author_key("J. R. R. Tolkien")],
                keep_name="J. R. R. Tolkien",
            ),
            AuthorMergeGroup(
                keys=[author_key("U. K. Le Guin"), author_key("Ursula K. Le Guin")],
                keep_name="Ursula K. Le Guin",
            ),
        ]

    def test_every_group_is_applied(self, db, user):
        groups = self._two_groups(db, user)

        answered = Authorship.seen_by(db, user.id).merge_batch(
            groups, by_user_id=user.id
        )

        assert [author.name for author in answered.merged] == [
            "J. R. R. Tolkien",
            "Ursula K. Le Guin",
        ]
        assert db.query(AuthorAlias).count() == 4

    def test_nothing_in_books_is_written(self, db, user):
        groups = self._two_groups(db, user)
        before = sorted(book.author for book in db.query(Book).all())

        Authorship.seen_by(db, user.id).merge_batch(groups, by_user_id=user.id)

        assert sorted(book.author for book in db.query(Book).all()) == before

    def test_a_key_naming_nobody_visible_refuses_the_whole_batch(self, db, user, other):
        shelve(db, other, "Sean P. Kane", private=True)
        groups = self._two_groups(db, user)
        groups.append(
            AuthorMergeGroup(
                keys=[author_key("Sean P. Kane"), author_key("S. P. Kane")],
                keep_name="Sean P. Kane",
            )
        )

        with pytest.raises(AuthorNotFound):
            Authorship.seen_by(db, user.id).merge_batch(groups, by_user_id=user.id)

        assert db.query(AuthorAlias).count() == 0

    def test_a_group_that_would_repoint_a_decision_refuses_the_whole_batch(
        self, db, user
    ):
        groups = self._two_groups(db, user)
        authorship = Authorship.seen_by(db, user.id)
        authorship.merge(
            [author_key("JRR Tolkien"), author_key("J. R. R. Tolkien")],
            "J. R. R. Tolkien",
            by_user_id=user.id,
        )
        # The same two spellings, folded the other way round. One merge would be
        # allowed to do this; a batch may not, because nobody reviewed it.
        contradicting = [
            AuthorMergeGroup(
                keys=[author_key("JRR Tolkien"), author_key("J. R. R. Tolkien")],
                keep_name="JRR Tolkien",
            ),
            groups[1],
        ]
        before = _points_at(db)

        with pytest.raises(DecisionStands) as refused:
            authorship.merge_batch(contradicting, by_user_id=user.id)

        assert refused.value.keys == (
            author_key("J. R. R. Tolkien"),
            author_key("JRR Tolkien"),
        )
        # The second group was good and is not applied either.
        assert _points_at(db) == before

    @staticmethod
    def _two_groups_and_planted_rows(db, user, planted: int) -> None:
        """Two suggestion groups, and alias rows that touch neither of them."""
        shelve(db, user, "Le Guin, Ursula K.", "Ursula K. Le Guin")
        shelve(db, user, "JRR Tolkien", "J. R. R. Tolkien")
        db.add_all(
            AuthorAlias(
                alias_key=f"planted {index}",
                canonical_name=f"Planted {index}",
                created_by_user_id=user.id,
            )
            for index in range(planted)
        )
        db.commit()

    @staticmethod
    def _author_key_calls(monkeypatch, call) -> int:
        """How many times **`authorship`** normalises a name during one call.

        **The scoping to this one module is load bearing, not tidiness.**
        `build_index` and `resolve_alias_map` normalise through `authors`' own
        binding and are excluded, which is what makes the equality in the arm
        below exact: the planted rows are self rows, so widening the patch to
        reach `authors.author_key` would count four more per row and turn a
        delta of one per row into five. A later reader widening it to be
        thorough breaks a green test for a reason nothing else would explain.
        """
        counted = 0
        # The same object the module imported, named through `authors` because
        # `authorship` re-exports it and a re-export is not an export.
        real = author_key

        def counting(name):
            nonlocal counted
            counted += 1
            return real(name)

        monkeypatch.setattr(authorship_module, "author_key", counting)
        try:
            call()
        finally:
            monkeypatch.setattr(authorship_module, "author_key", real)
        return counted

    def test_the_alias_table_is_indexed_once_and_not_once_per_group(
        self, db, user, monkeypatch
    ):
        """Building it once is one arm of this and is **not** the property that
        matters, which is why the second arm exists below."""
        self._two_groups_and_planted_rows(db, user, 0)
        authorship = Authorship.seen_by(db, user.id)
        built = 0
        real = authorship_module._AliasIndex.of

        def counted(aliases):
            nonlocal built
            built += 1
            return real(aliases)

        monkeypatch.setattr(authorship_module._AliasIndex, "of", counted)

        groups = authorship.suggestions()

        assert len(groups) > 1, "the shelf has to produce more than one group"
        assert built == 1

    def test_would_repoint_looks_up_rather_than_walking_the_table(self):
        """The guard against scanning, asked of the code rather than of a count.

        **A count measures a side effect of scanning; this measures scanning.**
        Handed an index whose two dictionaries answer a lookup and raise on any
        attempt to walk them, `_would_repoint` passes only if it looks up. Both
        scan shaped regressions raise here, including the one that re-normalises
        nothing and is therefore invisible to a count.

        A rung above the arms below as well: deleting this test is loud, because
        nothing else refuses a walk.
        """
        index = authorship_module._AliasIndex(
            by_alias=_NoScan({"boz": "charles dickens"}),
            by_target=_NoScan({"charles dickens": ["boz"]}),
        )

        # A row already pointing at the kept person changes nothing.
        assert (
            authorship_module._would_repoint(index, {"boz"}, "charles dickens")
            is False
        )
        # The same row, folded somewhere else, would be repointed.
        assert authorship_module._would_repoint(index, {"boz"}, "boz") is True

    def test_adding_alias_rows_costs_one_normalisation_each_not_one_per_group(
        self, db, user, monkeypatch
    ):
        """What the quadratic cost, in numbers rather than in a refusal.

        **Measured as a difference rather than as a total**, so nothing here has
        to model the constant: doubling the alias table must cost one
        `author_key` per row added, because `_AliasIndex.of` normalises each row
        once and `_would_repoint` normalises none. Scanning the table inside
        `_would_repoint` instead costs one per row **per group**, which is what
        made a plain GET quadratic.

        **What it catches, measured rather than asserted**: a scan that
        re-normalises per row, which is the shape the code actually had. That
        mutant reads 157 and 307 against this arm's 57 and 107, so the delta
        goes from 50 to 150 and the equality fails.

        **What it does not catch, and this sentence used to claim otherwise**: a
        scan over `index.by_alias.items()` that compares the already normalised
        keys. It calls `author_key` zero times, so it reads 57 and 107, exactly
        like the shipped code, and passes. It is nonetheless `groups x rows` in
        wall time. `test_would_repoint_looks_up_rather_than_walking_the_table`
        is the arm that refuses it, and it is the one to read first.

        So this arm states the normalisation cost in numbers; it is not the
        guard against scanning.
        """
        rows = 50
        self._two_groups_and_planted_rows(db, user, rows)
        authorship = Authorship.seen_by(db, user.id)
        groups = len(authorship.suggestions())
        assert groups > 1, "one group cannot tell the two costs apart"

        first = self._author_key_calls(monkeypatch, authorship.suggestions)
        db.add_all(
            AuthorAlias(
                alias_key=f"more {index}",
                canonical_name=f"More {index}",
                created_by_user_id=user.id,
            )
            for index in range(rows)
        )
        db.commit()
        second = self._author_key_calls(monkeypatch, authorship.suggestions)

        assert second - first == rows

    def test_it_costs_two_index_reads_whatever_the_batch_holds(self, db, user):
        """Two, not two per group, which is the whole reason this is not a loop
        over `merge`: that would scan every visible Book twice per group."""
        groups = self._two_groups(db, user)
        authorship = Authorship.seen_by(db, user.id)

        statements = selects(
            lambda: authorship.merge_batch(groups, by_user_id=user.id)
        )

        assert sum(1 for line in statements if "FROM books" in line) == 2


class TestABatchNeverClearsADecision:
    """A merge somebody made is an assertion; a matcher's grouping is a guess.

    So a batch only ever adds rows: after one, every row that existed before
    still means the same person.
    """

    def test_an_existing_row_still_means_the_same_person(self, db, user):
        shelve(db, user, "Le Guin, Ursula K.", "Ursula K. Le Guin", "U. K. Le Guin")
        authorship = Authorship.seen_by(db, user.id)
        authorship.merge(
            [author_key("U. K. Le Guin"), author_key("Ursula K. Le Guin")],
            "Ursula K. Le Guin",
            by_user_id=user.id,
        )
        before = _points_at(db)
        proposed = _group(
            authorship.suggestions(), "Le Guin", "Ursula K.", "Ursula K. Le Guin"
        )

        authorship.merge_batch(
            [
                AuthorMergeGroup(
                    keys=list(proposed.keys), keep_name=proposed.keep_name or ""
                )
            ],
            by_user_id=user.id,
        )

        after = _points_at(db)
        assert all(after[key] == target for key, target in before.items())

    def test_an_existing_row_is_not_rewritten_even_to_the_same_person(self, db, user):
        """**Asserted on the raw column, not through `author_key`.**

        `_points_at` normalises, so it cannot see a row rewritten from `Ursula
        K. Le Guin` to a differently punctuated spelling of the same key, and
        `build_index` reads the displayed name out of exactly that column. A
        batch doing it would be renaming somebody on the strength of a
        `keep_name` that merely normalises to the same key, which is what "it
        only ever adds rows" says it does not do.
        """
        shelve(db, user, "Le Guin, Ursula K.", "Ursula K. Le Guin", "U. K. Le Guin")
        authorship = Authorship.seen_by(db, user.id)
        authorship.merge(
            [author_key("U. K. Le Guin"), author_key("Ursula K. Le Guin")],
            "Ursula K. Le Guin",
            by_user_id=user.id,
        )
        before = {row.alias_key: row.canonical_name for row in db.query(AuthorAlias).all()}
        proposed = _group(
            authorship.suggestions(), "Le Guin", "Ursula K.", "Ursula K. Le Guin"
        )

        authorship.merge_batch(
            [
                AuthorMergeGroup(
                    # A spelling of the kept name that `author_key` folds to the
                    # same key, which is what the write pass must not adopt.
                    keys=list(proposed.keys),
                    keep_name="Ursula  K.   Le Guin",
                )
            ],
            by_user_id=user.id,
        )

        after = {row.alias_key: row.canonical_name for row in db.query(AuthorAlias).all()}
        assert all(after[key] == name for key, name in before.items())
        assert set(after) > set(before)

    def test_the_alias_map_is_still_flat_afterwards(self, db, user):
        """A chain resolves differently depending on the order rows are read in,
        which is what `resolve_alias_map` guards and what nothing should need."""
        shelve(db, user, "Le Guin, Ursula K.", "Ursula K. Le Guin", "U. K. Le Guin")
        authorship = Authorship.seen_by(db, user.id)
        authorship.merge(
            [author_key("U. K. Le Guin"), author_key("Ursula K. Le Guin")],
            "Ursula K. Le Guin",
            by_user_id=user.id,
        )
        proposed = _group(
            authorship.suggestions(), "Le Guin", "Ursula K.", "Ursula K. Le Guin"
        )
        authorship.merge_batch(
            [
                AuthorMergeGroup(
                    keys=list(proposed.keys), keep_name=proposed.keep_name or ""
                )
            ],
            by_user_id=user.id,
        )

        rows = {row.alias_key: row.canonical_name for row in db.query(AuthorAlias).all()}

        # Flat means one lookup is always enough, which is exactly resolution
        # being a fixed point. Compared on the key, because a row rewritten to a
        # different spelling of the same person is not a chain.
        assert {key: author_key(name) for key, name in resolve_alias_map(rows).items()} == {
            key: author_key(name) for key, name in rows.items()
        }

    def test_every_group_the_preview_offers_can_be_applied(self, db, user):
        """The diagonal: a preview whose proposals the writer then refuses would
        pass every test above and be useless."""
        shelve(db, user, "Le Guin, Ursula K.", "Ursula K. Le Guin", "U. K. Le Guin")
        shelve(db, user, "JRR Tolkien", "J. R. R. Tolkien")
        authorship = Authorship.seen_by(db, user.id)
        authorship.merge(
            [author_key("U. K. Le Guin"), author_key("Ursula K. Le Guin")],
            "Ursula K. Le Guin",
            by_user_id=user.id,
        )
        offered = [
            AuthorMergeGroup(keys=list(match.keys), keep_name=match.keep_name)
            for match in authorship.suggestions()
            if match.keep_name is not None
        ]

        assert offered
        assert len(authorship.merge_batch(offered, by_user_id=user.id).merged) == len(
            offered
        )
