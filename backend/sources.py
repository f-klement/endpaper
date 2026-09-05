"""Which catalogues are asked about a book, and in what order.

**The rules only.** `settings_store.catalogue_sources` reads the stored row and
hands it here; `metadata.py` is given the answer rather than asking a database,
which is what keeps that module free of a `Session`.

**This module owns which sources are asked and in what order. It does not own
which source is believed** when two disagree about a field: that is
`_MATCH_PRECEDENCE` for the search path and `_preferred_source` for the lookup
path, both in `metadata.py`.

**One list cannot honestly drive both**, and the reason is not tidiness. The two
orders disagree about Open Library in opposite directions, the lookup path's
belief rule is computed per ISBN rather than being a list at all, and no
permutation of this roster reproduces today's search belief. The full argument is
in `docs/decisions.md`.
"""

from dataclasses import dataclass
from typing import Any, Final

import isbn
import targets
from enums import CatalogueSource


@dataclass(frozen=True)
class Measured:
    """What one source was measured to do, so the order can be derived and not asserted.

    **The numbers live here rather than only in prose**, because a number written
    in prose stops being re-derived and starts being copied. `test_sources.py`
    computes `DEFAULT_ORDER` from this table and compares, so a reorder that does
    not also restate the measurement fails rather than being reviewed.

    **The sample these came off is committed**, at
    `backend/tests/fixtures/catalogue_survey_2026_08_31.json`, 500 rows of one
    ISBN each with what every source answered and how long it took.
    `TestTheConstantsAreRederivableFromTheCommittedSample` recomputes every field
    below from it. So the numbers are checkable rather than asserted, and that
    was a deliberate choice against the cheaper one: three integers whose
    evidence lived in a working directory deleted when the work shipped would be
    a stated bound nobody could ever contradict, in a module whose whole subject
    is that a stated reason must be checkable.

    **What that does not buy, since the smaller claim is easy to read as the
    larger one.** It proves the constants describe **that recorded run**. It
    cannot prove the run was honest, because editing the table and the sample
    together defeats it, and it cannot prove a re-run would agree: these are live
    third party catalogues and the figures are dated. Re-deriving them against
    the world means re-running the probe, not running the suite.

    `answered` and `p90_seconds` come from **one** sample, which is what lets them
    be compared: `MEASURED`'s own docstring names it.
    """

    #: ISBNs this source returned a record for, of `of` asked.
    answered: int
    #: The sample size. Its own, because a source excluded from its denominator
    #: for refusing to answer has a smaller one than its neighbour.
    of: int
    #: Ninetieth percentile latency for one lookup, seconds, nothing else in
    #: flight. **p90 and not the mean**, because a tier is gathered and so costs
    #: its slowest member, and a mean hides the case that decides the budget.
    p90_seconds: float
    #: How many of this source's answers fall in its single largest frame.
    #:
    #: **With `answered`, this is what separates a general catalogue from a
    #: national one**, and the ratio rather than either number is the thing:
    #: `largest_frame / answered` is how concentrated the source is. Stored as
    #: the raw count so this table stays measurements and the conclusion is
    #: computed. See `TIER_MAX_CONCENTRATION`.
    #:
    #: **This replaced a count of frames answered, and the replacement is the
    #: whole point.** The first version asked how many of the ten frames a source
    #: answers **anything** in, which a design critic measured as too weak in the
    #: round that introduced it: it flatters the DNB, which scores 5 frames while
    #: 83 of its 91 answers are in two, and it admits the OeNB at 4 frames and
    #: **1** marginal answer while barring the NLG at 1 frame and **34**. It is a
    #: rule about presence standing in for a rule about generality.
    #:
    #: The Czech National Library is what made that undeniable: it answers in
    #: **6** frames, so the frame count admits it to the tier, and **49 of its 59
    #: answers are Czech**. Concentration puts it where it belongs without
    #: anybody re-deciding.
    largest_frame: int


