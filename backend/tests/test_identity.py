"""The fold and the three predicates over it.

**Most arms here are a pair rather than a literal key.** What the module promises
is that two spellings land together or apart; the string in between is an
implementation detail, and a test asserting it would fail on any improvement to
the fold while proving nothing about the question callers ask.

**A literal and a pair pin different things, and treating them as alternatives
is what let three mutations through.** A literal pins what a rule *deletes*. A
pair pins how *wide* it is. `reading_history_title` was pinned only by literals,
all of them ASCII, so swapping `.lower()` for `.casefold()` changed nothing any
arm could see while widening exactly the rule whose narrowness is the point. So
the literals stay and the pairs are added beside them.

**Whether a constant is read off the module or retyped turns on what the arm
asserts.** Read it off where the arm asserts a **property the value must have**:
pinning the separator as the character `|` passed happily when the separator
became `:`, because the key kept its shape and lost its property. Retype it where
the arm asserts **which value it is**, because that claim has no source but a
second copy, and `_EDGE_MARKS` is the one such arm here.

**And never derive an arm's cases from the constant that arm exists to bound.**
Every arm over the edge marks read its cases off them, so adding a character
supplied its own blessing and removing one took its arm away with it. Four seats
across two rounds each found a widening the others had missed, and what closed
the class was an arm deriving the **expectation** from the constant while taking
the **behaviour** from the function.
"""

from __future__ import annotations

import itertools
import re
import sys
import unicodedata

import pytest

import identity


class TestTheFoldIgnoresWhatDoesNotSayWhichBookThisIs:
    def test_case_is_folded(self) -> None:
        assert identity.fold_title("Dune") == identity.fold_title("dune")

    def test_case_is_folded_rather_than_lowercased(self) -> None:
        """The arm above is ASCII, where the two functions are the same one.

        So it pins that case folds and nothing about **how far**, and this rule
        wants the wider one: `casefold` takes `ß` to `ss`, so two catalogues
        spelling one title either way reach one key. Swapping it for `.lower()`
        is the same substitution this module's own docstring records as having
        slipped past every arm on the sibling predicate, where it ran the other
        way round, and none of the arms added for the fold's two orderings sees
        it either.
        """
        assert identity.fold_title("Straße") == identity.fold_title("Strasse")

    def test_punctuation_is_dropped(self) -> None:
        assert identity.fold_title("Ulysses!") == identity.fold_title("Ulysses")

    def test_a_mark_with_no_precomposed_base_is_dropped_too(self) -> None:
        """What the deletion does to a mark the composition could not absorb.

        **This arm lives here and not with the accent arms**, because it asserts
        a mark is **deleted** and that class asserts an accent **survives**.

        Every accent arm uses a mark that **has** a precomposed form, so the
        composition absorbs it and the regex never sees a mark at all. Those arms
        therefore say nothing about a mark that survives composition, and `q`
        with a combining acute has no precomposed character to become.

        **Deleting it follows from the fold's own premise** that a mark says
        nothing about which book this is: a catalogue spelling `quest` with a
        stray acute is spelling `quest`. A deletion class that spared combining
        marks would key it `q́uest` and miss, and before this arm that was a
        mutation every arm in the file passed.
        """
        assert len(unicodedata.normalize("NFC", "q́")) == 2
        assert identity.fold_title("q́uest") == identity.fold_title("quest")

    def test_a_run_of_spaces_reads_as_one(self) -> None:
        assert identity.fold_title("Good  Omens") == identity.fold_title("Good Omens")

    def test_an_english_leading_article_is_dropped(self) -> None:
        assert identity.fold_title("The Hobbit") == identity.fold_title("Hobbit")

    def test_a_german_leading_article_is_dropped(self) -> None:
        assert identity.fold_title("Der Prozess") == identity.fold_title("Prozess")

    def test_an_article_is_dropped_once_rather_than_repeatedly(self) -> None:
        """The literal is the claim here, so it is asserted rather than paired.

        One article comes off, not every leading article word in turn: `The A
        Team` keeps the `a`, which is the title, rather than eroding to `team`
        and colliding with every other title ending that way.
        """
        assert identity.fold_title("The A Team") == "a team"

    def test_a_word_merely_starting_with_an_article_survives(self) -> None:
        assert identity.fold_title("Theory") == "theory"

    def test_nothing_folds_to_the_same_key_as_a_different_title(self) -> None:
        assert identity.fold_title("Dune") != identity.fold_title("Emma")

    def test_punctuation_closes_a_gap_rather_than_opening_one(self) -> None:
        """The title fold deletes punctuation; the credit fold turns it into a
        space. Two opposite policies on purpose, and this is the title's.

        `authors.author_key` states why a credit needs the other one: a space
        puts `J.R.R. Tolkien` with `J. R. R. Tolkien` where deleting would send
        it to `jrr`. A title has no such pair to serve, and deleting instead
        means `Dune:Messiah` is one word rather than folding with the genuinely
        two word `Dune Messiah`.
        """
        assert identity.fold_title("Dune:Messiah") != identity.fold_title(
            "Dune Messiah"
        )

    def test_none_is_the_empty_key_rather_than_an_error(self) -> None:
        assert identity.fold_title(None) == ""


