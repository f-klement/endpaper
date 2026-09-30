"""Who may be told a collection exists, and the rule that nothing else decides it.

The behaviour a member sees is pinned in `tests/routers/test_collections.py`
and `tests/routers/test_books_collections.py`, beside the routes that serve it.
What is here is the cross module rule: `shelving.Shelving` is the only place
this question is answered, and every other read of the table is classified with
a reason.
"""

import ast
from typing import Final

from tests.test_house_rules import _source_modules
from tests.test_shelf import _book_owned_offences, _statement_at
from tests.test_tags import _reaches_private

#: The entity, as the shared pass takes it. One name, resolved to
#: `models.Collection` per module rather than matched as text: the standard
#: library's `collections.abc.Collection` is the same seven letters, five
#: modules outside the tests bind it, and `_entity_aliases` is where that is
#: settled.
COLLECTION: Final = frozenset({"Collection"})

#: Every read of `Collection` **the fourth pass reports**, and why that one is
#: safe.
#:
#: Not every read there is. Five families sit outside it, named rather than
#: armed. **The first three have a live member and the bullet names it; the
#: last two have none and say so**, because a family with no live member is the
#: one nobody notices acquiring its first:
#:
#: * `backup.py` puts `("collections", Collection)` in `_TABLES` and reads it
#:   through a runtime bound name, so the whole table is dumped and no pass
#:   that reads the arguments to `query()` sees it. Safe because the route is
#:   admin only, which `tests/test_shelf.py` asserts separately, and unfiltered
#:   on purpose because an archive missing rows restores a library missing
#:   them.
#: * `Book.collection_id` is a column of `books`, not of this table. It is the
#:   shelf rule's, not this one's, and it is why the CSV export's
#:   `book.collection.name` is reported nowhere: the rows come off a Shelf and
#:   the name is reached through a relationship attribute.
#: * Where the rows **go**. The pass matches a statement that reads the entity
#:   and says nothing about what the caller does with the result, which is why
#:   the arm over the reader's private state exists beside it.
#: * **A raw `text(...)` read over the table.** `db.execute(text("SELECT id,
#:   name FROM collections"))` names no entity anywhere, so the pass is blind
#:   to it and an unentried module holding one stays green. **No live member**,
#:   measured 2026-09-30 over `_source_modules()`. The shape is written in this
#:   repository, by the `e7b3d02a5c94` revision that folded collection names
#:   outside ASCII, and `migrations/` is one of the directories that corpus
#:   excludes. `tests/test_shelf.py` carries the same hole for `books` on its
#:   own blind spot list, with the argument for naming it rather than chasing
#:   it.
#: * **A root name bound from outside this backend.** `_entity_aliases`
#:   subtracts a bare `Collection` imported from anywhere the backend corpus
#:   does not hold, because `collections.abc.Collection` is the same seven
#:   letters, so such a module is unreportable for this entity. **No live
#:   member**, measured 2026-09-30: the five modules that lose the alias,
#:   `custom_fields.py`, `lending.py`, `metadata.py`, `reading.py` and
#:   `shelf.py`, all bind the typing protocol and none reads this table.
#:   **This family was far wider until 2026-09-30 and did have live members.**
#:   The subtraction was keyed on the import not being from `models`, so
#:   `from shelving import Collection` struck the name out and left a whole
#:   module unreportable with nothing red. That is closed; what is left is the
#:   deliberate false refusal.
#:
#: **Keyed on the enclosing function and the whole flattened statement**,
#: positionally in line order, the same key `TAG_READERS` uses and for the same
#: measured reason: two of the entries below are spelled
#: `collection = db.get(Collection, collection_id)` and differ only in what the
#: next line does with it. Keyed on the statement alone their reasons would be
#: interchangeable and could drift onto each other in silence.
#:
#: A reason, not a restatement. "Admin only, and the name never leaves" is a
#: reason; "reads a Collection" is not.
COLLECTION_READERS: Final = {
    "routers/books.py": [
        (
            "_checked_collection: if db.get(Collection, collection_id) is None: "
            'raise HTTPException(status_code=400, detail="No such collection")',
            "the collection a book write names by id. **Gated two lines below** "
            "by `Shelving.assignable`, which is what collapses a collection the "
            "caller may not be told about into the 400 an unused id already "
            "gets. It is the door that mattered: three of its four call sites "
            "answer with a `BookOut`, which carries `collection_name`, so a "
            "guessed id used to hand back the name.",
        ),
    ],
    "routers/collections.py": [
        (
            "_named: query = db.query(Collection).filter( Collection.name_folded "
            "== fold_collection_name(name) )",
            "the collision check behind `uq_collections_name_folded`. "
            "**Deliberately unscoped, and it is the seam.** The index is global, "
            "so a viewer here would race the rule this exists to front, and a "
            "scoped check would answer 'free' for a name already taken and turn "
            "a 409 into a 500. What leaves it is the row for the name the "
            "caller typed, **carrying the stored spelling rather than the "
            "typed one**, so a caller who typed `ebooks` learns the shelf is "
            "called `Ebooks`; the rename hands back nothing at all. That is "
            "the name oracle `Shelving`'s docstring records as open.",
        ),
        (
            "_named: query = query.filter(Collection.id != other_than)",
            "the same statement's rename arm, narrowing the collision check "
            "away from the row being renamed. It reads an id the caller already "
            "named and resolves no name.",
        ),
        (
            "rename_collection: collection = db.get(Collection, collection_id)",
            "the collection a rename names by id. **Gated on the next line** by "
            "`Shelving.assignable`. Open to every member and answering over the "
            "whole id space, so left ungated beside a closed list it would have "
            "moved a broadcast to a poll.",
        ),
        (
            "delete_collection: collection = db.get(Collection, collection_id)",
            "admin only and answers 404 or 204, with no name in either. "
            "**Deliberately ungated**, with the measurement at its own site: an "
            "admin has no privilege over another member's private books, so "
            "gating it would make a collection holding only those permanently "
            "undeletable while it still holds its name against the unique "
            "index.",
        ),
    ],
    "routers/stats.py": [
        (
            "get_stats: by_collection = ( shelf.select(Collection.name, "
            'func.count(Book.id).label("count")) .join(Collection, '
            "Book.collection_id == Collection.id) .group_by(Collection.id) "
            ".order_by(func.count(Book.id).desc(), Collection.name) .all() )",
            "the statistics page's collection counts, rooted at the Shelf and "
            "inner joined out to `collections`, so a collection no visible book "
            "is filed in produces no row. **Correct before this rule existed and "
            "unchanged by it**, which is the evidence for the shape: derive from "
            "the shelf and no arm is needed. Reported anyway, which is the cost "
            "of not trying to recognise a correct join.",
        ),
    ],
    "serialisation.py": [
        (
            "_collection_names: rows = db.query(Collection.id, Collection.name)"
            ".filter(Collection.id.in_(ids)).all()",
            "the name of the collection each book on a page is filed in, read "
            "for books the caller already holds. Safe because the ids come off "
            "rows a Shelf produced and this resolves no id the caller did not "
            "already have, **and that is a property of its callers rather than "
            "of its signature**, which takes a plain `list[Book]`. Said at the "
            "site.",
        ),
    ],
    "shelving.py": [
        (
            "listable: return [ row for row in self._db.query(Collection) "
            ".order_by(func.lower(Collection.name)) .all() if "
            "self._may_be_told(row.id) ]",
            "**the rule itself**, and the one read in the tree whose job is to "
            "decide this question. The comprehension is the filter: the table is "
            "read whole and each row is kept only when one of the three arms "
            "admits it. The scoping is in the same statement as the read, which "
            "is what an entry here can check and a reader can see.",
        ),
    ],
}