#: What each free lookup source does, measured 2026-08-30, except the BNE's row.
#:
#: **The sample**: ten frames of 50 domestic ISBNs, 500 in all, so a source with
#: a national remit is measured on the books it is for rather than on a global
#: average that would hide it.
#:
#: **Coverage and latency were measured in separate passes**, and a latency pass
#: is void if anything else is in flight against the same host. The committed
#: numbers come from a pass with nothing else running.
#:
#: These figures drive `ALWAYS_ASKED` through the tier rules below. Re-measure
#: with the committed sample rather than adjusting a row.
MEASURED: Final[dict[CatalogueSource, Measured]] = {
    CatalogueSource.DNB: Measured(
        answered=91, of=500, p90_seconds=0.258, largest_frame=44
    ),
    CatalogueSource.K10PLUS: Measured(
        answered=210, of=500, p90_seconds=0.512, largest_frame=45
    ),
    CatalogueSource.OENB: Measured(
        answered=55, of=500, p90_seconds=0.538, largest_frame=30
    ),
    CatalogueSource.OPEN_LIBRARY: Measured(
        answered=237, of=500, p90_seconds=2.562, largest_frame=36
    ),
    CatalogueSource.NLG: Measured(
        answered=37, of=500, p90_seconds=0.238, largest_frame=37
    ),
    CatalogueSource.NKP: Measured(
        answered=59, of=500, p90_seconds=0.239, largest_frame=49
    ),
    # **This column is a later pass on the same 500 books**, measured
    # 2026-09-05, where every other column comes from the pass this table's own
    # heading dates, and that is said here rather than left for a reader to
    # infer from the fixture. The
    # comparison `Measured` promises is therefore exact for the coverage counts,
    # which are a property of the books, and approximate for `p90_seconds`,
    # which is a property of a day's network. It ranks **third** in the tail,
    # two books behind the NKP and six ahead of the NLG, and the tail is ordered
    # on `TAIL_MARGINAL` rather than on latency, so a latency figure could not
    # move its position at all.
    CatalogueSource.BNE: Measured(
        answered=57, of=500, p90_seconds=0.276, largest_frame=47
    ),
}

#: What the best tier of each size answers, of the same 500 ISBNs as `MEASURED`.
#:
#: **A union, which is exactly what `MEASURED` cannot express.** Two sources that
#: answer the same books are worth less together than two that miss different
#: ones, and a per source table has no way of saying so. Each entry is the best
#: tier of that size that `FIRST_TIER_BUDGET_SECONDS` allows: K10plus alone,
#: then K10plus with the DNB, then both with the OENB. That is every source the
#: tier **rule** allows, which is narrower than every source inside the budget:
#: five are inside the budget and three are inside it and under
#: `TIER_MAX_CONCENTRATION` as well.
#:
#: **It exists to pin the tier's size against something other than the tier.**
#: Without it, a guard that derives the tier from `MEASURED` slices with
#: `ALWAYS_ASKED` and so agrees with any size it is given: a critic raised the
#: constant to 3 and moved the OENB up to match, and the guard named for the
#: tier rule passed. Now the slots have to earn their places one at a time.
#:
#: Recomputed from the committed sample beside `MEASURED`, and subject to the
#: same limit: it is evidence about that run and not about a re-run.
#:
#: **Over the sources a tier may hold, which is narrower than "inside the
#: budget".** `TIER_MAX_CONCENTRATION` keeps two national catalogues out, and it
#: has to be applied here as well or this table would price a tier that cannot
#: be built: the best pair of everything inside the budget is K10plus with the
#: NKP at **254**, against **222** for the pair that ships. That pair reaches 42
#: books the shipping pair does not, and **40 of the 42 are Czech**. The NLG pair
#: is the same shape one step milder, 244, with all 37 of its answers in the
#: Greek frame.
TIER_UNION: Final[dict[int, int]] = {1: 210, 2: 222, 3: 223}

