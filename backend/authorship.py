"""Who wrote what: the half of author identity that touches the database.

## Three rules that are the design, not oversights

**A key is written by the system; a display name is written by a person.** The
two never swap roles, so a rename cannot silently repoint an identity.

**Removing a key is allowed; retyping it is refused.** `unmerge` deletes a row
rather than editing one, because editing a key means asserting a different
person under the same evidence. The same rule governs an authority identifier
from the other direction.

**A key is per spelling, not per person.** Two alias rows may disagree about who
a name refers to, and that disagreement is data rather than a fault to resolve.

## The index is read fresh, and there is no cache

A stale index answers a question about identity with yesterday's merge, and the
read is cheap enough that a cache would buy less than it risks.
"""

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import cast

from sqlalchemy.orm import Session

from authors import (
    AUTHOR_NAME_MAX,
    AuthorEntry,
    author_key,
    build_index,
    resolve_alias_map,
    split_authors,
    suggest_merges,
)
from catalogue import AuthorityAssertion
from enums import AuthorityProvenance, AuthorityScheme
from models import (
    AUTHOR_KEY_MAX,
    AUTHORITY_IDENTIFIER_MAX,
    AuthorAlias,
    AuthorIdentifier,
    Book,
)
from schemas.author import (
    AuthorIdentifierOut,
    AuthorMergeOut,
    AuthorOut,
    AuthorSuggestionOut,
)
from shelf import Shelf

logger = logging.getLogger(__name__)

#: How many authority assertions one catalogue record may deposit.
#:
#: **A stored denial of service bound, not a modelling opinion.** A catalogue
#: response has no size cap anywhere in `metadata.py`, and a record's credited
#: authors are `100` plus every `700` with an author relator, so a hostile SRU
#: answer carrying ten thousand `700` fields would otherwise write ten thousand
#: rows into a Library wide table on one member's refresh. The same reasoning
#: `MAX_CLASSIFICATIONS_PER_BOOK` applies per book, with the difference that
#: these rows are not deleted with any book.
#:
#: 20 rather than a rounder number: measured over 85 live DNB records on
#: 2026-08-24 the widest carried 7 credited names, and an anthology naming
#: twenty is a real thing to catalogue.
MAX_ASSERTIONS_PER_RECORD = 20


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


@dataclass(frozen=True, slots=True)
class RefusedAssertion:
    """A catalogue's assertion this Library declined, and what it kept instead.

    **The alternative to a `logger.info` and to a schema change.** Two
    catalogues, or one catalogue and one Member, can name different records for
    one spelling. The store holds one value per spelling per scheme, which is
    the invariant that makes "an identifier cannot be retyped" enforceable
    below the application, so the second value cannot be stored. Discarding it
    silently is resolution by precedence; adding a column to hold it moves the
    uniqueness rule into application code that has already been walked past
    three ways.

    So it is neither stored nor dropped: it is reported on the response of the
    request that produced it, to the person standing in front of it. A fact
    about one refresh, not about the Library.

    `kept_provenance` is what makes it actionable. A catalogue losing to another
    catalogue is a real upstream disagreement to look at. A catalogue losing to
    a **member** is somebody's guess outranking a national library, and the
    remedy is to delete the guess and refresh again.
    """

    name: str
    scheme: AuthorityScheme
    asserted: str
    kept: str
    kept_provenance: AuthorityProvenance


@dataclass(frozen=True, slots=True)
class RecordedAssertions:
    """What one catalogue record's assertions did: what stuck, and what did not."""

    stored: list[AuthorIdentifier]
    refused: list[RefusedAssertion]


