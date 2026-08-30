"""The provider list's rules: what a stored row means, and what the order does.

Every degrade path here is a row a **restore** or a hand edit can write, so the
question each test asks is the same one: does a value nobody validated end up
asking a catalogue this library switched off. That is the direction this file
cares about, because the failure is silent in exactly one direction.
"""

import itertools
import json
from collections import Counter
from pathlib import Path

import sources
from enums import CatalogueSource

#: The survey `sources.MEASURED` and `sources.TIER_UNION` were read off.
#:
#: **It is committed so the constants can be recomputed rather than believed.**
#: Without it the numbers would be three integers in a module whose evidence
#: lived in a working directory that is deleted when the work ships, which is the
#: shape this repository has already recorded as a bound that stops guarding
#: without ever failing: nothing that could contradict it still exists.
SAMPLE = Path(__file__).parent / "fixtures" / "catalogue_survey_2026_08_30.json"

#: The sources the sample covers, which is `LOOKUP_SOURCES` minus the metered one.
SAMPLED = ("dnb", "k10plus", "oenb", "open_library")


def _sample() -> list[dict]:
    return json.loads(SAMPLE.read_text())


def _p90(values: list[float]) -> float:
    """The convention the survey used: the sorted value at index `int(n * 0.9)`.

    Written here because a percentile has several defensible definitions and the
    constants were produced under this one. A different convention would disagree
    with `MEASURED` by a millisecond or two and read as a real regression.
    """
    return sorted(values)[int(len(values) * 0.9)]


class TestTheConstantsAreRederivableFromTheCommittedSample:
    """`MEASURED` and `TIER_UNION` recompute from the sample, or they are prose.

    **This is what makes the other class evidence rather than decoration.** Those
    tests derive the order from the table; these derive the table from the data.
    Without them a reorder backed by an invented number passes, which was a
    disclosed blind spot until the sample was committed.

    **What it still does not do, stated so nobody reads more into it.** It proves
    the constants describe **this recorded run**. It cannot prove the run was
    honest, because somebody editing the constants and the sample together defeats
    it, and it cannot prove a re-run would agree: these are live third party
    catalogues and the figures are dated 2026-08-30. Re-deriving them against the
    world means re-running the probe, not running this suite.
    """

    def test_the_sample_holds_what_it_claims_to(self):
        """A truncated or half written file would make every count below smaller
        and every one of them would still agree with a constant somebody then
        updated to match."""
        rows = _sample()
        assert len(rows) == 500
        assert {row["frame"] for row in rows} == {
            "argentina", "austria", "brazil", "czechia", "german",
            "greece", "italy", "portugal", "spain", "uruguay",
        }
        assert all(len(row["isbn"]) == 13 and row["isbn"].isdigit() for row in rows)
        # **Ten frames of fifty, which is the shape `MEASURED` states**, and 500
        # distinct books. Without both, a file of 491 italy rows and one of each
        # other frame passes every other test here and every constant still
        # recomputes from it, so the sample would stop being the sample the
        # docstrings describe without anything failing.
        counted = Counter(row["frame"] for row in rows)
        assert set(counted.values()) == {50}
        assert len({row["isbn"] for row in rows}) == len(rows)
        assert all(
            row[name] in ("found", "not_found") for row in rows for name in SAMPLED
        )

    def test_every_source_answered_every_isbn_in_the_sample(self):
        """`MEASURED`'s denominators all read 500 because of this. A refusal would
        have to be excluded from its own denominator and they would not."""
        rows = _sample()
        for name in SAMPLED:
            asked = sum(1 for row in rows if row[name] in ("found", "not_found"))
            assert asked == len(rows), name

    def test_what_each_source_answered_matches_the_table(self):
        rows = _sample()
        for source, row in sources.MEASURED.items():
            found = sum(1 for entry in rows if entry[source.value] == "found")
            assert row.answered == found, source
            assert row.of == len(rows), source

    def test_each_latency_matches_the_table(self):
        rows = _sample()
        for source, row in sources.MEASURED.items():
            measured = _p90([entry[f"seconds_{source.value}"] for entry in rows])
            assert row.p90_seconds == round(measured, 3), source

    def test_the_union_table_matches_the_sample(self):
        """Recomputed the way it was produced: the best tier of each size that
        the budget allows, by how many of the 500 it answers between them."""
        rows = _sample()
        within = [
            name
            for name in SAMPLED
            if _p90([entry[f"seconds_{name}"] for entry in rows])
            <= sources.FIRST_TIER_BUDGET_SECONDS
        ]
        for size in range(1, len(within) + 1):
            best = max(
                itertools.combinations(within, size),
                key=lambda names: sum(
                    1 for entry in rows if any(entry[n] == "found" for n in names)
                ),
            )
            answered = sum(
                1 for entry in rows if any(entry[n] == "found" for n in best)
            )
            assert sources.TIER_UNION[size] == answered, size

    def test_the_tail_marginal_the_order_rests_on_recomputes(self):
        """`DEFAULT_ORDER` orders the tail on 96 against 2, which is the one
        number in that docstring no per source table can hold."""
        rows = _sample()
        tier = [source.value for source in sources.DEFAULT_PLAN.lookup_together]
        missed = [
            entry for entry in rows if not any(entry[name] == "found" for name in tier)
        ]
        assert len(missed) == 297
        assert sum(1 for entry in missed if entry["open_library"] == "found") == 96
        assert sum(1 for entry in missed if entry["oenb"] == "found") == 2


