"""Which catalogues are asked about a book, and in what order.

**The rules only.** `settings_store.catalogue_sources` reads the stored row and
hands it here, and `metadata.py` is given the answer rather than asking a
database, which is what keeps that module free of a `Session`. Same split as
`authors.py` under `authorship.py`.

## What the order means, and what it deliberately does not

A source order decides two different things, and they are two rules rather than
one. **This module owns the first only:**

* **Which sources are asked, and in what order.** That is the ticket's own
  complaint: adding national catalogues to a fixed order asks all of them in an
  order nobody chose.
* **Which source is believed when two disagree about one field.** That stays in
  `metadata.py`, as `_MATCH_PRECEDENCE` for the search path and
  `_preferred_source` for the lookup path.

**One list cannot honestly drive both.** Three reasons, and the third is the
one that decides it:

1. The two orders disagree about one source in opposite directions.
   `metadata.py`'s chain comment calls Open Library "the broadest and the
   worst", five times slower than anything else (1.64s against 0.36s and
   0.11s), and kept it out of the pair asked on every lookup. `_MATCH_PRECEDENCE`
   puts it **first**, because its search index is edited towards how people
   write titles. **Only one of those two carries a number**: the exclusion is
   measured, the precedence is a reason. An earlier draft of this paragraph
   claimed both were measured, which was an overclaim a critic caught.
2. The lookup path's belief rule is not a list at all. `_preferred_source`
   returns the DNB for a `9783` ISBN and K10plus for anything else, computed per
   ISBN, because the DNB holds foreign books mostly as cross references. No
   static ordering can express that, and discarding it re-opens the failure
   `_is_placeholder_title` exists to catch.
3. **A single list would have to reproduce today's belief on the search path,
   and no order of this roster does.** `metadata._SECONDARY_SOURCES` is
   `{bnf, loc, oenb}` and it is exactly `_MATCH_PRECEDENCE[4:]`, so "believed
   last" is a contiguous tail **of that order**. In this module's order those
   three sit at positions 2, 5 and 6, which is not a tail and not contiguous.
   So a cut position in the ask order cannot express the regional set, and
   seeding a different ask order to make it contiguous changes the lookup chain
   instead. Either way something a household never touched moves.

**The two paths do not share a roster either**, which is not an argument on its
own but is why a single list would have two entries that mean nothing on half
the paths they claim to order: five sources answer an ISBN, seven answer a
title.

So the stored list is the **ask** order, and the settings screen says so rather
than implying it reorders belief.

## What this list does not reach, stated rather than left to be discovered

**Only the catalogues `metadata.py` asks about a book.** Three other paths reach
outward and none of them consults this list:

* `covers.py` asks `covers.openlibrary.org` and `portal.dnb.de` for a cover
  image, keyed on the ISBN, on every successful lookup. So switching Open
  Library off stops it being asked for a **record** and not for a **picture**.
* `authority.py` asks lobid, VIAF and Wikidata about an author.
* `google_books.py` is reached through this list on the lookup and search
  paths, and directly by nothing else.

That boundary is deliberate for now rather than an oversight, and the reason it
is defensible is narrow: the motivating case is a library that may not send its
readers' queries to a **commercial** API, and the only commercial source here is
Google Books, which this list does control completely. It is not defensible as a
general "nothing is asked" claim, so nothing here makes one. Extending the list
to the cover and authority hosts is its own piece of work: they are a different
subsystem with a different allowlist (`covers.is_fetchable`), and half doing it
would leave a switch that means two different things depending on the row.

## The tier is a position, not a property of the source

`metadata.lookup` asks a first tier together and a second tier one at a time,
stopping at the first hit. Membership of the first tier is `ALWAYS_ASKED`
positions from the top of the enabled list, and **not** a per source constant.

**That was the first draft and the OENB is what refuted it.** Reading
`_FALLBACK_SOURCES` as a speed classification is wrong: the OENB's measured mean
is 0.240s, faster than K10plus's 0.36s, and it sits in the second tier because
it adds 3 answers in 50 rather than because it is slow. Freezing that as a
property of the source would freeze exactly the case the ticket was filed about,
since an Austrian household wants it asked first and a German one does not.
A position is the thing a household can actually move.
"""

from dataclasses import dataclass
from typing import Any, Final

from enums import CatalogueSource