class IdentifierConflict(Exception):
    """This spelling already carries a different identifier under this scheme.

    **The refusal is the feature.** A display name is a preference and a member
    may overwrite it; an authority identifier is a claim about which record in
    an external file this author is, and a person editing one is only ever
    introducing an error. So there is no operation that changes `identifier` in
    place, and an attempt to assert a second value raises here rather than
    updating the row.

    Removal is a different question and is allowed: see `forget_identifier`.

    The router maps this to 409 rather than 422, because the request is
    well formed and the state is what refuses it.
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
        """Every author, as the API serves them.

        **Three statements rather than two**, and the third is the whole
        `author_identifiers` table. `_load`'s two are unchanged, so `entries`,
        `book_ids_for`, `merge` and `unmerge` still cost what they did and only
        the listing pays. The table holds one row per spelling per scheme
        Library wide, so reading it whole and grouping in Python is cheaper than
        a join that would have to name every visible key in an `IN` clause.
        """
        entries, aliases = self._load()
        alias_ids = {row.alias_key: row.id for row in aliases}
        identifiers = self._identifiers_by_key()
        return [self._out(entry, alias_ids, identifiers) for entry in entries]

    def _identifiers_by_key(self) -> dict[str, list[AuthorIdentifier]]:
        """Every stored authority identifier, grouped by the spelling it is filed under.

        **Not filtered, exactly like the alias table**, and for the same reason
        recorded under "The alias mapping is library wide": a row here says
        which record in an external file a *name* means and never says a Book
        exists. What is filtered is which of these rows an entry reaches, and
        that is `_out`, which offers only the keys already on this Member's
        shelf.
        """
        grouped: dict[str, list[AuthorIdentifier]] = {}
        for row in self._db.query(AuthorIdentifier).order_by(AuthorIdentifier.id).all():
            grouped.setdefault(row.author_key, []).append(row)
        return grouped

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
    def _out(
        entry: AuthorEntry,
        alias_ids: dict[str, int],
        identifiers: dict[str, list[AuthorIdentifier]],
    ) -> AuthorOut:
        """One index entry as the API serves it.

        `merged` is built from the entry's own `alias_keys`, which
        `build_index` fills in only for a spelling that appears on a Book **this
        Member can see**. That is the privacy line for the alias table: the rows
        are Library wide, and one whose spelling survives only on somebody
        else's Private Book would otherwise announce that the Book exists.
        """
        spelling_for = {author_key(spelling): spelling for spelling in reversed(entry.spellings)}
        # Only keys a visible Book evidences. `_evidenced_keys` carries the
        # measurement of what including `entry.key` here let a member read and
        # delete.
        rows = [
            row
            for key in sorted(_evidenced_keys(entry))
            for row in identifiers.get(key, [])
        ]
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
            identifiers=[
                AuthorIdentifierOut(
                    id=row.id,
                    spelling=spelling_for.get(row.author_key, entry.name),
                    scheme=AuthorityScheme(row.scheme),
                    identifier=row.identifier,
                    provenance=AuthorityProvenance(row.provenance),
                )
                for row in rows
            ],
            identifier_conflicts=sorted(_disagreements(rows)),
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
        return self._out(merged, alias_ids, self._identifiers_by_key())

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

    # ── Authority identifiers ─────────────────────────────────────────────────
    #
    # Which record in an external file a spelling means, as opposed to which
    # person this Household decided two spellings are. Both are keyed on a
    # spelling and they are not the same claim: an alias is a preference and is
    # editable, an identifier is a fact and is not. `models.AuthorIdentifier`
    # holds the asymmetry in full.

    def record_catalogue_assertions(
        self, assertions: Iterable[AuthorityAssertion], *, credited: str | None
    ) -> RecordedAssertions:
        """Store what a record found by this Book's own ISBN said, without asking.

        **Certain, and that is the caller's claim rather than this method's.**
        `100 $0` on a record the server fetched for a verified ISBN is a
        cataloguer's assertion about *this* Book, so it is stored silently. The
        identical subfield on a record found by a title and author search is a
        guess about somebody with a similar name, and the way that guess is
        refused is that no search path calls this. See
        `catalogue.AuthorityAssertion` for why certainty is not a field.

        **Never fed from a request body.** Every caller passes a
        `catalogue.Record` the server fetched itself. A payload the client
        posted back would let a member type any number and have it stored with
        `CATALOGUE` provenance, which is exactly the laundering
        `IdentifierConflict` exists to prevent, only from the other end.

        **A conflicting assertion is kept and reported, not discarded.** A
        refresh must not answer 500 because a catalogue disagrees with a number
        already stored, so the stored value stands and nothing raises. What
        changed is that the losing assertion used to vanish into a
        `logger.info`, which is resolution by precedence: whoever wrote first
        won, silently, and that is exactly what this feature refuses to do for
        two authority files.

        **The live case is not catalogue against catalogue, it is a member's
        guess beating a catalogue.** A Member confirms a number for a spelling
        that has none, a later refresh brings the DNB's real one, and the
        catalogue's fact lost to the guess with nothing on screen. That inverts
        this feature's own premise, that a person editing an identifier is only
        ever introducing an error, and it is reachable today with one supplier.

        So the refusal is returned rather than logged away, and the two handlers
        that call this put it on the response, where the person who caused the
        disagreement is standing. **No column and no migration**: it is a fact
        about one request, not about the Library.

        **`credited` is the Book's own credit line, and it is required.** Only
        an assertion naming somebody that line carries is stored, which is what
        makes `_evidenced_keys` reachable by construction rather than by
        convention. It is not a formality: `google_books.merge_into` skips
        `author` whenever the Book already has one and `overwrite` is false,
        which is the default, so on the commonest enrichment there is the
        catalogue's spelling **never reaches `books.author`**. Measured through
        the real handler with a Book credited `S. P. Kane` and a DNB record
        spelling the same person `Kane, Sean P.`: one `POST /enrich` wrote a row
        under `sean p kane`, `listing()` and `identifiers_for` could not see it,
        `forget_identifier` raised, and the response called it stored.

        Keyword-only and undefaulted so a new call site has to answer the
        question rather than inherit the old behaviour.

        **Storing nothing is the right answer when the spelling is not
        adopted.** The app then holds no evidence tying that identifier to any
        name it carries, and the Member still reaches the same record through
        the name search route, where confirming it files it under a spelling the
        shelf does carry.
        """
        carried = {
            key
            for spelling in split_authors(credited or "")
            if (key := _storable_key(spelling)) is not None
        }
        stored: list[AuthorIdentifier] = []
        refused: list[RefusedAssertion] = []
        # Bounded before anything is looked up, so a hostile record costs one
        # slice rather than one query per assertion. See
        # `MAX_ASSERTIONS_PER_RECORD`.
        for assertion in list(assertions)[:MAX_ASSERTIONS_PER_RECORD]:
            key = _storable_key(assertion.name)
            if key is None or not _storable_identifier(assertion.identifier):
                logger.info("Dropped an unstorable authority assertion: %r", assertion)
                continue
            if key not in carried:
                # The catalogue named somebody this Book does not credit, or
                # spells them a way this Library did not adopt. A bound rather
                # than a disagreement, so it is logged and not reported: there
                # is nothing for a Member to act on and nothing was overruled.
                logger.info(
                    "Dropped an assertion for %r, which is not in this book's "
                    "credit line",
                    assertion.name,
                )
                continue
            existing = self._identifier_row(key, assertion.scheme)
            if existing is not None:
                if existing.identifier != assertion.identifier:
                    refused.append(
                        RefusedAssertion(
                            name=assertion.name,
                            scheme=assertion.scheme,
                            asserted=assertion.identifier,
                            kept=existing.identifier,
                            kept_provenance=AuthorityProvenance(existing.provenance),
                        )
                    )
                    continue
                stored.append(existing)
                continue
            row = AuthorIdentifier(
                author_key=key,
                scheme=assertion.scheme,
                identifier=assertion.identifier,
                provenance=AuthorityProvenance.CATALOGUE,
                # Null by check constraint on a CATALOGUE row: a machine
                # assertion never names a person. See
                # `ck_author_identifiers_asserter`.
                created_by_user_id=None,
            )
            self._db.add(row)
            stored.append(row)
        if stored:
            self._db.commit()
        return RecordedAssertions(stored=stored, refused=refused)

    def confirm_identifier(
        self,
        author: str,
        scheme: AuthorityScheme,
        identifier: str,
        *,
        by_user_id: int,
    ) -> AuthorIdentifier:
        """A Member confirming a candidate that did not come from this Book's record.

        The other half of `record_catalogue_assertions`: a name search returns a
        candidate rather than a match, because a name is not a key and two
        authors share one. Nothing stores it until somebody says it is the right
        person, and that decision is recorded as `MEMBER` provenance so an audit
        of the list can tell it from a machine's.

        `author` is a key or any spelling, resolved the way every other
        operation here resolves one.

        Raises `AuthorNotFound` for a name naming nobody this Member can see,
        which is the same authority rule `unmerge` applies: confirm what you can
        see the effect of. Raises `IdentifierConflict` where the spelling
        already carries a different value under this scheme, because retyping is
        the one thing this store refuses.
        """
        entry = self._entry_for(author)
        if entry is None:
            raise AuthorNotFound
        key = _confirmable_key(entry)
        if key is None:
            raise AuthorNotFound

        existing = self._identifier_row(key, scheme)
        if existing is not None:
            if existing.identifier != identifier:
                raise IdentifierConflict
            return existing

        row = AuthorIdentifier(
            author_key=key,
            scheme=scheme,
            identifier=identifier,
            provenance=AuthorityProvenance.MEMBER,
            created_by_user_id=by_user_id,
        )
        self._db.add(row)
        self._db.commit()
        return row

    def record_cross_references(
        self,
        author: str,
        references: Mapping[AuthorityScheme, str],
        *,
        by_user_id: int,
    ) -> RecordedAssertions:
        """Store the other files' numbers that came with a confirmed record.

        **The second half of `confirm_identifier`, not a second door into the
        table.** A Member confirms a *person*, and a GND record for that person
        already carries their ISNI, LCNAF number, VIAF cluster and Wikidata
        item, and names the VIAF cluster that carries their six national library
        numbers. Before this, all of it was shown once and dropped.

        **`references` must come from `authority.cross_references` or
        `authority.national_identifiers` on a candidate the server itself
        resolved, never from a request body.** This
        is the rule `record_catalogue_assertions` states and the reason is the
        same: a payload the client posted back would let a member type any
        number and have it stored, which is the laundering `IdentifierConflict`
        exists to prevent, from the other end. Nothing in this signature can
        enforce it, so the router is where it is kept and where it is tested.

        **A conflict here is reported, not raised**, and that is the difference
        from `confirm_identifier`. The primary write is what the Member asked
        for and a refusal of it is an error they must see. These are facts that
        arrived with it, so one of them colliding with a value already held must
        not undo a confirmation that succeeded. `RecordedAssertions` is the
        shape `record_catalogue_assertions` already returns for exactly this,
        and `RefusedAssertion.kept_provenance` is what tells the reader whether
        a person's earlier guess or another record is what is being outranked.

        **Provenance is `MEMBER` on every row, and `created_by_user_id` is set.**
        The identifier is the authority file's, but nothing tied it to this
        author until a person said the record was theirs. Filing it as
        `CATALOGUE` would say the DNB asserted it about a Book this Library
        holds, which is what `record_catalogue_assertions` means and is not what
        happened here. It would also violate `ck_author_identifiers_asserter`,
        which forbids a named asserter on a `CATALOGUE` row, so the honest
        answer and the enforceable one are the same one.

        **Bounded by the enum**, which is why there is no slice here. The key
        type is `AuthorityScheme`, so a mapping cannot hold more entries than
        the enum has members. `record_catalogue_assertions` takes an `Iterable`
        off a catalogue record and needs `MAX_ASSERTIONS_PER_RECORD` for it.

        Raises `AuthorNotFound` on a name naming nobody this Member can see, the
        same authority rule `confirm_identifier` applies.
        """
        entry = self._entry_for(author)
        if entry is None:
            raise AuthorNotFound
        key = _confirmable_key(entry)
        if key is None:
            raise AuthorNotFound

        stored: list[AuthorIdentifier] = []
        refused: list[RefusedAssertion] = []
        for scheme, identifier in references.items():
            if not _storable_identifier(identifier):
                logger.info("Dropped an unstorable cross reference: %r", scheme)
                continue
            existing = self._identifier_row(key, scheme)
            if existing is not None:
                if existing.identifier != identifier:
                    refused.append(
                        RefusedAssertion(
                            name=entry.name,
                            scheme=scheme,
                            asserted=identifier,
                            kept=existing.identifier,
                            kept_provenance=AuthorityProvenance(existing.provenance),
                        )
                    )
                    continue
                stored.append(existing)
                continue
            row = AuthorIdentifier(
                author_key=key,
                scheme=scheme,
                identifier=identifier,
                provenance=AuthorityProvenance.MEMBER,
                created_by_user_id=by_user_id,
            )
            self._db.add(row)
            stored.append(row)
        if stored:
            self._db.commit()
        return RecordedAssertions(stored=stored, refused=refused)

    def forget_identifier(self, identifier_id: int) -> None:
        """Remove a wrong identifier. A later import may write it again.

        **"Never edited" must not mean "never removable."** An upstream cluster
        can be wrong, and a fact that cannot be corrected is a trap rather than
        an invariant. Deleting is the correction, and re-import is the undo, so
        nothing here is lost that a catalogue cannot say again.

        A row filed under a spelling on no Book this Member can see raises
        `AuthorNotFound`, for the reason `unmerge` gives: authority rather than
        secrecy, and the page offers this beside the spelling it names.
        """
        row = self._db.get(AuthorIdentifier, identifier_id)
        if row is None:
            raise AuthorNotFound
        if row.author_key not in self._visible_keys():
            raise AuthorNotFound
        self._db.delete(row)
        self._db.commit()

    def identifiers_for(self, author: str) -> list[AuthorIdentifier]:
        """Every identifier stored for one author, by key or by any spelling.

        Raises `AuthorNotFound` for a name naming nobody this Member can see,
        which is what makes this the access check for the authority lookup as
        well as its input: a caller who cannot see the author cannot use this
        app to ask an outside service about them either.

        An author who exists and carries none answers an empty list, which is
        the ordinary case and is what sends the caller down the name search
        route.
        """
        entry = self._entry_for(author)
        if entry is None:
            raise AuthorNotFound
        identifiers = self._identifiers_by_key()
        return [
            row
            for key in sorted(_evidenced_keys(entry))
            for row in identifiers.get(key, [])
        ]

    def spelling_for(self, key: str) -> str:
        """The shelf spelling one stored key belongs to.

        For rendering a single identifier row, where `listing()` renders many
        and already has the entries in hand. A key nothing on the shelf carries
        answers with the key itself, which is the honest answer and is what
        `_out` falls back to as well.

        The key is normalised past being readable (`le guin ursula k`), which is
        why nothing serves it to a person unresolved.
        """
        for entry in self.entries:
            for spelling in entry.spellings:
                if author_key(spelling) == key:
                    return spelling
        return key

    def display_name(self, author: str) -> str:
        """The name this Library shows for one author, by key or by any spelling.

        The name rather than the key, because the key is normalised past the
        point of being a name: `author_key` folds case, accents and punctuation,
        so putting one to an authority file would search for
        `le guin ursula k`.

        Raises `AuthorNotFound` on the same rule as everything else here.
        """
        entry = self._entry_for(author)
        if entry is None:
            raise AuthorNotFound
        return entry.name

    def _identifier_row(
        self, key: str, scheme: AuthorityScheme
    ) -> AuthorIdentifier | None:
        """The row this spelling already carries under one scheme, if any."""
        return (
            self._db.query(AuthorIdentifier)
            .filter(
                AuthorIdentifier.author_key == key,
                AuthorIdentifier.scheme == scheme,
            )
            .one_or_none()
        )

    def _visible_keys(self) -> set[str]:
        """Every spelling key that resolves to somebody on this Member's shelf."""
        return {key for entry in self.entries for key in _evidenced_keys(entry)}