#: How much of a source's coverage may sit in one frame and still be asked on
#: **every** lookup.
#:
#: **It decides the tier's size, not its membership.** Membership ranks by pooled
#: rate; the size rule unions rather than ranks, so without a concentration bound
#: the arithmetic demands a third concurrent request from every install
#: everywhere to serve one frame.
#:
#: **Concentration rather than a count of frames answered**, because a source
#: answering a little in many frames and one answering everything in one frame
#: are different propositions for a household that is in none of them.
TIER_MAX_CONCENTRATION: Final = 2 / 3

#: For each source asked one at a time, how many of the books the leading tier
#: missed it answers, of the same 500.
#:
#: **The tail's rule is marginal and no per source count can express it.** The
#: pooled counts read 237, 59, 57, 37 and 55; against the 278 books the leading
#: pair missed, the answers are 82, 42, 40, 34 and 1. So the pooled rule would
#: ask the OeNB before any of the three national catalogues, to reach a source
#: that answers one of those 278.
#:
#: **This is where a concentrated source earns its place.** The NKP is kept out
#: of the tier by `TIER_MAX_CONCENTRATION` and is second here, ahead of two
#: sources that answer more books overall, because what the tail is asked for is
#: precisely the books the tier could not find. The rule decides **where** a
#: national catalogue is asked, never whether.
#:
#: Google Books is absent for `MEASURED`'s reason: it is metered, a default
#: install has no key, and its position is a metering rule rather than a coverage
#: one.
TAIL_MARGINAL: Final[dict[CatalogueSource, int]] = {
    CatalogueSource.OPEN_LIBRARY: 82,
    CatalogueSource.NKP: 42,
    CatalogueSource.BNE: 40,
    CatalogueSource.NLG: 34,
    CatalogueSource.OENB: 1,
}

#: What one more concurrent slot has to answer before it is worth its request.
#:
#: Ten books per 500, and like `FIRST_TIER_BUDGET_SECONDS` it is a statement of
#: intent placed in a gap rather than a threshold fitted to the roster. The
#: second slot earns **12** and the third earns **1**, so every value from 2 to
#: 12 gives the same answer, and
#: `test_the_slot_threshold_is_not_fitted_to_this_roster` sweeps that rather
#: than asserting it. **The gap was [3, 35] before the NLG joined and the 020
#: rule changed**, and 10 sits 80.0% into the narrower one, which is inside that
#: test's bound and closer to an edge than it was.
#:
#: The cost the other side of it is not in this file and is the reason the
#: number is not lower: a slot is an outbound request on every lookup of every
#: install, against catalogues that are free to us and not free to run.
SLOT_MUST_EARN: Final = 10

#: How slow a source may be and still be asked on **every** lookup.
#:
#: **A statement of intent, not a threshold fitted to the roster.** Somebody is
#: standing at a shelf with a phone when this runs, and one second is what this
#: project is willing to spend before the first answer. The roster is nowhere
#: near it: the slowest source inside the budget is 0.538s (the OENB, which is
#: not in the tier) and the only one outside is
#: 2.562s, so every bound from 0.512s up to but not including 2.562s picks the
#: same tier. The endpoint is exclusive and that is not pedantry: at exactly
#: 2.562s Open Library qualifies and wins on coverage, so the tier changes.
#:
#: **The guard states that slack as a proportion of the interval, not in
#: seconds**, and that was a correction. An absolute floor of half a second left
#: 54ms of margin: K10plus need only remeasure at 0.500s, which is inside the
#: OENB's own run to run spread, and the guard would fail with no decision
#: changing. A proportion also survives a roster that is uniformly faster or
#: slower, where an absolute floor quietly becomes a different rule.
#: `test_the_budget_is_not_a_threshold_fitted_to_this_roster` asserts that across
#: the whole interval rather than leaving it as a claim.
FIRST_TIER_BUDGET_SECONDS: Final = 1.0