class TestNothingElseDecidesWhoMayBeToldACollectionExists:
    """`shelving.Shelving` is the only module answering this question.

    **The counterpart of `TestNothingElseDecidesWhoMaySeeATag`, one entity
    over.** The two rules share the instrument rather than a base class:
    `tests/test_shelf.py::_book_owned_offences` takes the entity set as a
    parameter, and a second walk written here would be a second thing to keep
    in step over a repository that has measured seven guards whose population
    was matched from source text and every one wrong at least once.

    **Why `collections` is not simply in `BOOK_OWNED` instead.** That set is
    derived from the foreign keys **into** `books`, and a collection is a
    parent rather than a child: `books.collection_id` points at it. Widening a
    foreign key derivation to catch a parent turns it into an inclusion list,
    which is the shape that goes stale. This is the second question, asked
    separately, exactly as the tag rule asks it.

    **What it does not see** is listed on `COLLECTION_READERS` above, with the
    live member of each family named. The shortest version: it reports a
    statement that reads the table and says nothing about where the rows go,
    which is why the arm over the reader's own state sits beside it.
    """

    #: The module the reader's private state belongs to. This arm is about a
    #: module boundary, unlike `COLLECTION_READERS`, which is about statements.
    OWNER: Final = "shelving.py"

    @staticmethod
    def _offences(sources: dict[str, str]) -> dict[str, list[int]]:
        return {
            name: lines
            for name, source in sources.items()
            if (lines := _book_owned_offences(source, COLLECTION))
        }

    @staticmethod
    def _key(source: str, line: int) -> str:
        """`<enclosing function>: <flattened statement>`, both off the `ast`.

        The same key `TAG_READERS` is read with, spelled here rather than
        imported: it is four lines, and importing a private helper out of a
        sibling test file to save them buys a coupling between two registries
        that are meant to move independently.
        """
        enclosing = [
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.lineno <= line <= (node.end_lineno or node.lineno)
        ]
        statement = _statement_at(source, line)
        if not enclosing:
            return statement
        holder = max(enclosing, key=lambda node: node.lineno)
        return f"{holder.name}: {statement}"

    def _report(self, sources: dict[str, str]) -> list[str]:
        """The comparison, over whatever corpus it is handed.

        **A parameter so the plants below run the rule the tree is read
        against**, rather than a copy of it: a fixture exercising its own copy
        reports on a rule nothing else uses.
        """
        found = self._offences(sources)

        report: list[str] = []
        for name in sorted(set(found) | set(COLLECTION_READERS)):
            lines = found.get(name, [])
            entries = COLLECTION_READERS.get(name, [])
            if len(lines) != len(entries):
                shown = "\n".join(
                    f"      {name}:{line}  {self._key(sources.get(name, ''), line)}"
                    for line in lines
                )
                report.append(
                    f"  {name}: {len(lines)} reads, {len(entries)} classified\n{shown}"
                )
                continue
            for line, (expected, _) in zip(lines, entries, strict=True):
                actual = self._key(sources.get(name, ""), line)
                if actual != expected:
                    report.append(
                        f"  {name}:{line} is not what its entry is keyed on.\n"
                        f"      entry expects: {expected}\n"
                        f"      statement is:  {actual}"
                    )

        return report

    def test_every_collection_reader_is_classified(self) -> None:
        report = self._report(_source_modules())

        assert not report, (
            "A statement reads the collections table, and either is not "
            "classified or is not the statement its entry was written for.\n\n"
            + "\n".join(report)
            + "\n\n  A collection carries no member any query may read, so "
            "nothing in a row says who may be told it exists: the answer is "
            "whoever may read a book filed in it, and `shelving.Shelving` is "
            "where that is decided. Serving a name out of this table unasked "
            "tells a member that somebody's books are filed somewhere, which "
            "is what `GET /api/collections` did.\n\n"
            "  If your read is genuinely safe, add an entry to "
            "COLLECTION_READERS with the statement exactly as printed above "
            "and why. If you cannot write the reason in a sentence, ask "
            "`Shelving` instead."
        )

    def test_a_bypass_beside_the_reader_is_not_exempt_for_being_there(self) -> None:
        """The plant the tag rule shipped green on its first version, run here
        before this one ships.

        Exempting the owning module by filename makes any read anywhere in it
        exempt with no entry and no reason: append a plain function returning
        the whole table, point the route at it, and the disclosure is back with
        the guard green, because the route then names no entity and the new
        read sits inside the exemption.

        **A floor on the number of reads in that module does not catch it.**
        The plant adds a read rather than removing one.
        """
        sources = dict(_source_modules())
        sources["shelving.py"] += (
            "\n\ndef every_collection_there_is(db):\n"
            "    return db.query(Collection).order_by(Collection.name).all()\n"
        )
        rewritten = sources["routers/collections.py"].replace(
            "for row in shelving.listable()",
            "for row in every_collection_there_is(db)",
            1,
        )
        assert rewritten != sources["routers/collections.py"], (
            "the route no longer spells the call this plant rewrites, so "
            "nothing was planted"
        )
        sources["routers/collections.py"] = rewritten

        report = self._report(sources)

        assert any("every_collection_there_is" in line for line in report), report

    def test_deleting_an_unrelated_entry_does_not_explain_that_red(self) -> None:
        """A red for the wrong reason is not a red.

        The plant above is reported with a second module's entry knocked out
        from under it, so the failure is the plant rather than an accident of
        the corpus holding exactly one spare offence.
        """
        sources = dict(_source_modules())
        sources["shelving.py"] += (
            "\n\ndef every_collection_there_is(db):\n"
            "    return db.query(Collection).all()\n"
        )
        knocked_out = sources["serialisation.py"].replace(
            "db.query(Collection.id, Collection.name)", "db.query(1)", 1
        )
        # The control. If the replace no ops, the arm still passes and has
        # quietly stopped deleting the unrelated thing it exists to delete.
        assert knocked_out != sources["serialisation.py"], (
            "the page's collection names no longer spell the columns this "
            "control knocks out, so nothing unrelated was deleted"
        )
        sources["serialisation.py"] = knocked_out

        report = self._report(sources)

        assert any("every_collection_there_is" in line for line in report), report

    def test_the_readers_private_state_is_reached_from_nowhere_else(self) -> None:
        """The half the registry structurally cannot see: where the rows go.

        The pass reports a statement that reads the table. It says nothing
        about a caller that holds what somebody else read, and the tag rule
        measured that exactly: one line swapping a vocabulary for another
        object's private index passed the whole gate and served a member a
        hidden name. Here the state at risk is `_carried`, which is every
        collection id some book is filed under, with no viewer applied.

        **What this contains is the class's surface, not the rows**, and
        `_reaches_private`'s own docstring carries the three mechanisms outside
        it and why `@final` and `__slots__` are load bearing for the sentence.
        Not restated here.
        """
        from shelving import Shelving

        private = frozenset(
            name
            for name in set(Shelving.__slots__) | set(vars(Shelving))
            if name.startswith("_") and not name.startswith("__")
        )
        assert private, "Shelving declares no private state, so this arm tests nothing"

        reaching = {
            name: sites
            for name, source in _source_modules().items()
            if name != self.OWNER and (sites := _reaches_private(source, private))
        }

        assert not reaching, (
            "`Shelving._carried` is every carried collection id with no viewer, "
            "and the registry entry for the read behind it is safe only because "
            f"nothing but the reader holds it. These reach into it: {reaching}."
        )