class TestTheOrderFollowsTheMeasurement:
    """The seeded order is derived from `sources.MEASURED`, never spelled out.

    **This replaces `TestTheDefaultsAreTodaysBehaviourWrittenDown`, and #115
    filed the reason.** That class asserted the literal tuples the two deleted
    constants had held, so it pinned the **spelling** of the order and said
    nothing about why it was that order: a reorder backed by nothing passed it
    exactly as easily as one backed by a survey, and it had to be deleted to
    make the reorder #115 asked for.

    These recompute the order from the same table the docstring draws its
    reasons from. Two rules, because the two tiers do two different jobs:

    * the **tier** is gathered on every lookup and so costs its slowest member.
      It holds the sources that answer most, among those inside
      `FIRST_TIER_BUDGET_SECONDS`.
    * the **tail** is asked one at a time and stops at the first hit, so it is
      ordered by how often a source answers at all.

    **What they cannot check, said rather than left to be discovered.** Four
    things, and every one of them was found by a critic attacking this class
    rather than by reading it.

    * **The tier rule ranks sources individually**, while what a gathered tier
      is worth is the best **union**. `MEASURED` cannot express a union, so
      `TIER_UNION` carries the joint measurement and only the sizes, not the
      membership. The two agree on this roster: `dnb + k10plus` answers 203 of
      500 against 185 for `k10plus + oenb` and 95 for `dnb + oenb`.
    * **The tail rule is marginal and the guard is unconditional.** The constant
      orders the tail by how often a source answers *a book the tier missed*, 96
      against 2; `test_the_tail_is_ordered_by_how_often_a_source_answers`
      compares `answered / of`, which counts books the tier already had. They
      agree here (237 > 44 and 96 > 2) and come apart on a roster where a broad
      source only holds what the tier holds.
    * **The tail guard sees only sources in `MEASURED`**, so it says nothing
      about where Google Books sits. Measured: moving Google Books above the
      OENB leaves that test green. Its position is a metering rule rather than a
      coverage one, and `test_a_metered_source_is_asked_last_by_default` below
      is what holds it. That bullet named the **tier** test until a critic
      measured it: the tier test keeps a metered source out of the pair asked
      together and says nothing about the tail, so Google Books at position 1 of
      `DEFAULT_ORDER` passed all 52 assertions in this file.
    * **Nothing checks the table against the world.** The sample it came off is
      committed and `TestTheConstantsAreRederivableFromTheCommittedSample`
      recomputes every figure from it, so a reorder backed by an invented number
      now has to invent 500 rows of catalogue answers to match. It is still a
      record of one dated run against live third party catalogues, and no test
      here can say a re-run would agree.

    **The tier's size is not in that list, and it used to be.** Deriving the tier
    from `MEASURED` slices with `ALWAYS_ASKED`, so the derivation agreed with any
    size it was given: a critic set `ALWAYS_ASKED = 3` and moved the OENB up to
    match, and the guard named for the tier rule passed. `TIER_UNION` and
    `SLOT_MUST_EARN` close that, by asking what each slot answered that the one
    before it did not.
    """

    @staticmethod
    def _free_lookup() -> set[CatalogueSource]:
        """The sources a default install actually asks about an ISBN.

        Metered ones are excluded because `Plan.lookup_together` bars them from
        the tier whatever position they hold, and a default install has no key
        for the only one there is.
        """
        return set(sources.LOOKUP_SOURCES - sources.NEEDS_A_KEY)

    @staticmethod
    def _rate(source: CatalogueSource) -> float:
        """Answered over asked, not the count.

        A source excluded from its own denominator for refusing to answer has a
        smaller sample than its neighbour, and comparing counts across two
        denominators is the arithmetic that put this ticket on the tracker.
        """
        row = sources.MEASURED[source]
        return row.answered / row.of

    @classmethod
    def _within(cls) -> list[CatalogueSource]:
        """The free lookup sources fast enough to be asked on every lookup."""
        return [
            source
            for source in cls._free_lookup()
            if sources.MEASURED[source].p90_seconds
            <= sources.FIRST_TIER_BUDGET_SECONDS
        ]

    @classmethod
    def _tier_for(cls, budget: float) -> set[CatalogueSource]:
        """The tier the stated rule produces for a given budget."""
        within = [
            source
            for source in cls._free_lookup()
            if sources.MEASURED[source].p90_seconds <= budget
        ]
        within.sort(key=lambda source: (-cls._rate(source), source.value))
        return set(within[: sources.ALWAYS_ASKED])

    def test_the_measurement_covers_every_free_lookup_source(self):
        """A source added to the roster cannot quietly go unmeasured."""
        assert set(sources.MEASURED) == self._free_lookup()

    def test_every_row_has_a_sample_behind_it(self):
        """A row of zeroes would satisfy every rule below without measuring one."""
        for source, row in sources.MEASURED.items():
            assert 0 < row.answered <= row.of, source
            assert row.p90_seconds > 0, source

    def test_the_tier_holds_the_sources_that_answer_most_inside_the_budget(self):
        assert set(sources.DEFAULT_PLAN.lookup_together) == self._tier_for(
            sources.FIRST_TIER_BUDGET_SECONDS
        )

    def test_nothing_in_the_tier_is_slower_than_the_budget(self):
        """The tier is gathered, so one slow member is paid on every lookup."""
        for source in sources.DEFAULT_PLAN.lookup_together:
            assert (
                sources.MEASURED[source].p90_seconds
                <= sources.FIRST_TIER_BUDGET_SECONDS
            )

    def test_the_budget_is_not_a_threshold_fitted_to_this_roster(self):
        """A bound chosen to produce the answer would move the answer when it moved.

        The interval is found by sweeping outwards rather than written down, so
        it is recomputed from the table instead of restating numbers the table
        already holds.

        **The slack is a proportion of that interval and not a number of
        seconds**, which was a correction. An absolute floor of half a second
        left 54ms of margin here: K10plus need only remeasure at 0.500s, which
        is inside the OENB's own run to run spread, and this would fail with no
        decision changing. A proportion also survives a roster that is uniformly
        faster or slower, where an absolute floor quietly becomes a different
        rule.
        """
        tier = set(sources.DEFAULT_PLAN.lookup_together)
        held = sources.FIRST_TIER_BUDGET_SECONDS
        assert self._tier_for(held) == tier
        step = 0.001
        low = held
        while low > step and self._tier_for(round(low - step, 3)) == tier:
            low = round(low - step, 3)
        high = held
        while high < 10 and self._tier_for(round(high + step, 3)) == tier:
            high = round(high + step, 3)
        where = (held - low) / (high - low)
        assert 0.15 <= where <= 0.85, (
            f"the budget sits {where:.1%} into the interval [{low}, {high}], "
            "which is near enough an edge to be a fit"
        )

    def test_the_union_table_agrees_with_the_per_source_one_where_they_touch(self):
        """The one point at which the two tables can check each other.

        A tier of one is a single source, so its union is that source's own
        count. Every other entry is a joint measurement `MEASURED` cannot
        reproduce, which is the reason `TIER_UNION` exists at all.
        """
        best = max(sources.MEASURED[source].answered for source in self._within())
        assert sources.TIER_UNION[1] == best

    def test_the_union_table_covers_every_tier_size_the_budget_allows(self):
        """Or the slot rules below stop short of the size somebody would try."""
        assert set(sources.TIER_UNION) == set(range(1, len(self._within()) + 1))

    def test_a_wider_tier_never_answers_less(self):
        """A union cannot shrink when a source is added, so a table where it
        does is a transcription error rather than a finding."""
        counts = [sources.TIER_UNION[size] for size in sorted(sources.TIER_UNION)]
        assert counts == sorted(counts)

    def test_every_slot_the_tier_holds_earned_its_place(self):
        """The tier's **size**, pinned against a measurement rather than against
        the guard's own answer.

        This is the one a critic got past. Deriving the tier from `MEASURED`
        slices with `ALWAYS_ASKED`, so `ALWAYS_ASKED = 3` with the OENB moved to
        position three produced a tier the derivation agreed with. Here the
        third slot has to answer something, and it answers 2.
        """
        for size in range(1, sources.ALWAYS_ASKED + 1):
            gain = sources.TIER_UNION[size] - sources.TIER_UNION.get(size - 1, 0)
            assert gain >= sources.SLOT_MUST_EARN, f"slot {size} earned only {gain}"

    def test_the_next_slot_would_not_have_earned_its_place(self):
        """The other half, and the refusal #115 recorded.

        Where the budget allows no wider tier there is no next slot to weigh, and
        the test above is what holds the size from below.
        """
        following = sources.ALWAYS_ASKED + 1
        if following in sources.TIER_UNION:
            gain = (
                sources.TIER_UNION[following]
                - sources.TIER_UNION[sources.ALWAYS_ASKED]
            )
            assert gain < sources.SLOT_MUST_EARN, f"slot {following} earned {gain}"

    def test_the_slot_threshold_is_not_fitted_to_this_roster(self):
        """The same question `FIRST_TIER_BUDGET_SECONDS` gets, asked of the other
        stated number: is it sitting in a gap, or on an edge?

        **This is the budget test's shape, and it did not used to be.** The first
        version asserted `min(kept) >= SLOT_MUST_EARN` and
        `max(dropped) < SLOT_MUST_EARN`, which are the two tests above it
        restated, plus a third that named `SLOT_MUST_EARN` nowhere. A critic
        measured what that let through: **3 survived and 35 survived**, both
        edges of the constant's own stated interval, and only 36 failed. So the
        constant was fitted to the roster and this was the test claiming it was
        not. The budget beside it had already been given the proportion of
        interval treatment; this one had not, which is the whole defect.
        """
        earned = [
            sources.TIER_UNION[size] - sources.TIER_UNION.get(size - 1, 0)
            for size in sorted(sources.TIER_UNION)
        ]
        kept, dropped = earned[: sources.ALWAYS_ASKED], earned[sources.ALWAYS_ASKED :]
        # Where the budget allows no wider tier there is no gap to sit in, and
        # `test_every_slot_the_tier_holds_earned_its_place` is the whole guard.
        if not dropped:
            return
        low, high = max(dropped) + 1, min(kept)
        where = (sources.SLOT_MUST_EARN - low) / (high - low)
        assert 0.15 <= where <= 0.85, (
            f"{sources.SLOT_MUST_EARN} sits {where:.1%} into the gap "
            f"[{low}, {high}], which is near enough an edge to be a fit"
        )

    def test_a_metered_source_is_asked_last_by_default(self):
        """The shipped default must not spend quota before the free ones miss.

        **The tier is not what this is about, and that was the hole.**
        `test_a_metered_source_never_joins_the_pair_asked_on_every_lookup` keeps a
        metered source out of the pair asked together and says nothing about the
        order of the tail. With Google Books at position 1 of `DEFAULT_ORDER` the
        tier is untouched, because `lookup_together` filters `METERED` before it
        slices, and `lookup_in_turn` becomes `(google_books, open_library, oenb)`,
        so the metered source is asked on every miss: 200 of the 500 sampled
        lookups today against 297, half again as many, against this module's own
        "Google Books is last of the five that answer an ISBN" and `docs/api.md`'s
        "an ordinary lookup therefore spends no quota at all".

        A **household** may promote it, and
        `test_a_metered_source_promoted_is_still_asked_earlier_in_the_tier_below`
        pins that as deliberate. This is about the order nobody chose.
        """
        chain = sources.DEFAULT_PLAN.lookup_in_turn
        free = [i for i, name in enumerate(chain) if name not in sources.METERED]
        metered = [i for i, name in enumerate(chain) if name in sources.METERED]
        # Both, or the inequality below is a statement about an empty set.
        assert metered, "no metered source in the default tail"
        assert free, "no free source in the default tail"
        assert min(metered) > max(free)

    def test_the_tail_is_ordered_by_how_often_a_source_answers(self):
        """It stops at the first hit, so a source ahead of the answerer costs a
        round trip and nothing else."""
        measured = [
            source
            for source in sources.DEFAULT_PLAN.lookup_in_turn
            if source in sources.MEASURED
        ]
        # Or the ordering assertion below is a statement about one element.
        assert len(measured) >= 2
        rates = [self._rate(source) for source in measured]
        assert rates == sorted(rates, reverse=True)

    def test_every_source_is_searched_by_default(self):
        assert set(sources.DEFAULT_PLAN.searched) == sources.SEARCH_SOURCES

    def test_the_two_lookup_tiers_are_the_whole_lookup_roster(self):
        """Nothing that can answer an ISBN is dropped between the tiers."""
        chain = (
            sources.DEFAULT_PLAN.lookup_together + sources.DEFAULT_PLAN.lookup_in_turn
        )
        assert set(chain) == sources.LOOKUP_SOURCES
        assert len(chain) == len(sources.LOOKUP_SOURCES)