def _evidenced_keys(entry: AuthorEntry) -> set[str]:
    """Every spelling key this person reaches that a **visible Book** carries.

    **The one place the reachable set is built, and `entry.key` is deliberately
    not in it.** That omission is a fix for a privacy breach rather than a
    tidy-up, so it must not be undone: `entry.key` is derived from `entry.name`,
    `entry.name` is an alias row's `canonical_name` once a merge has run, and
    `merge` accepts a `keep_name` that **no Book carries** by design, which
    `test_a_name_no_book_carries_is_allowed` pins. So a member could merge their
    own author under a name they guessed, and that guess became a key reaching
    rows derived from somebody else's Private Book.

    Measured through this module's seam before the fix, attacker owning only
    `Terry Pratchett` and a stranger owning a Private book by `Sean P. Kane`
    with one catalogue row: `listing()` went from `[]` to
    `('Sean P. Kane', '1042243212', CATALOGUE)`, `identifiers_for` returned the
    row, and `forget_identifier` **deleted it**. A destructive write against
    data derived from a Book the caller cannot see.

    The other two terms are evidence by construction. `build_index` records
    `alias_keys` from the visible rows it was handed, and `spellings` is the set
    of credit line spellings on those same rows, so neither can name a Book this
    Member cannot see.

    **The cost is an orphan, taken deliberately.** A row filed under a key no
    visible Book carries is unreachable and undeletable here. That is the trade
    `AuthorAlias` already documents for the alias table, and it is narrow rather
    than routine, because both writers are now constrained to evidenced keys:
    `record_catalogue_assertions` stores only an assertion naming somebody the
    Book's own credit line carries, and `confirm_identifier` files under a
    spelling the shelf carries rather than under the display name.

    **That first clause used to say "files under the catalogue's own spelling,
    which reaches `books.author` on the same refresh", and it was false on the
    commonest path there is.** `google_books.merge_into` skips `author`
    whenever the Book already has one and `overwrite` is false, which is the
    default, so an ordinary `POST /enrich` never adopts the catalogue's
    spelling. Measured through the real handler: a Book credited `S. P. Kane`
    enriched from a DNB record spelling the same person `Kane, Sean P.` wrote a
    row under `sean p kane`, which `listing()` and `identifiers_for` could not
    see, `forget_identifier` refused, and the response reported as stored.
    Unreclaimable, and every `GET /authors` reads the whole table.

    So nothing this app writes lands on an unevidenced key. A hand edit, a
    restore or a deleted Book can still produce one.
    """
    return set(entry.alias_keys) | {
        author_key(spelling) for spelling in entry.spellings
    }


