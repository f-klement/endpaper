"""Tests for backend/authors.py: reading people out of a free text column.

The three keys are what this file is mostly about. `author_key` folds with
nobody asked, so what it folds has to be a difference nobody would call a
decision; `squashed_key` only suggests, so it is allowed to be wrong; an alias
row is a decision and is the only thing here that is stored.
"""

import time

from authors import (
    FRAGMENT,
    INITIALS,
    MAX_BUCKET,
    MAX_SUGGESTIONS,
    SPELLING,
    author_key,
    build_index,
    resolve_alias_map,
    split_authors,
    squashed_key,
    suggest_merges,
)


class TestSplittingACreditLine:
    def test_one_name_is_one_author(self):
        assert split_authors("Ursula K. Le Guin") == ["Ursula K. Le Guin"]

    def test_a_comma_separates_two_people(self):
        assert split_authors("Terry Pratchett, Neil Gaiman") == [
            "Terry Pratchett",
            "Neil Gaiman",
        ]

    def test_a_name_in_catalogue_order_splits_into_two(self):
        """The residue the merge tool exists to repair.

        Nothing can tell "Le Guin, Ursula K." from "Terry Pratchett, Neil
        Gaiman" by looking at it: both are one comma. The field is comma
        separated, so this splits, and a person folds the halves back together.
        `flip_catalogue_name` must not be reused here for exactly this reason:
        it flips on one comma, which would mangle the two-author case.
        """
        assert split_authors("Le Guin, Ursula K.") == ["Le Guin", "Ursula K."]

    def test_nothing_credited_is_no_authors_rather_than_one_blank_one(self):
        assert split_authors(None) == []
        assert split_authors("") == []
        assert split_authors("   ") == []
        assert split_authors(",") == []
        assert split_authors(", ,") == []

    def test_a_trailing_separator_adds_nobody(self):
        assert split_authors("Iain M. Banks,") == ["Iain M. Banks"]

    def test_whitespace_inside_a_name_is_collapsed(self):
        assert split_authors("Iain  M.\tBanks") == ["Iain M. Banks"]

    def test_the_same_person_twice_is_counted_once(self):
        assert split_authors("Tolkien, TOLKIEN") == ["Tolkien"]

    def test_the_order_written_is_the_order_returned(self):
        assert split_authors("B, A")[0] == "B"


class TestTheKeyThatFoldsWithoutAsking:
    def test_case_does_not_make_a_second_person(self):
        assert author_key("URSULA K. LE GUIN") == author_key("Ursula K. Le Guin")

    def test_an_accent_does_not_make_a_second_person(self):
        assert author_key("Émile Zola") == author_key("Emile Zola")

    def test_punctuation_becomes_a_space_rather_than_nothing(self):
        """Which is what folds `J.R.R.` into `J. R. R.`

        Deleting the punctuation instead would fold that pair the other way
        (`jrr`) and would stop folding `Ann-Marie` into `Ann Marie` at all.
        """
        assert author_key("J.R.R. Tolkien") == author_key("J. R. R. Tolkien")
        assert author_key("Ann-Marie Baker") == author_key("Ann Marie Baker")

    def test_repeated_spaces_do_not_make_a_second_person(self):
        assert author_key("Ursula K.  Le Guin") == author_key("Ursula K. Le Guin")

    def test_a_name_with_the_spaces_moved_is_left_alone(self):
        """The line between folding and suggesting.

        `JRR` against `J. R. R.` is nearly always one person, and the rule that
        would catch it also catches `Ann Aker` against `Anna Ker`, which is
        not. So it is offered rather than done.
        """
        assert author_key("JRR Tolkien") != author_key("J. R. R. Tolkien")

    def test_a_name_of_only_punctuation_has_no_key(self):
        assert author_key("...") == ""

    def test_applying_it_to_its_own_output_changes_nothing(self):
        """Which is what lets the API take a key or a spelling in one field."""
        assert author_key(author_key("Ursula K. Le Guin")) == author_key("Ursula K. Le Guin")


class TestTheKeyThatOnlySuggests:
    def test_it_reaches_a_name_with_the_spaces_moved(self):
        assert squashed_key("JRR Tolkien") == squashed_key("J. R. R. Tolkien")

    def test_and_that_is_why_it_only_suggests(self):
        """Two different people, one squashed key. Pinned so nobody promotes
        this rule into `author_key` without meeting the counter-example."""
        assert squashed_key("Ann Aker") == squashed_key("Anna Ker")


class TestFlatteningTheAliasMap:
    def test_a_chain_resolves_to_its_end(self):
        resolved = resolve_alias_map({"a": "B", "b": "C"})
        assert resolved == {"a": "C", "b": "C"}

    def test_a_cycle_stops_rather_than_looping(self):
        """Not reachable through the API: the merge handler repoints rather
        than chaining. A hand-edited database is not bound by a handler."""
        resolved = resolve_alias_map({"a": "B", "b": "A"})
        assert set(resolved) == {"a", "b"}

    def test_a_row_pointing_at_itself_is_left_alone(self):
        assert resolve_alias_map({"emile zola": "Émile Zola"}) == {
            "emile zola": "Émile Zola"
        }