#: Every source, in the order a new install asks them.
#:
#: **This is today's behaviour written down, not a fresh opinion**, and the two
#: constants it replaces are gone rather than left beside it. The first two were
#: `metadata._FAST_SOURCES` and the next three were `metadata._FALLBACK_SOURCES`
#: in its order, so a household that never opens the settings screen sees no
#: change. BNF and LOC come last because they answer no ISBN lookup at all, so
#: their position only ever breaks a tie.
#:
#: **The measurements those constants carried, kept here because they are what
#: justifies this order rather than any other:**
#:
#: * The DNB and K10plus lead because they are free, unmetered, and fast enough
#:   that asking both costs the slower of the two rather than the sum.
#: * **The OENB is third, ahead of Open Library, and that is measured rather
#:   than alphabetical.** It is the only source that answers for an Austrian
#:   imprint the German pair both missed: 3 of 50, measured 2026-08-27.
#: * It is also much the fastest of the three, and **the two figures come from
#:   different samples and are not one measurement**: the OENB's mean of 0.240s
#:   is over the 50 live lookups of that same 2026-08-27 Austrian sample, while
#:   Open Library's 1.64s is off the ten ISBN comparison in `metadata.py`'s
#:   chain comment, taken on another date against another set of books. They are
#:   the right order of magnitude apart rather than precisely comparable, which
#:   is all this ordering needs.
#: * Google Books is last of the five that answer an ISBN because it is the only
#:   one with a key, a quota and a bill attached.
DEFAULT_ORDER: Final[tuple[CatalogueSource, ...]] = (
    CatalogueSource.DNB,
    CatalogueSource.K10PLUS,
    CatalogueSource.OENB,
    CatalogueSource.OPEN_LIBRARY,
    CatalogueSource.GOOGLE_BOOKS,
    CatalogueSource.BNF,
    CatalogueSource.LOC,
)

#: The sources that can answer an ISBN lookup: `metadata._SOURCES`' keys.
#:
#: BNF and LOC are absent because neither was worth an ISBN request. The
#: measured reason is in `metadata.py`'s chain comment: the Library of Congress
#: answered 2 of 10, and both were covered by something else.
LOOKUP_SOURCES: Final[frozenset[CatalogueSource]] = frozenset(
    {
        CatalogueSource.DNB,
        CatalogueSource.K10PLUS,
        CatalogueSource.OENB,
        CatalogueSource.OPEN_LIBRARY,
        CatalogueSource.GOOGLE_BOOKS,
    }
)

#: The sources that can answer a title search. All of them.
SEARCH_SOURCES: Final[frozenset[CatalogueSource]] = frozenset(DEFAULT_ORDER)

#: Sources that cost money per request, so asking one for a book another source
#: already answered is a bill for nothing. See `Plan.lookup_together`.
METERED: Final[frozenset[CatalogueSource]] = frozenset({CatalogueSource.GOOGLE_BOOKS})

#: Sources that need a credential the household supplies, so an install without
#: one has a provider in the list that can never answer. The settings screen
#: says so rather than leaving it as the silent cause of "why is this not
#: working". `config.google_books_api_key_from_env` and the stored key are the
#: two places one can come from; `settings_store.google_books_api_key` is the
#: single answer to whether there is one.
NEEDS_A_KEY: Final[frozenset[CatalogueSource]] = frozenset(
    {CatalogueSource.GOOGLE_BOOKS}
)

#: How many enabled lookup sources are asked **together** before the rest are
#: asked one at a time.
#:
#: Two, which is what `metadata._FAST_SOURCES` has always been, and the number
#: is a cost bound rather than a taste: an ordinary lookup makes this many
#: outbound requests whatever the household puts in the list, so reordering
#: cannot turn every lookup into a seven way fan out. What a household changes
#: is **which** two, which is the whole point of the control.
ALWAYS_ASKED: Final = 2

#: The key the stored object hangs the list off. An object rather than a bare
#: list because `settings_store.get_json` refuses a list on purpose: a list
#: parses as valid JSON and is then indexed by a string somewhere downstream.
_STORED_KEY: Final = "sources"


@dataclass(frozen=True)
class Preference:
    """One source, and whether this library asks it."""

    source: CatalogueSource
    enabled: bool