class TestAMarkAtTheEdgeOfATitleLeavesNothingBehind:
    """MARC 245 carries ISBD punctuation, so this is the ordinary case.

    Stripping whitespace before removing punctuation left the mark's own space
    in the key, so `Ulysses :` did not match `Ulysses` and the leading article
    of `( The Dune )` was no longer at the start of the string. Both are a miss
    at the site where a miss creates a second Book.
    """

    @pytest.mark.parametrize("mark", [":", "/", ";", ".", ","])
    def test_an_isbd_mark_does_not_change_the_key(self, mark: str) -> None:
        assert identity.fold_title(f"Ulysses {mark}") == identity.fold_title("Ulysses")

    def test_an_article_is_still_found_behind_leading_punctuation(self) -> None:
        assert identity.fold_title("( The Dune )") == identity.fold_title("Dune")

    def test_a_mark_inside_the_title_leaves_nothing_behind_either(self) -> None:
        """A mark with a word on either side of it.

        **Every other arm in this class puts the mark at an edge, where the
        final `.strip()` absorbs the space it leaves behind**, so every one of
        them passes with the two substitutions swapped: that is the exact
        mutation this class is named for. An interior mark has no `.strip()` to
        save it, and keys `ulysses  a novel` with two spaces when the collapse
        runs first.
        """
        assert identity.fold_title("Ulysses : a novel") == identity.fold_title(
            "Ulysses a novel"
        )


class TestAnAccentSurvivesWhicheverWayItArrived:
    """A combining mark is punctuation to the regex, so order decides.

    Composed before anything is deleted, a decomposed accent is a letter. Not
    composed, the accent is deleted and the bare letter survives, so one title
    keys two ways and one of them collides with a spelling somebody else chose.
    """

    def test_a_decomposed_accent_keys_as_the_composed_one(self) -> None:
        composed = unicodedata.normalize("NFC", "Les Misérables")
        decomposed = unicodedata.normalize("NFD", "Les Misérables")
        assert composed != decomposed
        assert identity.fold_title(composed) == identity.fold_title(decomposed)

    def test_an_accent_is_not_folded_away_to_the_bare_letter(self) -> None:
        """The fold folds spellings, not words.

        `Misérables` and `Miserables` are two spellings a cataloguer might
        choose between, and deciding they are one book is not this function's
        call to make silently.
        """
        assert identity.fold_title("Les Misérables") != identity.fold_title(
            "Les Miserables"
        )

    def test_a_letter_whose_casefold_decomposes_still_keeps_its_accent(self) -> None:
        """The second ordering edge: case is folded before the composition.

        Both arms above use `é`, whose casefold is already composed, so neither
        can see which side of the `normalize` call the `casefold` sits on.

        **A literal rather than a pair, because the pair is weaker than it
        looks here.** `fold_title("ǰules") != fold_title("jules")` also passes
        on a fold that does nothing at all, so it pins an inequality rather
        than this rule. This literal fails on the casefold moved after the
        composition, on the composition dropped, and on a fold that does
        nothing. A mark keeping regex on its own does **not** fail it, because
        casefolding before composing leaves no mark for any regex to reach.
        `test_a_mark_with_no_precomposed_base_is_dropped_too`, in the class about
        what the fold discards, is what covers that body. Named rather than
        pointed at by position, since a position drifts the moment an arm lands
        between them, which happened once while this was written. No fraction is
        quoted because the denominator is whichever broken bodies somebody
        thought of, which is not a property of the rule.

        **The input is decomposed and cased, and it needs to be both.** `J`
        with a combining caron has no precomposed uppercase form, asserted
        below because it is the premise the literal rests on, so composing
        first leaves the mark for `[^\\w\\s]` to delete and the key loses its
        accent. Casefolding first turns it into a `j`, which NFC then composes
        into one character that survives the deletion.
        """
        assert unicodedata.normalize("NFC", "J̌ules") == "J̌ules"
        assert identity.fold_title("J̌ules") == "ǰules"

    def test_no_letter_loses_its_mark_to_the_casefold_ordering(self) -> None:
        """The same rule over a derived set, because one codepoint is not it.

        `ǰ` in `test_a_letter_whose_casefold_decomposes_still_keeps_its_accent`
        is the readable example. This walks every **single** codepoint whose
        casefold is not already composed, derived rather than listed because it
        is a property of the Unicode data file and moves with it, so naming
        members would go stale silently rather than loudly.

        **What this arm does not cover, stated because the derivation reads
        like the whole class and is not.** The rule also fails on **sequences**
        where neither codepoint alone diverges, a cased letter followed by a
        combining mark that composes only after the casefold: that literal arm's
        own input is one such case and is deliberately not a member of this set,
        being two codepoints rather than one.

        **That family is not bounded, and neither its size nor the number of ways
        into it is stated here.** One route is a mark that casefolds to a
        **letter**, which becomes a base and absorbs the mark after it where
        composing first cannot: `A` with a ypogegrammeni and a grave. Another
        needs no such mark, only a triple whose **lowercase** form has a
        precomposed character where its uppercase form has none: a Greek capital
        iota with a dialytika and a varia. Both diverge with no shorter prefix
        diverging, and they are the two routes found rather than the two that
        exist. What a sweep reports moves with which letters **and** which marks
        it populates, and two seats measuring this separately got a large number
        and zero.

        **This arm describes the mechanism and counts nothing.** The literal arm
        is what covers the family.

        **Nor does it separate a fold that does nothing**, which holds for every
        case in the set. The literal above is what catches that, which is why
        both arms stay.

        **Stated as the mark not being lost, against the bare base letter.**
        The formulation that suggests itself, comparing the codepoint's key with
        its composed casefold's key, is worthless: the reordering degrades both
        sides identically, so it holds for every candidate under both orders.
        Asking instead whether the accented key still differs from the
        unaccented one separates the two orders completely.
        """
        cases = []
        for codepoint in range(sys.maxunicode + 1):
            folded = chr(codepoint).casefold()
            if folded == unicodedata.normalize("NFC", folded):
                continue
            bare = "".join(c for c in folded if not unicodedata.combining(c))
            if bare != folded and bare.strip():
                cases.append((chr(codepoint), bare))

        assert cases, "no codepoint casefolds to a decomposed sequence any more"
        for letter, bare in cases:
            assert identity.fold_title(letter) != identity.fold_title(bare), (
                f"U+{ord(letter):04X} lost its mark and keys as the bare letter"
            )


