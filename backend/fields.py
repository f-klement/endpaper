"""Which of the Library's own fields one Member may be told exist, and which
they may name by id.

**The reading counterpart for `custom_fields`, and the seam that table was
missing.** A `CustomField` carries no member anybody may read, so nothing in a
row says who may be told about it: the answer is whoever may read a Book
holding a value in it. That is a question about the Shelf, asked here once,
rather than a clause in each of the routes that read the table whole.

**Not `custom_fields.py`, and that is its own decision rather than a
preference.** That module's docstring declares *no `Shelf` here*, on the ground
that it is handed rows somebody already narrowed and taking a Shelf would put
the privacy rule in two places. A viewer scoped reader inside it falsifies the
sentence the whole module is built on. So the table's writers stay there and
the question of who may be told stays here, which is the same split
`shelving.py` makes against `collections`.

**Beside `tags.Vocabulary` and `shelving.Shelving`, not behind either.** The
three share a shape, a naming convention and an instrument, and differ in the
three places that matter: a Tag has a seeded arm, a Collection has a published
count, and a custom field has **neither**. `list_custom_fields` publishes no
count on purpose and `docs/security.md` records why, so this class holds sets
of ids where those two hold `dict[int, int]`. Generalising the three would have
to start by deciding whether the base class counts.
"""

from typing import Self, final

from sqlalchemy.orm import Session

import custom_fields
from models import Book, CustomField, CustomFieldValue
from shelf import Shelf