class TestAStoredRowAlwaysResolvesToTheWholeRoster:
    """`parse` returns a permutation, whatever it is handed.

    That is the property `metadata._SOURCES[name]` rests on: there is no name it
    can be given that has no function behind it, so there is no `KeyError` to
    reach on the path that adds a book.
    """

    def _roster(self, plan):
        return [entry.source for entry in plan.preferences]

    def test_an_empty_row_is_the_defaults(self):
        assert sources.parse({}) == sources.DEFAULT_PLAN

    def test_a_row_that_is_not_an_object_of_lists_is_the_defaults(self):
        assert sources.parse({"sources": "dnb"}) == sources.DEFAULT_PLAN

    def test_an_unknown_source_is_dropped_rather_than_raising(self):
        plan = sources.parse({"sources": [{"source": "libris", "enabled": True}]})
        assert self._roster(plan) == list(sources.DEFAULT_ORDER)

    def test_a_repeated_source_is_counted_once(self):
        plan = sources.parse(
            {
                "sources": [
                    {"source": "dnb", "enabled": False},
                    {"source": "dnb", "enabled": True},
                ]
            }
        )
        assert self._roster(plan).count(CatalogueSource.DNB) == 1

    def test_the_first_spelling_of_a_repeat_is_the_one_that_counts(self):
        plan = sources.parse(
            {
                "sources": [
                    {"source": "dnb", "enabled": False},
                    {"source": "dnb", "enabled": True},
                ]
            }
        )
        assert CatalogueSource.DNB not in plan.asked

    def test_a_source_the_row_never_named_is_appended_and_enabled(self):
        """A release that adds a source must not leave it unasked forever."""
        plan = sources.parse({"sources": [{"source": "dnb", "enabled": True}]})
        assert self._roster(plan)[0] is CatalogueSource.DNB
        assert set(self._roster(plan)) == set(sources.DEFAULT_ORDER)
        assert CatalogueSource.LOC in plan.asked

    def test_every_source_switched_off_is_preserved_rather_than_reset(self):
        """Off for everything is a statement, and it is not the same as empty."""
        plan = sources.parse(
            {
                "sources": [
                    {"source": source.value, "enabled": False}
                    for source in sources.DEFAULT_ORDER
                ]
            }
        )
        assert plan.asked == ()

    def test_a_stored_row_survives_a_round_trip(self):
        plan = sources.parse({"sources": [{"source": "loc", "enabled": False}]})
        assert sources.parse(sources.serialise(plan)) == plan


