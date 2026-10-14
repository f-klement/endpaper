"""Which of the Library's own fields one Member may be told exist, and which
they may name by id.

**The reading counterpart for `custom_fields`, and the seam that table was
missing.** Who may be told a `CustomField` exists is mostly not a property of
the row: it is whoever may read a Book holding a value in it. That is a
question about the Shelf, asked here once, rather than a clause in each of the
routes that read the table whole.

**`created_by_user_id` is the one thing the row does say**, and it answers the
two questions the Shelf cannot: a definer is told their own field exists even
when nothing they can see carries it, and a definer may rename it. This module
is the only one that reads that column, except the archive, which is what
keeps the member axis in the same place as the Shelf axis instead of in a
route.

**The archive is the exception and it is past every rule that matches a column
name.** `backup.py` selects every column of every table it archives without
naming any of them, so it reads this one and no walk over source can see that.
It is admin only for that reason, which `docs/security.md` records.

**A schema field named for it is a read, and it is the read no source walk can
see.** Pydantic populates such a field by reading the attribute off the row, so
the column reaches every client with no attribute access written anywhere.
`CustomFieldOut` answers a derived `renamable` for that reason, and
`tests/test_fields.py::TestFieldsIsTheOnlyReaderOfTheAuthorColumn` refuses the
declaration as well as the statement.

**Not `custom_fields.py`, and that is its own decision rather than a
preference.** That module's docstring declares *no `Shelf` here*, on the ground
that it is handed rows somebody already narrowed and taking a Shelf would put
the privacy rule in two places. A viewer scoped reader inside it falsifies the
sentence the whole module is built on. So the table's writers stay there and
the question of who may be told stays here, which is the same split
`shelving.py` makes against `collections`.

**The custom field arm of `disclosure.Disclosure`**, which owns the rule, its
three reads and their order for every vocabulary. What a field adds is the
definer arm and the absence of a count: `list_custom_fields` publishes none on
purpose and `docs/security.md` records why, so the rule reads this vocabulary's
visible arm as a set of ids, which `disclosure.Carrier.counted` decides.
"""

from typing import Self, final

from sqlalchemy.orm import Session

import custom_fields
from disclosure import Carrier, Disclosure
from models import CustomField