#: Every source, in the order a new install asks them.
#:
#: **The order decides latency and which records are merged, never coverage.**
#: `metadata.lookup` asks every enabled source until one answers, so the set of
#: ISBNs the chain resolves is the same under any permutation: modelled over
#: seven candidate orders against the 500 ISBN sample, **395 of 500 under every
#: one of them**. A reorder is never the fix for a book the chain misses.
#:
#: **The first tier is a latency budget.** `ALWAYS_ASKED` sources are gathered,
#: so the tier costs its slowest member rather than their sum, and membership is
#: *most likely to answer inside `FIRST_TIER_BUDGET_SECONDS` in more than one
#: frame*, deliberately not *most authoritative*. Promoting a source here changes
#: whether it is asked, never whether it is believed: belief is
#: `_preferred_source` per ISBN on the lookup path and `_MATCH_PRECEDENCE` on the
#: search path.
#:
#: The derivation, the seven modelled orders and the concentration rule are in
#: `docs/decisions.md`.
DEFAULT_ORDER: Final[tuple[CatalogueSource, ...]] = (
    CatalogueSource.DNB,
    CatalogueSource.K10PLUS,
    CatalogueSource.OPEN_LIBRARY,
    CatalogueSource.NKP,
    CatalogueSource.BNE,
    CatalogueSource.NLG,
    CatalogueSource.OENB,
    CatalogueSource.GOOGLE_BOOKS,
    CatalogueSource.BNF,
    CatalogueSource.LOC,
)

#: The sources that can answer an ISBN lookup.
#:
#: BNF and LOC are absent because neither was worth an ISBN request. The
#: measured reason is in `metadata.py`'s chain comment: the Library of Congress
#: answered 2 of 10, and both were covered by something else.
#: **Derived from the rows rather than written out**, which is the change this
#: ticket is. The capability was a Python set here and a dispatch table in
#: `metadata`, kept equal by a test; it is one field on one row now, so there is
#: nothing left for two lists to disagree about. What still has to be checked is
#: a different question, and `metadata.resolve` is where it went: whether the
#: reader a row names can actually read what the target answers with.
LOOKUP_SOURCES: Final[frozenset[CatalogueSource]] = frozenset(
    target.source for target in targets.SEEDED.values() if target.answers_lookup
)

#: The sources that can answer a title search.
#:
#: **Not "all of them" any more, and there are two exceptions with two
#: different kinds of reason.** This was `frozenset(DEFAULT_ORDER)` with a
#: comment saying every source answers a title search, which was true until the
#: Czech National Library joined.
#:
#: **The NKP's exception is the server's.** That target renders **one populated
#: record per response** whatever page size is asked for, measured across three
#: queries and four page sizes on 2026-08-31, so ten candidates would be ten
#: sequential requests to somebody else's free catalogue inside a 4.0s shared
#: deadline. Its ISBN lookup wants one record and gets one, 20 of 20, so that
#: path is unaffected.
#:
#: **The BNE's exception is ours, and it is a default rather than a finding.**
#: Its search works: 30 records, which is what a `search_multiplier` of 3 asks
#: for a limit of 10 and is the shape every other search row carries, answers in
#: 1.117s median over 15 samples. **This row's own search columns are zero**,
#: because it answers no search, so `search_records` on it returns 0 rather than
#: 30: the figure is what enabling it would cost, not what it asks today. Nobody has measured what a search
#: there would **find** that this roster does not, and no incumbent has that
#: measurement either: the BnF and the LoC hold search slots on the reverse
#: argument, that neither was worth an ISBN request. So this is not a bar the
#: BNE failed and the others passed. It is the conservative default for a source
#: nobody has measured on this path, taken because the cheap version of the
#: question is not free either: at 50 records the same target costs 2.448 to
#: 5.911s against a 4.0s whole fan out. Flipping it needs a measurement, not an
#: argument.
#:
#: **Derived from the rows**, and the sentence this replaces is worth keeping in
#: view: it said this was written out rather than derived, because a derivation
#: would have to encode the exception anyway. That was true while the alternative
#: was deriving it from `DEFAULT_ORDER` minus a special case. It is not true of
#: this derivation, because the exception is now the thing being read:
#: `targets.SEEDED[CatalogueSource.NKP].answers_search` is False, on the row,
#: with the measurement beside it.
SEARCH_SOURCES: Final[frozenset[CatalogueSource]] = frozenset(
    target.source for target in targets.SEEDED.values() if target.answers_search
)