class TestTheOffSwitchFailsClosed:
    """A value nobody validated must never resolve to "asked".

    Every case here was a live fail open found by the security seat. The shape
    they share is that `enabled` is not a boolean, which is exactly what a hand
    edit or a restore produces, and under the first implementation each of them
    read as **on**.
    """

    def _google(self, entry):
        plan = sources.parse({"sources": [{"source": "google_books", **entry}]})
        return CatalogueSource.GOOGLE_BOOKS in plan.asked

    def test_the_string_false_switches_a_source_off(self):
        """The spelling this settings table uses for every other boolean."""
        assert self._google({"enabled": "false"}) is False

    def test_a_zero_switches_a_source_off(self):
        assert self._google({"enabled": 0}) is False

    def test_a_null_switches_a_source_off(self):
        assert self._google({"enabled": None}) is False

    def test_a_real_false_switches_a_source_off(self):
        assert self._google({"enabled": False}) is False

    def test_a_real_true_leaves_it_on(self):
        assert self._google({"enabled": True}) is True

    def test_a_long_row_of_rubbish_cannot_switch_a_source_back_on(self):
        """The bound that was meant to contain a hostile row was an on switch.

        A cap of 100 entries read against a roster of seven meant a hundred
        unrecognised entries followed by a real one dropped the real one, and
        the "append what the row did not mention" rule then re-added it
        **enabled**. Measured at the cap that existed; the number is gone now
        and this is what stops it coming back.
        """
        junk = [{"source": f"nowhere-{index}", "enabled": True} for index in range(500)]
        plan = sources.parse(
            {"sources": [*junk, {"source": "google_books", "enabled": False}]}
        )
        assert CatalogueSource.GOOGLE_BOOKS not in plan.asked


