"""The provider list's rules: what a stored row means, and what the order does.

Every degrade path here is a row a **restore** or a hand edit can write, so the
question each test asks is the same one: does a value nobody validated end up
asking a catalogue this library switched off. That is the direction this file
cares about, because the failure is silent in exactly one direction.
"""

import sources
from enums import CatalogueSource


class TestTheDefaultsAreTodaysBehaviourWrittenDown:
    """The seeded order has to change nothing for a library that never looks.

    **Pinned against the literal tuples the constants held**, not against
    `DEFAULT_ORDER` restated, or the test would agree with any order it was
    given. `metadata._FAST_SOURCES` was `("dnb", "k10plus")` and
    `_FALLBACK_SOURCES` was `("oenb", "open_library", "google_books")`; both
    were deleted by this change and this is what holds them.
    """

    def test_the_leading_pair_is_the_old_fast_pair(self):
        assert sources.DEFAULT_PLAN.lookup_together == (
            CatalogueSource.DNB,
            CatalogueSource.K10PLUS,
        )

    def test_the_rest_of_the_chain_is_the_old_fallback_list(self):
        assert sources.DEFAULT_PLAN.lookup_in_turn == (
            CatalogueSource.OENB,
            CatalogueSource.OPEN_LIBRARY,
            CatalogueSource.GOOGLE_BOOKS,
        )

    def test_every_source_is_searched_by_default(self):
        assert set(sources.DEFAULT_PLAN.searched) == sources.SEARCH_SOURCES

    def test_the_two_lookup_tiers_are_the_whole_lookup_roster(self):
        """Nothing that can answer an ISBN is dropped between the tiers."""
        chain = sources.DEFAULT_PLAN.lookup_together + sources.DEFAULT_PLAN.lookup_in_turn
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
        assert plan.lookup_together == (CatalogueSource.DNB, CatalogueSource.K10PLUS)

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
        assert described[CatalogueSource.OENB].asked_first is True

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
