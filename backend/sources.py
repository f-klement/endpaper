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
   `{bnf, loc, oenb, nlg}` and it is exactly `_MATCH_PRECEDENCE[4:]`, so
   "believed last" is a contiguous tail **of that order**. In this module's
   order those four sit at positions 3, 4, 6 and 7, which is not a tail and not
   contiguous.
   So a cut position in the ask order cannot express the regional set, and
   seeding a different ask order to make it contiguous changes the lookup chain
   instead. Either way something a household never touched moves.

**The two paths do not share a roster either**, which is not an argument on its
own but is why a single list would have two entries that mean nothing on half
the paths they claim to order: six sources answer an ISBN, eight answer a
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
`_FALLBACK_SOURCES` as a speed classification is wrong: the OENB is **faster**
than K10plus and sits in the second tier anyway, because it rarely answers.
Freezing that as a property of the source would freeze exactly the case the
ticket was filed about, since an Austrian household wants it asked first and a
German one does not. A position is the thing a household can actually move.
"""

from dataclasses import dataclass
from typing import Any, Final

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
    #: How many of the sample's ten country frames this source answers anything
    #: in.
    #:
    #: **The field that separates a general catalogue from a national one**, and
    #: it exists because the NLG made the difference decidable. Everything else
    #: in this table is pooled over 500 ISBNs drawn as ten frames of fifty, so a
    #: source that answers one frame perfectly and nine not at all is scored as
    #: though its coverage were spread. That is the right instrument for
    #: coverage, where the question is whether a book resolves at all, and the
    #: wrong one for the **tier**, which every household pays on every lookup
    #: while its own shelf sits in one or two frames rather than ten.
    #:
    #: Measured in the coverage pass of 2026-08-30: K10plus and Open Library
    #: answer in 10 frames, the DNB in 5, the OeNB in 4 and the NLG in **1**.
    #: See `TIER_FRAMES_MINIMUM`.
    frames_answered: int


#: What each free lookup source does, measured on the night of 2026-08-30.
#:
#: **Two passes, and they are dated differently on purpose.** The coverage pass
#: ran on the evening of 2026-08-30 and the latency pass in the small hours of
#: 2026-08-31, which is why the committed sample is named for the later day. The
#: latency pass was taken twice: the first was voided because eight page size
#: probes were fired at one of these hosts while it was running, and only the
#: second, with nothing else in flight, is in the file.
#:
#: **The sample.** Ten frames of 50 domestic ISBNs, 500 in all. Eight are #91's
#: Wikidata sample by registration group, re-run rather than quoted; two are new
#: and are why this table exists, because #91 sampled no German language
#: publishing while this list leads with the two German catalogues. `german` is
#: drawn on the group `978-3-`, which is exactly the population
#: `metadata._GERMAN_PREFIX` keys on. `austria` is drawn on publisher country,
#: because Austria shares `978-3-` with Germany and Switzerland.
#:
#: **Drawn from Wikidata, which none of these sources is.** A sample drawn from a
#: catalogue under test finds itself. Wikidata leans towards notable editions,
#: which Open Library and Google Books hold best, so it understates the miss rate
#: rather than flattering it.
#:
#: **Asked through `metadata._SOURCES` itself**, so "answered" means what the
#: application means rather than what a probe decides. A source that returned
#: `rate_limited` or `unavailable` after five retries is dropped from its own
#: denominator instead of counted as a miss. None was: every source answered all
#: 500, which is why every `of` reads 500.
#:
#: **That exclusion protocol is the coverage run's**, and `answered` is what it
#: produced. The latency run is a second pass over the same 500 ISBNs and has no
#: retry at all, because a refusal there is a timing sample to discard rather
#: than a denominator to correct. It recorded none to discard.
#:
#: **The latency was taken with nothing else in flight, and the instrument
#: decided the number.** The coverage survey runs four ISBNs at once, and under
#: it Open Library measured 4.248s mean against 1.761s here, a factor of **2.4**.
#: The concurrent figure is the right instrument for a coverage ranking and the
#: wrong one for what one household's lookup costs, which is what
#: `FIRST_TIER_BUDGET_SECONDS` is about. Coverage came out identical under both
#: instruments, source by source, which is why only the timings were re-taken.
#:
#: **The sample is committed** at
#: `backend/tests/fixtures/catalogue_survey_2026_08_31.json`, so every figure
#: below recomputes in the suite. What that establishes and what it does not is
#: in `Measured`'s own docstring.
#:
#: **Google Books is absent and that is not a gap.** It is metered, so
#: `Plan.lookup_together` bars it from the tier whatever position it holds, and a
#: default install has no key for it, so the chain a default install runs is
#: exactly these five. `TestTheOrderFollowsTheMeasurement` asserts the table
#: covers them all, so a source added to the roster cannot quietly go unmeasured.
MEASURED: Final[dict[CatalogueSource, Measured]] = {
    CatalogueSource.DNB: Measured(
        answered=91, of=500, p90_seconds=0.251, frames_answered=5
    ),
    CatalogueSource.K10PLUS: Measured(
        answered=208, of=500, p90_seconds=0.471, frames_answered=10
    ),
    CatalogueSource.OENB: Measured(
        answered=55, of=500, p90_seconds=0.539, frames_answered=4
    ),
    CatalogueSource.OPEN_LIBRARY: Measured(
        answered=237, of=500, p90_seconds=2.757, frames_answered=10
    ),
    CatalogueSource.NLG: Measured(
        answered=37, of=500, p90_seconds=0.236, frames_answered=1
    ),
}

#: What the best tier of each size answers, of the same 500 ISBNs as `MEASURED`.
#:
#: **A union, which is exactly what `MEASURED` cannot express.** Two sources that
#: answer the same books are worth less together than two that miss different
#: ones, and a per source table has no way of saying so. Each entry is the best
#: tier of that size that `FIRST_TIER_BUDGET_SECONDS` allows: K10plus alone,
#: then K10plus with the DNB, then both with the OENB, which is every source
#: inside the budget and so the largest tier there can be.
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
#: **Over the sources a tier may hold, which is now narrower than "inside the
#: budget".** `TIER_FRAMES_MINIMUM` keeps a national catalogue out, and it has
#: to be applied here as well or this table would price a tier that cannot be
#: built: the best pair of everything inside the budget is K10plus with the NLG
#: at 242, against 221 for the pair that ships, and all 34 books of that
#: difference are in one frame.
TIER_UNION: Final[dict[int, int]] = {1: 208, 2: 221, 3: 222}

#: How many of the sample's ten frames a source must answer in to be asked on
#: **every** lookup.
#:
#: **What it decides is the tier's size, not its membership**, and stating that
#: the other way round was this constant's first draft. The membership rule
#: ranks by pooled rate and the NLG is fourth of the four sources inside the
#: budget, 37 of 500 against the OeNB's 55, so `_tier_for` excludes it unaided:
#: the tier is `{dnb, k10plus}` under every frame floor from 0 to 5. A design
#: critic executed that and the first version of this docstring was wrong.
#:
#: **The size rule is where it bites, because `TIER_UNION` does not rank, it
#: unions.** With the frame rule off, the best tier of each size reads
#: `{1: 208, 2: 242, 3: 255, 4: 256}`, so the slots earn 208, 34, 13 and 1, and
#: the third clears `SLOT_MUST_EARN` at 10. That is a measurement saying every
#: install everywhere should make a third concurrent request on every lookup.
#: With the frame rule on it reads `{1: 208, 2: 221, 3: 222}`, the third slot
#: earns 1, and `ALWAYS_ASKED` stays 2.
#:
#: **The reason to disbelieve the wider tier is the sample's own shape.** It is
#: ten frames of fifty by country, so a pooled union weights ten national
#: publishing outputs equally, and no household's shelf is one tenth Greek. What
#: the tier costs is paid by one library on every scan; what a national
#: catalogue answers is concentrated in the country it serves. All 34 of the
#: NLG's marginal answers are in one frame.
#:
#: **Three things wrong with the metric, stated because the next reader will
#: otherwise have to find them again.** A design critic found all three.
#:
#: * It counts "answers anything in", not "answers usefully in", which flatters
#:   the DNB: it scores 5 and 83 of its 91 answers are in two frames.
#: * It admits the OeNB, at 4 frames and **1** marginal answer, and bars the
#:   NLG, at 1 frame and **34**. So it is not a rule about contribution and
#:   should not be read as one. It is a rule about whether a contribution is
#:   general enough to charge every install for.
#: * The NLG sits at 1 and **one record moves it to 2**: a single Greek imprint
#:   catalogued under another frame's registration group. So the gap below is
#:   wide in this sample and the value is one observation from the boundary.
#:   `test_the_frame_rule_is_what_holds_the_tier_at_two` pins the decision rather
#:   than the count, which is why it survives that.
#:
#: The roster is otherwise nowhere near it: the sources this keeps answer in 4,
#: 5, 10 and 10 frames and the one it excludes answers in **1**, so every value
#: from 2 to 4 picks the same tier.
#:
#: **What it does not claim.** Ten frames are ten sampled countries, not the
#: world, so "answers in one frame" means one of the ten that were asked. A
#: catalogue serving a country nobody sampled would read as answering none, and
#: it would be kept out of the tier for the right reason by accident.
TIER_FRAMES_MINIMUM: Final = 2

#: For each source asked one at a time, how many of the books the leading tier
#: missed it answers, of the same 500.
#:
#: **The tail's rule is marginal and no per source count can express it**, which
#: `TestTheOrderFollowsTheMeasurement` disclosed as a blind spot before this
#: table existed: it ordered the tail by `answered / of`, which counts books the
#: tier already had. The two agreed while the tail was Open Library and the
#: OeNB, and the NLG is where they come apart. Measured over the 279 ISBNs of
#: 500 that the leading pair missed: Open Library answers 83, the **NLG 34** and
#: the OeNB **1**, while the pooled counts read 237, 37 and 55. So the pooled
#: rule would ask the OeNB before the NLG on every one of those 279 lookups, to
#: reach a source that answers one of them.
#:
#: Google Books is absent for `MEASURED`'s reason: it is metered, a default
#: install has no key, and its position is a metering rule rather than a
#: coverage one.
TAIL_MARGINAL: Final[dict[CatalogueSource, int]] = {
    CatalogueSource.OPEN_LIBRARY: 83,
    CatalogueSource.NLG: 34,
    CatalogueSource.OENB: 1,
}

#: What one more concurrent slot has to answer before it is worth its request.
#:
#: Ten books per 500, and like `FIRST_TIER_BUDGET_SECONDS` it is a statement of
#: intent placed in a gap rather than a threshold fitted to the roster. The
#: second slot earns **13** and the third earns **1**, so every value from 2 to
#: 13 gives the same answer, and
#: `test_the_slot_threshold_is_not_fitted_to_this_roster` sweeps that rather
#: than asserting it. **The gap was [3, 35] before the NLG joined and the 020
#: rule changed**, and 10 sits 72.7% into the narrower one, which is inside that
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
#: near it: the slowest source inside the budget is 0.539s (the OENB, which is
#: not in the tier) and the only one outside is
#: 2.757s, so every bound from 0.471s up to but not including 2.757s picks the
#: same tier. The endpoint is exclusive and that is not pedantry: at exactly
#: 2.757s Open Library qualifies and wins on coverage, so the tier changes.
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
#: ## What this order decides, and what it cannot
#:
#: **It does not decide which books are found.** `metadata.lookup` asks every
#: enabled source until one answers, so the set of ISBNs the chain resolves is
#: the same under any permutation of it. Modelled over seven candidate orders
#: against the 500 ISBN outcome set behind `MEASURED`: **336 of 500 under every
#: one of them.** So there is no ordering of this roster that "covers more", and
#: a reorder is never the fix for a book the chain misses.
#:
#: What it does decide is **latency**, and **which records are merged**: the
#: first tier is gathered and folded together by `metadata._merge`, while a hit
#: in the tail is used alone.
#:
#: ## The first tier is a latency budget, and the rule for it is stated
#:
#: `ALWAYS_ASKED` sources are asked concurrently, so **the tier costs its
#: slowest member and not their sum**. Membership is therefore *the sources most
#: likely to answer within `FIRST_TIER_BUDGET_SECONDS`, in more than one of the
#: sample's frames*, and it is deliberately **not** *the most authoritative*:
#: `metadata._preferred_source` decides belief per ISBN on the lookup path and
#: `_MATCH_PRECEDENCE` decides it on the search path, so promoting a source here
#: changes whether it is asked and never whether it is believed.
#:
#: **The frame condition is the newer half and `TIER_FRAMES_MINIMUM` carries the
#: reason.** Without it the NLG takes the second slot on the pooled measurement,
#: on 34 books that are all in one frame of ten.
#:
#: **Position inside the tier is immaterial only while the tier holds the source
#: `_preferred_source` names for that ISBN.** That is true of this tier and not
#: of every tier a household can build, and the difference is `metadata._merge`:
#: it sorts on `(source == preferred, completeness)` and `sorted` is stable, so
#: with the preferred source absent a tie falls through completeness to
#: **arrival order**, which is tier order, and `filled_from` then gives every
#: contested field to whichever record leads. A household that switches both
#: German catalogues off does decide a record by the order it puts the rest in.
#:
#: **The DNB leads and costs nothing.** It answers 8 of the 400 ISBNs outside
#: German publishing, which reads as a wasted slot, and it is not one: the tier
#: is gathered, so it costs its slowest member. `dnb + k10plus` costs a mean of
#: 0.369s and **K10plus alone costs a mean of 0.369s**, p90 0.471s against
#: 0.471s. What the slot spends is one HTTP request and under a millisecond.
#: What it buys is the 44 of 50 German language ISBNs and the 39 of 50 Austrian
#: ones it answers, and demoting it to the tail instead costs a modelled mean of
#: **1.447s against 1.366s** for the same 336 books.
#:
#: **Open Library is the broadest source and is kept out of the tier.** Paired
#: with K10plus it reaches 297 of 500 against the leading pair's 221, and its
#: `p90_seconds` is nearly six times the tier's. That is paid on every lookup,
#: including the 221 the fast pair already answers, and it makes the whole
#: lookup slower rather than faster: modelled mean **1.868s against 1.366s**,
#: for the same 336 books.
#:
#: **Every modelled figure here walks `lookup`'s two phases over the 500 rows
#: and costs a gathered tier as that row's own maximum**, never as the maximum
#: of four per source means. A tier costs its slowest member **on that ISBN**,
#: which is a maximum over a row and cannot be recovered from four separate
#: distributions. Doing it the other way overstated the absolute by 11% and the
#: third slot's gain by half.
#:
#: ## The tail is ordered by how often it answers a book the tier missed
#:
#: `Plan.lookup_in_turn` stops at the first hit, so a source ahead of the one
#: that would have answered costs a round trip and nothing else. Of the 279
#: ISBNs of 500 the leading pair missed, Open Library answers **83**, the NLG
#: **34** and the OENB **1**. `TAIL_MARGINAL` carries those three and
#: `test_the_tail_is_ordered_by_how_often_it_answers_what_the_tier_missed`
#: enforces them.
#:
#: **That rule minimises requests and not seconds, and here the two disagree.**
#: Modelled over the 500: the shipped tail costs a mean of **1.366s**, and
#: putting the NLG ahead of Open Library costs **1.329s**, because Open Library
#: is six times slower than the NLG and answers nothing at all in the Greek
#: frame. The 0.037s is not taken, for `TIER_FRAMES_MINIMUM`'s reason one
#: position down: it would ask a single frame catalogue before the broadest
#: source for every book in every library. Reversing the other pair is worse on
#: both counts, 1.381s and one fewer marginal answer.
#:
#: **What a national catalogue in the tail costs a library that is not Greek**,
#: stated because the pooled mean hides it: it is a round trip on every lookup
#: the tier misses, for a source that will not answer. Modelled per frame,
#: promoting the NLG out of the tail and into the tier saves 0.928s in the Greek
#: frame and 0.000s to 0.171s in the other nine, and the second range is that
#: cost rather than a benefit. Asking a national catalogue only for the
#: registration groups it serves is the fix and it is a separate piece of work.
#:
#: **What the reorder tells whom, since it changes who is asked about a book.**
#: The OENB now sees 165 lookups of 500 rather than 279, because Open Library
#: and the NLG answer first. The NLG sees 196: every lookup the leading pair
#: misses and Open Library does not answer, whatever country the book is from.
#: No new identifier is sent that was not already sent to the two sources ahead
#: of it, and it is an ISBN.
#:
#: **196 minus 165 is 31 and `TAIL_MARGINAL` says 34**, which is not an error in
#: either: the table is marginal against the **tier**, and a position in the
#: tail is marginal against everything ahead of it. Open Library answers 3 of
#: the NLG's 34 first, so 31 of them are still unanswered when the NLG is
#: reached. Stated because the two numbers sit four lines apart and do not
#: reconcile on sight.
#:
#: **The OENB's position corrects a reason that did not reproduce, #115.** This
#: docstring used to put it third as "the only source that answers for an
#: Austrian imprint the German pair both missed: 3 of 50". On a fresh 50 ISBN
#: Austrian publisher sample the German pair missed 7, the OENB holds **1** of
#: those and Open Library holds **2**, so it is neither the only source nor the
#: best one on its own justifying case. **The two samples do not disagree**:
#: `metadata.py`'s OENB comment records that every ISBN in the 2026-08-27 one
#: was taken off a live OENB record, so it measures books the OENB holds, while
#: this one measures books Austrian publishers published. Only the second can
#: answer how often the OENB answers where the German pair did not, which is the
#: question this position turns on.
#:
#: **Google Books is last of the six that answer an ISBN** because it is the
#: only one with a key, a quota and a bill attached, and BNF and LOC come after
#: it because they answer no ISBN lookup at all, so their position here only
#: ever breaks a tie on the search path.
DEFAULT_ORDER: Final[tuple[CatalogueSource, ...]] = (
    CatalogueSource.DNB,
    CatalogueSource.K10PLUS,
    CatalogueSource.OPEN_LIBRARY,
    CatalogueSource.NLG,
    CatalogueSource.OENB,
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
        CatalogueSource.NLG,
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
#:
#: **This is much of the chain's coverage, and most installs do not have it.**
#: The five free sources answer 336 of the 500 ISBNs behind `MEASURED` and miss
#: 164, and outside German language publishing they miss 160 of 400. #91
#: measured the same books with a key: Italy 36% missed keyless against 0% with
#: one, Greece 86% against 54%. So "the chain covers this country" is a claim
#: about a keyed install, and it is worth saying wherever the chain's coverage
#: is described rather than being left for a household to discover.
#:
#: **"Most of the chain's coverage" was true when it was written and is not
#: now**, which is why this paragraph says "much". Two things moved the free
#: figure from 300 to 336 on the same 500 books: the NLG, and the `020 $q` rule
#: in `metadata._isbn_entries`, which was refusing 51 records the sources
#: already held. The Greek figure above is the sharpest case, and it moved in
#: two steps rather than one: **7 of 50 keyless before either change, 8 with the
#: `020` fix alone, and 39 with the NLG**, none of it involving a key.
NEEDS_A_KEY: Final[frozenset[CatalogueSource]] = frozenset(
    {CatalogueSource.GOOGLE_BOOKS}
)

#: How many enabled lookup sources are asked **together** before the rest are
#: asked one at a time.
#:
#: A cost bound rather than a taste: an ordinary lookup makes this many outbound
#: requests whatever the household puts in the list, so reordering cannot turn
#: every lookup into an eight way fan out. What a household changes is **which**
#: sources fill the slots, which is the whole point of the control.
#:
#: **Three was measured and refused, #115, and re-measured and refused again on
#: a roster with two more candidates.** Open Library is outside
#: `FIRST_TIER_BUDGET_SECONDS` and Google Books is metered, so the candidates
#: are the OENB and, but for `TIER_FRAMES_MINIMUM`, the NLG.
#:
#: **The OENB is nearly free in wall clock and buys nothing.** The tier is
#: gathered and it is barely slower than K10plus, p90 0.471s becoming 0.579s,
#: and it takes a round trip off the miss path, so it models **0.032s** faster
#: over the whole 500, 1.366s to 1.334s. What it buys is **0 books**: it answers
#: 1 of the 279 the pair missed, and the tail reaches that one anyway.
#:
#: **The NLG would be the better third slot on every pooled number and is
#: refused on a different one.** It models 0.159s faster, 1.366s to 1.207s, and
#: also buys 0 books. Per frame that saving is 0.928s in the Greek frame and
#: 0.000s to 0.171s in the other nine, so most of it is one tenth of the sample,
#: and what the slot costs is a request on every lookup of every install
#: everywhere. `TIER_FRAMES_MINIMUM` is where that is decided.
#:
#: Recorded with the numbers so the next reader can reverse it against them
#: rather than guess.
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
        # entries read against a roster of eight looks like a bound on a hostile
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
    one source into an instruction to switch the other seven **on**: a request to
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