class TestAWriteNeverSwitchesSomethingElseOn:
    """`from_wire` completes a payload from what is stored, not from defaults.

    A payload naming one source is a statement about that source. Completing it
    from `DEFAULT_ORDER` would read it as an instruction to switch the rest on,
    so a request to disable Google Books would have re-enabled everything the
    library had already turned off.
    """

    def _all_off(self):
        return sources.parse(
            {
                "sources": [
                    {"source": source.value, "enabled": False}
                    for source in sources.DEFAULT_ORDER
                ]
            }
        )

    def test_a_partial_payload_leaves_the_sources_it_did_not_name_alone(self):
        current = self._all_off()
        written = sources.from_wire(
            [sources.Preference(CatalogueSource.DNB, True)], current
        )
        assert written.asked == (CatalogueSource.DNB,)

    def test_a_partial_payload_still_puts_what_it_named_first(self):
        written = sources.from_wire(
            [sources.Preference(CatalogueSource.LOC, True)], sources.DEFAULT_PLAN
        )
        assert written.preferences[0].source is CatalogueSource.LOC

    def test_the_sources_a_payload_omitted_keep_their_order(self):
        written = sources.from_wire(
            [sources.Preference(CatalogueSource.LOC, True)], sources.DEFAULT_PLAN
        )
        rest = [entry.source for entry in written.preferences[1:]]
        assert rest == [
            source for source in sources.DEFAULT_ORDER if source is not CatalogueSource.LOC
        ]

    def test_a_source_this_build_does_not_know_cannot_be_written(self):
        """The same door as a stored row, so one function decides the roster."""
        written = sources.from_wire([], sources.DEFAULT_PLAN)
        assert {entry.source for entry in written.preferences} == set(
            sources.DEFAULT_ORDER
        )


