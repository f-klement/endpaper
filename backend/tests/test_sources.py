"""The provider list's rules: what a stored row means, and what the order does.

Every degrade path here is a row a **restore** or a hand edit can write, so the
question each test asks is the same one: does a value nobody validated end up
asking a catalogue this library switched off. That is the direction this file
cares about, because the failure is silent in exactly one direction.
"""

import contextlib
import itertools
import json
from collections import Counter
from pathlib import Path

import pytest

import sources
from enums import CatalogueSource
from isbn import registration_group

#: The survey `sources.MEASURED` and `sources.TIER_UNION` were read off.
#:
#: **It is committed so the constants can be recomputed rather than believed.**
#: Without it the numbers would be three integers in a module whose evidence
#: lived in a working directory that is deleted when the work ships, which is the
#: shape this repository has already recorded as a bound that stops guarding
#: without ever failing: nothing that could contradict it still exists.
SAMPLE = Path(__file__).parent / "fixtures" / "catalogue_survey_2026_08_31.json"

#: The sources the sample covers, which is `LOOKUP_SOURCES` minus the metered one.
#:
#: **Derived from `MEASURED` rather than typed, because typing it left a source
#: out.** The Czech catalogue was added to `MEASURED` and not to this tuple, and
#: nothing failed: every guard in this file builds its candidate pool from here,
#: so the tier rule that was changed *for* that source could not see it. The
#: off-arm of `test_the_concentration_rule_is_what_holds_the_tier_at_two` then
#: computed a third slot worth 12 while its own docstring said 10, and the two
#: disagreeing was the only visible trace.
#:
#: A tuple that has to agree with `MEASURED` by hand is a fact stored twice. This
#: is the same list, ordered the same way, and a new source joins both at once.
SAMPLED = tuple(source.value for source in sources.MEASURED)


def _sample() -> list[dict]:
    return json.loads(SAMPLE.read_text())