class TestOnlyTheFirstCreditIsInTheKey:
    def test_a_second_credit_does_not_change_the_key(self) -> None:
        assert identity.fold_credit("Terry Pratchett, Neil Gaiman") == (
            identity.fold_credit("Terry Pratchett")
        )

    def test_spaced_initials_and_bare_ones_are_one_person(self) -> None:
        assert identity.fold_credit("J.R.R. Tolkien") == identity.fold_credit(
            "J. R. R. Tolkien"
        )

    def test_an_empty_leading_segment_is_nobody_rather_than_an_empty_credit(
        self,
    ) -> None:
        """`", , Jane Doe"` is a credit list nobody wrote.

        Taking the first comma separated segment blindly keys this book under
        the empty author, where it collides with every other malformed credit.
        """
        assert identity.fold_credit(", , Jane Doe") == identity.fold_credit("Jane Doe")

    def test_nobody_credited_is_the_empty_key(self) -> None:
        assert identity.fold_credit(None) == ""
        assert identity.fold_credit("") == ""

    def test_the_credit_folds_automatically_and_never_aggressively(self) -> None:
        """`authors.py` keeps three keys and only the mildest may fold with
        nobody asked.

        The aggressive one drops spaces too, which reaches `JRR Tolkien` from
        `J. R. R. Tolkien` and also reaches `Ann Aker` from `Anna Ker`. That is
        why it only ever suggests a merge for somebody to confirm. Reaching for
        it here would fold two different people automatically, at the site where
        that merges two books.
        """
        assert identity.fold_credit("Ann Aker") != identity.fold_credit("Anna Ker")


class TestAnArticleIsNeverStrippedFromASurname:
    """`Das Gupta` is a surname and `Das` is not an article in it.

    The fold used to run the article pass over the credit as well as the title,
    which collided two different people under one key at the site where a
    collision merges two books.
    """

    def test_two_surnames_differing_by_a_leading_article_word_stay_apart(self) -> None:
        assert identity.fold_credit("Das Gupta, Ranjit") != identity.fold_credit(
            "Gupta, Ranjit"
        )

    def test_an_initial_matching_an_article_is_kept(self) -> None:
        assert identity.fold_credit("A. Milne") != identity.fold_credit("Milne")