class TestWhatTheOrderReaches:
    """The order decides which sources are asked, and where it stops."""

    def _ordered(self, *names, enabled=True):
        rest = [source for source in sources.DEFAULT_ORDER if source not in names]
        return sources.parse(
            {
                "sources": [
                    *({"source": name.value, "enabled": enabled} for name in names),
                    *({"source": name.value, "enabled": True} for name in rest),
                ]
            }
        )

    def test_a_search_only_source_at_the_top_does_not_take_a_lookup_slot(self):
        """BNF and LOC answer no ISBN, so they cannot lead the lookup chain."""
        plan = self._ordered(CatalogueSource.LOC, CatalogueSource.BNF)
        # **A set, because this test is about which sources took the slots and
        # not about their order in the tuple.** As an ordered comparison it was
        # the last literal spelling pin in the file, and it made
        # `DEFAULT_ORDER`'s note about position inside the tier false: swapping
        # the tier's two members failed here and nowhere else.
        assert set(plan.lookup_together) == {
            CatalogueSource.DNB,
            CatalogueSource.K10PLUS,
        }

    def test_promoting_a_source_puts_it_in_the_pair_asked_on_every_lookup(self):
        plan = self._ordered(CatalogueSource.OENB)
        assert plan.lookup_together[0] is CatalogueSource.OENB

    def test_a_metered_source_never_joins_the_pair_asked_on_every_lookup(self):
        """Dragging Google to the top must not bill for every barcode scan."""
        plan = self._ordered(CatalogueSource.GOOGLE_BOOKS)
        assert CatalogueSource.GOOGLE_BOOKS not in plan.lookup_together

    def test_a_metered_source_promoted_is_still_asked_earlier_in_the_tier_below(self):
        """Excluded from the first tier is not the same as ignored."""
        plan = self._ordered(CatalogueSource.GOOGLE_BOOKS)
        assert plan.lookup_in_turn[0] is CatalogueSource.GOOGLE_BOOKS

    def test_a_disabled_source_is_in_no_tier_at_all(self):
        plan = sources.parse(
            {"sources": [{"source": "dnb", "enabled": False}]}
        )
        assert CatalogueSource.DNB not in plan.lookup_together
        assert CatalogueSource.DNB not in plan.lookup_in_turn
        assert CatalogueSource.DNB not in plan.searched

    def test_the_pair_asked_together_never_grows_past_the_stated_bound(self):
        """An ordinary lookup costs a fixed number of requests, whatever the list."""
        assert len(sources.DEFAULT_PLAN.lookup_together) == sources.ALWAYS_ASKED