#: Catalogues whose title search does not fit the default deadline, so the
#: default search leaves them out and a reader has to ask for them.
#:
#: **Named `SLOW_SEARCHES` and not `SLOW`, because this module already bounds
#: how slow a source may be.** `FIRST_TIER_BUDGET_SECONDS` bounds an ISBN lookup
#: at 1.0s to earn a place in the gathered tier: a different path, a different
#: statistic and a different bound. One word covering both is how a reader comes
#: to apply one measurement to the other.
#:
#: A subset of `SEARCH_SOURCES`, never of the lookup path.
SLOW_SEARCHES: Final[frozenset[CatalogueSource]] = frozenset()

#: Sources that cost money per request, so asking one for a book another source
#: already answered is a bill for nothing. See `Plan.lookup_together`.
METERED: Final[frozenset[CatalogueSource]] = frozenset(
    target.source for target in targets.SEEDED.values() if target.metered
)

#: Sources that need a credential the household supplies, so an install without
#: one has a provider in the list that can never answer. The settings screen
#: says so rather than leaving it as the silent cause of "why is this not
#: working". `config.google_books_api_key_from_env` and the stored key are the
#: two places one can come from; `settings_store.google_books_api_key` is the
#: single answer to whether there is one.
#:
#: **This is much of the chain's coverage, and most installs do not have it.**
#: The seven free sources answer 395 of the 500 ISBNs behind `MEASURED` and miss
#: 105, and outside German language publishing they miss 101 of 400. #91
#: measured the same books with a key: Italy 36% missed keyless against 0% with
#: one, Greece 86% against 54%. So "the chain covers this country" is a claim
#: about a keyed install, and it is worth saying wherever the chain's coverage
#: is described rather than being left for a household to discover.
#:
#: **"Most of the chain's coverage" was true when it was written and is not
#: now**, which is why this paragraph says "much". Three things moved the free
#: figure from 300 to 395 on the same 500 books: three national catalogues, and
#: the `020 $q` rule in `metadata._isbn_entries`, which was refusing 51 records
#: the sources already held. The Greek figure above is the sharpest case, and it moved in
#: two steps rather than one: **7 of 50 keyless before either change, 8 with the
#: `020` fix alone, and 39 with the NLG**, none of it involving a key.
NEEDS_A_KEY: Final[frozenset[CatalogueSource]] = frozenset(
    target.source for target in targets.SEEDED.values() if target.needs_key
)