def _disagreements(rows: list[AuthorIdentifier]) -> set[AuthorityScheme]:
    """The schemes on which the spellings folded into one person do not agree.

    **Reported rather than resolved.** Two alias keys carrying different GND
    numbers means either the local merge is wrong or the upstream cluster is,
    and there is no rule that says which. Automatic merging on a shared
    identifier is out of scope for the same reason in the other direction.
    """
    values: dict[AuthorityScheme, set[str]] = {}
    for row in rows:
        values.setdefault(AuthorityScheme(row.scheme), set()).add(row.identifier)
    return {scheme for scheme, seen in values.items() if len(seen) > 1}


def _confirmable_key(entry: AuthorEntry) -> str | None:
    """The key a Member's own confirmation is filed under.

    **The most used spelling on the shelf, not the display name**, and the
    difference is a defect rather than a preference. `entry.name` is an alias
    row's `canonical_name` once a merge has run, and `merge` accepts a
    `keep_name` no Book carries: filing here under that name put the row on an
    unevidenced key, so `_evidenced_keys` could not reach it and a second merge
    to a different `keep_name` orphaned it outright, invisible in the listing
    and undeletable through `forget_identifier`.

    A spelling is the right key anyway, and not merely the safe one: this table
    is per spelling by design, exactly as `author_aliases` is, and the display
    name is the one string in the whole feature that is a choice rather than
    something a Book carries.

    `spellings` is ordered most used first by `build_index`, and it is non empty
    for any entry, because an entry is derived from credit lines. The None is
    for the case that cannot happen and would otherwise file a row under `""`,
    which no spelling can ever match.
    """
    if not entry.spellings:
        return None
    return _storable_key(entry.spellings[0])


def _storable_key(name: str) -> str | None:
    """The key a name is filed under, or None if the column cannot hold it.

    **Dropped rather than raised**, the same call `classifications.bounded_headings`
    makes for a heading: a catalogue record is a third party value with no size
    cap anywhere in `metadata.py`, and nothing in one is worth failing a
    member's refresh for.

    A name that normalises to nothing has an empty key, which no spelling can
    ever match, so a row under it would be unreachable and undeletable.
    """
    if len(name) > AUTHOR_NAME_MAX:
        return None
    key = author_key(name)
    if not key or len(key) > AUTHOR_KEY_MAX:
        return None
    return key


def _storable_identifier(identifier: str) -> bool:
    """Whether `ck_author_identifiers_bounds` would accept this value."""
    return bool(identifier) and len(identifier) <= AUTHORITY_IDENTIFIER_MAX