class TestTheWorkKeyIsTitleAndCredit:
    def test_two_editions_of_one_book_share_it(self) -> None:
        assert identity.work_key("The Hobbit", "J.R.R. Tolkien") == identity.work_key(
            "Hobbit", "J. R. R. Tolkien"
        )

    def test_one_title_by_two_people_is_two_works(self) -> None:
        """Every library holds more than one *Selected poems*."""
        assert identity.work_key("Selected Poems", "W. B. Yeats") != identity.work_key(
            "Selected Poems", "Philip Larkin"
        )

    def test_the_credit_cannot_be_read_as_part_of_the_title(self) -> None:
        """Without a separator, a longer title and a shorter credit collide."""
        assert identity.work_key("Dune Frank", "Herbert") != identity.work_key(
            "Dune", "Frank Herbert"
        )

    def test_a_boundary_falling_on_no_space_still_needs_the_separator(self) -> None:
        """The arm above chose a pair that collides even with no separator.

        Measured with the separator removed: `Dune` plus `Messiah` gives
        `dune messiah` and `DuneMessiah` plus nobody gives `dunemessiah`, which
        are still different, so that arm passes on a key with no separator at
        all. This pair puts the boundary where no space falls, which is the only
        shape that can tell the two apart.
        """
        assert identity.work_key("Dune", "Messiah") != identity.work_key(
            "DuneMessiah", None
        )

    def test_neither_separator_is_a_character_a_fold_can_emit(self) -> None:
        """The property, derived from the rule rather than from examples.

        Both folds keep exactly `\\w` and `\\s` and neither invents a character,
        so a separator matching neither class cannot appear in a folded value,
        whatever the input. **Asserted as that condition rather than over a list
        of inputs**, because a list is an enumeration: a version of this arm that
        fed seven strings through the folds passed happily for a separator of
        `_`, which `\\w` admits, purely because no input in the list contained
        one.

        Read off the module's constants, so changing either one to a character a
        fold can emit fails here.
        """
        for separator in (identity._KEY_SEPARATOR, identity._YEAR_SEPARATOR):
            assert re.fullmatch(r"[\w\s]", separator, flags=re.UNICODE) is None

    @pytest.mark.parametrize(
        "text", ["Dune|Frank", "a|b", "||", "Pipe | Dream", "|leading", "a:b", "::"]
    )
    def test_a_folded_value_is_only_word_characters_and_spacing(
        self, text: str
    ) -> None:
        """The witness beside the derived arm above, which is what proves the
        derivation still describes these functions.

        The condition is only about the separators. This is about the folds:
        together they say the key is unambiguous.

        **Asserted as the whole output's shape rather than as two characters
        being absent**, which is strictly stronger for the same line. A known
        hole remains and is deliberate: a fold mutated to emit a separator only
        for an input this list does not carry escapes both arms, and no finite
        list of inputs closes that. The guard stops here rather than growing a
        list of spellings, which is the shape this repository has already paid
        to learn.
        """
        for folded in (identity.fold_title(text), identity.fold_credit(text)):
            assert re.fullmatch(r"[\w\s]*", folded, flags=re.UNICODE)

    def test_a_work_key_carries_one_separator_and_a_printing_key_two(self) -> None:
        """The count is what keeps the two kinds of key apart, so it is pinned.

        The arm that used to sit here pinned the two characters as different and
        justified it with a collision that cannot happen. This pins the property
        the comment beside the constants actually rests on, and it is derived:
        it counts whatever the constants are rather than naming them, so it
        still holds if either changes.
        """

        def separators(key: str) -> int:
            return sum(
                key.count(s)
                for s in (identity._KEY_SEPARATOR, identity._YEAR_SEPARATOR)
            )

        assert separators(identity.work_key("Dune", "Frank Herbert")) == 1
        assert separators(identity.printing_key("Dune", "Frank Herbert", 1965)) == 2
        assert separators(identity.printing_key("Dune", None, None)) == 2
        assert separators(identity.work_key("Dune|Messiah", "Herbert: Frank")) == 1


class TestThePrintingKeyTellsTwoYearsApart:
    def test_two_printings_of_one_work_are_two_keys(self) -> None:
        assert identity.printing_key("Dune", "Frank Herbert", 1965) != (
            identity.printing_key("Dune", "Frank Herbert", 1984)
        )

    def test_a_missing_year_is_one_bucket_rather_than_an_error(self) -> None:
        assert identity.printing_key("Dune", "Frank Herbert", None).endswith(
            identity._YEAR_SEPARATOR
        )

    def test_it_carries_the_work_key_so_two_works_never_share_a_printing(self) -> None:
        assert identity.printing_key("Dune", "Frank Herbert", 1965) != (
            identity.printing_key("Emma", "Jane Austen", 1965)
        )