#: How many enabled lookup sources are asked **together** before the rest are
#: asked one at a time.
#:
#: A cost bound rather than a taste: an ordinary lookup makes this many outbound
#: requests whatever the household puts in the list, so reordering cannot turn
#: every lookup into an eight way fan out. **Eight, not ten**, and the number is
#: `LOOKUP_SOURCES` rather than the roster: two of the ten answer a title search
#: only and are never asked about an ISBN at all. What a household changes is
#: **which** sources fill the slots, which is the whole point of the control.
#:
#: **Three was measured and refused, #115, and re-measured and refused again on
#: a roster with three more candidates.** Open Library is outside
#: `FIRST_TIER_BUDGET_SECONDS` and Google Books is metered, so the candidates
#: are the OENB and, but for `TIER_MAX_CONCENTRATION`, the NKP, the BNE and the
#: NLG.
#:
#: **The OENB is nearly free in wall clock and buys nothing.** The tier is
#: gathered and it is barely slower than K10plus, p90 0.513s becoming 0.574s,
#: and it takes a round trip off the miss path, so it models **0.012s** faster
#: over the whole 500, 1.435s to 1.423s. What it buys is **0 books**: it answers
#: 1 of the 278 the pair missed, and the tail reaches that one anyway.
#:
#: **The three national catalogues are the best third slots on every pooled
#: number and are refused on a different one.** The BNE models 0.190s faster,
#: 1.435s to 1.244s; the NLG 0.162s faster, to 1.273s; the NKP 0.160s, to
#: 1.275s. All three buy **0 books**, because the tail reaches everything they
#: would. Per frame each saving is concentrated the way that catalogue's
#: coverage is: the BNE answers 47 of its 57 in the Spanish frame and the NKP 49
#: of its 59 in the Czech one, and what the slot costs is a request on every
#: lookup of every install everywhere, including every install that will never
#: see a Spanish or a Czech ISBN. `TIER_MAX_CONCENTRATION` is where that is
#: decided.
#:
#: **The strongest candidate being the one the rule refuses is why the rule was
#: changed rather than the constant raised**, and the roster has now produced
#: that shape twice. The retired `TIER_FRAMES_MINIMUM` asked a source to answer
#: in at least two frames of ten; the NKP answers in **six**, so it passed a
#: rule written to exclude exactly this shape, while the NLG, whose 37 answers
#: sit in one frame, failed it. Counting frames answers "how many places did it
#: appear", and what the tier needs to know is "how much of it is one place".
#: The BNE arrives as the fastest third slot of the three and is refused on the
#: same reading, which is the rule holding rather than being re-argued.
#:
#: Recorded with the numbers so the next reader can reverse it against them
#: rather than guess.
ALWAYS_ASKED: Final = 2

#: Which registration groups a catalogue's collecting remit covers, for the
#: sources whose remit is one, and nothing at all for the sources whose is not.
#:
#: **What it buys**, modelled over the 500 ISBN sample across `lookup`'s two
#: phases: **1.435s mean today, 1.336s with this table**, for the same **395**
#: books, with **673** tail requests instead of **872**. Per frame it runs from
#: 0.000s, where the leading pair answers before the tail is reached, to 0.231s.
#:
#: **A remit is only listed where there is no book the source alone answers
#: outside it.** That is why the Czech National Library carries none: the rule is
#: about what a source is *for*, and a wrong entry silently stops asking the one
#: catalogue that holds a book.
SERVES_GROUPS: Final[dict[CatalogueSource, frozenset[str]]] = {
    CatalogueSource.NLG: frozenset({"978-960", "978-618"}),
    CatalogueSource.OENB: frozenset({"978-3"}),
}