@dataclass(frozen=True)
class Plan:
    """Which sources to ask on one request, resolved once and passed in.

    **A permutation of the roster, always.** `parse` guarantees it, so nothing
    downstream has to handle a name `metadata._SOURCES` has no function for, and
    there is no `KeyError` to reach on the hourly path.
    """

    preferences: tuple[Preference, ...]

    @property
    def asked(self) -> tuple[CatalogueSource, ...]:
        """Every enabled source, in the household's order."""
        return tuple(entry.source for entry in self.preferences if entry.enabled)

    @property
    def lookup_together(self) -> tuple[CatalogueSource, ...]:
        """The leading enabled sources that answer an ISBN, asked concurrently.

        **A metered source is never here, whatever position it holds**, and that
        is the one thing the household's order does not decide. This tier is
        asked on **every** lookup, including the ones another source answers, so
        a metered source in it bills for a book that was already found. Google
        Books at the top would be a charge per barcode scan.

        The refusal is structural rather than a warning on a screen, because the
        promise it protects is structural: `lookup` says an ordinary lookup
        never spends quota, and a sentence in a browser cannot keep that true.
        Moving a metered source up still moves it earlier in the tier below,
        which is where being asked can actually save a miss.
        """
        return tuple(
            name for name in self._lookup_chain if name not in METERED
        )[:ALWAYS_ASKED]

    @property
    def lookup_in_turn(self) -> tuple[CatalogueSource, ...]:
        """Asked one at a time, and only if the first tier found nothing.

        Everything in the chain that the first tier did not take, in the
        household's order, so a metered source excluded from that tier is asked
        here at the position it was given rather than dropped.
        """
        leading = frozenset(self.lookup_together)
        return tuple(name for name in self._lookup_chain if name not in leading)

    @property
    def searched(self) -> tuple[CatalogueSource, ...]:
        """Every enabled source that answers a title search, in order."""
        return tuple(name for name in self.asked if name in SEARCH_SOURCES)

    @property
    def _lookup_chain(self) -> tuple[CatalogueSource, ...]:
        return tuple(name for name in self.asked if name in LOOKUP_SOURCES)


#: What a library that has never opened the settings screen gets.
DEFAULT_PLAN: Final = Plan(
    tuple(Preference(source, True) for source in DEFAULT_ORDER)
)


def parse(stored: dict[str, Any]) -> Plan:
    """Turn whatever the settings row holds into a full roster.

    **The result is a permutation of `DEFAULT_ORDER` by construction**, which is
    the property that matters and the reason this is not a validator returning
    errors. A name nobody recognises is dropped, a repeat is ignored, and every
    source the stored value failed to mention is appended in the default order
    and enabled. So a row written by a restore, by a hand edit, or by a release
    that knew a source this one does not, degrades to something askable instead
    of raising inside a request.

    That is the same degrade rule `settings_store.get_int`, `get_json` and
    `get_locale` follow, and it matters more here: the caller is on the lookup
    path, so a raise would break adding a book rather than one screen.

    **Absent and empty are the same thing and both mean "the defaults"**, which
    is what makes a fresh install and a cleared row behave alike. Turning every
    source off is a different statement and is preserved: the entries are
    present and each says `false`.
    """
    entries = stored.get(_STORED_KEY)
    if not isinstance(entries, list):
        return DEFAULT_PLAN

    preferences: list[Preference] = []
    seen: set[CatalogueSource] = set()
    for entry in entries:
        # **No truncation, deliberately, and it was here once.** A cap of 100
        # entries read against a roster of seven looks like a bound on a hostile
        # row and is an **on switch**: a hundred unrecognised entries followed by
        # `google_books` switched off drops the real entry, and the tail below
        # then appends google_books enabled. The bound meant to contain a
        # corrupt row would have defeated the off switch, which is the one thing
        # this value exists to make true.
        #
        # The list is already in memory by the time it reaches here, since
        # `settings_store.get_json` parsed the whole row, so iterating it costs
        # nothing the read did not already cost. The bound that matters is on
        # the **write**, which is `schemas.settings.MAX_CATALOGUE_SOURCES`.
        if len(seen) == len(DEFAULT_ORDER):
            break
        if not isinstance(entry, dict):
            continue
        raw = entry.get("source")
        if not isinstance(raw, str):
            continue
        try:
            source = CatalogueSource(raw)
        except ValueError:
            continue
        if source in seen:
            continue
        seen.add(source)
        # **`is True`, not truthiness, and not `is not False`.** This table
        # stores every other boolean as the string `"false"`, so a hand edit or
        # a restore writing that spelling here is likely rather than exotic, and
        # under `is not False` the string `"false"` is a **true** value: the
        # off switch would fail open on the most probable way of getting it
        # wrong. The default is `True` because an entry that names a source and
        # says nothing about it is the same case as a source the value never
        # named at all, which the tail below enables.
        preferences.append(Preference(source, entry.get("enabled", True) is True))

    if not preferences:
        return DEFAULT_PLAN

    # Every source the stored value did not mention, in the default order. A
    # release that adds a source must not leave it unasked for every library
    # that saved a list before it existed.
    preferences.extend(
        Preference(source, True) for source in DEFAULT_ORDER if source not in seen
    )
    return Plan(tuple(preferences))


@dataclass(frozen=True)
class Described:
    """One source with everything a settings screen needs already decided.

    **The rules live here rather than in the browser**, for the reason
    `public_catalogue_published` is computed on the server: two places deciding
    one rule is how a screen comes to promise something the server does not do.
    """

    source: CatalogueSource
    enabled: bool
    answers_lookup: bool
    answers_search: bool
    asked_first: bool
    needs_a_key: bool
    has_key: bool
    ready: bool