class TestTheIndex:
    def test_a_book_is_counted_once_for_each_person_on_it(self):
        entries = build_index([(1, "Terry Pratchett, Neil Gaiman")], {})
        assert [(entry.name, entry.book_ids) for entry in entries] == [
            ("Neil Gaiman", (1,)),
            ("Terry Pratchett", (1,)),
        ]

    def test_two_spellings_of_one_key_are_one_person(self):
        entries = build_index([(1, "Emile Zola"), (2, "Émile Zola")], {})
        assert len(entries) == 1
        assert entries[0].book_ids == (1, 2)

    def test_the_most_used_spelling_is_the_one_shown(self):
        entries = build_index(
            [(1, "emile zola"), (2, "Emile Zola"), (3, "Emile Zola")], {}
        )
        assert entries[0].name == "Emile Zola"
        assert entries[0].spellings == ("Emile Zola", "emile zola")

    def test_a_name_somebody_chose_beats_the_most_used_spelling(self):
        entries = build_index(
            [(1, "Le Guin"), (2, "Le Guin"), (3, "Ursula K. Le Guin")],
            {"le guin": "Ursula K. Le Guin"},
        )
        assert [entry.name for entry in entries] == ["Ursula K. Le Guin"]
        assert entries[0].book_ids == (1, 2, 3)

    def test_the_most_recent_choice_wins_when_two_aliases_disagree(self):
        """Two merges into one person, spelled differently.

        Both canonical names have the same key, so they are one author; the
        map is ordered oldest first by the caller, so the second is the later
        decision and the one a reader is looking for.
        """
        entries = build_index(
            [(1, "Zola"), (2, "E. Zola")],
            {"zola": "Émile Zola", "e zola": "Emile Zola"},
        )
        assert [entry.name for entry in entries] == ["Emile Zola"]

    def test_a_folded_spelling_is_reported_only_where_it_is_on_a_book(self):
        """The privacy line for the alias table.

        `build_index` is fed rows the caller may see. An alias whose spelling
        survives only on somebody else's private book leaves no trace here, so
        nothing downstream can announce that the book exists.
        """
        entries = build_index([(1, "Ursula K. Le Guin")], {"le guin": "Ursula K. Le Guin"})
        assert entries[0].alias_keys == frozenset()

    def test_every_alias_applies_whatever_is_on_this_shelf(self):
        """The mapping is library wide, so a chain resolves to its end here
        too, even when the middle name is on no book in these rows.

        Filtering the mapping per caller was tried and withdrawn: it made one
        book resolve to a different person for different members, which is
        identity diverging rather than a view narrowing.
        """
        entries = build_index(
            [(1, "Zola")], {"zola": "E. Zola", "e zola": "Émile Zola"}
        )

        assert [entry.name for entry in entries] == ["Émile Zola"]

    def test_but_a_book_nobody_here_can_see_puts_nobody_in_the_index(self):
        """The other half, and the privacy rule in one line: entries come from
        the rows, so a mapping that names somebody nothing here is credited to
        produces no author at all."""
        assert build_index([], {"anne frank": "Annelies Marie Frank"}) == []

    def test_a_book_credited_twice_to_one_person_is_counted_once(self):
        entries = build_index(
            [(1, "Le Guin, Ursula K.")], {"le guin": "X", "ursula k": "X"}
        )
        assert [(entry.name, entry.book_ids) for entry in entries] == [("X", (1,))]

    def test_an_author_nobody_has_a_book_by_is_not_in_the_index(self):
        assert build_index([], {"le guin": "Ursula K. Le Guin"}) == []

    def test_a_book_with_nobody_credited_contributes_nothing(self):
        assert build_index([(1, None), (2, "   "), (3, ",")], {}) == []

    def test_people_are_sorted_by_name_not_by_byte(self):
        entries = build_index([(1, "zadie smith"), (2, "Anne Enright")], {})
        assert [entry.name for entry in entries] == ["Anne Enright", "zadie smith"]