def _serves(source: CatalogueSource, registration_group: str | None) -> bool:
    """Whether this source's remit reaches an ISBN in that registration group.

    Three ways of answering yes, and the third is the one that took a round to
    find.

    **A source with no row in `SERVES_GROUPS`** has no remit to state and is
    asked about everything.

    **A group of None** is `isbn.registration_group` declining to make a claim,
    for an unassigned range or a group added to the published list after this
    build, and every source is asked then.

    **A group in a Bookland prefix the remit never mentions.** 978 and 979 are
    two separate assignment spaces, so a remit listing only 978 groups is
    **silent** about 979 rather than negative about it, and a catalogue whose
    country has no 979 group yet has no way to say "none". Without this arm every
    979 ISBN lost both national catalogues: `979-8` is a real group, it is in
    neither remit, and both were dropped. The sample behind `SERVES_GROUPS` is
    500 rows of `978`, so nothing measured it and nothing failed.

    **Within a prefix the remit does mention, the listing is exhaustive and a
    miss is a skip.** That is the positive claim the whole feature rests on, and
    it is the arm the zero book bound guards: dropping `978-618` from the NLG's
    row costs seven books and
    `test_no_source_with_a_remit_uniquely_answers_outside_it` fails. The two arms
    cover the two ways a remit can be incomplete, and neither guards the other.

    **Every default here is "ask", including a group neither side can parse.**
    `group_prefix` answers None for anything it cannot take apart, on either the
    ISBN's group or a declared one, and both are read as "no claim" rather than
    "no match", because the failure the other way is a catalogue quietly not
    asked about a book it holds and nothing reports it.

    The incoming half of that is reachable: `Plan.lookup_in_turn` is public and
    takes any string, so `registration_group`'s guarantee is the caller's rather
    than this function's. A mutation harness found it unreachable through the
    only caller that exists, which is how it came to be pinned by
    `test_a_group_nobody_can_parse_asks_everyone` rather than left as a
    defensive arm nothing exercises.

    **An empty remit behaves exactly like no remit**, because a remit with no
    groups mentions no prefixes and the arm above then forgives everything. So
    the `groups is None` return is about not testing membership against None,
    not about behaviour.
    """
    groups = SERVES_GROUPS.get(source)
    if groups is None or registration_group is None:
        return True
    if registration_group in groups:
        return True
    prefix = isbn.group_prefix(registration_group)
    return prefix is None or not any(
        isbn.group_prefix(group) == prefix for group in groups
    )


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
    downstream has to handle a name `targets.SEEDED` has no row for, and
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
            name for name in self.lookup_chain if name not in METERED
        )[:ALWAYS_ASKED]

    def lookup_in_turn(
        self, registration_group: str | None
    ) -> tuple[CatalogueSource, ...]:
        """Asked one at a time, and only if the first tier found nothing.

        Everything in the chain that the first tier did not take, in the
        household's order, so a metered source excluded from that tier is asked
        here at the position it was given rather than dropped, **minus the
        sources whose `SERVES_GROUPS` remit does not reach this ISBN**.

        **The argument is required and has no default**, which is the point of
        it being a method rather than two properties. A default of None would
        mean "filter nothing", so a caller that forgot to pass the group would
        get today's behaviour: every dead source asked, no error, no log line,
        and the entire cost this rule removes back again. Required, it is a type
        error instead.

        **None filters nothing, deliberately.** It is what
        `isbn.registration_group` returns when it has no claim to make, and the
        answer to "no claim" is to ask everyone, because the alternative is a
        catalogue not asked about a book it holds.

        **This filters the tail and never the tier.** A gathered tier costs its
        slowest member rather than their sum, measured in `DEFAULT_ORDER` at
        0.389s for dnb with k10plus against 0.388s for k10plus alone, so a tier
        member that cannot answer costs one request and under a millisecond and
        there is no round trip to take away. Filtering it would also resize it
        per ISBN, and its size is the one cost bound `ALWAYS_ASKED` promises a
        household is fixed.
        """
        leading = frozenset(self.lookup_together)
        return tuple(
            name
            for name in self.lookup_chain
            if name not in leading and _serves(name, registration_group)
        )

    @property
    def searched(self) -> tuple[CatalogueSource, ...]:
        """What the default title search asks: enabled, answers a search, not slow.

        **`SLOW_SEARCHES` is subtracted here rather than at the fan out**, so every caller
        of the default search gets the same roster and there is no second place
        to remember it. `searched_harder` is the one door past it, and it is a
        different property rather than an argument, so a caller that wants the
        slow catalogues has to say so in a name a reader can grep for.
        """
        return tuple(
            name for name in self.searched_harder if name not in SLOW_SEARCHES
        )

    @property
    def searched_harder(self) -> tuple[CatalogueSource, ...]:
        """Every enabled source that answers a title search at all, slow included.

        What an explicit "search harder" asks, and it is a superset of `searched`
        by construction rather than by a second filter agreeing with the first.

        **A subset of `SEARCH_SOURCES` whatever the household stores**, which is
        the one place the memory argument for this feature belongs.
        `fetch.MAX_RESPONSE_BYTES` prices its concurrency on the roster's size
        rather than on what is enabled, and
        `tests/test_fetch.py::_concurrent_search_sources` is what enforces that,
        so this roster being wider than `searched` costs the bound nothing.
        """
        return tuple(name for name in self.asked if name in SEARCH_SOURCES)

    @property
    def searched_only_harder(self) -> tuple[CatalogueSource, ...]:
        """The enabled search catalogues only the harder search asks.

        **Public because emptiness here is the question two callers ask**, the
        same reason `lookup_chain` is public. Empty means asking harder would ask
        nothing new: the router declines to spend the longer deadline on it, and
        the screen declines to offer a button that runs the identical search
        twice.

        **Not named after `SLOW_SEARCHES`**, deliberately. That set is a property
        of the catalogues and this is a fact about one household's roster, and a
        constant and a property one underscore apart is a pair a reader has to
        keep straight rather than read.
        """
        return tuple(
            name for name in self.searched_harder if name in SLOW_SEARCHES
        )

    @property
    def lookup_chain(self) -> tuple[CatalogueSource, ...]:
        """Every enabled source that can answer an ISBN at all, in order.

        **Public because emptiness here is what `metadata.Outcome.NO_SOURCES`
        means**, and that is a different question from what any one ISBN is
        asked. `lookup_in_turn` can be empty because this library's catalogues
        do not reach one registration group, which is a fact about the book;
        this being empty is a fact about the library, and it is the one the 409
        and its "switch one back on" wording describe.
        """
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
        # entries read against a roster of nine looks like a bound on a hostile
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
    #: Whether the default title search leaves this catalogue out for being too
    #: slow to answer inside its deadline.
    #:
    #: **A property of the catalogue, not a setting**, which is why it sits here
    #: with the derived fields rather than beside `enabled`. A household decides
    #: whether a source is asked and where; how long it takes is the source's
    #: own. `SLOW_SEARCHES` carries the bar and the measurements.
    #:
    #: **It is not a second off switch and the screen must not draw it as one.**
    #: A slow catalogue that is switched on is asked on every scan exactly as
    #: before, and left out of one path only. That is the distinction the
    #: settings section exists to make: off because it is slow, rather than off
    #: because it is broken.
    slow: bool
    asked_first: bool
    needs_a_key: bool
    has_key: bool
    ready: bool
    #: The registration groups this catalogue's remit covers, empty for a source
    #: with no remit to state. Sorted, so the screen and the tests read one order
    #: and a `frozenset`'s iteration order never reaches either.
    #:
    #: **The declared remit, not the filter that was applied**, and the two are
    #: not the same row. `SERVES_GROUPS` is a fact about the catalogue and this
    #: field repeats it unconditionally, while the filter reaches only the
    #: sources asked one at a time. So a source in `lookup_together` carries a
    #: non empty value here and is asked about every ISBN regardless of it,
    #: measured: a plan of `oenb, nlg` gives both `asked_first=True` **and** a
    #: populated `serves_groups`. Anything rendering this has to read
    #: `asked_first` first, which is what `ProviderSection.statusOf` does and
    #: says.
    serves_groups: tuple[str, ...]


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
            # Unconditional, like `needs_a_key` and for the same reason: it is a
            # fact about the catalogue, and a household switching one on wants
            # to be told what it costs at the moment it switches it on.
            slow=entry.source in SLOW_SEARCHES,
            asked_first=entry.source in leading,
            needs_a_key=entry.source in NEEDS_A_KEY,
            has_key=entry.source in credentials,
            ready=entry.source in ready,
            # **Sent rather than left for the screen to infer**, for the reason
            # every other derived field here is: a source that is switched on,
            # in position, and silent on nine ISBNs in ten is the sharpest
            # version of "why is this not answering", and the screen cannot work
            # it out from `enabled` and `asked_first`.
            #
            # **Unconditional, deliberately, and not conjoined with `leading`
            # above.** This reports the remit; whether the remit is applied to a
            # given lookup is `asked_first`'s business, and folding the two would
            # make one field answer two questions and lose the ability to say
            # "regional, but promoted, so asked about everything".
            serves_groups=tuple(sorted(SERVES_GROUPS.get(entry.source, ()))),
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
    one source into an instruction to switch the other eight **on**: a request to
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