def in_force(plan: Plan, ready: frozenset[CatalogueSource]) -> Plan:
    """The plan as it will actually be used: switched on **and** able to answer.

    **The single reconciliation point, and it exists because Google Books has
    two switches.** Its own section decides whether this library uses Google at
    all and holds the key; the provider list decides whether it is asked and
    where. Two rows for one source is a fact stored twice, and the answer here
    is the one `settings_store.public_catalogue_is_published` already uses for
    the two publishing switches: conjoin them in one function that every caller
    goes through, so the two cannot be read as disagreeing.

    Doing it here rather than at the six call sites is the whole point. Before
    this, `GOOGLE_BOOKS_ENABLED` was honoured at four of them and ignored at the
    two that matter most: scanning a barcode and refreshing a record both sent
    the ISBN to Google with the toggle off, and with no key stored they sent it
    anonymously rather than not at all. Two critics found that independently.

    `stored_catalogue_sources` is what the settings screen reads, for the reason
    `get_raw` exists beside `in_force`: a screen must show what an admin typed,
    or they turn a switch on and watch it come back off.
    """
    return Plan(
        tuple(
            Preference(entry.source, entry.enabled and entry.source in ready)
            for entry in plan.preferences
        )
    )


def describe(
    plan: Plan,
    *,
    ready: frozenset[CatalogueSource],
    credentials: frozenset[CatalogueSource],
) -> tuple[Described, ...]:
    """The whole roster, in order, with the derived facts filled in.

    `plan` is the **stored** one, so the screen shows what an admin set.

    **Two sets rather than one, and they are two different causes.** `ready` is
    "could answer if asked"; `credentials` is "a key for it is in force". They
    differ for exactly the case that made this a finding: a library with a
    Google Books key whose Google Books card is switched off is not ready, and a
    screen reading `ready` alone told it to add a key it already had, which is
    the sentence this whole feature exists to stop somebody hunting for. Sending
    the two facts rather than their conjunction lets the screen name the cause.

    Only a caller holding a database can answer either, so both are passed in,
    which is what keeps this module free of one.

    **Both ignore `enabled` on purpose.** A household switching Google Books on
    wants to be told there is no key at the moment it switches it on, and a
    field that went false only once the source was already enabled could not say
    so first.
    """
    # **The leading pair as it will actually be asked**, so a source kept out of
    # the plan for want of a key does not hold a slot on the screen that it does
    # not hold in a request. Computed here rather than taken from the stored
    # plan, which agreed only by accident: today the one unready source is also
    # the one barred from this tier for being metered.
    leading = frozenset(in_force(plan, ready).lookup_together)
    return tuple(
        Described(
            source=entry.source,
            enabled=entry.enabled,
            answers_lookup=entry.source in LOOKUP_SOURCES,
            answers_search=entry.source in SEARCH_SOURCES,
            asked_first=entry.source in leading,
            needs_a_key=entry.source in NEEDS_A_KEY,
            has_key=entry.source in credentials,
            ready=entry.source in ready,
        )
        for entry in plan.preferences
    )


def serialise(plan: Plan) -> dict[str, Any]:
    """The object to store. Written back in full, never patched."""
    return {
        _STORED_KEY: [
            {"source": entry.source.value, "enabled": entry.enabled}
            for entry in plan.preferences
        ]
    }


def from_wire(entries: list[Preference], current: Plan) -> Plan:
    """A plan from what a client sent, completed from what is already stored.

    **An unmentioned source keeps its current setting**, which is the one place
    this differs from `parse`, and the difference is not cosmetic. `parse` fills
    a gap from `DEFAULT_ORDER`, enabled, because there the gap means "a source
    this release added after that row was written". Here it means "the client
    did not mention it", and defaulting that to enabled turns a payload naming
    one source into an instruction to switch the other six **on**: a request to
    disable Google Books would have re-enabled everything a household had
    turned off.

    Order follows the same rule: the sources the payload named lead, in its
    order, and the rest follow in the order they already had.
    """
    named = {entry.source: entry.enabled for entry in entries}
    ordered = [Preference(entry.source, named[entry.source]) for entry in entries]
    seen = set(named)
    ordered.extend(
        entry for entry in current.preferences if entry.source not in seen
    )
    # Through `parse` all the same, so one function decides what a roster is and
    # a source this build does not know is dropped in exactly one place.
    return parse({_STORED_KEY: [
        {"source": entry.source.value, "enabled": entry.enabled} for entry in ordered
    ]})