class TestSuggestions:
    def _names(self, entries):
        return [group.names for group in suggest_merges(entries)]

    def test_the_same_name_with_the_spaces_moved(self):
        entries = build_index([(1, "JRR Tolkien"), (2, "J. R. R. Tolkien")], {})
        [group] = suggest_merges(entries)
        assert SPELLING in group.reasons

    def test_an_abbreviated_given_name_against_a_full_one(self):
        entries = build_index([(1, "U. K. Le Guin"), (2, "Ursula K. Le Guin")], {})
        [group] = suggest_merges(entries)
        assert INITIALS in group.reasons

    def test_two_different_people_sharing_a_surname_are_not_offered(self):
        """The rule that would catch `J. Smith` also catches `John` against
        `James`, so an abbreviation somewhere is required."""
        entries = build_index([(1, "John Smith"), (2, "James Smith")], {})
        assert suggest_merges(entries) == []

    def test_a_catalogue_order_split_lands_beside_the_whole_name(self):
        entries = build_index(
            [(1, "Le Guin, Ursula K."), (2, "Ursula K. Le Guin")], {}
        )
        [group] = suggest_merges(entries)
        assert set(group.names) == {"Le Guin", "Ursula K.", "Ursula K. Le Guin"}
        assert FRAGMENT in group.reasons

    def test_a_one_word_name_is_not_a_fragment_of_everything(self):
        """`Homer` is inside `Homer Hickam` and is not Homer Hickam."""
        entries = build_index([(1, "Homer"), (2, "Homer Hickam")], {})
        assert suggest_merges(entries) == []

    def test_a_shelf_with_nothing_to_merge_offers_nothing(self):
        entries = build_index([(1, "Anne Enright"), (2, "Zadie Smith")], {})
        assert suggest_merges(entries) == []

    def test_two_rules_reaching_the_same_names_make_one_group(self):
        entries = build_index(
            [(1, "J. Smith"), (2, "John Smith"), (3, "James Smith")], {}
        )
        [group] = suggest_merges(entries)
        assert len(group.keys) == 3

    def test_a_group_reports_every_rule_that_built_it(self):
        """The reasons survive the group being re-rooted as it grows, which is
        what attaching them during the union loses."""
        entries = build_index(
            [(1, "Le Guin, Ursula K."), (2, "Ursula K. Le Guin"), (3, "U. K. Le Guin")],
            {},
        )
        [group] = suggest_merges(entries)
        assert set(group.reasons) == {FRAGMENT, INITIALS}

    def test_the_number_of_groups_is_capped(self):
        entries = build_index(
            [(index, f"J{index}RR Tolkien{index}") for index in range(300)]
            + [(1000 + index, f"J. {index} R R Tolkien{index}") for index in range(300)],
            {},
        )
        assert len(suggest_merges(entries)) == MAX_SUGGESTIONS

    def test_a_bucket_past_the_cap_is_skipped(self):
        """The pair is real and is dropped anyway, because its bucket is huge.

        Advisory output, so dropping a pathological bucket is the correct
        answer rather than a compromise: two of the three rules compare every
        pair inside a bucket, and "every author sharing one word" is a set a
        member fills by typing.
        """
        padding = [
            (index, f"Padding{index} Guin") for index in range(MAX_BUCKET + 1)
        ]
        entries = build_index(
            [*padding, (9001, "U. K. Le Guin"), (9002, "Ursula K. Le Guin")], {}
        )

        assert suggest_merges(entries) == []

    def test_and_a_bucket_under_it_is_not(self):
        """The other half, or the cap could be satisfied by suggesting nothing.

        The same pair, the same rule, a bucket ten names deep instead of two
        hundred and one.
        """
        padding = [(index, f"Padding{index} Guin") for index in range(10)]
        entries = build_index(
            [*padding, (9001, "U. K. Le Guin"), (9002, "Ursula K. Le Guin")], {}
        )

        [group] = suggest_merges(entries)
        assert set(group.names) == {"U. K. Le Guin", "Ursula K. Le Guin"}

    def test_a_cover_that_skips_no_bucket_is_still_bounded(self):
        """`MAX_BUCKET` bounds one bucket; nothing bounded how many of them.

        Every bucket here is exactly at the cap, so nothing is skipped, and the
        graph is nearly complete: a 500 character credit line carries up to 125
        words, which makes buckets as cheap to plant as names. Measured on the
        suite's runner, this shape cost 1.99s and 48.9 MB in the fragment rule
        alone before the pass budget, and 0.28s and 1.8 MB after it.

        The assertion is on time rather than on the numbers, because a shared
        runner is not a benchmark. What it catches is the budget being removed.
        """
        buckets = 32
        rows = [
            (index, f"U{index} K{index % buckets} K{(index + 1) % buckets}")
            for index in range(3200)
        ]
        entries = build_index(rows, {})

        # The shape only proves anything if `MAX_BUCKET` really does not fire.
        sizes: dict[str, int] = {}
        for entry in entries:
            for word in author_key(entry.name).split():
                sizes[word] = sizes.get(word, 0) + 1
        assert max(sizes.values()) == MAX_BUCKET

        started = time.monotonic()
        suggest_merges(entries)
        assert time.monotonic() - started < 5

    def test_a_shared_word_does_not_make_the_pass_quadratic(self):
        """The plantable shape, which the first version of this test missed.

        That version built `Given{n} Family{n}`, which puts every name in a
        bucket of one, so it measured a pass that never compares anything: on
        names sharing a surname the same code took 0.04s at 200 names, 11.61s
        at 1,600, and did not finish in ten minutes at 4,000.

        Measured on the suite's runner, timed around `suggest_merges` only,
        with the index built first: 2,000 names in one bucket cost 24.65s and
        195.9 MB uncapped and 0.19s and 1.0 MB capped. The assertion is
        generous because a shared runner is not a benchmark; what it catches is
        the cap being removed, which is two orders of magnitude.
        """
        rows = [(index, f"Given{index} Family") for index in range(2000)]
        entries = build_index(rows, {})
        started = time.monotonic()
        suggest_merges(entries)
        assert time.monotonic() - started < 5