class TestTheReadingHistoryTitleTakesHalfTheFold:
    """The outlier, and what it **refuses** is the claim here.

    Widening it is the one change on this rule a member can feel, so the
    refused half is pinned as a **relation against `fold_title`** rather than
    as a literal. An arm asserting only that this key keeps a leading article
    passes just as happily on a fold that has stopped removing one, and that is
    the single edit under which the two predicates agree and this class is
    green: the two rules lose the behaviour together and nothing is red.
    """

    def test_it_lowercases_what_it_does_not_strip(self) -> None:
        """A literal, because a literal is what pins the characters kept.

        `!` is not in `_EDGE_MARKS`, so it survives at an edge where a colon
        would not. That is the whole difference between this rule and stripping
        any edge run, which the scoring found merges four pairs of genuinely
        different books.
        """
        assert identity.reading_history_title("The Hobbit!") == "the hobbit!"

    def test_it_does_not_drop_punctuation_from_outside_the_edge_set(self) -> None:
        assert identity.reading_history_title("Ulysses!") != (
            identity.reading_history_title("Ulysses")
        )

    def test_one_title_by_two_people_is_one_key_here_and_two_anywhere_else(
        self,
    ) -> None:
        """Two editions of one title collide, which is the accepted cost.

        **Stated as a contrast with `work_key` over the same pair**, because
        this predicate takes no credit argument, so there is no input by which
        it alone can show what it ignores. The previous form of this arm compared
        the function's output with itself, which every mutation survives.
        """
        assert identity.reading_history_title("Selected Poems") == (
            identity.reading_history_title("selected poems")
        )
        assert identity.work_key("Selected Poems", "Yeats") != identity.work_key(
            "Selected Poems", "Larkin"
        )

    def test_it_case_folds_rather_than_lowercasing(self) -> None:
        """The arms above are all ASCII, where the two are the same function.

        So they pin what this predicate keeps and nothing about how wide its
        case rule is, and `.lower()` is the narrower one: it leaves `ß` alone
        where `casefold` takes it to `ss`, so two catalogues spelling one title
        either way would key apart. This arm ran the other way round until
        2026-09-24, which is the day the normalisation was widened; the
        predicate's author blindness did not move with it.
        """
        assert identity.reading_history_title("Straße") == (
            identity.reading_history_title("Strasse")
        )

    def test_a_run_of_spaces_reads_as_one_here_too(self) -> None:
        assert identity.reading_history_title("Good  Omens") == (
            identity.reading_history_title("Good Omens")
        )

    def test_a_decomposed_accent_keys_as_the_composed_one_here_too(self) -> None:
        composed = unicodedata.normalize("NFC", "Les Misérables")
        decomposed = unicodedata.normalize("NFD", "Les Misérables")
        assert composed != decomposed
        assert identity.reading_history_title(composed) == (
            identity.reading_history_title(decomposed)
        )

    def test_case_is_folded_before_the_composition_here_as_well(self) -> None:
        """The ordering `_casefolded` owns, asserted through this caller too.

        **The input has to be a pair the two orders disagree about, and almost
        nothing is.** Case folding preserves canonical equivalence, so for
        nearly every title both orders induce the same key. The first version of
        this arm used `J̌ules` against the precomposed `ǰules`, which keys
        together under **both** orders, because U+01F0 casefolds to a `j` and a
        combining caron whichever side of the composition it sits on. That arm
        could not fail, and it took a seat that had not written it to find that
        its own stated mechanism was the sibling's rather than this caller's.

        **What does separate them** is a precomposed character whose casefold
        decomposes, against an equivalent spelling that has no precomposed form
        to reach. Composing first leaves the second uncomposed, so the two
        casefold to sequences of different lengths. The pair below renders
        identically and differs in codepoints.

        **In `fold_title` the wrong order loses the accent outright**, because
        the mark left uncomposed is then deleted. Here nothing deletes it, so
        the cost is one title reaching two keys, which is a miss rather than a
        merge, and is why both callers keep an arm.

        **This is where the implementation departs from the decision as
        written**, which reads composition then case. Taken in that order this
        pair keys apart.
        """
        precomposed = "ΐ"
        equivalent = "Ϊ́"
        assert precomposed != equivalent
        assert unicodedata.normalize("NFC", equivalent) == equivalent
        assert identity.reading_history_title(precomposed) == (
            identity.reading_history_title(equivalent)
        )

    def test_the_edge_marks_are_exactly_these_nine(self) -> None:
        """The one constant in this file that is retyped rather than read off.

        **Every other arm about this set derives its cases from the set**, so a
        character added to it arrives with its own arm blessing it and a
        character removed takes its arm away with it. Measured: adding `'`, `*`,
        `&`, `1`, `s`, a guillemet or a fullwidth colon passed every arm in the
        file as it then stood, and so did **removing** `,` or `/`. No arm count
        is quoted, because a figure measured against the tree before this arm
        existed reads as current.

        **This is the file's rule rather than an exception to it.** The rule
        turns on what an arm asserts: read the constant off the module where the
        arm asserts a **property the value must have**, and retype it where the
        arm asserts **which value it is**. `_KEY_SEPARATOR` is the first kind,
        and retyping `|` let its property lapse while the shape still passed.
        This is the second kind, and a claim about which value a constant holds
        has no source but a second copy.

        Sorted, because membership is the claim and order is not.
        """
        assert sorted(identity._EDGE_MARKS) == sorted(":/;.,()[]")

    @pytest.mark.parametrize("mark", list(identity._EDGE_MARKS))
    def test_a_mark_at_either_edge_comes_off(self, mark: str) -> None:
        """Read off the constant, so a character added to it arrives with arms.

        Both edges, because the rule strips both and the trailing one is where
        MARC 245 puts its ISBD punctuation: an arm on the trailing edge alone
        would pass on a rule that had quietly stopped stripping the leading one.
        """
        assert identity.reading_history_title(f"Ulysses {mark}") == (
            identity.reading_history_title("Ulysses")
        )
        assert identity.reading_history_title(f"{mark} Ulysses") == (
            identity.reading_history_title("Ulysses")
        )

    def test_a_run_of_marks_comes_off_as_a_run(self) -> None:
        """One mark at an edge is the common case and not the rule.

        A record that has had two subfields concatenated carries both marks, so
        a rule stripping a single character passes every arm above and misses
        the case those arms were written for.
        """
        assert identity.reading_history_title("Middlemarch. :") == (
            identity.reading_history_title("Middlemarch")
        )

    def test_a_bracketed_title_is_the_same_title(self) -> None:
        """Why brackets are in the subset and the ISBD marks alone are not it.

        A cataloguer brackets a title they supplied rather than transcribed, so
        `[Hamlet]` and `Hamlet` are one book. These are the two cases the ISBD
        marks alone do not reach, which is why brackets are in the set at all.
        """
        assert identity.reading_history_title("[Hamlet]") == (
            identity.reading_history_title("Hamlet")
        )
        assert identity.reading_history_title("(Dubliners)") == (
            identity.reading_history_title("Dubliners")
        )

    @pytest.mark.parametrize(
        ("one", "other"),
        [
            ("C++", "C#"),
            ("C++", "C"),
            ("C#", "C"),
            ("C+", "C-"),
            ("C-", "C"),
            ("B#", "Bb"),
            ("The C++ Programming Language", "The C Programming Language"),
        ],
    )
    def test_punctuation_a_title_is_about_is_not_stripped(
        self, one: str, other: str
    ) -> None:
        """The harmful half of what the subset was scored against.

        These are books whose punctuation **is** which book they are, and every
        wider candidate merges some of them. Retyped rather than read off a
        constant because they are a judgement about the world and not a property
        of the module.

        **No count is quoted here.** This arm and its beneficial counterpart
        **are** the scoring, recomputed on every run, and the counts once written
        beside them had already drifted against the set, when a pair was added
        and two sentences saying "six" were not.

        The last pair is the interior case, and it is the one that separates the
        two rejected candidates from each other: an edge rule spares it and a
        rule reaching inside a title does not.
        """
        assert identity.reading_history_title(one) != (
            identity.reading_history_title(other)
        )

    @pytest.mark.parametrize(
        ("spelling", "title"),
        [
            ("Ulysses :", "Ulysses"),
            ("Dune /", "Dune"),
            ("Kim ;", "Kim"),
            ("Persuasion.", "Persuasion"),
            ("Emma,", "Emma"),
            ("Middlemarch. :", "Middlemarch"),
            (". Nostromo", "Nostromo"),
            ("/ Leaves of Grass", "Leaves of Grass"),
            ("Beloved :.", "Beloved"),
            ("[Hamlet]", "Hamlet"),
            ("(Dubliners)", "Dubliners"),
        ],
    )
    def test_a_catalogue_spelling_reaches_the_title_it_spells(
        self, spelling: str, title: str
    ) -> None:
        """The beneficial half, which had no arm at all until it was asked for.

        The harmful half above was an arm from the start and this side was a
        measurement quoted in prose, which is a weaker rung: nothing recomputed
        it, so a narrowing that lost one of these would have been silent. The
        two halves are what the subset was chosen on and they belong at the same
        rung.

        The list is ISBD punctuation from MARC 245 at one edge or the other,
        singly and in runs, and then the two bracket cases, which are the ones
        the ISBD marks alone do not reach. Deliberately not summarised by a
        count: an earlier version of this docstring carried a breakdown that
        disagreed with the list beside it.
        """
        assert identity.reading_history_title(spelling) == (
            identity.reading_history_title(title)
        )

    @pytest.mark.parametrize("article", identity._ARTICLES)
    def test_a_leading_article_survives_here_and_not_in_the_fold(
        self, article: str
    ) -> None:
        """Both halves, and the second half is the reason this arm exists.

        **Asserting only that this key keeps the article is satisfied by a
        `fold_title` that has stopped dropping one.** That is a single edit, it
        is the widening this class exists to refuse, and under it the two rules
        lose the behaviour together with nothing red. The second assertion is
        what makes the arm about the **difference** between the two predicates
        rather than about one of them.

        Parametrised over `identity._ARTICLES` rather than a list retyped here,
        so a word added to that constant arrives with an arm rather than
        without one.
        """
        kept = f"{article}Hobbit"
        assert identity.reading_history_title(kept) != (
            identity.reading_history_title("Hobbit")
        )
        assert identity.fold_title(kept) == identity.fold_title("Hobbit")

    def test_a_mark_inside_the_title_survives_here_and_not_in_the_fold(self) -> None:
        """The other refused half, stated the same way and for the same reason.

        A rule that reached inside a title would merge `Dune: Messiah` with
        `Dune Messiah`, which `fold_title` does on purpose at a site that has a
        credit to tell the two apart. This one has none.

        **The mark needs a space after it, which is the whole of the arm.**
        Written `Dune:Messiah` against `Dune Messiah`, a predicate that deleted
        interior punctuation keys `dunemessiah` against `dune messiah`, still
        apart, so the arm passed the one mutation it is named for. Found by a
        seat that had not written it.
        """
        assert identity.reading_history_title("Dune: Messiah") != (
            identity.reading_history_title("Dune Messiah")
        )
        assert identity.fold_title("Dune: Messiah") == identity.fold_title(
            "Dune Messiah"
        )

    def test_a_title_of_nothing_but_marks_is_not_the_empty_key(self) -> None:
        """The empty key is not inert, so the strip is not allowed to reach it.

        **The bound this asserts is the one not in the owner's rule**, and it is
        here because the empty key has a live source. `create_missing` stores a
        Book titled `.` on the first sync that sees one, `Book.is_private`
        defaults false so that Book enters every member's `Shelf.seen_by`, and
        every later punctuation-only title from any source then matches it and
        takes everything a matched Book takes. Every marks-only title collapses
        to that one key without the guard, which is what the assertion below
        measures from the other side.

        **Asserted as injectivity over a derived family, because every pair and
        every narrower family let something through.** A pair of `[]` against
        `. :` differs in its first character, so a fallback of `text[:1]`
        satisfied it while collapsing the family onto 9 keys. Widening to every
        one and two character title over the marks still let a fallback with its
        spaces removed through, because no title that short contains a space.
        Both evasions were chosen by a seat that had not written the arm, and the
        second was found only after the first was fixed.

        **The space has to be a member of the alphabet**, and the family has to
        be the titles already in the form the collapse and the strip leave, or it
        counts two spellings of one title as two and the arm fails on a correct
        rule. The family size is recomputed below rather than stated, and the
        failure message carries it.

        **Its residual is the bound, and the bound is why it is four rather than
        three.** No family bounded at N can see a fallback that changes behaviour
        only above N, so a fallback keeping the text up to three characters and
        returning a constant beyond it passed every arm at three, and that
        constant collided with the real title it spelled. Four is what kills that
        one. **The class is not closed and cannot be by this arm**: a threshold
        above the bound survives by construction, which is a statement about
        bounded families rather than about this fallback. Four costs
        milliseconds, and five is ten times the family for no case anybody has
        produced. **The milliseconds are not written down**, because a timing
        without its machine is not a measurement and the machine that produced
        this one is not the machine the suite runs on.
        """
        marks = identity._EDGE_MARKS + " "
        titles = [
            candidate
            for n in (1, 2, 3, 4)
            for candidate in ("".join(t) for t in itertools.product(marks, repeat=n))
            if identity._WHITESPACE.sub(" ", candidate).strip() == candidate
            and candidate.strip()
        ]
        keys = {identity.reading_history_title(t) for t in titles}

        assert len(keys) == len(titles), (
            f"{len(titles)} marks-only titles collapsed onto {len(keys)} keys"
        )
        assert "" not in keys
        assert [k for k in keys if not set(k) <= set(marks)] == []

    def test_a_genuinely_empty_title_is_still_the_empty_key(self) -> None:
        """The guard above must not invent a key for a title that has none.

        Both call sites refuse an untitled record before matching, so this is
        the boundary of the guard rather than a reachable case, and pinning it
        is what stops the guard being widened into one that fabricates a match
        for a blank.
        """
        assert identity.reading_history_title("") == ""
        assert identity.reading_history_title("   ") == ""

    def test_what_comes_off_an_edge_is_exactly_what_the_constant_allows(
        self,
    ) -> None:
        """The behaviour, partitioned over every codepoint there is.

        **This exists because pinning the constant left the expression that uses
        it unpinned**, which is the replacement stronger where it was aimed and
        weaker where nobody looked. The arm above fixes the constant's value; the
        strip is spelled separately, so `strip(_EDGE_MARKS + " «»")` changed the
        behaviour with the constant untouched and passed every arm in the file.
        Two seats found that independently, neither of them the one that had
        written the arm it defeated.

        **Whole of Unicode, and a derived expectation, so there is no exclusion
        to state.** Earlier versions of this class sampled
        `string.punctuation`, 32 ASCII characters, and a guillemet, a fullwidth
        colon, an ideographic full stop and an em dash all sat outside the
        sample. Sampling is what failed, not the choice of sample.

        **The expectation names no character**, not even the Greek question mark
        that `test_a_character_that_decomposes_into_the_set_is_stripped_too`
        spells out: a character comes off an edge exactly when casefolding and
        composing it leaves nothing but edge marks and whitespace. That rule
        derives the members, the decomposing members and the whitespace the
        strip set also carries, and it is the reason this arm needs no list.

        **Each edge is its own comparison, and probing both at once hid exactly
        one thing.** The first version put the character at both ends of one
        title, which is symmetric and therefore blind to an asymmetric rule: a
        widening applied to the leading edge alone leaves the trailing copy in
        place, the key differs from the bare key, and the arm's own expectation is
        also False, so it agrees with itself and passes. Two seats found that
        independently, and it was a **regression** against the ASCII arm this one
        replaced, which asserted each edge in its own statement. Narrowings were
        never hidden; only widenings, which is the dangerous direction. A `strip`
        rewritten as a regex with two character classes is where the edges drift.

        **What each arm holds, since three now overlap.** This one holds that the
        behaviour follows the constant, at each edge separately. The arm above
        holds which value the constant has. Neither implies the other, and
        together they are what makes a change to the set visible whichever half
        somebody edits.

        **It also catches a change of normaliser**, because the expectation
        recomputes NFC itself rather than calling `_casefolded`: moving the
        implementation to NFKC shows up here as a disagreement.

        **Its residual is context, and no number of probes closes it.** Each
        character is placed alone at an edge, so the expectation is per character
        in isolation and a rule conditional on what sits **beside** the character,
        or on how many of it there are, is outside this arm: a widening firing
        only behind a listed mark, and one firing only on a run of two, both give
        zero disagreements here. Adding the obvious second probe pair catches the
        first and not the second, which is the tell that the class is
        context-dependent rather than under-sampled. Run behaviour is held by
        `test_a_run_of_marks_comes_off_as_a_run` and
        `test_a_catalogue_spelling_reaches_the_title_it_spells` instead, and
        narrowings of that kind are the safe direction anyway. **Stated rather
        than chased**, because a probe added per witness is the enumeration this
        arm exists to stop being.

        **It is the most expensive arm in this file**, by roughly an order of
        magnitude, which is worth knowing before anybody adds a third probe pair.
        """
        marks = set(identity._EDGE_MARKS)
        bare = identity.reading_history_title("Ulysses")
        wrong = []
        for codepoint in range(sys.maxunicode + 1):
            character = chr(codepoint)
            reduced = unicodedata.normalize("NFC", character.casefold())
            allowed = bool(reduced) and all(
                c in marks or c.isspace() for c in reduced
            )
            for edge, title in (
                ("leading", f"{character}Ulysses"),
                ("trailing", f"Ulysses{character}"),
            ):
                if (identity.reading_history_title(title) == bare) != allowed:
                    wrong.append(f"U+{codepoint:04X} at the {edge} edge")

        assert wrong == [], wrong[:20]

    def test_a_character_that_decomposes_into_the_set_is_stripped_too(self) -> None:
        """What the arm above cannot say, because the set is matched after NFC.

        U+037E, the Greek question mark, canonically decomposes to `;`, so it
        arrives as a member without being listed as one. A Greek interrogative
        title therefore strips where its Latin equivalent does not, `?` not
        being a member and having no route to becoming one. Pinned so that the
        constant is not read as the whole of what this removes.
        """
        assert unicodedata.normalize("NFC", ";") == ";"
        assert identity.reading_history_title("Γιατί;") == (
            identity.reading_history_title("Γιατί")
        )
        assert identity.reading_history_title("Why Not Me?") != (
            identity.reading_history_title("Why Not Me")
        )

    def test_whitespace_collapses_before_the_marks_come_off(self) -> None:
        """The predicate's own statement ordering, which nothing else sees.

        Every edge arm above uses an ASCII space, and with the two statements
        reversed all of them still pass: the strip set contains a space, so a
        mark separated by one still comes off. A **non-space** whitespace
        character is what separates the orders, because the collapse is what
        turns it into the space the strip set knows. OPDS titles come out of
        XML text nodes, which routinely carry a newline, so this is the
        ordinary case rather than the odd one. `fold_title`'s sibling class is
        named for this same mutation and this class had no analogue.
        """
        assert identity.reading_history_title("Ulysses :\n") == (
            identity.reading_history_title("Ulysses")
        )
        assert identity.reading_history_title("Ulysses\t:") == (
            identity.reading_history_title("Ulysses")
        )