@final
class Fields:
    """The custom fields one Member may be told about, and may name by id.

    One `Fields` per request, holding one `disclosure.Disclosure`. Every read
    is lazy and cached, so `listable()` over the whole table costs the same
    whatever the number of definitions: one read of the table, plus the arms
    that ran, never one per definition.
    `tests/test_fields.py::TestListingCostsTheSameWhateverTheNumberOfDefinitions`
    measures one definition against a library at the ceiling and asserts
    equality.

    ## Sets of ids, never a count, and that is the difference from its two siblings

    `tags.Vocabulary.counts` and `shelving.Shelving.counts` are published
    numbers that double as the first arm. `CustomFieldOut` carries no count and
    `list_custom_fields` says why: a count over a field is drawn from Books the
    caller may not see, and a viewer scoped one in a delete confirmation would
    understate what the delete is about to destroy. So the rule's first arm
    here is `SELECT DISTINCT field_id`, which answers the arm and cannot become
    a published number by somebody reaching for an attribute that was already
    there: `Disclosure.counts` refuses this vocabulary.

    ## The arms

    The rule's own, in its order: a Book this Member can see holds a value in
    it; a deleted Book this Member may see does; no Book at all does. For the
    first, `CustomFieldValueOut` carries `name` inline with every value and the
    route serving it resolves through `BookForRead`, which is the same
    predicate, so the set the arm admits and the set that payload can reach
    are the same set by construction. For the second, nothing serves a field
    name off a Book in the trash, so the reason is the restore alone: it
    reinstates the value, and without the arm trashing the last carrier takes
    the field off the page of the Member about to bring it back.

    **And one of its own: this Member defined it.**
    `CustomField.created_by_user_id`, read off the class in one statement.
    Without it a Member who defines a field and then has its only value land
    on somebody else's Private Book loses the field from their own settings
    page, and retyping the name is a loop rather than a recovery. It runs
    behind the two scoped arms and before the empty one, which is where the
    rule puts a vocabulary's own arm, for the equality `disclosure` states.

    There is no other. `tags.Vocabulary` has a seeded arm because
    `PREDEFINED_TAGS` is published by the mirror; nothing ships a custom field,
    so nothing here is public by construction.

    **The ownership arm arrived with its column**, and this class is the only
    reader of it. Everything a `CustomField` row says about a member is read
    here, on the class rather than on the row, which is the shape
    `_author_of` explains and
    `tests/test_house_rules.py::TestProvenanceColumnsAreNeverRead` requires.

    ## What this closes

    **The broadcast, and the two doors that take an id.** No Member learns from
    a page load that a field exists whose every value is on Books they cannot
    see; renaming such a field by guessed id answers 404, which is the answer
    an absent id already gives; and writing a value into one answers 404 before
    `custom_fields.write` is reached, which is what keeps that function's URL
    refusal from naming a field the caller could not have listed.

    **That third one is the door that defeats the first on its own.**
    `PUT /api/books/{a Book I own}/custom-fields/{a guessed id}` answers with
    the Book's whole list, and every entry in it carries `name`. Without
    `addressable` the write door is a name oracle over a small integer id
    space and the scoped list buys nothing.

    ## What this newly accepts, and it is created by this rule rather than found

    **The ceiling refusal becomes an arithmetic oracle.** The cap is Library
    wide, so a Member who lists three fields and is refused at it learns that
    twenty two exist which they cannot see, for one `POST`.

    **No wording closes it, and the reason is the refusal rather than the
    constant.** The oracle is the event: a Member who has never read a line of
    this source defines fields until the refusal fires and subtracts, so the
    number arrives whatever the message says. That `MAX_CUSTOM_FIELDS` is
    declared in a published module is a **second** reason and not the first;
    hanging the claim on it would leave the door looking closable by moving
    the constant. **State the mechanism and bound nothing**: what the oracle
    gives is a cardinality, not a name, a kind or an id, and only at the cap.

    **And discovery leaves the product, for everybody but the definer.** A
    field whose every value is on other members' Private Books is gone from
    the picker of a Member who ought to be filling it in. The definer arm
    exempts the one Member who can be named from the row and nobody else, so
    what replaces it for the rest is a house agreeing a field name out loud, which is not a
    mechanism this code can offer.

    ## The non monotonicity is the thing a reader will call a bug

    A field is hidden while its only values are on invisible Books and listed
    again once the last of those values is destroyed. That reads backwards and
    it is correct: the rule tracks what there is to disclose, and when there is
    nothing left to disclose there is nothing left to withhold. The transition
    is observable, so a Member watching the settings page sees a row return
    when somebody else's last value goes. **It is the narrowest channel here
    and it is not zero**, which is the whole claim.

    ## What this does not close, and cannot

    **Uniqueness is whole table of necessity**, since two Members must not mint
    colliding names, so `custom_fields.define` and `custom_fields.rename` both
    read every row. Those two doors are answerable as refusal **wording** and
    not by scope:

    * `define` still hands back the colliding row, with its stored
      capitalisation, id and kind. **Left open pending a ruling, and not
      because it is a way back, which it is not.** That argument was made and
      is false: `define` returns the existing row and **writes nothing**, so
      no value moves, so this predicate answers exactly as it did, so the
      write that was going to restore the visible arm answers 404. Retyping the name is
      **a loop rather than a recoverable state**, which is the phrase
      `shelving.Shelving` already uses for the identical pair, measured a day
      earlier.
      `tests/routers/test_books_custom_fields.py::TestNamingAHiddenFieldByItsId::
      test_retyping_the_name_is_a_loop_rather_than_a_recovery` drives both
      steps, because an arm on the write alone pins half of it.

      **Who is in that loop narrowed when the definer arm arrived, and the loop itself
      did not.** A Member recorded as a field's author does not enter it:
      the definer arm admits their field whatever carries it, so there is nothing to
      retype. **Every other Member does, and on the morning of the upgrade
      that is everybody**, because the migration backfills no author and the definer arm
      admits a matching id rather than a definer in the abstract. For them the
      way back is still an admin, whose only verb destroys every value under
      the row. Retyping remains a loop rather than a recovery, for a set that
      shrinks by one field each time somebody defines one, which is why this
      bullet is narrowed rather than deleted.
    * `rename` no longer names the field it clashed with. That refusal said
      `This library already has a field called {name}` over the whole table, so
      it published a hidden name to any Member who guessed it.

    **The ids stay enumerable.** `CustomFieldOut` publishes `id` and the column
    is a consecutive integer primary key, so a filtered list reading 1, 2, 5
    says rows exist between them or were deleted. Narrower than a name, still a
    tell, and not closed here.
    """

    __slots__ = ("_authors", "_db", "_rule", "_viewer_id")

    def __init__(self, db: Session, viewer_id: int) -> None:
        self._db = db
        self._viewer_id = viewer_id
        self._authors: dict[int, int | None] | None = None
        self._rule = Disclosure.seen_by(
            db, viewer_id, Carrier.CUSTOM_FIELD_VALUES, self._defined_by
        )

    @classmethod
    def seen_by(cls, db: Session, viewer_id: int) -> Self:
        """The definitions as they look to this Member.

        Named to be asked the way `Shelf.seen_by`, `Vocabulary.seen_by` and
        `Shelving.seen_by` are asked, because it is the same question one level
        out and a reader who knows one should not have to learn a fourth
        spelling.
        """
        return cls(db, viewer_id)

    def listable(self) -> list[CustomField]:
        """Every field this Member may be told exists, in definition order.

        Ordered by `custom_fields.definitions`, which is insertion order and is
        that function's rule rather than this one's: a Book lists its fields
        the same way twice and two Books list them the same way as each other.
        Reusing it is also what keeps the ordering decision in one place when
        this list and a Book's values are rendered side by side.

        The table is read whole and the predicate is applied in the
        comprehension, which is what a reader can see and an allowlist entry
        can check.
        """
        return [
            row
            for row in custom_fields.definitions(self._db)
            if self._rule.may_be_told(row.id)
        ]

    def addressable(self, field_id: int) -> bool:
        """Whether this Member may act on a field they have named by id.

        False means 404, from the rename and from the value write, which is the
        answer an id no row carries already gets there: a field this Member may
        not be told about becomes indistinguishable from one that is not there.

        **Two callers and not three.** The delete is admin only and
        deliberately ungated, for the reason `Shelving.resolve` gives and
        which is sharper here: an admin has no privilege over another member's
        Private Books, so gating it would leave a field whose every value sits
        on those Books undeletable for good, and the delete is the only verb
        that can retire a name from a Library wide vocabulary with a ceiling of
        25.

        **The same three arms as `listable`, and that is a result rather than a
        shortcut.** For a Collection the empty arm belongs to both questions
        because an empty collection is a destination; here it belongs to both
        because a definition with no values is the normal state of a field
        somebody has just defined, and the write that fills it is the one this
        predicate gates. If a later change gives a field a carrier at
        definition time, this splits, and `tags.Vocabulary` is the shape to
        split it into.
        """
        return self._rule.may_be_told(field_id)

    def resolve(self, field_id: int) -> CustomField | None:
        """The definition at this id, or None for an id no row carries and for
        one this Member may not be told about alike, which the two id doors
        answer with the same 404."""
        return self._rule.resolve(field_id, self._row)

    def _row(self, field_id: int) -> CustomField | None:
        """The read `resolve` hands the rule, which asks it after the gate."""
        return self._db.get(CustomField, field_id)

    def renamable(self, field_id: int) -> bool:
        """Whether this Member may relabel a field they may be told about.

        **False is a 403 and never a 404**, which is the one place in this
        class the two come apart. Everything else here withholds the existence
        of a row, so the answer has to be the answer an absent id gives. This
        predicate is asked only of a field `addressable` has already admitted,
        so existence is disclosed before it runs and refusing in a way that
        says "yours, not mine" gives the caller nothing they did not have.

        **Three states, and the null is the one that matters on day one.**
        A field this Member defined is theirs. A field another Member defined
        is not. A field with **no** author belongs to nobody and keeps the rule
        the whole table had before the column existed: any Member may rename
        it. Every row defined before the migration is in that third state, and
        so is every row restored from an archive taken before it, so a rule
        that refused on a null would take the rename away from the entire
        existing vocabulary of every deployment at once.

        **An admin is not an arm here**, and that is deliberate rather than an
        omission: this class is built from a viewer id and knows nothing about
        roles. `rename_custom_field` holds the admin arm, beside the
        `require_admin` the delete already carries, which keeps one question
        about privilege in one place.
        """
        if not self.addressable(field_id):
            return False
        author = self._author_of.get(field_id)
        return author is None or author == self._viewer_id

    @property
    def _author_of(self) -> dict[int, int | None]:
        """Who defined each definition, for the two questions that need it.

        **Read off the class and never off a row**, which is a guard's
        requirement rather than a style: three other models carry a
        `created_by_user_id` that nothing may consult, and
        `tests/test_house_rules.py::TestProvenanceColumnsAreNeverRead` refuses
        every instance read of such a name anywhere in the tree, because an
        instance read has no statically resolvable owner. Naming the model
        here is what tells that rule which column this is. Reading it off a
        `CustomField` row, which is the obvious spelling, is reported and
        should be.

        **Naming the model buys nothing in a schema, and that is deliberate.**
        A Pydantic field named for one of these columns is refused whichever
        row it would be validated from, because a declaration has no receiver
        to resolve: the same rule says why, and the exit is to publish a
        derived answer rather than the id.

        **One statement for both questions**, and it is the whole table, which
        `custom_fields.definitions` already does for the same reason:
        `MAX_CUSTOM_FIELDS` is 25, so a per id lookup would be more statements
        for less. Lazy like the other three reads, so a caller that never asks
        about authorship never issues it.

        **Unscoped, and it discloses nothing.** What crosses is a member id per
        definition id, for definitions this class decides separately whether to
        admit: `listable` filters by the rule and `renamable` is asked
        only after `addressable` has. A viewer scoped version of this question
        is not available, because the question is who the author **is** rather
        than which Books carry the field.

        **`None` is a value here and not a missing key**, which is what keeps
        `renamable` readable: a field with no author answers `None` from the
        row, and a field id no row carries answers `None` from `dict.get`. The
        two mean different things and neither reaches `renamable` without
        `addressable` having answered first.
        """
        if self._authors is None:
            rows = self._db.query(
                CustomField.id, CustomField.created_by_user_id
            ).all()
            self._authors = {row[0]: row[1] for row in rows}
        return self._authors

    def _defined_by(self, field_id: int) -> bool:
        """The definer arm as the rule asks it, by id."""
        return field_id in self._defined_by_this_member

    @property
    def _defined_by_this_member(self) -> frozenset[int]:
        """The fields this Member defined. The definer arm.

        **The arm `CustomField` had no column for**, and the rule's other three
        arms, in `disclosure.Disclosure`, are what made its absence a lockout
        rather than an inconvenience: a field
        whose every value sits on another Member's Private Book fails both
        scoped arms and is carried, so it fails the empty arm. The Member who
        defined it watched it leave their own settings page, and retyping the
        name is a loop rather than a recovery, because `custom_fields.define`
        hands back the existing row and writes nothing.

        **Behind the two scoped arms and in front of the empty one.** The
        visible arm answers for every field this Member has a value in, which
        is the ordinary page load, so a statement in front of it would be paid
        on every request to serve a case that is rare by construction. What
        puts it in front of the empty arm is the statement count equality
        `disclosure` states, not the cost.
        """
        return frozenset(
            field_id
            for field_id, author in self._author_of.items()
            if author == self._viewer_id
        )
