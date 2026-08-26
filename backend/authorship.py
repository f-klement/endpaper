"""Who wrote what: the half of author identity that touches the database.

`authors.py` holds the thinking and is deliberately pure: `author_key`,
`squashed_key`, `resolve_alias_map`, `build_index`, `suggest_merges`, no session
and no writes. That purity is why it is easy to test, and it is not the problem.
The problem was that **everything the database knows about "these two spellings
are one person" lived in a route handler**: the index query, the merge write, the
repointing pass, the alias delete and the resolution behind `?author=`. The pure
functions were extracted so they could be tested, and the failures that matter
now were in the calling code left behind. That is a locality problem, not a
testing one.

So this module owns both halves. `authors.py` stays exactly as it is and becomes
the implementation underneath: still pure, still tested that way, still imported
directly by the three modules that need `AUTHOR_NAME_MAX`, `author_key`
and `split_authors`: `models.py`, `schemas/author.py` and `schemas/book.py`.

## The interface

    authorship = Authorship.seen_by(db, member.id)
    authorship.listing()                       # every author, as the API serves them
    authorship.suggestions()                   # names that are probably one person
    authorship.book_ids_for("le guin ursula k")
    authorship.merge(keys, keep_name, by_user_id=member.id)
    authorship.unmerge(alias_id)

`seen_by` mirrors `Shelf.seen_by`, and for the same reason: an author index is a
Book query wearing a different hat, so it is scoped to a viewer at the point of
construction rather than by each caller remembering to pass an id.

## Three rules that are the design, not oversights

**A key is written by the system; a display name is written by a person.**
`author_key` derives the key from the name, so a merge retires the keys it folds
exactly as it retires the spellings. Both the filter and the merge endpoint
therefore accept either a key or any spelling, and resolve a retired one through
the alias rows. Nothing lets a caller choose a key.

**Removing a key is allowed; retyping it is refused.** `unmerge` deletes a row
and the spelling becomes its own author again. There is no operation that
changes an `alias_key` in place, because that is not an undo of anything: it
would silently reassign every book carrying that spelling.

**A key is per spelling, not per person.** Two alias rows may disagree about who
a pair of spellings means, and that disagreement is evidence about what two
members decided rather than a bug to reconcile. `resolve_alias_map` flattens
what it is given; it does not adjudicate.

## The index is read fresh, and there is no cache

An earlier version of this module cached the index per instance and invalidated
it from the two writes. **It saved nothing.** Measured over every method: no path
reads the index twice without a write between the two reads, `merge` loads,
writes and loads again for two loads either way, and every route builds a fresh
instance for a single call. Its stated justification, "read three times in one
merge", was a wrong count.

It was removed rather than kept as insurance, on the module's own argument
against a session watcher: machinery guarding against a caller that does not
exist. The two tests that pinned "a read after a write is not stale" were kept,
because that behaviour still has to hold and they now guard against the cache
coming back.
"""

from typing import cast

from sqlalchemy.orm import Session

from authors import (
    AuthorEntry,
    author_key,
    build_index,
    resolve_alias_map,
    suggest_merges,
)
from models import AuthorAlias, Book
from schemas.author import AuthorMergeOut, AuthorOut, AuthorSuggestionOut
from shelf import Shelf


class AuthorNotFound(Exception):
    """No author by that name, or none this Member is allowed to know about.

    **The two are the same answer on purpose**, and the router turns this into a
    404 rather than a 403 for the reason an invisible Book is a 404: a 403 would
    confirm that somebody owns a book by that name, which is exactly what
    privacy withholds.

    An exception rather than `None`, because every caller of the operations that
    raise it treats the case as an error, and returning `None` from a write
    would make "nothing to merge" and "merged nothing" the same value.
    """