def _concentration_of(rows: list[dict], name: str) -> float:
    """What share of one source's answers sit in its single largest frame.

    Computed from the sample rather than read off `MEASURED`, so the guards that
    use it cannot agree with the table by construction.
    """
    per_frame = Counter(row["frame"] for row in rows if row[name] == "found")
    return max(per_frame.values()) / sum(per_frame.values())


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
    catalogues and the figures are dated 2026-08-31. Re-deriving them against the
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

    def test_each_largest_frame_matches_the_table(self):
        """`largest_frame` with `answered` is what keeps a national catalogue out
        of the tier, so it is recomputed rather than asserted."""
        rows = _sample()
        for source, row in sources.MEASURED.items():
            per_frame = Counter(
                entry["frame"] for entry in rows if entry[source.value] == "found"
            )
            assert per_frame, source
            assert row.largest_frame == max(per_frame.values()), source

    def test_the_marginal_table_matches_the_sample(self):
        """`TAIL_MARGINAL` counts books the leading tier missed, which is the
        one figure the tail's order rests on and no per source count holds."""
        rows = _sample()
        tier = [source.value for source in sources.DEFAULT_PLAN.lookup_together]
        missed = [
            entry for entry in rows if not any(entry[name] == "found" for name in tier)
        ]
        for source, stated in sources.TAIL_MARGINAL.items():
            answered = sum(1 for entry in missed if entry[source.value] == "found")
            assert stated == answered, source

    def test_the_union_table_matches_the_sample(self):
        """Recomputed the way it was produced: the best tier of each size that
        the budget allows, by how many of the 500 it answers between them."""
        rows = _sample()
        within = [
            name
            for name in SAMPLED
            if _p90([entry[f"seconds_{name}"] for entry in rows])
            <= sources.FIRST_TIER_BUDGET_SECONDS
            # The concentration rule, applied here too, or this table prices a
            # tier `_tier_for` cannot build. See `TIER_MAX_CONCENTRATION`.
            and _concentration_of(rows, name) < sources.TIER_MAX_CONCENTRATION
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
        """`DEFAULT_ORDER` orders the tail on 82, 42, 34 and 1, which is the one
        figure in that docstring no per source table can hold.

        **The pooled counts say the opposite about three of the four**, which is
        why this is spelled out here as well as in `TAIL_MARGINAL`: 237, 59, 37
        and 55 would put the OeNB ahead of both national catalogues and the NKP
        behind the NLG.
        """
        rows = _sample()
        tier = [source.value for source in sources.DEFAULT_PLAN.lookup_together]
        missed = [
            entry for entry in rows if not any(entry[name] == "found" for name in tier)
        ]
        assert len(missed) == 278
        assert sum(1 for entry in missed if entry["open_library"] == "found") == 82
        assert sum(1 for entry in missed if entry["nkp"] == "found") == 42
        assert sum(1 for entry in missed if entry["nlg"] == "found") == 34
        assert sum(1 for entry in missed if entry["oenb"] == "found") == 1


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
      membership. The two agree on the sources a tier may hold: `dnb + k10plus`
      answers 221 of 500 against 215 for `k10plus + oenb` and 95 for
      `dnb + oenb`. **They stopped agreeing over the whole roster**, which is
      what `TIER_MAX_CONCENTRATION` is for: `k10plus + nkp` answers 254, and 49
      of the NKP's 59 answers are Czech.
    * **The tail rule is marginal, and the guard now measures the same thing.**
      It used to compare `answered / of`, which counts books the tier already
      had, and the disclosure here said the two "come apart on a roster where a
      broad source only holds what the tier holds". The NLG is that roster:
      pooled it answers 37 against the OeNB's 55, and of the books the tier
      missed it answers 34 against 1. So the guard reads `TAIL_MARGINAL`, and
      the pooled rate now orders nothing.
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

    @staticmethod
    def _concentration(source: CatalogueSource) -> float:
        """What share of a source's answers sit in its single largest frame."""
        row = sources.MEASURED[source]
        return row.largest_frame / row.answered

    @classmethod
    def _within(cls) -> list[CatalogueSource]:
        """The free lookup sources a tier may hold.

        Two conditions, not one: fast enough to be asked on every lookup, and
        **general** enough to be worth asking on every lookup. See
        `sources.TIER_MAX_CONCENTRATION` for the second, which the NLG and the
        NKP both fail, at 100% and 83% of their answers in one frame.
        """
        return [
            source
            for source in cls._free_lookup()
            if sources.MEASURED[source].p90_seconds
            <= sources.FIRST_TIER_BUDGET_SECONDS
            and cls._concentration(source) < sources.TIER_MAX_CONCENTRATION
        ]

    @classmethod
    def _tier_for(
        cls, budget: float, concentration: float | None = None
    ) -> set[CatalogueSource]:
        """The tier the stated rule produces for a given budget and bound."""
        bound = (
            sources.TIER_MAX_CONCENTRATION
            if concentration is None
            else concentration
        )
        within = [
            source
            for source in cls._free_lookup()
            if sources.MEASURED[source].p90_seconds <= budget
            and cls._concentration(source) < bound
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
            # A largest frame bigger than the source's own answer count is a
            # transcription error; one of zero means it answered nothing, which
            # `answered` already refuses.
            assert 0 < row.largest_frame <= row.answered, source

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

    @staticmethod
    def _best_union(pool: list[str], size: int) -> int:
        """What the best tier of that size answers, of the committed sample."""
        rows = _sample()
        return max(
            sum(1 for row in rows if any(row[name] == "found" for name in names))
            for names in itertools.combinations(pool, size)
        )

    def _within_names(self, *, general_only: bool) -> list[str]:
        """The sources a tier may hold, with the concentration rule on or off."""
        rows = _sample()
        return [
            name
            for name in SAMPLED
            if _p90([row[f"seconds_{name}"] for row in rows])
            <= sources.FIRST_TIER_BUDGET_SECONDS
            and (
                not general_only
                or _concentration_of(rows, name) < sources.TIER_MAX_CONCENTRATION
            )
        ]

    def test_the_concentration_rule_is_what_holds_the_tier_at_two(self):
        """The decision `TIER_MAX_CONCENTRATION` actually makes, pinned.

        **Not the tier's membership**, which the rate rule decides on its own: no
        national catalogue reaches the top two by pooled rate, so a guard
        asserting one is out of the tier passes with this rule deleted and says
        nothing. A critic established that against the frame count this replaced.

        The size is the decision. `TIER_UNION` unions rather than ranks, so with
        both national catalogues eligible the best pair is `k10plus + nkp` at 254
        and the third slot earns **34** against a bar of **10**. With the rule the
        pair is `dnb + k10plus` at 222 and the third slot earns **1**.

        **Both numbers are computed here rather than quoted**, and an earlier
        version of this docstring quoted a third figure that neither arm produces.
        It said 10, which is what the off arm computes when the NKP alone is
        admitted and the NLG is not, a bound this test never uses. The reason it
        went unnoticed is worth more than the number: `SAMPLED` had been typed by
        hand and omitted the NKP, so the off arm's pool was missing the very
        source the rule was changed for and computed 12 while the prose said 10.

        Both arms are computed from the committed sample rather than from
        `TIER_UNION`, so neither can agree with the constant by construction.
        """
        for general_only, expected in ((True, False), (False, True)):
            pool = self._within_names(general_only=general_only)
            assert len(pool) >= 3, (general_only, pool)
            earned = self._best_union(pool, 3) - self._best_union(pool, 2)
            assert (earned >= sources.SLOT_MUST_EARN) is expected, (
                f"with the concentration rule {'on' if general_only else 'off'} "
                f"the third slot earns {earned} against a bar of "
                f"{sources.SLOT_MUST_EARN}"
            )

    def test_the_concentration_rule_changes_which_sources_a_tier_may_hold(self):
        """Or the two arms above are the same arm twice."""
        assert self._within_names(general_only=True) != self._within_names(
            general_only=False
        )

    def test_the_concentration_bound_is_not_fitted_to_this_roster(self):
        """The third stated number, given the treatment the other two have.

        The tier must be the same for every bound between the most concentrated
        source it keeps and the least concentrated one it excludes, or the
        constant is sitting on an edge and the next remeasurement moves it.
        Measured: 55% kept, 83% excluded, and two thirds sits 42% into that.
        """
        kept = self._within()
        # **Excluded by *this* rule, not by the budget.** Open Library is out of
        # the tier because it is slow, and its concentration is the lowest of
        # any source, so including it here made the gap run backwards and the
        # first version of this test failed on the unmutated tree.
        excluded = [
            source
            for source in self._free_lookup()
            if source not in kept
            and sources.MEASURED[source].p90_seconds
            <= sources.FIRST_TIER_BUDGET_SECONDS
        ]
        assert kept and excluded
        low = max(self._concentration(s) for s in kept)
        high = min(self._concentration(s) for s in excluded)
        assert low < sources.TIER_MAX_CONCENTRATION < high
        where = (sources.TIER_MAX_CONCENTRATION - low) / (high - low)
        assert 0.15 <= where <= 0.85, (
            f"{sources.TIER_MAX_CONCENTRATION:.3f} sits {where:.1%} into the gap "
            f"[{low:.3f}, {high:.3f}], which is near enough an edge to be a fit"
        )
        # **Sweeping the decision the rule makes, which is the tier's size.**
        # This loop used to sweep `_tier_for`, and could not fail: membership is
        # `{dnb, k10plus}` at every bound from 0.49 to 1.05, because the rate
        # rule decides membership on its own. A critic executed it and found
        # both endpoints producing the same input set. What moves with the bound
        # is whether a third slot earns its place, so that is what is swept.
        for bound in (low + 0.001, (low + high) / 2, high - 0.001):
            pool = [
                name
                for name in SAMPLED
                if _p90([row[f"seconds_{name}"] for row in _sample()])
                <= sources.FIRST_TIER_BUDGET_SECONDS
                and _concentration_of(_sample(), name) < bound
            ]
            earned = self._best_union(pool, 3) - self._best_union(pool, 2)
            assert earned < sources.SLOT_MUST_EARN, (
                f"at a bound of {bound:.3f} the third slot earns {earned}, so "
                f"the tier's size is not the same across the gap"
            )

        # **And the margin ends at the gap, not beyond it.** Admitting the NKP
        # takes the third slot's gain to 10, which meets the bar exactly. So the
        # gap is the whole of the safety margin on the size decision, where the
        # budget's gap leaves room on both sides. Recorded because the two read
        # as the same kind of number and are not.
        just_over = [
            name
            for name in SAMPLED
            if _p90([row[f"seconds_{name}"] for row in _sample()])
            <= sources.FIRST_TIER_BUDGET_SECONDS
            and _concentration_of(_sample(), name) < high + 0.001
        ]
        assert (
            self._best_union(just_over, 3) - self._best_union(just_over, 2)
        ) >= sources.SLOT_MUST_EARN

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
        position three produced a tier the derivation agreed with. Here every
        slot the tier holds has to answer something: they answer 210 and 12.

        **This loop stops at `ALWAYS_ASKED`, so it never weighs a third slot.**
        `test_the_next_slot_would_not_have_earned_its_place` is the one that
        does, and it reads 1. Saying otherwise here was a second seat's finding.
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
        edges of the interval the roster had **then**, and only 36 failed. So the
        constant was fitted to the roster and this was the test claiming it was
        not. The interval is [2, 12] now, so those two figures are a record of a
        superseded roster rather than a bound anybody can check today. The budget
        beside it had already been given the proportion of interval treatment;
        this one had not, which is the whole defect.
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
        slices, and `lookup_in_turn(None)` becomes
        `(google_books, open_library, nkp, nlg, oenb)`, so the metered source is
        asked on every miss: 123 of the 500 sampled lookups today against 278,
        against this module's own "Google Books is last of the seven that answer
        an ISBN"
        and `docs/api.md`'s "an ordinary lookup therefore spends no quota at
        all".

        A **household** may promote it, and
        `test_a_metered_source_promoted_is_still_asked_earlier_in_the_tier_below`
        pins that as deliberate. This is about the order nobody chose.
        """
        chain = sources.DEFAULT_PLAN.lookup_in_turn(None)
        free = [i for i, name in enumerate(chain) if name not in sources.METERED]
        metered = [i for i, name in enumerate(chain) if name in sources.METERED]
        # Both, or the inequality below is a statement about an empty set.
        assert metered, "no metered source in the default tail"
        assert free, "no free source in the default tail"
        assert min(metered) > max(free)

    def test_the_tail_is_ordered_by_how_often_it_answers_what_the_tier_missed(self):
        """It stops at the first hit, so a source ahead of the answerer costs a
        round trip and nothing else, and what it saves is a book the tier missed.

        **Against `TAIL_MARGINAL`, not against `answered / of`, and that was the
        correction.** The pooled rate counts books the tier already had. The two
        agreed while the tail was Open Library and the OeNB, and the NLG is the
        roster this class disclosed as the one where they come apart: pooled it
        answers 37 against the OeNB's 55, marginally it answers 34 against 1.
        """
        measured = [
            source
            for source in sources.DEFAULT_PLAN.lookup_in_turn(None)
            if source in sources.TAIL_MARGINAL
        ]
        # Or the ordering assertion below is a statement about one element.
        assert len(measured) >= 2
        marginals = [sources.TAIL_MARGINAL[source] for source in measured]
        assert marginals == sorted(marginals, reverse=True)

    def test_the_marginal_table_covers_the_whole_measured_tail(self):
        """A source in the tail and not in that table is one the ordering rule
        above cannot see, and it would sort wherever it was put."""
        tail = {
            source
            for source in sources.DEFAULT_PLAN.lookup_in_turn(None)
            if source in sources.MEASURED
        }
        assert tail == set(sources.TAIL_MARGINAL)

    def test_every_source_is_searched_by_default(self):
        """The two search rosters, stated as a partition rather than as one set.

        `searched_harder` is the whole of `SEARCH_SOURCES` and `searched` is
        that minus `SLOW_SEARCHES`. Written this way so the day a catalogue is marked
        slow the failure lands where the rule is, rather than here as a set
        comparison nobody can read a reason off.
        """
        assert set(sources.DEFAULT_PLAN.searched_harder) == sources.SEARCH_SOURCES
        assert (
            set(sources.DEFAULT_PLAN.searched) == sources.SEARCH_SOURCES - sources.SLOW_SEARCHES
        )

    def test_the_two_lookup_tiers_are_the_whole_lookup_roster(self):
        """Nothing that can answer an ISBN is dropped between the tiers.

        **Asked with no registration group**, which is what `SERVES_GROUPS` is
        told when `isbn.registration_group` has no claim to make, and the case
        in which nothing is filtered. Passing a real group here would make this
        a statement about that group rather than about the roster.
        """
        chain = (
            sources.DEFAULT_PLAN.lookup_together
            + sources.DEFAULT_PLAN.lookup_in_turn(None)
        )
        assert set(chain) == sources.LOOKUP_SOURCES
        assert len(chain) == len(sources.LOOKUP_SOURCES)


class TestAStoredRowAlwaysResolvesToTheWholeRoster:
    """`parse` returns a permutation, whatever it is handed.

    That is the property `targets.SEEDED[name]` rests on: there is no name it
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
        assert plan.lookup_in_turn(None)[0] is CatalogueSource.GOOGLE_BOOKS

    def test_a_disabled_source_is_in_no_tier_at_all(self):
        plan = sources.parse(
            {"sources": [{"source": "dnb", "enabled": False}]}
        )
        assert CatalogueSource.DNB not in plan.lookup_together
        assert CatalogueSource.DNB not in plan.lookup_in_turn(None)
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
        """**Against the roster, not `SEARCH_SOURCES`.** Those were the same set
        until a lookup only source joined, and this test then asserted that a
        source answering no title search is not asked at all."""
        plan = sources.in_force(sources.DEFAULT_PLAN, self._ready_without_google())
        assert set(plan.asked) == set(sources.DEFAULT_ORDER) - {
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


def _free_plan_names() -> tuple[list[str], list[str]]:
    """The tier and tail a keyless install runs, as sample column names.

    Google Books is dropped because the sample has no column for it: it needs a
    key, a default install has none, and `MEASURED`'s own docstring says the
    chain a default install runs is exactly the sampled five.
    """
    tier = [s.value for s in sources.DEFAULT_PLAN.lookup_together]
    tail = [
        s.value
        for s in sources.DEFAULT_PLAN.lookup_in_turn(None)
        if s in sources.MEASURED
    ]
    return tier, tail


def _walk(row: dict, tier: list[str], tail: list[str]) -> tuple[float, bool]:
    """One lookup's modelled cost and whether it found the book.

    **`lookup`'s two phases, and a gathered tier costs that row's own maximum**,
    never the maximum of per source means. A tier costs its slowest member on
    that ISBN, which cannot be recovered from separate distributions: doing it
    the other way overstated an earlier absolute by 11%.
    """
    cost = max(row[f"seconds_{name}"] for name in tier)
    if any(row[name] == "found" for name in tier):
        return cost, True
    for name in tail:
        cost += row[f"seconds_{name}"]
        if row[name] == "found":
            return cost, True
    return cost, False


@contextlib.contextmanager
def _patched_remits(remits: dict[CatalogueSource, frozenset[str]]):
    """Swap `SERVES_GROUPS` for the body, then put the real one back.

    Restored in a `finally` and asserted identical afterwards, because a seat
    that mutates a module and writes its own copy back has already cost this
    repository a round.
    """
    original = sources.SERVES_GROUPS
    sources.SERVES_GROUPS = remits  # type: ignore[misc]
    try:
        yield
    finally:
        sources.SERVES_GROUPS = original  # type: ignore[misc]
    assert sources.SERVES_GROUPS is original


def _served_tail(tail: list[str], row: dict) -> list[str]:
    """`tail` as `SERVES_GROUPS` leaves it for this row's ISBN."""
    group = registration_group(row["isbn"])
    return [
        name
        for name in tail
        if sources._serves(CatalogueSource(name), group)
    ]


class TestACatalogueIsOnlyAskedAboutTheISBNsItsRemitReaches:
    """`SERVES_GROUPS`, the rule under it, and the bound that keeps it honest.

    **The failure this guards is silent in one direction only**, which is the
    same shape as the rest of this file. A group set that is too **wide** costs a
    round trip that was already being paid. A group set that is too **narrow**,
    or a registration group decoded wrongly, takes a catalogue out of the chain
    for a book it holds, and the reader is told the book does not exist. So
    every test below is pointed at the second.
    """

    def test_every_declared_group_is_a_group_the_decoder_recognises(self):
        """A group nobody can decode matches no ISBN, so the source it belongs
        to is skipped on every lookup and nothing says so.

        Checked by building an ISBN in each declared group and reading its group
        back, rather than by eye: `978-96` and `978-9600` both look like
        plausible spellings of the Greek group and neither is one.
        """
        for source, groups in sources.SERVES_GROUPS.items():
            for group in groups:
                prefix, element = group.split("-")
                body = (prefix + element).ljust(12, "0")[:12]
                total = sum(
                    int(digit) * (1 if position % 2 == 0 else 3)
                    for position, digit in enumerate(body)
                )
                isbn = body + str((10 - total % 10) % 10)
                assert registration_group(isbn) == group, (source, group)

    def test_a_group_set_only_belongs_to_a_source_that_answers_an_isbn(self):
        """The rule applies on the lookup path, so a set on a search only source
        would be a constant with no effect and a claim nobody checks.

        **Deliberately not `LOOKUP_SOURCES & SEARCH_SOURCES`**, which was
        proposed and passes today. It would forbid a lookup only source from
        carrying a remit, which is a rule nobody decided and which this ticket's
        own docstring argues against: the NKP is lookup only and is the source
        that came closest to a row. The screen was the thing that could not draw
        the combination, and the screen is where it was fixed, as
        `providers.status.lookupOnlyRegional`.
        """
        assert set(sources.SERVES_GROUPS) <= sources.LOOKUP_SOURCES

    def test_no_source_with_a_remit_uniquely_answers_outside_it(self):
        """**The bound, and it is zero rather than a threshold.**

        The objection this whole rule has to answer is that a catalogue stops
        being asked about a book it holds, so the only tolerable number of books
        the chain loses is none, and there is no gap to sweep a value across the
        way `TIER_MAX_CONCENTRATION` and `SLOT_MUST_EARN` are swept.

        Measured over the committed sample: the NLG answers nothing at all
        outside its two groups, and the OeNB answers five, every one of which
        the leading pair also holds.
        """
        rows = _sample()
        for source, groups in sources.SERVES_GROUPS.items():
            others = [name for name in SAMPLED if name != source.value]
            lost = [
                row
                for row in rows
                if row[source.value] == "found"
                and registration_group(row["isbn"]) not in groups
                and not any(row[name] == "found" for name in others)
            ]
            assert lost == [], (source, [row["isbn"] for row in lost])

    def test_the_bound_is_what_keeps_the_czech_catalogue_out(self):
        """**The arm that stops the test above being vacuous.** Every source in
        the table passes it, so on its own it cannot show the rule refuses
        anything, and a rule that has never refused anything is a rule nobody
        has measured.

        The NKP is the case: it would be the largest single saving here, and it
        is the only source in the roster holding `9789727765584` (Portuguese)
        and `9789878853932` (Argentinian). `TIER_MAX_CONCENTRATION` refused it
        on a different measurement, so this is the second rule to and the
        catalogue is not the worse for either: it answers 42 of the 278 the
        leading pair misses.
        """
        rows = _sample()
        others = [name for name in SAMPLED if name != CatalogueSource.NKP.value]
        lost = [
            row["isbn"]
            for row in rows
            if row["nkp"] == "found"
            and registration_group(row["isbn"]) != "978-80"
            and not any(row[name] == "found" for name in others)
        ]
        assert sorted(lost) == ["9789727765584", "9789878853932"]
        assert CatalogueSource.NKP not in sources.SERVES_GROUPS

    def test_the_rule_costs_the_sample_no_book_at_all(self):
        """The bound above is per source. This is the same question asked of the
        chain, which is what a reader actually loses: same 500 ISBNs, same
        answer."""
        rows = _sample()
        tier, tail = _free_plan_names()
        before = sum(_walk(row, tier, tail)[1] for row in rows)
        after = sum(_walk(row, tier, _served_tail(tail, row))[1] for row in rows)
        assert before == after == 377

    def test_the_saving_the_constant_claims_recomputes(self):
        """`SERVES_GROUPS` states 1.396s becoming 1.279s and 753 tail requests
        becoming 518. A number written in prose stops being re-derived and starts
        being copied."""
        rows = _sample()
        tier, tail = _free_plan_names()

        def totals(served: bool) -> tuple[float, int]:
            seconds = 0.0
            requests = 0
            for row in rows:
                this = _served_tail(tail, row) if served else tail
                seconds += _walk(row, tier, this)[0]
                if not any(row[name] == "found" for name in tier):
                    for name in this:
                        requests += 1
                        if row[name] == "found":
                            break
            return seconds / len(rows), requests

        # Unpacked rather than compared as tuples: mypy reads
        # `tuple[float, int] == tuple[ApproxBase, int]` as non overlapping and
        # refuses it, which is correct about the types and wrong about the test.
        plain_seconds, plain_requests = totals(False)
        served_seconds, served_requests = totals(True)
        assert plain_seconds == pytest.approx(1.396, abs=0.001)
        assert plain_requests == 753
        assert served_seconds == pytest.approx(1.279, abs=0.001)
        assert served_requests == 518

    def test_ordering_alone_saves_almost_nothing(self):
        """**Why the rule skips rather than demotes**, which is the design this
        constant was written against and is the one a reader will propose first
        because it cannot lose a book.

        Moving a source that cannot answer to the back of the tail models at
        1.3959s against 1.3964s: half a millisecond. The tail stops at the first
        hit, so a dead source ahead of the answerer is only paid when something
        behind it answers, and on the rows where nothing answers every source is
        asked whatever the order. The saving is the failed lookups, and ordering
        cannot reach them.

        **Three decimals are not enough here and that is the point of the
        fourth.** Demotion measured 1.385s when it was first tried, which is a
        small saving rather than none, and that run had the NKP in the table too.
        Rounded to three places the two runs would both read 1.385 and 1.396 and
        look like one measurement.
        """
        rows = _sample()
        tier, tail = _free_plan_names()

        def demoted(row: dict) -> list[str]:
            served = _served_tail(tail, row)
            return served + [name for name in tail if name not in served]

        mean = sum(_walk(row, tier, demoted(row))[0] for row in rows) / len(rows)
        plain = sum(_walk(row, tier, tail)[0] for row in rows) / len(rows)
        assert mean == pytest.approx(1.3959, abs=0.0001)
        assert plain == pytest.approx(1.3964, abs=0.0001)
        assert sum(_walk(row, tier, demoted(row))[1] for row in rows) == 377

    def test_an_unrestricted_source_is_asked_about_every_isbn(self):
        for group in ("978-3", "978-960", "978-80", None):
            asked = sources.DEFAULT_PLAN.lookup_in_turn(group)
            assert CatalogueSource.OPEN_LIBRARY in asked, group

    def test_a_restricted_source_is_asked_inside_its_remit(self):
        greek = sources.DEFAULT_PLAN.lookup_in_turn("978-960")
        assert CatalogueSource.NLG in greek
        assert CatalogueSource.OENB not in greek

    def test_a_restricted_source_is_not_asked_outside_it(self):
        spanish = sources.DEFAULT_PLAN.lookup_in_turn("978-84")
        assert CatalogueSource.NLG not in spanish
        assert CatalogueSource.OENB not in spanish

    def test_a_second_group_reaches_the_same_source(self):
        """The NLG carries two groups and both are Greek publishing. One of them
        alone would silently halve it: 978-618 is 11 of the 50 sampled Greek
        ISBNs."""
        assert CatalogueSource.NLG in sources.DEFAULT_PLAN.lookup_in_turn("978-618")

    def test_the_sample_is_one_bookland_prefix_and_the_bound_says_so(self):
        """**What the zero book bound is measured over, pinned rather than
        stated.**

        Every row is `978` and every row decodes, so the bound above says nothing
        about `979` and nothing about the undecodable case, and those are the two
        paths the whole design's safety rests on. They are covered by tests
        rather than by data, which is weaker, and this is here so that stays
        visible: if a later sample gains a `979` row this fails and the bound
        starts meaning more than it does today.
        """
        rows = _sample()
        assert {row["isbn"][:3] for row in rows} == {"978"}
        assert all(registration_group(row["isbn"]) is not None for row in rows)

    def test_a_prefix_no_remit_mentions_reaches_every_source(self):
        """**979 is a separate assignment space and a remit is silent about it.**

        Before this arm every 979 ISBN lost both national catalogues: `979-8` is
        a real group, it is in neither remit, and both were dropped with nothing
        measuring it. A catalogue whose country has no 979 group yet cannot spell
        "none", so silence has to read as no claim.
        """
        for group in ("979-8", "979-12"):
            asked = sources.DEFAULT_PLAN.lookup_in_turn(group)
            assert CatalogueSource.NLG in asked, group
            assert CatalogueSource.OENB in asked, group

    def test_a_remit_that_names_a_prefix_is_exhaustive_within_it(self):
        """The other half, or the arm above would forgive every miss.

        Once a remit names a prefix, a group inside it that the remit does not
        list is a skip. That is the positive claim the saving comes from, and
        both remits name `978`.
        """
        assert all(
            group.startswith("978-")
            for groups in sources.SERVES_GROUPS.values()
            for group in groups
        )
        spanish = sources.DEFAULT_PLAN.lookup_in_turn("978-84")
        assert CatalogueSource.NLG not in spanish
        assert CatalogueSource.OENB not in spanish

    def test_a_remit_naming_two_prefixes_filters_inside_both(self):
        """The arm that shows the prefix rule is not a blanket exemption for 979.

        The day a served country is assigned a 979 group and it is written into
        the row, that prefix stops being silent and a **different** 979 group is
        skipped again.
        """
        patched = {
            **sources.SERVES_GROUPS,
            CatalogueSource.NLG: frozenset({"978-960", "978-618", "979-15"}),
        }
        assert sources._serves(CatalogueSource.NLG, "979-15") is True
        assert sources._serves(CatalogueSource.NLG, "979-8") is True
        with _patched_remits(patched):
            assert sources._serves(CatalogueSource.NLG, "979-15") is True
            assert sources._serves(CatalogueSource.NLG, "979-8") is False
            # The OeNB still names only 978, so 979 stays silent for it.
            assert sources._serves(CatalogueSource.OENB, "979-8") is True

    def test_a_group_nobody_can_parse_asks_everyone(self):
        """`lookup_in_turn` is public and takes any string, so a group that is
        not one has to fail open like a group that is None.

        **Pinned because a mutation harness showed it was not.** The arm existed
        and no test reached it, since the one caller in the tree passes
        `isbn.registration_group`'s output, which is always decodable or None.
        An arm nothing exercises is an arm somebody deletes.
        """
        for group in ("nonsense", "978", "978-", ""):
            asked = sources.DEFAULT_PLAN.lookup_in_turn(group)
            assert CatalogueSource.NLG in asked, group
            assert CatalogueSource.OENB in asked, group

    def test_a_malformed_remit_entry_asks_rather_than_skips(self):
        """Every default in `_serves` is "ask", including a row it cannot parse.

        `test_every_declared_group_is_a_group_the_decoder_recognises` is what
        stops one being written; this is what stops one being expensive if it
        ever is.
        """
        with _patched_remits({CatalogueSource.NLG: frozenset({"nonsense"})}):
            assert sources._serves(CatalogueSource.NLG, "978-84") is True

    def test_an_undecodable_group_asks_everyone(self):
        """**Fail open, which is the whole reason `registration_group` returns
        None rather than guessing.** An unassigned range, a group added to the
        published list after this build, or an ISBN that is not one: every
        source is asked, exactly as before this rule existed.
        """
        assert sources.DEFAULT_PLAN.lookup_in_turn(None) == tuple(
            name
            for name in sources.DEFAULT_PLAN.lookup_chain
            if name not in sources.DEFAULT_PLAN.lookup_together
        )

    # **The tier being unfiltered is pinned in `test_metadata.py`, not here.**
    # A version of it lived at this spot and was tautological: `lookup_together`
    # takes no registration group, so asserting it is the same for every group
    # is true by construction and no mutation of this module could fail it. The
    # thing that can go wrong is `metadata.lookup` deciding to filter the tier at
    # the call site, which only a call site test sees. See
    # `TestACatalogueIsNotAskedAboutAForeignIsbn`.

    def test_a_household_that_enabled_only_a_national_catalogue_still_has_one(self):
        """**The case the ticket refused to create.** A library whose list is one
        national catalogue is the library that most wants it, and this rule may
        not make it unreachable: the catalogue is asked about every ISBN its
        remit reaches, at the position it holds.

        What that library does **not** get is the catalogue asked about a book it
        could not answer, which is the point, and `lookup_chain` staying full is
        what stops `metadata.lookup` reporting that as "nothing is switched on".

        **`ALWAYS_ASKED + 1` sources rather than one**, because the leading tier
        is never filtered and would swallow a smaller roster whole, so a one or
        two source plan would pass whatever the rule did. Here the NLG is the
        first source past the tier, which is where the rule reaches it.
        """
        kept = ("k10plus", "open_library", "nlg")
        assert len(kept) == sources.ALWAYS_ASKED + 1
        plan = sources.parse(
            {
                "sources": [
                    {"source": source.value, "enabled": source.value in kept}
                    for source in sources.DEFAULT_ORDER
                ]
            }
        )
        assert plan.lookup_together == (
            CatalogueSource.K10PLUS,
            CatalogueSource.OPEN_LIBRARY,
        )
        assert plan.lookup_in_turn("978-960") == (CatalogueSource.NLG,)
        assert plan.lookup_in_turn("978-618") == (CatalogueSource.NLG,)
        # Outside its remit it is not asked, and the library still has a chain,
        # which is what `metadata.lookup` reads to decide between "this book is
        # in no catalogue" and "this library has switched every catalogue off".
        assert plan.lookup_in_turn("978-84") == ()
        assert len(plan.lookup_chain) == len(kept)

    def test_the_screen_is_told_which_groups_a_source_is_asked_about(self):
        """A source switched on, in position, and silent on nine scans in ten is
        the sharpest form of "why is this not answering", and the screen cannot
        derive it from `enabled` and `asked_first`."""
        described = {
            row.source: row
            for row in sources.describe(
                sources.DEFAULT_PLAN,
                ready=frozenset(CatalogueSource),
                credentials=frozenset(),
            )
        }
        assert described[CatalogueSource.NLG].serves_groups == ("978-618", "978-960")
        assert described[CatalogueSource.OENB].serves_groups == ("978-3",)
        assert described[CatalogueSource.OPEN_LIBRARY].serves_groups == ()

    def test_a_promoted_source_reports_its_remit_and_is_asked_about_everything(self):
        """**The field is the remit declared, not the filter applied**, and the
        two disagree on exactly this row.

        A catalogue promoted into `lookup_together` is asked about every ISBN,
        because that tier is never filtered, and it still reports the groups it
        collects. So `serves_groups` alone cannot be read as "this source is
        filtered": `asked_first` is the field that answers that, and a screen has
        to read it first. Three documents said otherwise until two critics
        measured this plan.
        """
        plan = sources.parse(
            {
                "sources": [
                    {"source": source.value, "enabled": source.value in ("oenb", "nlg")}
                    for source in sources.DEFAULT_ORDER
                ]
            }
        )
        described = {
            row.source: row
            for row in sources.describe(
                plan, ready=frozenset(CatalogueSource), credentials=frozenset()
            )
        }
        for source in (CatalogueSource.OENB, CatalogueSource.NLG):
            assert described[source].asked_first is True, source
            assert described[source].serves_groups != (), source
        # And they really are asked about a book neither collects. Compared as a
        # set: `parse` orders by `DEFAULT_ORDER`, not by the order this fixture
        # names its two sources in, which is a trap this file has now sprung
        # twice.
        assert set(plan.lookup_together) == {CatalogueSource.OENB, CatalogueSource.NLG}
        assert plan.lookup_in_turn("978-84") == ()


class TestASlowCatalogueIsAskedOnlyWhenSomebodyAsks:
    """The default search leaves the slow catalogues out; a second action adds them.

    **Every behavioural test here injects a slow source**, because `sources.SLOW_SEARCHES`
    is empty on today's roster and a suite that only ran against the live value
    would assert nothing at all. `test_nothing_on_this_roster_is_marked_slow`
    pins the live value on its own, so the injection cannot quietly become the
    only thing this class knows about.

    The ÖNB is the source injected, because it is the one the deadline is
    likeliest to drop today and so the closest live thing to the case: measured
    0.156s to 3.23s across 24 live title searches on 2026-08-27, against a 4.0s
    deadline.
    """

    @pytest.fixture
    def slow_oenb(self, monkeypatch):
        monkeypatch.setattr(
            sources, "SLOW_SEARCHES", frozenset({CatalogueSource.OENB})
        )
        return sources.DEFAULT_PLAN

    def test_the_marking_can_only_name_a_catalogue_that_answers_a_search(self):
        """A member outside `SEARCH_SOURCES` is a rule that can never apply.

        The set relation on its own is vacuous while the set is empty, and a
        critic said so: delete the assertion and nothing goes red, delete the
        rule it names and nothing goes red either. The arm below drives the
        consequence instead of asserting the absence of one.
        """
        assert sources.SLOW_SEARCHES <= sources.SEARCH_SOURCES

    def test_marking_a_catalogue_that_answers_no_search_is_silently_inert(
        self, monkeypatch
    ):
        """Which is why the subset above is a rule rather than a preference.

        Both rosters filter on `SEARCH_SOURCES` before consulting the marking,
        so a member outside it changes nothing and raises nothing. The Czech
        National Library is the live instance: on the roster, answers an ISBN,
        answers no title search.
        """
        monkeypatch.setattr(
            sources, "SLOW_SEARCHES", frozenset({CatalogueSource.NKP})
        )
        plan = sources.DEFAULT_PLAN
        assert CatalogueSource.NKP not in plan.searched
        assert CatalogueSource.NKP not in plan.searched_harder
        assert plan.searched_only_harder == ()
        # The marking made no difference at all, and nothing anywhere would have
        # said it had been misapplied. That is what the subset rule buys.
        assert set(plan.searched) == set(plan.searched_harder)

    def test_nothing_on_this_roster_is_marked_slow(self):
        """Empty, and said out loud so the day it changes somebody re-reads why.

        The bar is a measured title search at or above
        `metadata.SEARCH_DEADLINE_SECONDS`; the slowest this tree records is
        3.23s. Deleting this leaves the class below testing an injected value and
        nothing testing the shipped one.
        """
        assert not sources.SLOW_SEARCHES

    def test_the_default_search_does_not_ask_a_slow_catalogue(self, slow_oenb):
        assert CatalogueSource.OENB not in slow_oenb.searched

    def test_the_harder_search_does_ask_it(self, slow_oenb):
        assert CatalogueSource.OENB in slow_oenb.searched_harder

    def test_the_two_rosters_differ_by_exactly_the_slow_catalogues(self, slow_oenb):
        """A partition that sums, checked in both directions.

        **Tautological against today's definition, and that is what it is for.**
        `searched` is `searched_harder` minus the marking, one filter over one
        list, so both assertions follow from the code rather than testing it. A
        critic said so and the honest answer is not to dress it up: what this
        pins is that the two stay **one** computation. Rewrite either as its own
        pass over `asked` and they become two rules free to disagree, which is
        the shape a corrected partition that does not sum arrives in.
        """
        assert set(slow_oenb.searched_harder) - set(slow_oenb.searched) == {
            CatalogueSource.OENB
        }
        assert set(slow_oenb.searched) | {CatalogueSource.OENB} == set(
            slow_oenb.searched_harder
        )

    def test_the_harder_search_keeps_the_household_order(self, slow_oenb):
        """Position still decides precedence, so the longer roster is not resorted."""
        harder = slow_oenb.searched_harder
        assert list(harder) == [
            name for name in slow_oenb.asked if name in sources.SEARCH_SOURCES
        ]

    def test_slow_searches_names_what_the_default_left_out(self, slow_oenb):
        assert slow_oenb.searched_only_harder == (CatalogueSource.OENB,)

    def test_slow_searches_is_empty_when_nothing_is_slow(self):
        """What the screen reads to decide whether the second action is offered."""
        assert sources.DEFAULT_PLAN.searched_only_harder == ()

    def test_a_slow_catalogue_that_is_switched_off_is_in_neither_roster(
        self, monkeypatch
    ):
        """Slow is not a second on switch, in either direction.

        The household's off switch still wins: asking harder asks the
        catalogues this library kept, not every catalogue that exists.
        """
        monkeypatch.setattr(sources, "SLOW_SEARCHES", frozenset({CatalogueSource.OENB}))
        plan = sources.parse({"sources": [{"source": "oenb", "enabled": False}]})
        assert CatalogueSource.OENB not in plan.searched
        assert CatalogueSource.OENB not in plan.searched_harder
        assert plan.searched_only_harder == ()

    def test_a_slow_catalogue_is_still_asked_on_every_scan(self, slow_oenb):
        """The ISBN path is untouched, which is half of what #108 decided.

        A regression test rather than a new rule: `lookup_chain` and the two
        tiers under it never consult `SLOW_SEARCHES`, because a sequential chain reaches
        a slow source only after every faster one has missed, which is exactly
        when a reader wants it.
        """
        assert CatalogueSource.OENB in slow_oenb.lookup_chain
        assert CatalogueSource.OENB in (
            slow_oenb.lookup_together + slow_oenb.lookup_in_turn(None)
        )

    def test_a_library_whose_search_catalogues_are_all_slow_has_an_empty_default(
        self, monkeypatch
    ):
        """An empty default roster and a full harder one, rather than an error.

        The shape `_within_deadline` once answered with a 500. It is also the
        case that decides which roster the router's refusal is keyed on: this
        library has switched nothing off, so telling it to switch one back on
        would be a screen naming the wrong cause.
        """
        monkeypatch.setattr(sources, "SLOW_SEARCHES", sources.SEARCH_SOURCES)
        assert sources.DEFAULT_PLAN.searched == ()
        assert set(sources.DEFAULT_PLAN.searched_harder) == sources.SEARCH_SOURCES

    def test_the_screen_is_told_which_catalogues_are_slow(self, monkeypatch):
        monkeypatch.setattr(sources, "SLOW_SEARCHES", frozenset({CatalogueSource.OENB}))
        described = {
            row.source: row.slow
            for row in sources.describe(
                sources.DEFAULT_PLAN,
                ready=frozenset(CatalogueSource),
                credentials=frozenset(),
            )
        }
        assert described[CatalogueSource.OENB] is True
        assert described[CatalogueSource.K10PLUS] is False

    def test_the_screen_is_told_even_for_a_catalogue_that_is_switched_off(
        self, monkeypatch
    ):
        """Unconditional, like `needs_a_key`.

        A household switching a slow catalogue on wants to be told what it costs
        at the moment it switches it on, and a field that went true only once the
        source was already enabled could not say so first.
        """
        monkeypatch.setattr(sources, "SLOW_SEARCHES", frozenset({CatalogueSource.OENB}))
        plan = sources.parse({"sources": [{"source": "oenb", "enabled": False}]})
        [row] = [
            row
            for row in sources.describe(
                plan, ready=frozenset(CatalogueSource), credentials=frozenset()
            )
            if row.source is CatalogueSource.OENB
        ]
        assert row.enabled is False
        assert row.slow is True
