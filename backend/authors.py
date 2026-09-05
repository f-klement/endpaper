"""Who wrote what, read out of one free text column.

`books.author` is a single `String(500)` holding a **comma separated** credit
line, and it stays that way: see `docs/decisions.md`, "An author is a name on a
book, not a row". Everything an author page needs is derived here, and the one
thing derivation cannot do (deciding that two spellings are one person) is
recorded in `author_aliases` rather than by rewriting the books.

Three keys, and the difference between them is the whole design:

`author_key`   what folds **automatically**, with nobody asked. Case, accents
               and punctuation, the last of which becomes a space: `J.R.R.
               Tolkien` and `J. R. R. Tolkien` are one person without anybody
               being consulted.
`squashed_key` what is **suggested**, for a person to confirm. It drops the
               spaces too, which reaches `JRR Tolkien` and also reaches `Ann
               Aker` from `Anna Ker`, which is why it only suggests.
an alias row   what a person **decided**. Anything else, including a
               misspelling, a name in catalogue order, and initials against a
               full given name.

The separator is a comma, and that is a different decision from the one
`google_books.join_categories` made. Categories are joined with a semicolon
*because* Google's own category names contain commas; author names contain
commas too ("Le Guin, Ursula K."), and the field is nonetheless comma
separated, because every writer of it says so: `metadata._marc_authors`,
`_bnf_authors` and `google_books` all join with `", "`, and every import path
runs a name through `flip_catalogue_name` first so that a catalogue-order name
arrives here already flipped. So a stored comma means "and", and the residue
(a name that reached the column in catalogue order anyway, by hand or from a
source that does not mark it) splits into two people. That residue is what
merging exists to repair, and `flip_catalogue_name` must **not** be reused
here: it flips on exactly one comma, which is also what "Terry Pratchett, Neil
Gaiman" has, so applying it to a stored credit line would mangle every
two-author book on the shelf.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

#: The longest canonical name a caller may choose when merging.
#:
#: Shorter than `books.author` (500) on purpose: that column holds a whole
#: credit line and this holds one person out of it. Long enough for the real
#: outliers, which are corporate authors and transliterated full names.
AUTHOR_NAME_MAX = 300

#: How many suggestion groups are computed and returned.
#:
#: The pass is O(pairs sharing a token) rather than O(n squared), so the cap is
#: not there for the machine: it is there because a page offering four hundred
#: merges is a page nobody works through, and because every group returned is
#: read and rendered. Groups are sorted before the cut, so the cap takes the
#: tail of a stable order rather than an arbitrary slice.
MAX_SUGGESTIONS = 100

#: How many names may share a word before that word's bucket is skipped.
#:
#: **This is a denial of service bound, not a tuning knob.** Two of the three
#: suggestion rules compare every pair inside a bucket, and a bucket is "every
#: author sharing one word", which a member controls: `books.author` is capped
#: at 500 characters and splits on commas, so one book carries up to 38 names,
#: and 53 books are enough to put 2,000 names in one bucket. `POST /api/books`
#: is open to any member, and the published image runs uvicorn without
#: `--workers`, so that heap is the whole app's.
#:
#: Measured on the suite's runner (four cores), names sharing one surname
#: token, timed around `suggest_merges` with the index already built:
#:
#:     names    uncapped            capped
#:       500     1.39s   12.4 MB     0.03s   0.2 MB
#:     1,000     5.80s   49.1 MB     0.07s   0.5 MB
#:     2,000    24.65s  195.9 MB     0.19s   1.0 MB
#:
#: `MAX_SUGGESTIONS` caps none of that, because the cost is paid building the
#: edges rather than returning them: every row above returned **zero** groups.
#:
#: Skipping the bucket outright is the right answer rather than truncating it,
#: and it is right because of what suggestions are: advice a person confirms.
#: A word shared by more than this many authors is not a lead anybody works
#: through, and every other bucket is still offered. 200 is two orders of
#: magnitude above a real library surname and bounds one bucket at 19,900
#: pairs.
MAX_BUCKET = 200

#: How many pairs the whole suggestion pass may compare before it gives up.
#:
#: **`MAX_BUCKET` bounds one bucket; this bounds how many.** A shelf can hold
#: every bucket at exactly the cap and still be quadratic overall: a 500
#: character credit line carries up to 125 words, so buckets are as cheap to
#: plant as names, and a round-robin cover (each token used exactly 200 times)
#: skips nothing while comparing nearly every pair. That shape was measured at
#: 5.07s and 87.4 MB over 1,600 names and 18.67s and 347.5 MB over 3,200 in
#: review, which is 3.7x the time and 4.0x the memory per doubling.
#:
#: Re-measured on the suite's runner, same cover, three configurations on one
#: machine so the rows compare:
#:
#:     names   fragment rule as it was   whole pass, no budget   shipped
#:     1,600      1.01s   24.4 MB            0.49s   1.0 MB      0.18s  0.9 MB
#:     3,200      1.99s   48.9 MB            1.11s   1.9 MB      0.28s  1.8 MB
#:
#: The memory came from a `compared` set sized by distinct pairs across every
#: bucket, which is gone: a pair sharing two words is now compared twice
#: instead of remembered, so the peak is linear in names rather than in pairs.
#:
#: A budget is the one bound that cannot be shaped around, because it measures
#: the thing that costs rather than a proxy for it. Spent, the pass stops
#: mid-rule and returns what it has: this is advice, so less of it is a fair
#: answer where refusing to load the page is not.
#:
#: 200,000 against a real library, where a bucket is a shared surname holding
#: two or three names: the honest workload is thousands of comparisons, so this
#: is two orders of magnitude of headroom and still a fifth of a second.
#:
#: **That headroom is measured against honest shelves, and says nothing about
#: a deliberate one.** Eleven full buckets spend the whole budget (11 x 19,900
#: = 218,900), which is 2,200 names, about 22,000 characters, and therefore
#: **44 books** at the 500 character cap: measured at 44 with names at the
#: shortest that still parse, and reproduced here at 48 with slightly longer
#: ones. On a clean shelf of three real names the pass returns one group, from
#: the fragment rule; with that junk added it returns none, in 0.21s. So one
#: member can switch the fragment rule off for everyone here, quietly.
#:
#: **Recorded rather than mitigated, and the reason is that the obvious
#: mitigation does not work.** Giving each rule a reserved floor guarantees it
#: a share of the budget, not that the share is spent on honest names: buckets
#: are visited in insertion order, so a reserved half is spent on whichever
#: buckets come first, which are the planted ones. It converts a total loss
#: into an arbitrary partial one.
#:
#: What makes recording proportionate is that this is a **functionality**
#: denial rather than a resource one (the page still loads, in a fifth of a
#: second), and that it is not covert: the planted names sit on the author
#: index in plain view, on the very page whose suggestions they suppress, and
#: deleting or merging them restores it. If that ever stops being true, the fix
#: is to bucket the pass by shelf age or to run it off the request path, not a
#: bigger number here.
MAX_COMPARISONS = 200_000


class _Budget:
    """Comparisons left in this pass, shared by the rules that need one.

    Shared rather than one each, because the cost is the pass and a member
    filling one rule's buckets must not also buy a full allowance for the next.
    The rules spend it in declaration order, so a hostile shelf exhausts it on
    `_edges_on_initials` and `_edges_on_fragments` returns early; that is the
    right way round, since the fragment rule is the one that returns nothing on
    exactly the input that plants such buckets.
    """

    __slots__ = ("left",)

    def __init__(self, left: int) -> None:
        self.left = left

    def spend(self) -> bool:
        """One comparison, or False when there is nothing left to spend."""
        if self.left <= 0:
            return False
        self.left -= 1
        return True

#: Characters that separate the people in a credit line.
#:
#: Only the comma. `&` and `and` are deliberately not separators: "Simon and
#: Schuster" is a name, and there is no way to tell it from a join without
#: guessing, which is the class of guess that produces two authors nobody can
#: find. A library that writes "A & B" gets one author and can merge it.
_SEPARATOR = ","

_PUNCTUATION = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def split_authors(credit: str | None) -> list[str]:
    """The people named in one book's credit line, in the order written.

    Empty, whitespace-only and separator-only strings all give an empty list,
    which is the same answer as a NULL column: a book with nobody credited has
    no authors rather than one author called "".

    Repeats are dropped, keeping the first: "Tolkien, Tolkien" is one person
    written twice, and counting the book twice on their page would be wrong in
    the one place the page exists to be right.
    """
    if not credit:
        return []
    names: list[str] = []
    seen: set[str] = set()
    for part in credit.split(_SEPARATOR):
        name = _WHITESPACE.sub(" ", part).strip()
        if not name:
            continue
        key = author_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def author_key(name: str) -> str:
    """The key two spellings share when folding them needs nobody's permission.

    Case, accents and punctuation, and nothing else. A fold at this level has
    no row behind it, so there is nothing to delete to undo one: it has to be a
    difference nobody would call a decision. Everything that *is* a decision
    goes through a merge, which is reversible.

    Punctuation becomes a **space** rather than nothing, which is what folds
    `J.R.R. Tolkien` into `J. R. R. Tolkien` and `Ann-Marie Baker` into `Ann
    Marie Baker`. Deleting it instead would fold the first pair the other way
    (`jrr`) and stop folding the second at all.

    What it deliberately does not reach is a spelling with the spaces moved
    rather than the punctuation: `JRR Tolkien` keeps its own key, because the
    rule that would catch it also catches `Ann Aker` and `Anna Ker`. See
    `squashed_key`.
    """
    decomposed = unicodedata.normalize("NFKD", name.casefold())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _WHITESPACE.sub(" ", _PUNCTUATION.sub(" ", stripped)).strip()


def squashed_key(name: str) -> str:
    """`author_key` with the spaces gone too, for suggesting rather than folding.

    This is the aggressive key. It reaches `JRR Tolkien` from `J. R. R.
    Tolkien`, which is nearly always right, and `Ann Aker` from `Anna Ker`,
    which is not: hence a suggestion somebody confirms rather than a fold.
    """
    return author_key(name).replace(" ", "")


def resolve_alias_map(aliases: Mapping[str, str]) -> dict[str, str]:
    """Flatten `alias_key -> canonical name` so one lookup is always enough.

    The writer keeps the map flat (`authorship.Authorship.merge` repoints any
    row that pointed at a name being folded away, and follows a name that is
    itself folded before storing it), so this is a guard rather than a
    mechanism: a hand-edited database, or a future writer that forgets, would
    otherwise leave a chain whose resolution depends on the order the rows
    happen to be read in.

    A cycle resolves to where it was entered rather than looping forever. It
    cannot be produced through the API and the loop bound says so out loud.
    """
    resolved: dict[str, str] = {}
    for alias_key, canonical in aliases.items():
        name = canonical
        for _ in range(len(aliases)):
            following = aliases.get(author_key(name))
            if following is None or author_key(following) == author_key(name):
                break
            name = following
        resolved[alias_key] = name
    return resolved


@dataclass(frozen=True)
class AuthorEntry:
    """One person, as far as this shelf knows.

    `key` is what an author is addressed by and is **not** an identity: it is
    derived from the name, so a merge moves it exactly as it moves the name.
    What it is stable under is the spelling differences `author_key` folds. A
    link carrying a retired key still resolves, through `alias_keys` rather
    than through the key being durable. `name` is for reading.
    """

    key: str
    name: str
    #: The books this person is credited on, ascending. Ids the caller may
    #: already see: `build_index` is fed a query that applied `visible_to`.
    book_ids: tuple[int, ...]
    #: Every spelling of this person on the shelf, as written, most used first.
    #: The merge panel shows them, and the book filter matches on them.
    spellings: tuple[str, ...]
    #: Spellings folded into this person by a merge that a member made, which
    #: are the ones an "undo" is offered for.
    alias_keys: frozenset[str]


def build_index(
    rows: Iterable[tuple[int, str | None]],
    aliases: Mapping[str, str],
) -> list[AuthorEntry]:
    """Every author on the shelf, from `(book_id, credit line)` pairs.

    The caller does the filtering: pass rows from a query that applied
    `visible_to()`, and every count and every book id below is filtered too.
    Nothing here can put back a row the query left out.

    `aliases` maps `author_key(folded spelling) -> canonical name`, ordered
    oldest first. When two aliases name one person with different spellings,
    the **last** wins, because that is the most recent decision somebody made
    and the one they will be looking for. Taking it from the alias map rather
    than from whichever book happened to be read last is what makes the
    displayed name independent of the order books were added in.

    **Every alias applies, whoever is asking.** The mapping is library wide,
    like a collection's name, so one book is filed under the same person for
    every member and `?author=` resolves the same way for all of them.

    Filtering the mapping per caller was tried and withdrawn in review. It made
    identity itself per member (one book under two keys and two names depending
    on who asked), it broke an old link whose spelling was on no book at all,
    and, because the merge endpoint gates on a different set, the two gates
    disagreed and the narrower one leaked what the wider one withheld.

    What stays filtered is the **shelf**, and that is the whole privacy rule
    here: entries come from `counts`, which only the rows passed in populate.
    An author whose every book is private therefore cannot appear for anybody
    else, because nothing they can see is credited to a spelling resolving to
    that person. The mapping says who a name means; it never says a book
    exists.

    Sorted by the display name, case insensitively, so the index reads as a
    list of people rather than as a list of byte values.
    """
    resolved = resolve_alias_map(aliases)
    chosen = {author_key(canonical): canonical for canonical in resolved.values()}

    book_ids: defaultdict[str, set[int]] = defaultdict(set)
    counts: defaultdict[str, defaultdict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    folded: defaultdict[str, set[str]] = defaultdict(set)

    for book_id, credit in rows:
        for spelling in split_authors(credit):
            raw_key = author_key(spelling)
            canonical = resolved.get(raw_key)
            key = author_key(canonical) if canonical is not None else raw_key
            if canonical is not None:
                # Recorded from the rows, so it holds only spellings on a book
                # this caller can see. The mapping is library wide; this is
                # the part of it they have evidence for, which is what the page
                # offers an undo beside.
                folded[key].add(raw_key)
            book_ids[key].add(book_id)
            counts[key][spelling] += 1

    entries: list[AuthorEntry] = []
    for key, spellings in counts.items():
        # Most used first, then alphabetically, so the display name does not
        # depend on which book was added first. A name somebody chose in a
        # merge wins over both, because it is the one fact here that was
        # actually decided rather than counted.
        ordered = sorted(spellings, key=lambda name: (-spellings[name], name))
        entries.append(
            AuthorEntry(
                key=key,
                name=chosen.get(key, ordered[0]),
                book_ids=tuple(sorted(book_ids[key])),
                spellings=tuple(ordered),
                alias_keys=frozenset(folded[key]),
            )
        )
    return sorted(entries, key=lambda entry: (entry.name.casefold(), entry.key))


# ── Suggestions ───────────────────────────────────────────────────────────────
#
# Why suggestions may be lossy, stated once: an accepted one writes an alias
# row and nothing else, and deleting that row puts the shelf back exactly as it
# was. Reversibility is what buys the licence to guess here, and it is why the
# same licence is *not* taken by `author_key`, which folds with nobody asked.

class SuggestionReason(StrEnum):
    """Which rule offered a group, so a person can tell a certainty from a guess.

    **An enum rather than four string constants, and the reason is a defect it
    already caused.** `AuthorSuggestionOut.reasons` crosses the API, and while
    it was typed `list[str]` the client held its own map of three of the four
    and fell back to rendering the raw value. `identity` shipped that way and a
    reader saw the word `identity` beside `same name, spaced differently`.

    As an enum it reaches the client as a union, so
    `SuggestionCard.tsx`'s `REASONS` is exhaustive by type and **a fifth rule
    fails `bun run typecheck` instead of shipping untranslated.** That is the
    guard; nothing here can enforce it from the Python side.

    Module local rather than in `enums.py`, which is the house pattern for a set
    no column stores: `covers.CoverOutcome`, `metadata.Outcome`,
    `targets.Transport` and `schemas.public.PublicBookSort` are the same shape.
    `enums.py` is for the closed sets the ORM writes to a column, and no row
    anywhere holds one of these: a suggestion is computed per request and stored
    nowhere.
    """

    #: The two spellings carry the same ISNI. The one rule that reads a stored
    #: fact rather than the letters of a name.
    IDENTITY = "identity"
    SPELLING = "spelling"
    INITIALS = "initials"
    FRAGMENT = "fragment"


@dataclass(frozen=True)
class AuthorSuggestion:
    """Names that are probably one person, and why they are being offered."""

    keys: tuple[str, ...]
    names: tuple[str, ...]
    reasons: tuple[SuggestionReason, ...]


def suggest_merges(
    entries: Sequence[AuthorEntry],
    spines: Mapping[str, frozenset[str]] | None = None,
) -> list[AuthorSuggestion]:
    """Groups of names that look like one person.

    Four rules, each of which has to be worth a person's attention:

    `identity`  the two spellings carry the same ISNI. The only rule here that
                reads a stored fact rather than the letters of a name, and the
                only one that is right about a pen name, a transliteration or a
                married name, none of which look alike. `spines` supplies it:
                see `_edges_on_identity`, and `authorship.IDENTITY_SPINE` for
                which file it comes from.
    `spelling`  the same name with the spaces moved: `JRR Tolkien` and `J. R.
                R. Tolkien`. Nearly always right, and the only reason it is not
                folded automatically is `Ann Aker` against `Anna Ker`.
    `initials`  the same surname and the same first initial, where at least one
                side abbreviates a given name: `U. K. Le Guin` and `Ursula K.
                Le Guin`. The abbreviation is required, or `John Smith` and
                `James Smith` would be offered as one person on every shelf
                that holds both.
    `fragment`  one name's words are all inside the other's, and the shorter
                has two of them: `Le Guin` and `Ursula K.` against `Ursula K.
                Le Guin`. That is the catalogue-order split, and both halves of
                it land in the same group as the whole name. Two words are
                required because a one-word name is a fragment of far too much:
                `Homer` would otherwise be offered against `Homer Hickam`.

    Transitive by construction: a name matched by two rules pulls both groups
    together, so `J. Smith`, `John Smith` and `James Smith` arrive as one group
    of three. That is deliberate. The merge panel takes a subset, and a group
    somebody has to split is more useful than three pairs that hide the fact
    they overlap.

    Two of the four rules compare pairs inside a bucket, so both skip a bucket
    holding more than `MAX_BUCKET` names. See that constant: the bucket is
    member-controlled and the cost is paid before `MAX_SUGGESTIONS` can cap
    anything.

    **`spines` is optional so that every caller with no rows in hand keeps
    working unchanged**, which is what the ticket's open question asks for from
    the other end: an author with no ISNI is offered exactly the suggestions
    they were offered before, because the identity rule contributes no edge for
    a key it holds nothing for. A shelf where nobody has confirmed an authority
    record is that case for every author on it.
    """
    by_key = {entry.key: entry for entry in entries}
    budget = _Budget(MAX_COMPARISONS)
    edges = [
        # No budget: bucketed by an exact key, so it is one pass over the names
        # and compares nothing.
        *_edges_on_identity(by_key, spines or {}),
        *_edges_on_squashed_key(by_key),
        *_edges_on_initials(by_key, budget),
        *_edges_on_fragments(by_key, budget),
    ]

    parent = {key: key for key in by_key}

    def find(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for left, right, _reason in edges:
        a, b = find(left), find(right)
        if a != b:
            parent[b] = a

    # Reasons are attached after every edge has been applied, so a group filed
    # under a root that changed while it grew keeps all of them. Attaching them
    # during the union loses the ones recorded against a root that later became
    # a child.
    reasons: defaultdict[str, set[SuggestionReason]] = defaultdict(set)
    for left, _right, reason in edges:
        reasons[find(left)].add(reason)

    grouped: defaultdict[str, list[str]] = defaultdict(list)
    for key in by_key:
        grouped[find(key)].append(key)

    suggestions = [
        AuthorSuggestion(
            keys=tuple(sorted(keys)),
            names=tuple(by_key[key].name for key in sorted(keys)),
            reasons=tuple(sorted(reasons[root])),
        )
        for root, keys in grouped.items()
        if len(keys) > 1
    ]
    # Biggest first, then by name, so the order does not depend on dictionary
    # insertion and the cap below takes the same tail on every run.
    suggestions.sort(key=lambda group: (-len(group.keys), group.names))
    return suggestions[:MAX_SUGGESTIONS]


#: One suggested pairing: two author keys and the rule that produced it.
_Edge = tuple[str, str, SuggestionReason]


def _edges_on_identity(
    by_key: Mapping[str, AuthorEntry], spines: Mapping[str, frozenset[str]]
) -> list[_Edge]:
    """Two spellings carrying the same ISNI are one person, and say so.

    `spines` maps an entry key to every value that entry's evidenced spellings
    carry under one authority file. **Which file is the caller's to decide and
    is not checkable here**: these are opaque strings, so a second caller
    inherits none of `authorship._spines`' rules, neither the scheme nor the
    visibility walk. `authorship.IDENTITY_SPINE` names the file, and
    `tests/test_authorship.py::TestOnlyTheSpineSaysTwoSpellingsAreOnePerson`
    guards the one production caller rather than this function.

    **A suggestion, like the other three, and the reason is that an automatic
    fold would mint an author id.** A shared ISNI is the strongest evidence this
    app can hold that two spellings are one person, so the case for folding on
    it is real and it is refused anyway: folding here would make the ISNI the
    key that groups books, and an author would stop being a name on a book.
    That is the internal identifier `AuthorAlias` refuses, arriving without a
    column.

    "It would adjudicate at write time" is **not** the argument, and the
    distinction is worth keeping straight because it is the one a later change
    will reach for: this rule runs on a read, so folding here would be
    derivation rather than a write. What holds is that the spelling has to stay
    the key. The merge stays the act somebody performs, and deleting the alias
    row still puts the shelf back.

    **An entry holding more than one distinct value contributes nothing.** That
    is a disagreement and not an identity: two spellings a member folded
    together carry different ISNIs, so the merge is wrong or one of the numbers
    is, and there is no rule here entitled to say which. Keeping either would be
    resolution by ordering, which is the call `authority._viaf_sources` makes for
    a code a cluster names twice and `authority._national_from_wikidata` makes
    for a property with two values. The disagreement is not lost by being
    dropped here: `AuthorOut.identifier_conflicts` reports it under its scheme.

    **No budget, and the reason is the bucketing rather than a judgement about
    how many rows there are.** Grouping is by an exact identifier, so this is one
    pass over the entries and compares no pair, which is what
    `_edges_on_squashed_key` does with a name. A member can plant a bucket, by
    confirming one ISNI under many spellings, and a planted bucket of N costs
    N-1 edges rather than the N squared that `MAX_BUCKET` exists to bound.
    """
    buckets: defaultdict[str, list[str]] = defaultdict(list)
    for key in by_key:
        values = spines.get(key) or frozenset()
        # Exactly one, never the first of several. See the docstring: a second
        # value is a disagreement, and this rule reports nothing it cannot be
        # sure of.
        if len(values) == 1:
            buckets[next(iter(values))].append(key)
    return [
        (keys[0], other, SuggestionReason.IDENTITY)
        for keys in buckets.values()
        for other in keys[1:]
    ]


def _edges_on_squashed_key(by_key: Mapping[str, AuthorEntry]) -> list[_Edge]:
    buckets: defaultdict[str, list[str]] = defaultdict(list)
    for key, entry in by_key.items():
        buckets[squashed_key(entry.name)].append(key)
    return [
        (keys[0], other, SuggestionReason.SPELLING)
        for keys in buckets.values()
        for other in keys[1:]
    ]


def _edges_on_initials(
    by_key: Mapping[str, AuthorEntry], budget: _Budget
) -> list[_Edge]:
    """Same surname, same first initial, at least one side abbreviated.

    Bucketed on the last word, so a shelf is compared within surnames rather
    than name against name. A bucket past `MAX_BUCKET` is skipped whole: the
    comparison inside one is quadratic and the bucket is member-controlled.

    **This is the rule the cap costs something.** A name has exactly one last
    word, so an oversized surname bucket loses this rule for everybody in it:
    a library with two hundred and one authors called Smith gets no initials
    suggestion for any Smith. That is the trade, and it is the right way round,
    because the alternative is a page that does not load. `_edges_on_fragments`
    degrades far more gently for the reason recorded there.
    """
    # `abbreviated` is decided per name rather than per pair, and that is the
    # difference between this rule costing 0.71s and 0.16s over 200,000
    # comparisons: the test used to be
    # `any(len(w) == 1 for w in words[:-1] + other_words[:-1])`, which builds
    # two slices and a concatenation for every pair. It distributes over the
    # two names, so asking each name once answers every pair it appears in.
    buckets: defaultdict[str, list[tuple[str, str, bool]]] = defaultdict(list)
    for key, entry in by_key.items():
        words = author_key(entry.name).split()
        if len(words) > 1:
            # An abbreviation is a one-letter word: `u`, out of `U.`
            abbreviated = any(len(word) == 1 for word in words[:-1])
            buckets[words[-1]].append((key, words[0][0], abbreviated))

    edges: list[_Edge] = []
    for candidates in buckets.values():
        if len(candidates) > MAX_BUCKET:
            continue
        for index, (key, initial, abbreviated) in enumerate(candidates):
            for other_key, other_initial, other_abbreviated in candidates[index + 1 :]:
                if not budget.spend():
                    return edges
                if initial != other_initial:
                    continue
                # One side abbreviated is what keeps two different people with
                # the same surname and the same initial out of each other's
                # groups.
                if not (abbreviated or other_abbreviated):
                    continue
                edges.append((key, other_key, SuggestionReason.INITIALS))
    return edges


def _edges_on_fragments(
    by_key: Mapping[str, AuthorEntry], budget: _Budget
) -> list[_Edge]:
    """One name's words are all inside another's, and the shorter has two.

    Bucketed on each word, so only names sharing a word are compared at all,
    and a bucket past `MAX_BUCKET` is skipped whole.

    **This rule degrades gently, which the one above does not.** A name sits in
    one bucket per word it has, so an oversized "de" or "van" bucket costs the
    pairs that would have been found through *that* word only; every name in it
    is still compared through its other words. Losing a bucket here loses a
    little recall, where losing a surname bucket in `_edges_on_initials` loses
    the whole rule for those names.

    The cap is nonetheless what keeps the rule safe rather than merely fast:
    "every author sharing one word" is a set a member fills by typing, so a
    shelf where five hundred names carry "de" is a shelf where this rule
    compares 124,750 pairs on every page load. On that input it is also the
    least productive of the three, because a bucket of names sharing one word
    yields no fragment edge at all: the subset test fails on every pair of it.
    """
    words = {
        key: frozenset(author_key(entry.name).split()) for key, entry in by_key.items()
    }
    buckets: defaultdict[str, list[str]] = defaultdict(list)
    for key, tokens in words.items():
        for token in tokens:
            buckets[token].append(key)

    edges: list[_Edge] = []
    for keys in buckets.values():
        if len(keys) > MAX_BUCKET:
            continue
        for index, key in enumerate(keys):
            for other in keys[index + 1 :]:
                if not budget.spend():
                    return edges
                # A pair sharing two words is compared twice, and that is
                # cheaper than remembering it. The set that used to dedupe here
                # was sized by distinct pairs **across every bucket**, which is
                # where the memory went: 347.5 MB at 3,200 names. A repeated
                # comparison costs one subset test and a duplicate edge, and
                # the union below is idempotent.
                left, right = words[key], words[other]
                shorter, longer = (
                    (left, right) if len(left) < len(right) else (right, left)
                )
                if len(shorter) >= 2 and shorter < longer:
                    edges.append((key, other, SuggestionReason.FRAGMENT))
    return edges