class Authorship:
    """Author identity in this Library, as one Member sees it."""

    __slots__ = ("_db", "_viewer_id")

    def __init__(self, db: Session, viewer_id: int) -> None:
        self._db = db
        self._viewer_id = viewer_id

    @classmethod
    def seen_by(cls, db: Session, viewer_id: int) -> Authorship:
        """Author identity as this Member sees it.

        Named like `Shelf.seen_by` because it is the same promise: everything
        below is derived from Books this Member may see.
        """
        return cls(db, viewer_id)

    # ── Reading ───────────────────────────────────────────────────────────────

    def _load(self) -> tuple[list[AuthorEntry], list[AuthorAlias]]:
        """Every author this Member can see, and the alias rows behind them.

        **Two statements, whatever the shelf holds**: the visible credit lines,
        and the alias table. Measured by `test_books_authors.py::
        test_the_author_index_costs_two_statements` on a shelf of 40 books,
        which is the same number it costs on a shelf of one.

        The scan is unpaginated on purpose, like `/duplicates` and
        `/locations`: the grouping needs the whole catalogue to count anything
        correctly, and a page of it would count only the page. It selects two
        columns rather than whole rows, so what comes back is one id and one
        string per Book.

        **The shelf is asked for here and nowhere else in the feature.** Every
        author, every count and every book id downstream is derived from these
        rows, so a Private Book cannot reach an author page, a count, a
        suggestion or a filter without passing this line first.
        """
        # `.tuples()` rather than `.all()`: a `Row` is a tuple at runtime and is
        # not one to a type checker, and `build_index` takes pairs.
        #
        # Narrowed with `cast` because `Shelf.select` takes `*columns` and so
        # resolves to `Session.query`'s untyped fallback overload rather than
        # to the two-column one. The cast states the pair this statement
        # selects; it is the only place that knows it, and getting it wrong is
        # a mypy error at `build_index` rather than a silent widening.
        rows = cast(
            "list[tuple[int, str | None]]",
            Shelf.seen_by(self._db, self._viewer_id)
            .select(Book.id, Book.author)
            .filter(Book.author.isnot(None))
            .tuples()
            .all(),
        )
        # Ordered oldest first, which is what makes "the most recent decision
        # wins" mean something in `build_index` when two aliases name one
        # person with different spellings.
        #
        # The alias table is Library wide and not filtered, which is the
        # decision recorded in `docs/decisions.md` under "The alias mapping is
        # library wide". A row says who a name means; it never says a Book
        # exists.
        aliases = self._db.query(AuthorAlias).order_by(AuthorAlias.id).all()
        entries = build_index(rows, {row.alias_key: row.canonical_name for row in aliases})
        return entries, aliases

    @property
    def entries(self) -> list[AuthorEntry]:
        """Every author on this Member's shelf, most books first."""
        return self._load()[0]

    def listing(self) -> list[AuthorOut]:
        """Every author, as the API serves them."""
        entries, aliases = self._load()
        alias_ids = {row.alias_key: row.id for row in aliases}
        return [self._out(entry, alias_ids) for entry in entries]

    def suggestions(self) -> list[AuthorSuggestionOut]:
        """Names that are probably one person.

        A suggestion and never a verdict: accepting one writes an alias row,
        and deleting that row puts the shelf back exactly as it was.

        Returns the schema type, like `listing()` and `merge()`. Returning the
        domain `AuthorSuggestion` left the router knowing its field names,
        which is exactly the locality this module exists to remove.
        """
        return [
            AuthorSuggestionOut(
                keys=list(group.keys), names=list(group.names), reasons=list(group.reasons)
            )
            for group in suggest_merges(self.entries)
        ]

    def book_ids_for(self, author: str) -> list[int]:
        """The visible Books credited to one author, by key or by any spelling.

        Liberal in what it accepts: `author_key` is idempotent on a key this
        API issued, so a link carrying the key and a link carrying the display
        name both land here. A spelling that a merge folded away resolves to
        the person it was folded into, which is what makes an old link keep
        working after a tidy-up.

        Resolved through the **whole** alias map rather than through the
        spellings on this Member's shelf. A link may name a spelling no Book
        carries any more: fold "Le Guin" into "Ursula K. Le Guin", then that
        into "U. K. Le Guin", and the middle name is on nothing. Resolving
        through the shelf returned an empty list for it, which reads as "we own
        nothing by her".

        An unknown name gives an empty list rather than raising. This is a
        filter on a listing, and a listing that matches nothing is empty: the
        alternative turns a stale bookmark into an error page.
        """
        entry = self._entry_for(author)
        return list(entry.book_ids) if entry is not None else []

    def _entry_for(self, author: str) -> AuthorEntry | None:
        """The index entry a key or a spelling resolves to, following aliases."""
        entries, aliases = self._load()
        resolved = resolve_alias_map({row.alias_key: row.canonical_name for row in aliases})
        key = author_key(author)
        canonical = resolved.get(key)
        if canonical is not None:
            key = author_key(canonical)
        return next((entry for entry in entries if entry.key == key), None)

    @staticmethod
    def _out(entry: AuthorEntry, alias_ids: dict[str, int]) -> AuthorOut:
        """One index entry as the API serves it.

        `merged` is built from the entry's own `alias_keys`, which
        `build_index` fills in only for a spelling that appears on a Book **this
        Member can see**. That is the privacy line for the alias table: the rows
        are Library wide, and one whose spelling survives only on somebody
        else's Private Book would otherwise announce that the Book exists.
        """
        spelling_for = {author_key(spelling): spelling for spelling in reversed(entry.spellings)}
        return AuthorOut(
            key=entry.key,
            name=entry.name,
            book_count=len(entry.book_ids),
            spellings=list(entry.spellings),
            merged=sorted(
                (
                    AuthorMergeOut(
                        alias_id=alias_ids[key], spelling=spelling_for.get(key, entry.name)
                    )
                    for key in entry.alias_keys
                    # The author's own key is not a spelling folded **into**
                    # them. A merge writes a row for every key it was given, the
                    # kept one included, which is what pins the display name;
                    # listing it here put "Folded in: J. R. R. Tolkien" under
                    # the heading "J. R. R. Tolkien", with an undo beside it.
                    if key != entry.key and key in alias_ids
                ),
                key=lambda merged: merged.spelling.casefold(),
            ),
        )

    # ── Writing ───────────────────────────────────────────────────────────────

    def merge(self, keys: list[str], keep_name: str, *, by_user_id: int) -> AuthorOut:
        """Say that these spellings are one person.

        **Nothing in `books` is written.** Every named author keeps its credit
        line exactly as printed, and what changes is one row per spelling saying
        who that spelling means. Deleting the row undoes it, and a later import
        that re-creates the spelling is folded by the row already there. A
        rewrite of the strings could do neither: it is not reversible, and it
        repairs a split only until the same file is imported again.

        A `keep_name` that no Book carries is allowed and is the point: "Le
        Guin, Ursula K." splits into two people, neither spelled correctly, and
        the repair is a name typed by hand.

        Raises `AuthorNotFound` for a key naming nobody this Member can see.
        """
        entries, aliases = self._load()
        by_key = {entry.key: entry for entry in entries}

        # `author_key` on what arrived, not the raw string. It is idempotent on
        # a key this API issued, so a caller may send either the key or a
        # spelling of the name and gets the same answer.
        requested = {author_key(key) for key in keys}
        # An author the caller can see, or a spelling a previous merge folded
        # away that they can still see the effect of. The second half is what
        # lets a merge be corrected without undoing it first: the folded
        # spelling is no longer an author in its own right, so it is not in
        # `by_key`.
        reachable = by_key.keys() | {key for entry in entries for key in entry.alias_keys}
        if any(key not in reachable for key in requested):
            raise AuthorNotFound

        keep_name = self._resolved_keep_name(keep_name, requested, aliases)
        keep_key = author_key(keep_name)

        for row in aliases:
            # Rows that pointed at a name being folded away have to come along,
            # or they are left naming somebody who is now a spelling of
            # somebody else.
            if author_key(row.canonical_name) in requested and row.alias_key != keep_key:
                row.canonical_name = keep_name

        by_alias_key = {row.alias_key: row for row in aliases}
        for key in sorted(requested):
            existing = by_alias_key.get(key)
            if existing is not None:
                existing.canonical_name = keep_name
            else:
                self._db.add(
                    AuthorAlias(
                        alias_key=key,
                        canonical_name=keep_name,
                        created_by_user_id=by_user_id,
                    )
                )

        self._db.commit()

        entries, aliases = self._load()
        alias_ids = {row.alias_key: row.id for row in aliases}
        merged = next((entry for entry in entries if entry.key == keep_key), None)
        if merged is None:
            # Unreachable while every requested key named an author with a
            # visible Book, which is what the check above enforces. It is here
            # for the race: another Member trashing the last of those Books
            # between the two index reads leaves an author with nothing to show.
            raise AuthorNotFound
        return self._out(merged, alias_ids)

    @staticmethod
    def _resolved_keep_name(
        keep_name: str, requested: set[str], aliases: list[AuthorAlias]
    ) -> str:
        """The name to keep, followed one hop if it is itself already folded.

        Following it keeps the map flat: without this the new rows would point
        at a name that itself points elsewhere, and resolution would depend on
        the order the rows are read in.

        Followed whoever the row belongs to: a canonical name is Library wide,
        like a Collection's name, so there is nothing here to withhold. Gating
        this on what the caller can see was tried and withdrawn: it made a chain
        storable, and it disagreed with the `reachable` set above, which is a
        different question with a different answer.

        **But not a row naming one of the keys being merged.** Reversing a merge
        is folding A and B the other way round, which arrives as the same two
        keys with the other `keep_name`; following the row that says "B means A"
        would rewrite the request back into itself and answer 200 with nothing
        changed.
        """
        by_alias_key = {row.alias_key: row for row in aliases}
        existing_target = by_alias_key.get(author_key(keep_name))
        if existing_target is not None and existing_target.alias_key not in requested:
            return existing_target.canonical_name
        return keep_name

    def unmerge(self, alias_id: int) -> None:
        """Undo one merge. The spelling becomes its own author again.

        This is why merging is allowed to guess. Nothing was rewritten, so
        removing the row restores exactly the state before it was written, and
        the Books were never involved.

        A row whose spelling is on no Book this Member can see raises
        `AuthorNotFound`, and the reason is authority rather than secrecy: undo
        what you can see the effect of. The page offers this beside the spelling
        it folded, so a row with no such spelling on your shelf has no button
        here and no meaning here either.

        That leaves an **orphan** alias, whose spelling is on nobody's shelf
        because the Book was deleted, unreachable and undeletable. Accepted: it
        maps a name nothing is credited with, so it changes no view, and it
        starts working again by itself if an import re-creates that spelling,
        which is the property the whole design is for.
        """
        alias = self._db.get(AuthorAlias, alias_id)
        if alias is None:
            raise AuthorNotFound

        if not any(alias.alias_key in entry.alias_keys for entry in self.entries):
            raise AuthorNotFound

        self._db.delete(alias)
        self._db.commit()