@final
class Fields:
    """The custom fields one Member may be told about, and may name by id.

    One `Fields` per request. Each of the three reads below is issued **lazily
    and once**, so a caller that asks about a single id pays only for the arms
    that id reaches, and `listable()` over the whole table pays at most three
    statements however many definitions there are.

    ## Sets of ids, never a count, and that is the difference from its two siblings

    `tags.Vocabulary.counts` and `shelving.Shelving.counts` are published
    numbers that double as the first arm. `CustomFieldOut` carries no count and
    `list_custom_fields` says why: a count over a field is drawn from Books the
    caller may not see, and a viewer scoped one in a delete confirmation would
    understate what the delete is about to destroy. So arm 1 here is
    `SELECT DISTINCT field_id`, which answers the arm and cannot become a
    published number by somebody reaching for the attribute that was already
    there.

    ## Three arms, in cost order

    1. **A Book this Member can see holds a value in it.** `Shelf.seen_by`, so
       the Member can already read the name off that Book: `CustomFieldValueOut`
       carries `name` inline with every value, and the route serving it resolves
       through `BookForRead`, which is this same predicate. The set this arm
       admits and the set that payload can reach are therefore the same set by
       construction rather than by agreement.
    2. **A deleted Book this Member may see holds a value in it.**
       `Shelf.trashed_by`, which is this Member's own trashed Books and every
       Member's trashed public ones. A restore reinstates the value, so without
       this arm trashing the last Book carrying a field takes the field off the
       settings page of the Member who is about to restore it.
       `in_trash_for` is not an ownership test and states so at its own site.
    3. **No Book at all holds a value in it.** Unscoped, a set of ids and never
       a count. A definition nothing carries discloses no Book, and this arm is
       what makes defining a field still work: between `POST /custom-fields`
       and the first value there is no carrier, so without it a Member would
       define a field and watch it fail to appear.

    There is no fourth. `tags.Vocabulary` has a seeded arm because
    `PREDEFINED_TAGS` is published by the mirror; nothing ships a custom field,
    so nothing here is public by construction.

    **And no ownership arm**, because there is no column to read:
    `CustomField` is `id`, `name` and `kind`. That absence is also why arm 3
    carries more weight here than it does for a Collection, and why the
    residual below is the one it is.

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

    **And discovery leaves the product.** A field whose every value is on other
    members' Private Books is gone from the picker of a Member who ought to be
    filling it in. What replaces it is a house agreeing a field name out loud,
    which is not a mechanism this code can offer.

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
      write that was going to restore arm 1 answers 404. Retyping the name is
      **a loop rather than a recoverable state**, which is the phrase
      `shelving.Shelving` already uses for the identical pair, measured a day
      earlier. The way back needs an admin, and the admin's only verb destroys
      every value under the row.
      `tests/routers/test_books_custom_fields.py::TestNamingAHiddenFieldByItsId::
      test_retyping_the_name_is_a_loop_rather_than_a_recovery` drives both
      steps, because an arm on the write alone pins half of it.
    * `rename` no longer names the field it clashed with. That refusal said
      `This library already has a field called {name}` over the whole table, so
      it published a hidden name to any Member who guessed it.

    **The ids stay enumerable.** `CustomFieldOut` publishes `id` and the column
    is a consecutive integer primary key, so a filtered list reading 1, 2, 5
    says rows exist between them or were deleted. Narrower than a name, still a
    tell, and not closed here.
    """

    __slots__ = ("_carried", "_db", "_on_the_shelf", "_trashed", "_viewer_id")

    def __init__(self, db: Session, viewer_id: int) -> None:
        self._db = db
        self._viewer_id = viewer_id
        self._on_the_shelf: frozenset[int] | None = None
        self._trashed: frozenset[int] | None = None
        self._carried: frozenset[int] | None = None

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
            if self._may_be_told(row.id)
        ]

    def addressable(self, field_id: int) -> bool:
        """Whether this Member may act on a field they have named by id.

        False means 404, from the rename and from the value write, which is the
        answer an id no row carries already gets there: a field this Member may
        not be told about becomes indistinguishable from one that is not there.

        **Two callers and not three.** The delete is admin only and
        deliberately ungated, for the reason `Shelving.assignable` gives and
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
        return self._may_be_told(field_id)

    def _may_be_told(self, field_id: int) -> bool:
        """The one predicate both questions ask, three arms, in cost order.

        **In cost order and short circuiting, which is the whole statement
        budget.** Arm 1 is one statement and answers for every field this
        Member has a value in, so the ordinary path pays one query. Arms 2 and
        3 fire only for a field that arm did not admit.

        Keeping this one function rather than two is deliberate, and
        `shelving.Shelving` gives the reason: two cooperating predicates over
        one question is the shape that drifts, and the seam between them is
        where the defect lands.
        """
        if field_id in self._on_a_book_this_member_sees:
            return True
        if field_id in self._in_the_trash_this_member_sees:
            return True
        return field_id not in self._carried_by_any_book

    @property
    def _on_a_book_this_member_sees(self) -> frozenset[int]:
        """The fields holding a value on a Book this Member can see.

        **Joined to `books` through the Shelf, like every other query that
        reads a Book owned table.** Unscoped it would answer for every Member's
        Private Books, which is the disclosure this class exists to close.

        **`field_id` and `distinct()`, so the number `list_custom_fields`
        refuses is not computed here and cannot be read off this set.** That
        number is how many Books carry a field, and producing it needs a
        different statement: a count, or this read without the `distinct`.
        Either is a changed statement, which is what the register entry in
        `tests/test_shelf.py` is keyed on.

        **What the set's own cardinality gives is a different number and is
        not withheld**: how many definitions this Member may be told about,
        which is the length of the list the route already returns. Claiming
        more than that for this line was wrong and is corrected rather than
        armed.
        """
        if self._on_the_shelf is None:
            rows = (
                Shelf.seen_by(self._db, self._viewer_id)
                .select(CustomFieldValue.field_id)
                .join(CustomFieldValue, CustomFieldValue.book_id == Book.id)
                .distinct()
                .all()
            )
            self._on_the_shelf = frozenset(row[0] for row in rows)
        return self._on_the_shelf

    @property
    def _in_the_trash_this_member_sees(self) -> frozenset[int]:
        """The fields holding a value on a deleted Book this Member may see.

        **This Member's own trashed Books and every Member's trashed public
        ones**, which is `in_trash_for` and is stated in full there. The name
        reads as an ownership test and is not one.

        **`tags.Vocabulary`'s reason for the same arm does not carry here, and
        this docstring borrowed it.** That reason is that the Member is served
        those Books in their trash listing, so the name is already readable off
        one. True for a Tag: the listing's element type carries tags. False for
        a custom field: `CustomFieldValueOut` is reached only through the two
        `/{book_id}/custom-fields` routes, both resolving through
        `BookForRead` or `BookForWrite`, and `visible_to` excludes a trashed
        Book. So nothing serves a field name off a Book in the trash.

        **The arm is right for its own reason**, which is the one its register
        entry gives: a restore reinstates the value and the field is then arm
        1, so without this arm trashing the last carrier takes the field off
        the page of the Member who is about to bring it back. What it admits
        is therefore a Book that **may become** a carrier the viewer can see,
        not one whose name they can already read.

        `Shelf.trashed_by` and not a flag on `seen_by`, for the reason that
        method gives: a predicate meaning "on the shelf" or "in the trash"
        depending on an argument is one a caller can get backwards, and
        backwards here would answer this question over every Member's trash.
        """
        if self._trashed is None:
            rows = (
                Shelf.trashed_by(self._db, self._viewer_id)
                .select(CustomFieldValue.field_id)
                .join(CustomFieldValue, CustomFieldValue.book_id == Book.id)
                .distinct()
                .all()
            )
            self._trashed = frozenset(row[0] for row in rows)
        return self._trashed

    @property
    def _carried_by_any_book(self) -> frozenset[int]:
        """The fields some Book in the Library holds a value in, viewer or no
        viewer.

        **Deliberately unscoped, and the only read here that is.** Every other
        read asks what one Member may see; this one asks whether a definition
        has anything to disclose at all, and scoping it would answer "nothing"
        for a field filled in all over somebody else's Private Books, which is
        exactly the case arm 3 exists to separate from an unused definition.

        **Ids, never a count and never a name.** What crosses is the set of
        field ids that are carried, so nothing about how many hidden Books
        carry one, or whose they are, can leave through it. That is the same
        bound `shelf.collections_any_book_is_filed_in` states, and it is the
        whole of what this class borrows from that precedent.

        **It lives here rather than in `shelf.py`**, which is where that
        precedent sits, and the difference is the table. That function reads
        `books`, which is `shelf.py`'s rule whatever the rows come back as;
        the house rule itself is about queries returning or counting **Books**
        and this returns a field id.

        **The decisive reason is the shape of the register, not the record.**
        `shelf.py` is the one module
        `test_shelf.py::TestTheShelfIsTheOnlyWayIn::
        test_only_the_counted_statements_read_a_table_that_belongs_only_to_a_book`
        does not walk, and it holds five book owned reads with no key in that
        register at all, so this statement would have become a sixth
        unreported one. What stands in front of those is a literal of three
        function names with hand written caller counts: a fourth unscoped
        function added there **reds nothing**. `BOOK_OWNED_READERS` is derived
        from the tree with exact count equality and refuses a stale entry in
        both directions, so keeping the statement here keeps it under a
        derived register rather than moving it to a literal one, which is this
        repository's standing remedy and not a preference. `tags.Vocabulary`
        keeps the identical arm in its own module for the same reason.
        """
        if self._carried is None:
            rows = self._db.query(CustomFieldValue.field_id).distinct().all()
            self._carried = frozenset(row[0] for row in rows)
        return self._carried