class TestASourceThatCannotAnswerIsNotAsked:
    """`in_force` is the one place the two Google switches are reconciled."""

    def _ready_without_google(self):
        return frozenset(set(sources.DEFAULT_ORDER) - {CatalogueSource.GOOGLE_BOOKS})

    def test_a_source_whose_key_is_missing_is_dropped_from_the_plan(self):
        plan = sources.in_force(sources.DEFAULT_PLAN, self._ready_without_google())
        assert CatalogueSource.GOOGLE_BOOKS not in plan.asked

    def test_dropping_it_leaves_every_other_source_alone(self):
        plan = sources.in_force(sources.DEFAULT_PLAN, self._ready_without_google())
        assert set(plan.asked) == sources.SEARCH_SOURCES - {
            CatalogueSource.GOOGLE_BOOKS
        }

    def test_the_whole_roster_is_still_reported_so_the_screen_can_offer_it_back(self):
        plan = sources.in_force(sources.DEFAULT_PLAN, self._ready_without_google())
        assert len(plan.preferences) == len(sources.DEFAULT_ORDER)

    def test_readiness_is_reported_independently_of_whether_it_is_switched_on(self):
        """The screen has to warn about a missing key before the toggle is used."""
        off = sources.parse({"sources": [{"source": "google_books", "enabled": False}]})
        described = self._described(off, ready=frozenset(), credentials=frozenset())
        assert described[CatalogueSource.GOOGLE_BOOKS].enabled is False
        assert described[CatalogueSource.GOOGLE_BOOKS].ready is False

    def test_a_free_source_is_ready_without_any_credential(self):
        described = self._described(sources.DEFAULT_PLAN)
        assert described[CatalogueSource.DNB].needs_a_key is False
        assert described[CatalogueSource.DNB].ready is True

    def test_a_key_that_is_held_is_reported_even_when_the_source_is_not_ready(self):
        """The finding this field exists for.

        A library with a Google Books key whose Google Books card is switched
        off is not ready, and was told to add a key it already had.
        """
        described = self._described(
            sources.DEFAULT_PLAN,
            ready=frozenset(),
            credentials=frozenset({CatalogueSource.GOOGLE_BOOKS}),
        )
        row = described[CatalogueSource.GOOGLE_BOOKS]
        assert row.has_key is True
        assert row.ready is False

    def test_a_key_that_is_absent_says_so(self):
        described = self._described(
            sources.DEFAULT_PLAN, ready=frozenset(), credentials=frozenset()
        )
        assert described[CatalogueSource.GOOGLE_BOOKS].has_key is False

    def test_the_leading_pair_on_screen_is_the_pair_that_is_actually_asked(self):
        """`asked_first` follows the plan in force, not the stored one.

        A source kept out of the plan for want of a key must not hold a slot on
        screen that it does not hold in a request. The two agreed only by
        accident before: today the one unready source is also the one barred
        from this tier for being metered.
        """
        without_dnb = frozenset(set(sources.DEFAULT_ORDER) - {CatalogueSource.DNB})
        described = self._described(
            sources.DEFAULT_PLAN, ready=without_dnb, credentials=without_dnb
        )
        assert described[CatalogueSource.DNB].asked_first is False
        # **Derived from `DEFAULT_ORDER`, not named**, so a reorder moves it
        # rather than failing it. Reading it back off `describe` would be
        # tautological: that is the function under test.
        promoted = next(
            source
            for source in sources.DEFAULT_ORDER
            if source in sources.LOOKUP_SOURCES
            and source not in sources.METERED
            and source not in sources.DEFAULT_PLAN.lookup_together
        )
        assert described[promoted].asked_first is True

    def _described(
        self,
        plan: sources.Plan,
        *,
        ready: frozenset[CatalogueSource] | None = None,
        credentials: frozenset[CatalogueSource] | None = None,
    ) -> dict[CatalogueSource, sources.Described]:
        everything = frozenset(sources.DEFAULT_ORDER)
        return {
            row.source: row
            for row in sources.describe(
                plan,
                ready=everything if ready is None else ready,
                credentials=everything if credentials is None else credentials,
            )
        }
