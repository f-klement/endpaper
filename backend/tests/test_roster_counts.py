"""The roster's size is spelled in prose all over this tree, and this recomputes it.

**One fact, dozens of places, and nothing that compares them.** Adding one
catalogue source in #111 made twenty two prose statements stale. They were found
in three passes and every pass believed it was the last; one of them was
`backend/ratelimit.py`, whose published counterpart in `docs/security.md` had
been corrected in the first pass by the seat that missed its source.

`test_fetch.py::test_the_constant_states_the_source_count_the_tree_has` had the
right idea and one sentence's worth of reach: it reads one docstring for
`asks (\\w+) sources at once` and compares the spelled word to
`len(sources.SEARCH_SOURCES)`. It was green throughout #111, because it guards
the sentence somebody thought to guard.

## Why a scan alone cannot do this

**"The roster count" is not one number.** There are **six** named sets a claim
may bind to, and only **four** distinct sizes among them, because three of the
six are 9. Nothing in a sentence's shape says which is meant. So "six sources" in
this tree is a correct count of the free lookup sources, a correct count of some
other subject entirely, or a stale search count. Measured over the census below,
**40** of its occurrences count something that is not the roster, so a scan with
no classification fails 40 times on its first run and is switched off.

Both figures in that paragraph are recomputed by `TestThisFileCountsItself`
rather than reread, because this file's own prose is inside its subject.

## The shape, and what each half stops

**A census, and a verdict for everything it finds, checked in both directions.**

1. `CARDINALITIES` is computed from `sources.py`. No count is written down here.
2. The census finds every candidate: a number, at most two words, a roster noun.
   A candidate is in scope only if its **value is one of the live
   cardinalities**, so the bound is derived rather than picked and widens on its
   own the day a set changes size.
3. Every candidate must carry a verdict in `CLAIMS`, keyed on the file and the
   matched phrase **with the number elided**, so this table holds no counts and
   correcting a stale sentence needs no edit here. `Counts` names a cardinality
   and the guard compares. `NotTheRoster` records what the number counts
   instead. `KnownStale` records a wrong count nobody here could correct.
4. **A candidate with no verdict fails.** This is what an enumeration of sites
   cannot do: the site nobody adds is the site nobody checks, and the census adds
   it whether or not its author thought about this file.
5. **A verdict matching nothing fails**, and a `KnownStale` that has been
   corrected fails. Without those the table rots in the other direction, which
   is the same defect one level up.
6. **A roster set added to `sources.py` and left out of `CARDINALITIES` fails**,
   so the census's own bound cannot silently stop covering a new set.

## What it does not see, measured rather than left to be discovered

The census reads a quantified noun phrase, so a roster count written any other
way is invisible. Each of the first five rows is a real sentence in this tree,
correct today and unguarded. The sixth names a shape and deliberately names no
sentence, for a reason given under it:

* the noun is elided, `docs/api.md` "A new install has all nine on". It was
  stale at "eight" and was corrected in the commit that added this file, by
  hand, because nothing here can see it.
* an ordinal, `backend/fetch.py` "The NKP is the ninth". An ordinal states a
  position rather than a size, so there is nothing to compare it with.
* a sub count with its own denominator, `docs/legend.md` "One of the three
  sources fetched over plaintext HTTP". Invisible because neither 1 nor 3 is a
  live cardinality.
* the first half of "N of the M sources", `docs/legend.md`, where the nine is
  checked and the seven beside it is not.
* the noun is elided, `backend/metadata.py` "Building all eight and dropping
  some would leave un-awaited coroutines". A live `SEARCH_SOURCES` count with
  no census occurrence anywhere in its block, unlike the two other "all N"
  sentences in that file and in `tests/helpers.py`, each of which restates a
  count the census reads **in the same block**. Block, not a line distance:
  that is the unit `_paragraph` works in, and a first draft of this row quoted
  one distance for the two sites, which are two and three.
* **the value has drifted out of the bound.** A candidate is admitted only if
  its value is a live cardinality, so a count that goes far enough out of date
  leaves the census's scope on the very commit that makes it wrong.

**No sentence is named for that row, and the omission is the row.** Every
instance of it is by construction a count that is wrong, so every instance gets
corrected, and a row naming one is stale as soon as it works. The five rows
above can name a sentence precisely because those sentences are right.

**It is the bound narrowing, where the comment at `live_cardinalities` says only
that it widens.** Both are true and the second is the one nobody expects, and it
inverts what a reader assumes about the guard's strength: it is best at catching
a count that is **slightly** wrong, which usually lands on another live
cardinality and is compared against the wrong set until somebody looks, and
blind to one that is **badly** wrong.

**Widening the bound to reach them is the refusal recorded below, and this is
what it would cost.** Over the whole scope on 2026-09-03, **254** matches of the
census grammar are refused for their value alone at 1 to 5, split 120, 79, 27,
23 and 5. The 226 at 1 to 3 are ordinary English, and even at 4 and 5 the
majority are correct counts of real subsets. So that row cannot be reached by a
bound at all, only by a verdict, and a verdict needs a candidate.

**A second hole in the grammar, and the two compose in the direction that hides
things.** Markup around the number blinds the pattern: `**nine** sources` is not
a match where `**nine sources**` is, because the gap must begin with whitespace,
and `_nine_ sources` is invisible for a different reason, that `_` is a word
character so the boundary before the number never holds.

**Measuring this at a live cardinality reports it empty, and that is the trap
rather than the result.** Measured 2026-09-03 by permitting the markers around
either token and testing "not adjacent to an alphanumeric" in place of a word
boundary, so that no spelling is privileged, **three** sites in the whole scope
are hidden by markup at a live cardinality and **none is a claim**: two are the
fixtures in the paragraph above, and the third reaches its noun inside a dotted
code span two words along. **Each fixture occurs exactly once, so spelling
either of them a further way moves this figure**, which is this paragraph
counting itself and is the same recursion as the dash table in the working notes
at the root. Drop the bound to 4 and 5 and more appear, and at
least one of those was a real and wrong roster count on the day this was
written. **So the shape is not empty; the instrument that reported it empty was
filtering on exactly the value rule the row above says hides a badly wrong
count.** A count can be concealed twice over, once by its markup and once by its
value, and the second concealment hides it from the measurement you would use to
find the first.

**That three was two under each of the two instruments that were tried first,
and their twos were different twos.** One kept the word boundaries outside the
marker class and so could see `_nine_` and not `**nine**`; the other kept them
inside and saw the reverse. Each reported a stable looking 2 while missing one
of the two fixtures this paragraph is made of, and the disagreement was invisible
in the counts and obvious in the sets. **This is the compare the sets rule
landing on the number in the paragraph that states it**, and the reason the
figure above names its instrument in full rather than saying "with markup
allowed".

**Three more sat in that list as stale, and the fix was to bring the sentence
inside the grammar rather than to widen the grammar to reach it.** The route
docstring behind the enrichment endpoint said "searches all seven" of a fan out
of eight, and **published** it: FastAPI puts a route docstring into the OpenAPI
description, so the wrong number was committed in `frontend/openapi.json` and
shipped as API documentation. `settings_store.py` said "seven entries" twice, at
the default and again where the row is read back, of a row that spells nine.
Each now names the set it counts, so the census sees the claims and a verdict
pins every one of them.

**What stops the noun being written back out is
`test_every_verdict_still_has_a_claim_to_judge`.** A sentence reworded out of
the grammar leaves its verdict judging nothing and is named there, so a
correction is held from both sides by a rule that was already here rather than
by new machinery. That is the shape to copy for the rows above, and it is not
free: it constrains how a sentence may be written, and a sentence whose subject
is a position or a sub count cannot be rewritten as a size without lying.

**The two cheap widenings were measured and refused.** Matching a bare number
after "all" finds 52 occurrences this census does not already see, and "the other
N" finds 25. The great majority count palettes, routes, call sites and authority
schemes rather than catalogues, and every one of them would need classifying.
Doubling the table to judge palette counts buys the two "all" shaped sites named
above, and it buys them by making every future sentence about anything countable
somebody's problem. They are named here instead of missed silently.

**The other refusal is the census bound.** Widening it from the cardinalities of
the sets that count sources to the cardinalities of *every* collection of
`CatalogueSource` in `sources.py` takes the census from 77 occurrences to 299,
because `METERED`, `SERVES_GROUPS` and `TAIL_MARGINAL` are 1, 2 and 4 and those
are ordinary English. `roster_sets()` keeps the guard honest about that instead:
every set is accounted for, and the ones that are not roster counts say so.

**All four of those figures, the 52 and 25 above and the 77 and 299 here, are
snapshots rather than recomputed, and saying why belongs in the file that
recomputes everything else.** They count sentences in this tree, so they move
whenever anybody writes prose anywhere in it, about anything. A test asserting
one would go red on an edit to a paragraph about covers, which teaches a reader
to change a number until the failure stops rather than to ask what it means.

**A snapshot needs its instrument written beside it**, and that is what this
paragraph did not have. All four are matches of `_CLAIM` over the flattened text
of every file in `scope()`: the census is those whose value is a live
cardinality, the widened figure those whose value is any `roster_sets()` size,
and the two above are the "all N" and "the other N" spellings carrying a live
cardinality where the census does not already report one.

**Re-derived that way against the merge that wrote them they read 39, 19, 64 and
238, where the prose said 38, 18, 64 and 238.** Two agree exactly and two are one
out, which is a definition the prose never carried rather than a count somebody
got wrong: it said "matching a bare number after all" and never said over what
scope, against which values, or whether an occurrence the census already reports
counts twice. **Re-derived against this branch's base, nineteen commits later,
the widened figure had already moved from 238 to 250 with nothing failing**, which is
exactly what a snapshot does and why the reason above for not asserting one is
still the right call.

All four were recounted on 2026-09-03 with `docs/decisions.md` in scope for the
first time. What moves least is the multiple: the widened bound takes in roughly
four times as many occurrences, 3.88 today against 3.72 at the merge, so the
shape of the refusal survives a recount even though neither figure does.

**The table's size is the comfort to distrust.** A complete classification reads
like a complete sweep and is not one: it is complete over the census's grammar,
which is the paragraph above.

## The historical count, and why a date is not the test

The obvious rule is that a count naming a date is history and may disagree. It
does not separate anything: measured over this census, 27 occurrences carry a
date, `measured` or an issue number in the same paragraph, and that 27 holds both
a correct exemption and a stale claim. What separates them is tense and a current
figure beside the old one. `docs/security.md` is the model:

    across the six sources `metadata.search` asked at once when that was
    measured, 463.8 MB peak ... It asks eight now, so that figure is the shape
    it was taken at rather than today's.

So the exemption is a recorded classification naming the subject, and `dated` is
an optional extra the guard verifies where the prose already carries one.
"""

import ast
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

import sources
from enums import CatalogueSource
from tests.test_house_rules import _is_vendored

#: This module's own docstring, bound while it is still the nearest one.
#: `__doc__` inside a method body is an ordinary global lookup and reads
#: whichever docstring the enclosing scope happens to expose, which is not
#: reliably this one.
_DOC = __doc__

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent


def roster_sets() -> dict[str, int]:
    """Every collection of `CatalogueSource` bound at module level in `sources`.

    **Found by reflection so a new one cannot be missed.** A hand written list
    here would be the second thing to update when a set is added, and the first
    would be the prose this file exists to guard.
    """
    found = {}
    for name, value in vars(sources).items():
        if name.startswith("_"):
            continue
        members = list(value) if isinstance(value, dict) else value
        if not isinstance(members, (frozenset, set, tuple, list)) or not members:
            continue
        if all(isinstance(member, CatalogueSource) for member in members):
            found[name] = len(members)
    return found


#: Every live cardinality a roster claim can carry, computed.
#:
#: **A claim binds to a name here and the guard reads the number out of the
#: tree**, which is the whole point: nothing in this file states how many
#: sources there are.
#:
#: **`Counts` compares a number, not a set, and a reader will read it as the
#: set.** Three of these six names are 9 today, so six names discriminate four
#: ways and a claim can bind to the wrong one and pass. Live instance:
#: `test_books_google.py` says enrichment reaches all nine sources and binds to
#: `the whole roster`, while `helpers.py` states the identical fact about the
#: identical helper and binds to `lookup or search`. Both pass. The day those
#: two stop being equal, one fails naming a set it was never about. No test can
#: catch that, because the two claims are indistinguishable by number, which is
#: all a number carries.
CARDINALITIES = {
    "the whole roster": lambda: len(CatalogueSource),
    "DEFAULT_ORDER": lambda: len(sources.DEFAULT_ORDER),
    "SEARCH_SOURCES": lambda: len(sources.SEARCH_SOURCES),
    "LOOKUP_SOURCES": lambda: len(sources.LOOKUP_SOURCES),
    "the free lookup sources": lambda: len(sources.LOOKUP_SOURCES - sources.METERED),
    "lookup or search": lambda: len(sources.LOOKUP_SOURCES | sources.SEARCH_SOURCES),
}

#: The sets in `sources.py` that are not a count of sources, and what each is.
#:
#: **Named rather than skipped**, so `test_every_roster_set_is_accounted_for`
#: can insist that every set is one thing or the other and a tenth set fails on
#: arrival. Their sizes stay out of the census bound: they are 1, 2 and 4, and
#: admitting those roughly quadruples the census, because "one source" and "two
#: catalogues" are ordinary English. The figures, and why they are dated rather
#: than recomputed, are in this module's docstring.
NOT_A_ROSTER_COUNT = {
    "METERED": "which sources cost money, not how many there are",
    "NEEDS_A_KEY": "which sources need a credential",
    "SERVES_GROUPS": "which sources have a registration group remit",
    "TAIL_MARGINAL": "what each tail source answers, keyed on the source",
    # The one entry whose reason a reader will check against the census bound
    # and find inside it: `MEASURED` has six members, and six is a live
    # cardinality. It is here anyway because it is a mapping of measurements
    # keyed on the source rather than a count of sources, and its size equalling
    # one is a coincidence of today's roster.
    "MEASURED": "what each free source was measured to do, keyed on the source",
}

#: The words a count is spelled with here, and the digits it may be written as.
#:
#: **Both, deliberately.** Every one of #111's twenty two stale sites was
#: spelled, and covering the digit costs one alternation. A guard that covers
#: only the shape that has failed before is a guard one edit behind.
SPELLED = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}

_NUMBER = rf"(?:{'|'.join(SPELLED)}|\d{{1,3}})"
_NOUN = r"(?:sources?|catalogues?|providers?)"

#: A number, at most two words, a roster noun.
#:
#: **Wrapped in a lookahead so matches may overlap.** Consuming the match makes
#: the scan miss a second claim starting inside the first: measured, one claim
#: in `test_fetch.py` disappears when the pattern consumes.
_CLAIM = re.compile(
    rf"(?=\b({_NUMBER})\b((?:[ \t]+[^\s]+){{0,2}}[ \t]+)({_NOUN})\b)", re.I
)

#: A line break plus whatever prefix the next line carries in a comment or a
#: docstring.
#:
#: **Replaced with spaces of the same width rather than removed**, so every
#: offset in the flattened text is still an offset in the file and a line number
#: is a `count("\\n")`. Prose here wraps at 88 columns, so a claim spanning a
#: line is ordinary rather than exotic: measured, a line by line scan misses
#: six, two of them the only claim in their file, and one of those two is the
#: stale count in `frontend/`.
_WRAP = re.compile(r"\n[ \t]*(?:#:?|\*|//)?[ \t]*")

#: The one register the census does not read, and why the other one is now read.
#:
#: **`CHANGELOG.md` is dated by its own structure.** Every entry sits under one
#: of its fifteen headings, so a count in it says what was true when that entry
#: was written and correcting it would falsify the record rather than repair it.
#:
#: **Fifteen headings, not fifteen versions**, and the difference is the clause
#: this comment carried wrongly. Counted 2026-09-03, `^## ` matches fifteen and
#: the subset starting a version matches fourteen: the fifteenth is
#: `## Unreleased`, which is the one heading that is not dated by a release. It
#: becomes one, which is why the reasoning survives, and saying "version
#: headings" of all fifteen did not.
#:
#: **`docs/decisions.md` was excluded on the same reasoning and it does not
#: hold.** That register carries **no** version headings, counted, and it
#: records decisions that still bind, so its counts read as present tense. It
#: held **four** stale roster counts when this file landed, each found by a
#: critic reading the register rather than by anything here. Those were fixed at
#: the merge, and the exclusion then rested on a second reason that was true and
#: temporary: the trio writing this guard was not permitted to edit a shared
#: register.
#:
#: **It is in the census now**, and what that cost is the thing worth knowing:
#: not a line here, but a verdict for every candidate in a ten thousand line
#: file. Most of its counts are legitimately historical, so most of them are a
#: `NotTheRoster` whose subject names the moment the figure was taken. The pass
#: is recorded in that register under "This register is in the census, and a
#: historical count says when it was taken", and it found two errors this guard
#: could not have: writing down what a number counts forces a check against the
#: thing it counts.
#:
#: **The architecture decision records are the third of these and are not named
#: here**, because they are not published and this file is. `scope()` reads
#: `docs/*.md` rather than `docs/**/*.md`, and every subdirectory under `docs/`
#: is stripped from the public mirror, so naming one would leave a published
#: file pointing at a stripped path. The publish gate refuses that, and it
#: refused two drafts of this comment: once for the record it named, once for
#: the script it credited.
DATED_REGISTERS = ("CHANGELOG.md",)

#: Generated trees under this project's own source, holding no prose a person
#: wrote about this application.
#:
#: **The tool directories are not listed here and must not be**, because this
#: was a name list and the name list is what broke. It read `.venv`,
#: `node_modules` and `__pycache__`, which is every cache anybody had seen
#: locally, and CI sets `UV_CACHE_DIR` to `.uv-cache` inside the build
#: directory. The census then walked third party source and found roster sized
#: numbers beside roster nouns in it, in a Pygments lexer and in a charset
#: detector, neither of which any verdict here could ever cover. **Ten of twenty
#: pushes to `main` went red on that and none of them locally**, because the
#: difference was the environment rather than the tree.
#:
#: **The phrases are deliberately not quoted here.** The first fix spelled both
#: out, and the census reported this comment: a note about a count that contains
#: the count is the recursion the dash table at the root already records.
#:
#: `test_house_rules._is_vendored` is that rule, structural rather than
#: enumerated, and it is imported rather than restated: it had already been
#: fixed once in this repository and the lesson did not travel to this file.
NOT_PROSE = ("/generated/", "/dist/")

#: The declaration every document stripped from the public mirror carries, in
#: the publish gate's own spelling.
#:
#: **A file that says this is out of scope, and naming those files instead was
#: refused by the gate twice.** Two documents at the repository root were being
#: read: the working notes for this checkout, and a session's own plan when one
#: exists. Editing either to say "eight sources" turned the backend suite red,
#: and a session plan is deleted at the end of the wave, so the failure landed
#: in a file about to stop existing. Neither carried a roster count on the day
#: this was written, which is exactly what made the trap silent.
#:
#: **Keyed on the declaration rather than on a list of names**, because the
#: names are themselves stripped paths, so a published file may not spell them,
#: and because the gate already requires this line of every document it strips.
#: One convention, enforced at both ends.
#:
#: **Measured when this replaced the name list**, over the candidate set
#: `len(candidates())` reports, 547 files recounted 2026-09-03: six carry the
#: declaration, every one of them is stripped from the mirror, and between them
#: they hold **zero** census candidates. So the rule drops exactly what the
#: mirror drops and costs no coverage today.
#:
#: **The anchoring is a rule about shape and this corpus does not justify it**,
#: which is worth saying because the first version of this comment claimed it
#: did. There are seven occurrences of the phrase across those six files and
#: **all seven match the anchored pattern**: the one that is a prose mention
#: rather than a declaration is backticked at the start of its own line, so
#: `[^A-Za-z0-9]{0,6}` eats the backtick and matches it too. On this evidence a
#: bare substring would drop the same six. The anchor is kept because it is the
#: publish gate's own pattern and a rule about mentioning is not a rule about
#: declaring, not because anything here separates the two.
#:
#: **The gate's own corpus would separate them and is deliberately not quoted.**
#: Not because the measurement cannot be stated without naming a stripped path,
#: which it can: because a figure copied from there is a number that has stopped
#: being re-derived, which is this file's whole subject, and re-deriving it means
#: walking a directory the mirror strips to justify a rule about shape.
#:
#: **The two ends bound different windows**, and that is a difference rather
#: than a defect: this reads the first 2000 characters and the gate reads the
#: first 30 lines. Measured across every candidate, they disagree about nothing
#: today; a file with a long enough header would separate them.
_INTERNAL = re.compile(
    r"^[^A-Za-z0-9]{0,6}[ \t]*\*\*This file is internal\.\*\*", re.M
)


def declares_itself_internal(path) -> bool:
    """Whether a file carries the declaration in its opening lines."""
    try:
        return _INTERNAL.search(path.read_text(encoding="utf-8")[:2000]) is not None
    except (OSError, UnicodeDecodeError):
        return False


@dataclass(frozen=True)
class Occurrence:
    """One place in the tree that spells a number beside a roster noun."""

    path: str
    line: int
    value: int
    #: The matched text with the number elided, lowercased. The table's key.
    phrase: str
    #: The run of lines the match sits in, which is what `near` and `dated` are
    #: claims about.
    paragraph: str
    #: The line that run starts on.
    #:
    #: **Identity, where `paragraph` is only text.** Two blocks with the same
    #: words are the same string and different sentences, so the rule that one
    #: verdict may not cover two paragraphs has to compare this and not that.
    block: int

    def where(self) -> str:
        spelled = self.phrase.replace("{n}", str(self.value))
        return f"{self.path}:{self.line}: {spelled}"


@dataclass(frozen=True)
class Counts:
    """This phrase states the size of a named set, and the guard checks it."""

    of: str
    #: A distinctive string that must appear in the claim's own paragraph.
    #:
    #: **"Paragraph" is a block of lines, not a sentence's surroundings**, so an
    #: anchor written expecting sentence scope reaches further than its author
    #: meant. `_paragraph` runs to the nearest blank line: a comment block of six
    #: lines holding two anchors offers both to every claim inside it, and in
    #: Markdown a blank line never falls within a table, so a whole table is one
    #: paragraph. Pick an anchor out of the claim's own sentence.
    near: str | None = None


@dataclass(frozen=True)
class NotTheRoster:
    """This phrase counts something else, and `subject` says what."""

    subject: str
    #: A date the prose already names beside the claim. Where it is given the
    #: guard checks it is really there. It is not the exemption: see the module
    #: docstring on why a date separates nothing on its own.
    dated: str | None = None
    near: str | None = None


@dataclass(frozen=True)
class KnownStale:
    """This phrase is wrong, and whoever wrote this entry could not fix it.

    **Strict, so it clears itself.** The guard asserts the number is still
    wrong, so the day somebody corrects the prose this entry fails and has to
    be deleted. A debt register that goes quiet when the debt is paid is a
    second stale list, which is the defect this whole file is about.

    `because` says why it was not fixed here. The only reasons that have ever
    been true are that the file belongs to somebody else this wave.
    """

    of: str
    because: str
    near: str | None = None


def _value(token: str) -> int:
    lowered = token.lower()
    return SPELLED.get(lowered, int(token) if token.isdigit() else 0)


def _paragraph(text: str, offset: int) -> tuple[str, int]:
    """The run of non blank lines the offset sits in, flattened to one line.

    A blank line, or a line whose only content is a comment marker, ends it.
    That is what makes `near` and `dated` claims about the sentence's own
    surroundings rather than about the whole file.

    **Flattened, because an anchor that has to know where the line broke is an
    anchor nobody can write.** `` `metadata.search` asks `` is one phrase in
    `fetch.py` and two lines in the file, and matching it against the raw text
    failed while looking correct.
    """
    lines = text.splitlines()
    index = text.count("\n", 0, offset)

    def blank(i: int) -> bool:
        return not re.sub(r"""[#*:/\s"']""", "", lines[i])

    start = index
    while start > 0 and not blank(start - 1):
        start -= 1
    end = index
    while end + 1 < len(lines) and not blank(end + 1):
        end += 1
    joined = " ".join(
        re.sub(r"^[ \t]*(?:#:?|\*|//)[ \t]?", "", line)
        for line in lines[start : end + 1]
    )
    return re.sub(r"\s+", " ", joined).strip(), start + 1


def live_cardinalities() -> set[int]:
    """Every value a roster claim can carry today.

    **The census's bound, and it is derived rather than chosen.** A hand picked
    range is a range somebody can narrow until a failure goes quiet; this one
    widens on its own the day a set changes size, which is the day the claims
    need re-reading anyway.
    """
    return {factory() for factory in CARDINALITIES.values()}


def scan(name: str, text: str):
    """Every candidate in one file's text, in file order."""
    live = live_cardinalities()
    flat = _WRAP.sub(lambda m: " " * len(m.group(0)), text)
    for match in _CLAIM.finditer(flat):
        number, gap, noun = match.group(1), match.group(2), match.group(3)
        value = _value(number)
        if value not in live:
            continue
        phrase = re.sub(r"\s+", " ", f"{{n}}{gap}{noun}").strip().lower()
        paragraph, block = _paragraph(text, match.start())
        yield Occurrence(
            path=name,
            line=text.count("\n", 0, match.start()) + 1,
            value=value,
            phrase=phrase,
            paragraph=paragraph,
            block=block,
        )


def candidates():
    """Every file the census would read before the declaration rule is applied.

    Split out so the declaration rule can be pinned over the whole set rather
    than over the corner of it somebody remembers to glob.
    """
    paths = []
    for pattern in (
        "backend/**/*.py",
        "docs/*.md",
        "*.md",
        "frontend/src/**/*.ts",
        "frontend/src/**/*.tsx",
        "frontend/tests/**/*.ts",
        "frontend/tests/**/*.tsx",
    ):
        paths += sorted(REPO.glob(pattern))
    skip = NOT_PROSE + DATED_REGISTERS
    return [
        p
        for p in dict.fromkeys(paths)
        if not _is_vendored(p, REPO)
        and not any(s in str(p.relative_to(REPO)) or s in str(p) for s in skip)
    ]


def scope():
    """Where prose a person wrote about this application lives.

    **Everything, minus what cannot hold it.** A new file is covered by default
    rather than by somebody remembering to add it, which is the property an
    enumeration of sites cannot have.

    **`docs/*.md` and not `docs/**/*.md`, which is the docs that ship.** Every
    subdirectory under `docs/` is stripped from the public mirror, so a count
    in one is unpublished by construction and naming its path here would make
    this file point at a stripped one.

    **A file declaring itself internal is dropped last**, by its own opening
    line rather than by name. See `_INTERNAL`.
    """
    return [p for p in candidates() if not declares_itself_internal(p)]


def census():
    """Every candidate in the whole scope, in file order."""
    for path in scope():
        yield from scan(
            str(path.relative_to(REPO)), path.read_text(encoding="utf-8")
        )


#: The dict methods that only read. Anything else on `CLAIMS` is refused.
READS_ONLY = frozenset({"get", "items", "keys", "values", "copy"})

#: The AST fields that carry a bound name as a string rather than as a `Name`.
#:
#: **Swept by field rather than matched by node type**, which is the difference
#: between covering nine binders and covering the three somebody listed.
#:
#: **Counted against the grammar rather than against what came to mind**, which
#: is the only way this claim is worth anything. Python has twelve places where
#: a binding is a bare string: `alias.name` and `.asname`, `FunctionDef.name`,
#: `AsyncFunctionDef.name`, `ClassDef.name`, `ExceptHandler.name`,
#: `MatchAs.name`, `MatchStar.name`, `MatchMapping.rest`, `arg.arg`,
#: `Global.names` and `Nonlocal.names`. These three fields cover the first
#: **nine**. `Global` and `Nonlocal` are refused separately below, because they
#: hold a list rather than a string and because they are declarations rather
#: than bindings. That leaves `arg`, and it is the one deliberate exclusion.
#:
#: **`rest` was missing and it was not hypothetical.** `case {**CLAIMS}:` bound
#: the table and passed both halves of this guard silently: the audited literal
#: held two keys and the table that ran held two different ones, so comparing
#: lengths saw nothing. It sits in the same `match` family as `MatchAs`, which
#: had been added one commit earlier, and the comment claiming every form was
#: covered is what carried it past a reader.
#:
#: **Not `arg`**: a parameter binds inside another scope and cannot reach this
#: table, and `keyword.arg` is a call site rather than a binding at all.
BINDS_A_NAME = ("name", "asname", "rest")


def _module_scope(tree: ast.AST):
    """Every node in the module's own scope, not inside a def, lambda or class.

    A definition is yielded, because it binds its own name out here; its body is
    not, because a name bound in there is a different name.
    """
    nested = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
    stack = list(ast.iter_child_nodes(tree))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, nested):
            stack.extend(ast.iter_child_nodes(node))


def claims_keys_in(source: str) -> list:
    """Every key written into a `CLAIMS` dict literal in `source`.

    **A dict keeps the last of two equal keys and says nothing**, so this reads
    the text instead. Not hypothetical: a second entry for one key silently
    discarded two anchored verdicts and left the suite green against a table
    that was not the one on the page.

    Raises `AssertionError` naming the construction whenever the table is built
    in a shape it cannot audit. **Refusing is the point rather than a fallback**:
    the first version returned `[]` for a `**` spread because it skipped a
    `None` key, which is a hole in exactly the refactor a growing table invites,
    splitting it into a base and a set of additions.

    **Three axes, and they are guarded three different ways.** Method names are
    **allowlisted**: a call on the table is refused unless `READS_ONLY` names
    it. Binding is a **count**, so every form of it is covered including the
    walrus, the for target, the tuple unpack and the `with ... as` that nobody
    wrote down. Reaching the table is **enumerated**, a call on the receiver and
    a subscript on it, and that enumeration has a boundary.

    **The boundary, attacked rather than assumed.** An audit keyed on the
    receiver cannot see the table passed as an **argument**, so
    `dict.update(CLAIMS, ...)` and `getattr(CLAIMS, "update")(...)` both reach
    it with no attribute node on the name for this to find. Those are deliberate
    edits rather than the drift these exist for, and the caller's second check
    stands behind them: comparing `len(CLAIMS)` with the key count catches
    anything that changes how many keys the table holds, however it was spelled.
    What neither catches is a replacement of an existing key by that route.
    """
    tree = ast.parse(source)

    # **The binding axis is a count, not a list of assignment forms**, which is
    # the correction that matters. Enumerating forms is what let `CLAIMS |= {}`
    # through: `AugAssign` was one shape past the end of the list, a character
    # from the `|` merge that was already refused.
    #
    # **Two dimensions, and both are swept rather than listed.** Most binders
    # put a `Store` on a `Name`. The rest carry the bound name as a **string**
    # in a field, and those are swept by field name rather than by node type:
    # `asname` for an import, `name` for a `def`, a `class`, an `except ... as`
    # and a `case ... as`. Listing node types is what the version before this
    # did, and it named three of those five, so `except Exception as CLAIMS` and
    # `case dict() as CLAIMS` both walked through a rule whose comment claimed
    # every form was covered. The second was measured end to end: the audited
    # literal held two keys and the table that ran held two different ones.
    #
    # **Module scope only**, which is what makes the sweep safe rather than
    # merely wide: `def f(CLAIMS)` and `lambda CLAIMS` bind inside another scope
    # and cannot touch this table, so descending into a body would refuse a file
    # for something harmless.
    #
    # **What is still a list is the field names**, and that is the residual: a
    # binder the grammar grows under a field this does not sweep would need one
    # more string here. `BINDS_A_NAME` counts today's against the grammar.
    #
    # **`global` is checked over the whole tree and not this scope**, which is
    # the one place that boundary is wrong to apply. A `global CLAIMS` inside a
    # function reaches out and rebinds the module name, so the stated reason for
    # the boundary, that another scope cannot touch this table, is true of a
    # parameter and false of a declaration. Measured: a same length replacement
    # through `global` swapped the table with both halves of this guard green.
    for node in ast.walk(tree):
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            assert "CLAIMS" not in node.names, (
                "a `global` or `nonlocal` declaration names CLAIMS, so a "
                "function can rebind the table this audits"
            )

    bindings = sum(
        (
            isinstance(node, ast.Name)
            and node.id == "CLAIMS"
            and isinstance(node.ctx, ast.Store)
        )
        or any(getattr(node, field, None) == "CLAIMS" for field in BINDS_A_NAME)
        for node in _module_scope(tree)
    )
    assert bindings == 1, (
        f"the name CLAIMS is bound {bindings} times at module scope, so the "
        "table that runs is not the one literal this audits"
    )

    # Module scope here too, so this agrees with the count above rather than
    # refusing a local named CLAIMS inside some unrelated function, which cannot
    # reach the table and which the two rules disagreed about.
    dicts: list[ast.expr | None] = []
    for node in _module_scope(tree):
        if isinstance(node, ast.AnnAssign):
            targets: list[ast.expr] = [node.target]
        elif isinstance(node, ast.Assign):
            targets = list(node.targets)
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == "CLAIMS" for t in targets):
            dicts.append(node.value)
    assert len(dicts) == 1, (
        f"CLAIMS is bound {len(dicts)} times; this can audit exactly one literal"
    )
    literal = dicts[0]
    assert isinstance(literal, ast.Dict), (
        "CLAIMS is no longer a dict literal, so its keys cannot be read back"
    )
    assert all(key is not None for key in literal.keys), (
        "CLAIMS is built with a `**` spread, which hides whatever the spread "
        "holds and can quietly replace a verdict"
    )
    for node in _module_scope(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "CLAIMS"
        ):
            # Allowlisted over METHOD NAMES, so a method nobody thought of is
            # refused. That property does not extend to the axis below it: the
            # ways of reaching the table are still enumerated here, a call on
            # the receiver and a subscript on it, and the boundary of that
            # enumeration is in this function's docstring.
            assert node.func.attr in READS_ONLY, (
                f"CLAIMS.{node.func.attr}() is not a read, so the table that "
                "runs is not the literal this audits"
            )
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, (ast.Store, ast.Del))
            and isinstance(node.value, ast.Name)
            and node.value.id == "CLAIMS"
        ):
            raise AssertionError(
                "CLAIMS is assigned into or deleted from after the literal"
            )
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id != "CLAIMS" for t in node.targets
        ):
            assert not (
                isinstance(node.value, ast.Name) and node.value.id == "CLAIMS"
            ), "CLAIMS is bound to a second name, which can be mutated out of sight"
    return [ast.literal_eval(key) for key in literal.keys if key is not None]


def judge(occurrence: Occurrence, entries, occurrences: int):
    """Which verdict covers this occurrence, or a sentence saying why none does.

    Returns `(index into entries, None)` or `(None, complaint)`.

    **`near` is required by the occurrence count, not by the verdict count**, and
    that distinction is the whole of the rule. The first version asked only
    whether a key had two verdicts, so a key with one verdict and no anchor
    covered every sentence in that file spelling that phrase, forever, whatever
    they were about. Because a key elides the number, **a new sentence on a new
    subject reusing an existing phrase is indistinguishable from the sentence the
    verdict was written for**: writing "Eight catalogues are asked concurrently"
    into `docs/legend.md` would have been judged as that file's table of national
    catalogues, silently, including on the day the fan out became nine.
    """
    if not entries:
        return None, (
            f"{occurrence.where()}\n"
            "  is a roster sized number beside a roster noun and CLAIMS does not "
            "say what it counts. Add a Counts, a NotTheRoster or a KnownStale for "
            f'("{occurrence.path}", "{occurrence.phrase}").'
        )
    if occurrences == 1 and len(entries) == 1 and entries[0].near is None:
        return 0, None
    without = [e for e in entries if e.near is None]
    if without:
        return None, (
            f"{occurrence.where()}\n"
            f'  ("{occurrence.path}", "{occurrence.phrase}") covers {occurrences} '
            f"occurrences with {len(entries)} verdicts, so every one of them needs "
            f"a `near` to say which sentence it judges. {len(without)} has none."
        )
    matched = [
        i for i, e in enumerate(entries)
        if e.near is not None and e.near in occurrence.paragraph
    ]
    if len(matched) == 1:
        return matched[0], None
    return None, (
        f"{occurrence.where()}\n"
        f"  {len(matched)} of {len(entries)} verdicts match this paragraph and "
        "exactly one must. Their anchors are "
        + ", ".join(repr(e.near) for e in entries)
        + "."
    )


def judgements():
    """The whole census resolved at once, as `(occurrence, key, index, complaint)`.

    **One pass, because three of the rules are about a verdict's relationship to
    every occurrence it could cover** rather than to the one in front of it: how
    many sentences share its key, whether any sentence at all reached it, and
    whether the anchor it carries actually told those sentences apart.
    Resolving one occurrence at a time cannot see any of the three.

    **The third arrived as a regression from the fix for the first.** Requiring
    `near` where a key covers several sentences made the anchor *exist*; nothing
    made it *discriminate*, so with two verdicts over three occurrences the
    pigeonhole does the rest and one anchor silently swallows a sentence written
    about something else. It was live in this file's own prose: the anchor
    `463.8 MB` was written for the module docstring's quotation and also took
    two lines of the `DATED_REGISTERS` comment, which quoted the same figure
    until that comment was rewritten on 2026-09-03.

    **The test is the block a claim starts in, not the words in it**, because
    two blocks carrying the same words are one string and two sentences.

    **Its own limit is worth knowing.** One
    verdict may cover several occurrences only when they sit in the same block,
    which is what a sentence naming two counts looks like. Where two genuinely
    different sentences share one comment block, this cannot separate them
    either, for the reason stated at `near`: a paragraph here is a block of
    lines. That is a smaller hole than the one it closes, and it is stated
    rather than left to be found.
    """
    grouped: dict[tuple[str, str], list[Occurrence]] = {}
    for occurrence in census():
        grouped.setdefault((occurrence.path, occurrence.phrase), []).append(occurrence)
    for key, occurrences in grouped.items():
        entries = CLAIMS.get(key, [])
        judged = [
            (occurrence, *judge(occurrence, entries, len(occurrences)))
            for occurrence in occurrences
        ]
        covered: dict[int, list[Occurrence]] = {}
        for occurrence, index, _ in judged:
            if index is not None:
                covered.setdefault(index, []).append(occurrence)
        for occurrence, index, complaint in judged:
            if complaint is None and index is not None:
                shared = covered[index]
                if len({o.block for o in shared}) > 1:
                    complaint = (
                        f"{occurrence.where()}\n"
                        f"  is judged by the verdict anchored on {entries[index].near!r}, "
                        f"which also covers {len(shared) - 1} other occurrence(s) in a "
                        "different paragraph: lines "
                        + ", ".join(str(o.line) for o in shared)
                        + ". An anchor has to tell them apart, not merely exist."
                    )
                    index = None
            yield occurrence, key, index, complaint


def verdicts():
    """Every occurrence that resolved, with the verdict object itself."""
    for occurrence, key, index, _complaint in judgements():
        if index is not None:
            yield occurrence, CLAIMS[key][index]


def _known_stale_now_fixed(pairs) -> list[str]:
    """Every `KnownStale` whose prose has started agreeing with its set, named.

    Split out of the test so the rule can be driven from a fixture. `CLAIMS`
    holds no `KnownStale` today, and a rule that only reads the live table
    stops being checked the moment the table empties.
    """
    fixed = []
    for occurrence, verdict in pairs:
        if not isinstance(verdict, KnownStale):
            continue
        if occurrence.value == CARDINALITIES[verdict.of]():
            fixed.append(
                f"{occurrence.where()}\n"
                f"  now agrees with {verdict.of}, so delete its KnownStale entry"
            )
    return fixed


def _occurrence_valued(value: int) -> Occurrence:
    """An `Occurrence` carrying one number, for driving a rule that has no live
    subject left in the tree."""
    return Occurrence(
        path="fixture.py",
        line=1,
        value=value,
        phrase="{n} catalogue",
        paragraph="a fixture",
        block=1,
    )


def orphans() -> list[str]:
    """Every verdict in `CLAIMS` that judged nothing in the tree, named.

    **The census in reverse, and the reason a sentence brought into the grammar
    stays in it.** Three counts here were stale *because* they were invisible:
    the number sat beside no roster noun, so nothing compared it with anything.
    Correcting them meant writing the noun in, and that is worth only as much
    as the rule stopping it being written back out. This is the rule. A
    reworded sentence leaves its verdict with nothing to judge, and a verdict
    with nothing to judge is named here.

    Split out of the test below so it can be driven with a stubbed census
    rather than only observed against the real one.
    """
    used = {(key, index) for _, key, index, _ in judgements() if index is not None}
    return sorted(
        f"{key[0]} {key[1]!r} entry[{i}] near={entry.near!r}"
        for key, entries in CLAIMS.items()
        for i, entry in enumerate(entries)
        if (key, i) not in used
    )


#: Every occurrence the census finds, and what each one counts.
#:
#: **Keyed on the file and the phrase with the number elided**, so no count is
#: written here and correcting a stale sentence needs no edit to this table.
#: **A key covering more than one sentence needs `near` on every verdict**, a
#: distinctive string from the claim's own paragraph, and that rule keys on the
#: occurrence count rather than the verdict count. One unanchored verdict is
#: fine for one sentence and wrong for two: the second inherits a judgement
#: written for the first, and since a key elides the number, a sentence on a
#: different subject reusing the phrase is indistinguishable from it.
CLAIMS: dict[tuple[str, str], list[Counts | NotTheRoster | KnownStale]] = {
    ("README.md", "{n} catalogues"): [Counts("LOOKUP_SOURCES")],
    ("backend/classifications.py", "{n} catalogues"): [
        NotTheRoster("the sources that build a Heading, which `_merge` concatenates")
    ],
    ("backend/fetch.py", "{n} catalogue"): [Counts("the whole roster")],
    ("backend/targets.py", "{n} catalogues"): [Counts("the whole roster")],
    ("backend/tests/test_house_rules.py", "{n} catalogue"): [
        Counts("the whole roster")
    ],
    ("backend/fetch.py", "{n} third party catalogues"): [Counts("the whole roster")],
    ("backend/fetch.py", "{n} sources"): [
        Counts("SEARCH_SOURCES", near="`metadata.search` asks"),
        Counts("the whole roster", near="compression is not requested"),
    ],
    ("backend/models.py", "{n} catalogues"): [
        NotTheRoster(
            "the retired figure, quoted verbatim and labelled retired so the "
            "sentence that was wrong stays readable beside the correction",
            near="now retired",
        )
    ],
    ("backend/models.py", "{n} sources"): [
        Counts("the whole roster", near="Driven rather than read"),
        Counts("the whole roster", near="per record figures came from a catalogue"),
    ],
    ("backend/metadata.py", "{n} catalogues"): [
        NotTheRoster("the sources that build a Heading, which `_merge` concatenates")
    ],
    # The **singular** phrase, and the three entries around it are all plural, so
    # this collides with none of them and needs no anchor. The sentence prices the
    # harder search's concurrency against what a whole fan out costs, so its eight
    # is a search roster count read off that comment's own arithmetic.
    ("backend/metadata.py", "{n} source"): [Counts("SEARCH_SOURCES")],
    ("backend/metadata.py", "{n} free sources"): [
        Counts("the free lookup sources", near="most deployments actually run"),
        NotTheRoster(
            "the free lookup sources on the day the eight query comparison ran",
            dated="2026-08-27",
            near="comparison",
        ),
    ],
    ("backend/metadata.py", "{n} sources"): [
        NotTheRoster(
            "the sources `_NOT_A_BOOK` refuses for, which is the roster minus the "
            "two ordinary web APIs and has no constant of its own to compare with",
            near="_NOT_A_BOOK",
        ),
        NotTheRoster(
            "the sources `_is_physical_book` is reached from, enumerated in the "
            "same sentence and with no constant of its own",
            near="_is_physical_book",
        ),
        Counts("SEARCH_SOURCES", near="wall clock"),
    ],
    ("backend/ratelimit.py", "{n} public catalogues"): [Counts("SEARCH_SOURCES")],
    # Both halves of one sentence in the enrichment route's docstring, which
    # FastAPI publishes as the endpoint's OpenAPI description. It said
    # "searches all seven" with the noun elided, so nothing here could see it
    # and the wrong number shipped in `frontend/openapi.json`.
    #
    # **The sentence counts the roster, and the first correction made it count
    # a new install instead.** That is a claim about a plan, and it was wrong
    # in both numbers: a keyless install asks six and seven, because Google
    # Books is not ready until its section is on and a key is in force. A
    # verdict names a **set**, so no verdict can pin a sentence about a plan,
    # and both would have passed here forever.
    ("backend/routers/books.py", "{n} lookup sources"): [Counts("LOOKUP_SOURCES")],
    ("backend/routers/books.py", "{n} search sources"): [Counts("SEARCH_SOURCES")],
    # The stored provider row, twice: what the default writes instead, and what
    # a populated one costs to parse. Both said "seven entries" of a row that
    # spells nine, and "entries" is not a roster noun.
    ("backend/settings_store.py", "{n} sources"): [
        Counts("DEFAULT_ORDER", near="absent means the defaults"),
        Counts("DEFAULT_ORDER", near="invalidated on write"),
    ],
    ("backend/sources.py", "{n} free sources"): [Counts("the free lookup sources")],
    ("backend/sources.py", "{n} sources"): [Counts("LOOKUP_SOURCES")],
    ("backend/tests/helpers.py", "{n} sources"): [Counts("lookup or search")],
    ("backend/tests/routers/test_books_google.py", "{n} sources"): [
        Counts("the whole roster")
    ],
    ("backend/tests/routers/test_books_search.py", "{n} sources"): [
        NotTheRoster("a quotation of a sentence that was wrong when it was written")
    ],
    ("backend/tests/test_authority.py", "{n} viaf source"): [
        NotTheRoster("VIAF's own source codes, which are not catalogues this app asks")
    ],
    ("backend/tests/test_fetch.py", "{n} catalogues"): [Counts("the whole roster")],
    ("backend/tests/test_fetch.py", "{n} sources"): [
        NotTheRoster(
            "the fan out the bound was written for before the OENB joined, in the "
            "sentence recording why this count is read from the tree",
            near="Derived from the tree rather than written down",
        ),
        Counts("SEARCH_SOURCES", near="asked now"),
        NotTheRoster(
            "the arithmetic at the previous roster size, quoted to show the drift "
            "this pair of tests exists to catch",
            near="4.79 MiB",
        ),
        NotTheRoster(
            "the count the assertion above used to hardcode",
            near="not written here",
        ),
        NotTheRoster(
            "the count that leaves the assertion above passing, which is why this "
            "test exists beside it",
            near="weaker",
        ),
    ],
    ("backend/tests/test_metadata.py", "{n} other sources"): [
        NotTheRoster(
            "the sources `_NOT_A_BOOK` refuses for besides the NKP, with no "
            "constant of its own; `metadata.py` counts the same set including it"
        )
    ],
    ("backend/tests/test_metadata.py", "{n} sources"): [
        Counts("SEARCH_SOURCES", near="asked at once"),
        Counts("the whole roster", near="deduplicated by what"),
    ],
    ("backend/tests/test_ratelimit.py", "{n} public catalogues"): [
        Counts("LOOKUP_SOURCES")
    ],
    ("backend/tests/test_roster_counts.py", "{n} sources"): [
        NotTheRoster(
            "an example phrase, in the file that states the rule",
            near="is not one number",
        ),
        NotTheRoster(
            "a quotation of the sentence named as the model in the line above",
            near="the shape it was taken at",
        ),
        NotTheRoster(
            "a fixture text, in the file that states the rule",
            near="queries at 50 records",
        ),
        NotTheRoster(
            "a fixture text, in the file that states the rule",
            near="stops_at_a_blank_line",
        ),
        NotTheRoster(
            "an example of two verdicts that pass while meaning different sets",
            near="reader will read it as the set",
        ),
        NotTheRoster(
            "an example of the claim a root file could carry and did not",
            near="repository root",
        ),
        NotTheRoster(
            "the fixture in the sentence stating that emphasis blinds the "
            "pattern, which is the one spelling of it the pattern does match",
            near="must begin with whitespace",
        ),
    ],
    ("backend/tests/test_roster_counts.py", "{n} catalogues"): [
        NotTheRoster(
            "the sentence a reader could add to `legend.md` and have misjudged, "
            "quoted in the rule that now refuses it",
            near="indistinguishable",
        ),
        NotTheRoster(
            "a fixture text, in the file that states the rule",
            near="fact about the past",
        ),
    ],
    ("backend/tests/test_roster_counts.py", "{n} third party catalogues"): [
        NotTheRoster("a fixture text, in the file that states the rule")
    ],
    ("backend/tests/test_z3950.py", "{n} sources"): [Counts("SEARCH_SOURCES")],
    ("backend/z3950.py", "{n} source"): [Counts("SEARCH_SOURCES")],
    ("backend/z3950.py", "{n} sources"): [Counts("SEARCH_SOURCES")],
    ("docs/api.md", "{n} catalogues"): [
        Counts("SEARCH_SOURCES", near="asked concurrently"),
        Counts("LOOKUP_SOURCES", near="two phases"),
    ],
    ("docs/api.md", "{n} free sources"): [Counts("the free lookup sources")],
    ("docs/api.md", "{n} sources"): [Counts("LOOKUP_SOURCES")],
    ("docs/data-model.md", "{n} catalogues"): [
        NotTheRoster("the sources that build a Heading, which `_merge` concatenates")
    ],
    # The register of decisions, brought into the census on 2026-09-03. Most of
    # these are historical by construction: this file records what was decided
    # and what was measured at the time, so a figure in it is a record and a
    # correction would falsify it. That is a `NotTheRoster` whose subject names
    # the moment, and not a `dated` annotation: a date beside a number separates
    # nothing here, which is measured in this module's docstring.
    #
    # **Three of these judge a live present tense claim and are still not
    # checked**, and that is worth saying rather than leaving to be noticed: the
    # XML parsed sources, the sources a shared refusal reaches besides the NKP,
    # and the sources that answer in a record schema. Each counts a real set
    # that `sources.py` does not name, so no `Counts` can bind to it and a
    # `NotTheRoster` is the correct verdict rather than an evasion. `LOOKUP_SOURCES`
    # is 7 today and so are two of the three, which is exactly the coincidence
    # `CARDINALITIES` warns about. The consequence is that "five of the seven",
    # corrected by hand in the pass that wrote these, is permanently unchecked
    # and a reader re-deriving it has to go back to `metadata.py`.
    ("docs/decisions.md", "{n} catalogue"): [
        NotTheRoster(
            "the catalogue sources whose responses are XML parsed, which is the "
            "roster minus the two ordinary web APIs and has no constant of its own"
        )
    ],
    ("docs/decisions.md", "{n} catalogues"): [
        NotTheRoster(
            "a quotation of the invented worst case the entry around it refutes",
            near="CATEGORIES_MAX",
        ),
        NotTheRoster(
            "the sentence a reader could add to `legend.md` and have misjudged, "
            "quoted in the rule that now refuses it",
            near="asked concurrently",
        ),
    ],
    ("docs/decisions.md", "{n} other sources"): [
        NotTheRoster(
            "the sources `_NOT_A_BOOK` refuses for besides the NKP, with no "
            "constant of its own; `metadata.py` counts the same set including it"
        )
    ],
    ("docs/decisions.md", "{n} source"): [
        NotTheRoster(
            "the source adapters at the time `catalogue.Record` replaced the two "
            "dict dialects, in the past tense"
        )
    ],
    ("docs/decisions.md", "{n} sources"): [
        NotTheRoster(
            "the search fan out on the day the decompression figure was taken; "
            "the sentence says it was asked at once when that was measured",
            near="a cap counted after decoding",
        ),
        NotTheRoster(
            "the sources the plaintext parser risk pre-dated, in the entry "
            "recording the item that added a seventh",
            near="_LOC_URL",
        ),
        Counts("SEARCH_SOURCES", near="whole fan out"),
        Counts("the whole roster", near="Driven rather than read"),
        Counts("the whole roster", near="per record figures came from a catalogue"),
        NotTheRoster(
            "an example phrase, in the entry that states the rule",
            near="is not one number",
        ),
        NotTheRoster(
            "a quotation of the sentence in `docs/security.md` named as the model",
            near="A date is not the exemption rule",
        ),
        NotTheRoster(
            "a quotation of this file's own stale sentence, in the paragraph "
            "that corrects it",
            near="found two errors",
        ),
        NotTheRoster(
            "a fixture text, in the entry that states the rule",
            near="50 records",
        ),
        NotTheRoster(
            "the sources that answer in a record schema, which is the roster "
            "minus the two ordinary web APIs and has no constant of its own",
            near="The list of languages is open",
        ),
    ],
    ("docs/legend.md", "{n} catalogues"): [
        NotTheRoster(
            "the national and union catalogues in the table above it, which is "
            "the roster minus the two ordinary web APIs and has no constant"
        )
    ],
    ("docs/legend.md", "{n} metadata sources"): [Counts("the whole roster")],
    ("docs/security.md", "{n} catalogue"): [Counts("the whole roster")],
    ("docs/security.md", "{n} public catalogues"): [Counts("SEARCH_SOURCES")],
    ("docs/security.md", "{n} third party catalogues"): [Counts("the whole roster")],
    ("docs/security.md", "{n} sources"): [
        NotTheRoster(
            "the search fan out on the day the decoded byte figure was taken; the "
            "sentence says so and gives today's count in the line after it"
        )
    ],
    ("frontend/src/pages/BookDetail/hooks.ts", "{n} catalogue"): [
        Counts("SEARCH_SOURCES")
    ],
    (
        "frontend/tests/pages/SettingsPage/LibrarySettingsPage/components"
        "/MarcImport.test.tsx",
        "{n} records this catalogue",
    ): [
        NotTheRoster("MARC records in an uploaded file", near="not the whole file"),
        NotTheRoster("MARC records in an uploaded file", near="user.click"),
    ],
}


class TestEveryRosterCountInTheTreeIsAccountedFor:
    """The census and the table, checked against each other in both directions."""

    def test_every_candidate_the_census_finds_carries_a_verdict(self):
        """The half an enumeration of sites cannot do.

        A sentence added anywhere in the scope is found whether or not its
        author knew this file existed, and it fails until somebody says what
        its number counts.
        """
        complaints = [c for _, _, _, c in judgements() if c is not None]
        assert not complaints, "\n".join(complaints)

    def test_the_census_reads_nothing_this_project_did_not_write(self):
        """The regression that turned `main` red on half its pushes.

        `UV_CACHE_DIR` is `.uv-cache` in the backend job, so CI has third party
        source under `backend/` that no developer has locally. The census walked
        it and reported prose in a syntax highlighter and a charset detector,
        which no verdict here could ever cover.

        **The rung this sits on is honest rather than flattering.** Locally this
        passes because the directory is not there, so it is vacuous on the
        machine where it is usually run and load bearing in the place that broke.
        What carries the property off this machine is
        `test_house_rules.TestTheSourceWalkSeesOnlyThisProject`, which drives the
        rule against constructed paths from both roots and cannot go vacuous.
        """
        vendored = [
            str(path.relative_to(REPO))
            for path in candidates()
            if _is_vendored(path, REPO)
        ]

        assert not vendored, f"the census reached code this project did not write: {vendored}"

    def test_every_verdict_still_has_a_claim_to_judge(self):
        """The other direction, without which the table rots the same way.

        A sentence reworded or deleted leaves a verdict describing nothing, and
        a table of verdicts about sentences that are gone is exactly the stale
        list this whole file is about, one level up.
        """
        found = orphans()
        assert not found, (
            "these verdicts judge nothing in the tree, so the sentence each was "
            "written for has been reworded, deleted, or was never matched by the "
            "anchor it carries:\n  " + "\n  ".join(found)
        )

    #: A well formed table, and every way found so far of changing what runs
    #: without changing what `claims_keys_in` reads.
    TABLE = "CLAIMS: dict = {\n    ('a','x'): [1],\n    ('b','y'): [2],\n}\n"
    REFUSED = {
        "a duplicate key": "CLAIMS: dict = {('a','x'): [1], ('a','x'): [2]}\n",
        "a second binding": TABLE + "CLAIMS: dict = {('c','z'): [3]}\n",
        "an augmented assignment": TABLE + "CLAIMS |= {('a','x'): ['S']}\n",
        "a walrus": TABLE + "if (CLAIMS := {}): pass\n",
        "a for target": TABLE + "for CLAIMS in []: pass\n",
        "a tuple unpack": TABLE + "CLAIMS, o = {}, 1\n",
        "a with block": TABLE + "import contextlib\nwith contextlib.nullcontext() as CLAIMS: pass\n",
        "an import": TABLE + "import os as CLAIMS\n",
        "an except handler": TABLE + "try:\n    pass\nexcept Exception as CLAIMS:\n    pass\n",
        "a match case": TABLE + "match {'k': 1}:\n    case dict() as CLAIMS:\n        pass\n",
        "a match mapping rest": TABLE + "match {'k': 1}:\n    case {**CLAIMS}:\n        pass\n",
        "a global declaration": TABLE + "def f():\n    global CLAIMS\n    CLAIMS = {}\n",
        "a def": TABLE + "def CLAIMS(): pass\n",
        "a class": TABLE + "class CLAIMS: pass\n",
        "dict()": "CLAIMS: dict = dict([(('a','x'),[1])])\n",
        "a | merge": "CLAIMS: dict = {('a','x'): [1]} | {('a','x'): [2]}\n",
        "a ** spread": "B = {}\nCLAIMS: dict = {**B, ('a','x'): [2]}\n",
        "update()": TABLE + "CLAIMS.update({})\n",
        "a subscript": TABLE + "CLAIMS[('a','x')] = ['S']\n",
        "a delete": TABLE + "del CLAIMS[('a','x')]\n",
        "a second name": TABLE + "A = CLAIMS\nA[('c','z')] = [3]\n",
    }
    ALLOWED = {
        "the table alone": TABLE,
        "a get": TABLE + "v = CLAIMS.get(('a','x'))\n",
        "an items": TABLE + "list(CLAIMS.items())\n",
        # Another scope entirely, so neither can reach this table. Here because
        # a binding sweep that refused them would be wide rather than right.
        "a parameter of that name": TABLE + "def f(CLAIMS): return CLAIMS\n",
        "a local of that name": TABLE + "def f():\n    CLAIMS = {}\n    return CLAIMS\n",
    }

    @pytest.mark.parametrize("shape", sorted(REFUSED))
    def test_a_table_it_cannot_audit_is_refused(self, shape):
        """Driven, one construction at a time, rather than read.

        **Eleven of these are carried by the binding count**, and that count
        matches no node type at all: it sweeps a `Store` on a `Name` and the
        fields carrying a bound name as a string. `AugAssign` appears in a
        comment about why the list of forms was abandoned, and `FunctionDef`,
        `AsyncFunctionDef`, `ClassDef` and `Lambda` in the scope boundary
        deciding which nodes are looked at, none in a rule that detects a
        binding. The twelfth refusal that is not in that eleven is
        `global CLAIMS`, which is caught by its own check because a declaration
        is not a binding and so does not move the count.

        **That sentence has been wrong twice and is now recomputed by
        `test_the_docstring_states_what_the_binding_count_carries`.** It said six
        and then seven while the answer was four, both times counting forms the
        code named as arms, in the docstring of the test that demonstrates the
        mechanism, in a ticket about stated counts that nothing recomputes.
        """
        with pytest.raises(AssertionError):
            keys = claims_keys_in(self.REFUSED[shape])
            assert len(keys) == len(set(keys)), "duplicate key"

    @pytest.mark.parametrize("shape", sorted(ALLOWED))
    def test_a_table_it_can_audit_is_allowed(self, shape):
        """The other half of the diagonal: a rule that refuses everything is not
        a rule. Reads stay reads."""
        assert len(claims_keys_in(self.ALLOWED[shape])) == 2

    def test_no_key_is_written_into_the_table_twice(self):
        """The audit runs against the source, and against the table that runs.

        `len(CLAIMS)` is compared with the key count because reading the literal
        proves nothing if something adds to the table afterwards. The
        constructions are driven one at a time by the two tests above rather
        than listed here, which is what stops this paragraph going stale: it
        used to name "no annotation" among those refused, and an unannotated
        table is not refused at all, only caught when it also carries a
        duplicate.
        """
        keys = claims_keys_in((BACKEND / "tests" / "test_roster_counts.py").read_text())
        assert keys, "CLAIMS holds no keys"
        assert len(keys) == len(set(keys)), (
            "these keys are written into CLAIMS more than once, and every entry "
            "but the last was discarded: "
            + str(sorted(k for k in set(keys) if keys.count(k) > 1))
        )
        assert len(CLAIMS) == len(keys), (
            f"the literal holds {len(keys)} keys and the table that runs holds "
            f"{len(CLAIMS)}, so something changes it after it is written"
        )

    def test_a_counted_claim_states_the_number_the_tree_has(self):
        """The precedent guard's property, at every site that carries a claim.

        `test_fetch.py::test_the_constant_states_the_source_count_the_tree_has`
        does exactly this for one sentence. The number is never written here:
        the verdict names a set and the size is read off `sources.py`.
        """
        wrong = []
        for occurrence, verdict in verdicts():
            if not isinstance(verdict, Counts):
                continue
            expected = CARDINALITIES[verdict.of]()
            if occurrence.value != expected:
                wrong.append(
                    f"{occurrence.where()}\n"
                    f"  says {occurrence.value}; {verdict.of} is {expected}"
                )
        assert not wrong, "\n".join(wrong)

    def test_a_known_stale_claim_is_deleted_once_it_is_fixed(self):
        """Strict, so the debt register cannot go quiet.

        A `KnownStale` asserts the count is **still** wrong. Correcting the
        prose fails here until the entry goes, which is the only arrangement
        where a list of known problems cannot become a second stale list.

        **`CLAIMS` holds no `KnownStale` today**, which makes this arm vacuous
        on the live tree: the loop skips every verdict and passes. That is the
        shape this repository calls a guard going quiet with nothing failing,
        so the rule is driven from a fixture below as well as from the tree.
        """
        assert not _known_stale_now_fixed(verdicts()), "\n".join(
            _known_stale_now_fixed(verdicts())
        )

    def test_the_rule_reports_a_known_stale_that_has_started_agreeing(self):
        """Anti vacuity. Built rather than found, because the live table is
        empty and an empty table cannot show that the arm still works."""
        agreeing = _occurrence_valued(CARDINALITIES["SEARCH_SOURCES"]())
        reported = _known_stale_now_fixed(
            [(agreeing, KnownStale("SEARCH_SOURCES", because="a fixture"))]
        )
        assert len(reported) == 1, reported
        assert "delete its KnownStale entry" in reported[0]

    def test_the_rule_leaves_a_known_stale_that_is_still_wrong(self):
        """The other edge, so the fixture above is not merely a rule that
        reports everything."""
        still_wrong = _occurrence_valued(CARDINALITIES["SEARCH_SOURCES"]() + 1)
        assert (
            _known_stale_now_fixed(
                [(still_wrong, KnownStale("SEARCH_SOURCES", because="a fixture"))]
            )
            == []
        )

    def test_a_dated_exemption_names_a_date_that_is_really_beside_it(self):
        """`dated` is verified where it is given, and it is never the exemption.

        Measured over this census, 27 occurrences carry a date, `measured` or
        an issue number in the same paragraph, and that 27 holds both a correct
        exemption and a stale claim, so a date separates nothing on its own.
        What it does buy is that a verdict claiming to rest on one cannot rest
        on a date the prose does not carry.
        """
        missing = []
        for occurrence, verdict in verdicts():
            if not isinstance(verdict, NotTheRoster) or verdict.dated is None:
                continue
            if verdict.dated not in occurrence.paragraph:
                missing.append(
                    f"{occurrence.where()}\n"
                    f"  is exempted as measured on {verdict.dated} and that date "
                    "is not in its paragraph"
                )
        assert not missing, "\n".join(missing)


class TestTheCensusBoundIsDerivedAndNotChosen:
    def test_every_roster_set_in_sources_is_accounted_for(self):
        """A set added to `sources.py` cannot quietly stay outside the bound.

        Found by reflection rather than listed, because a list here would be
        the second thing to update when a set is added and the prose this file
        guards would be the first.
        """
        found = roster_sets()
        assert found, "reflection found no roster set at all in `sources.py`"
        unaccounted = sorted(
            name
            for name in found
            if name not in CARDINALITIES and name not in NOT_A_ROSTER_COUNT
        )
        assert not unaccounted, (
            f"{unaccounted} are collections of CatalogueSource in `sources.py` "
            "that are neither a cardinality a claim may bind to nor named in "
            "NOT_A_ROSTER_COUNT"
        )

    def test_nothing_is_both_a_cardinality_and_not_a_count(self):
        overlap = sorted(set(CARDINALITIES) & set(NOT_A_ROSTER_COUNT))
        assert not overlap, overlap

    def test_the_bound_is_read_from_the_tree(self):
        """Delete the reflection or the constants and this goes red.

        The bound is the set of sizes the named cardinalities have, so it moves
        when they do. A literal range is a range somebody narrows until a
        failure goes quiet.
        """
        assert live_cardinalities() == {
            factory() for factory in CARDINALITIES.values()
        }
        assert len(sources.SEARCH_SOURCES) in live_cardinalities()
        assert len(CatalogueSource) in live_cardinalities()


class TestTheCensusSeesWhatItClaimsTo:
    """Attacked rather than read. Every fixture here is a shape measured in the
    tree, and each one broke a draft of the scanner."""

    def test_it_reads_a_claim_that_wraps_across_a_line(self):
        """Prose wraps at 88 columns, so this is ordinary rather than exotic.

        A line by line scan missed four claims in this tree, one of them the
        only one in its file and one of them the stale count in `frontend/`.
        """
        found = list(scan("t.py", "#: Measured live, all nine\n#: sources answer.\n"))
        assert [(o.value, o.phrase) for o in found] == [(9, "{n} sources")]

    def test_it_reports_the_line_the_number_is_on(self):
        """The offsets survive flattening, which is why the wrap is padded
        rather than removed."""
        text = "one\ntwo\n#: all nine\n#: sources\n"
        assert [o.line for o in scan("t.py", text)] == [3]

    def test_a_number_out_of_scope_does_not_swallow_a_claim_behind_it(self):
        """Why the pattern is a lookahead, and the reason is not the obvious one.

        The obvious reason is two claims in one sentence, and that needs no
        lookahead at all: a consuming scan walks from the end of the first match
        and finds the second perfectly well. That is what the fixture here used
        to assert, which is why deleting the lookahead left it green.

        **The real case is a number the census does not want, matching across
        one it does.** The value filter runs after the match, so a consuming
        pattern matches on the 50 below, is then discarded for being no roster
        size, and takes the claim inside its own span with it. `re` does not go
        back over ground a completed match has covered.

        Measured over the whole scope, one file differs between the two
        engines, and it is `test_fetch.py`, where what a consuming scan loses is
        the live statement of the search fan out.
        """
        text = "queries at 50 records. Eight sources are asked now.\n"
        assert [o.value for o in scan("t.py", text)] == [8]

    def test_it_reads_a_digit(self):
        """Every stale site in #111 was spelled. That is a fact about the past."""
        assert [o.value for o in scan("t.py", "8 catalogues answer.\n")] == [8]

    def test_it_ignores_a_number_no_roster_set_has(self):
        """The bound is what keeps 287 ordinary English sentences out.

        Counted on 2026-09-03 as the `_CLAIM` matches over `scope()` whose value
        is not a live cardinality, which is the instrument named in this
        module's docstring beside the other snapshots."""
        assert not list(scan("t.py", "three sources answer.\n"))

    def test_it_reads_across_two_intervening_words(self):
        assert [o.phrase for o in scan("t.py", "nine third party catalogues.\n")] == [
            "{n} third party catalogues"
        ]

    def test_it_stops_at_three_intervening_words(self):
        """Stated because it is the edge the grammar was drawn at, not because
        three words is a principle."""
        assert not list(scan("t.py", "nine of the third party catalogues.\n"))

    def test_a_paragraph_stops_at_a_blank_line(self):
        """`near` and `dated` are claims about the sentence's surroundings. A
        paragraph that ran to the end of the file would make both vacuous."""
        text = "#: eight sources here.\n#:\n#: 2026-08-27 down here.\n"
        assert "2026-08-27" not in next(iter(scan("t.py", text))).paragraph

    def test_two_verdicts_for_one_phrase_need_an_anchor_on_both(self):
        """The failure a bare elided phrase would hide: `backend/fetch.py`
        spells `{n} sources` for the search fan out and for the whole roster."""
        occurrence = Occurrence("f.py", 1, 8, "{n} sources", "anything", 1)
        index, complaint = judge(
            occurrence, [Counts("SEARCH_SOURCES"), Counts("x")], occurrences=1
        )
        assert index is None and "needs a `near`" in complaint

    def test_one_verdict_covering_two_sentences_needs_an_anchor_too(self):
        """**The rule is the occurrence count, not the verdict count**, and this
        is the arm that says so.

        One verdict and no anchor is fine for one sentence and wrong for two:
        the second inherits a judgement written for the first, and because a key
        elides the number, a sentence on a wholly different subject reusing the
        phrase is indistinguishable from it.
        """
        occurrence = Occurrence("f.py", 1, 8, "{n} catalogues", "anything", 1)
        alone = judge(occurrence, [NotTheRoster("the table above")], occurrences=1)
        assert alone == (0, None)
        index, complaint = judge(
            occurrence, [NotTheRoster("the table above")], occurrences=2
        )
        assert index is None and "needs a `near`" in complaint
        assert "covers 2 occurrences" in complaint

    def test_an_anchor_has_to_tell_two_sentences_apart_not_merely_exist(self, monkeypatch):
        """The regression the fix for the one above introduced.

        Requiring `near` where a key covers several sentences made the anchor
        exist and never made it discriminate. With two verdicts over three
        occurrences the pigeonhole does the rest: one anchor covers two
        sentences and, under the first version of this rule, nothing complained.
        It was live in this file's own prose.

        **Blocks, not paragraph text.** The last two fixtures carry identical
        words in different blocks, which is one string and two sentences, and
        comparing the words would call them the same paragraph.
        """
        entries = [
            Counts("SEARCH_SOURCES", near="alpha"),
            Counts("LOOKUP_SOURCES", near="beta"),
        ]
        rows = [
            Occurrence("f.py", 1, 8, "{n} sources", "alpha here", 1),
            Occurrence("f.py", 5, 8, "{n} sources", "alpha again", 5),
            Occurrence("f.py", 9, 7, "{n} sources", "beta here", 9),
        ]
        monkeypatch.setitem(CLAIMS, ("f.py", "{n} sources"), entries)
        monkeypatch.setattr(
            "tests.test_roster_counts.census", lambda: iter(rows)
        )
        judged = {o.line: (i, c) for o, _, i, c in judgements()}
        assert judged[9][0] == 1, "the discriminated one still resolves"
        for line in (1, 5):
            index, complaint = judged[line]
            assert index is None, f"line {line} was swallowed silently"
            assert "not merely exist" in complaint

        same_words = [
            Occurrence("f.py", 1, 8, "{n} sources", "alpha here", 1),
            Occurrence("f.py", 40, 8, "{n} sources", "alpha here", 40),
        ]
        monkeypatch.setattr(
            "tests.test_roster_counts.census", lambda: iter(same_words)
        )
        assert all(i is None for _, _, i, _ in judgements()), (
            "identical words in two blocks are two sentences, not one paragraph"
        )

    def test_a_sentence_reworded_out_of_the_grammar_orphans_its_verdict(
        self, monkeypatch
    ):
        """What holds a count that was corrected by bringing it into the grammar.

        Three counts here were stale because the census could not see them, and
        they were fixed by writing the roster noun in rather than by widening
        the census. That trade is sound only if the noun cannot quietly go out
        again, and this is what stops it.

        **Per entry, not per key, and the first draft of this test could not
        tell the two apart.** It stubbed the census empty, under which every
        verdict in the table is an orphan, so a rule keying `used` on the file
        and phrase alone passed it. The live case is exactly the one that
        misses: `settings_store.py` carries two sentences under one key, and
        rewording one of them has to name that one. Synthetic sentences, so an
        edit to a real file cannot make this vacuous.
        """
        # The premise. The census reads a number beside a roster noun, so the
        # reworded sentence yields nothing and there is an orphan to find.
        assert not list(
            scan("f.py", "# An empty object rather than the nine entries.\n")
        )

        key = ("f.py", "{n} sources")
        monkeypatch.setitem(
            CLAIMS,
            key,
            [
                Counts("DEFAULT_ORDER", near="alpha"),
                Counts("DEFAULT_ORDER", near="beta"),
            ],
        )
        both = [
            Occurrence("f.py", 1, 9, "{n} sources", "alpha here", 1),
            Occurrence("f.py", 5, 9, "{n} sources", "beta here", 5),
        ]
        monkeypatch.setattr("tests.test_roster_counts.census", lambda: iter(both))
        assert not [o for o in orphans() if o.startswith("f.py")]

        # The second sentence reworded out. The first still resolves, so a rule
        # that asked only whether the key was reached would report nothing.
        monkeypatch.setattr(
            "tests.test_roster_counts.census", lambda: iter(both[:1])
        )
        named = [o for o in orphans() if o.startswith("f.py")]
        assert len(named) == 1 and "entry[1]" in named[0], named

    def test_an_anchor_that_matches_nothing_is_a_failure_not_a_default(self):
        occurrence = Occurrence("f.py", 1, 8, "{n} sources", "nothing here", 1)
        index, complaint = judge(
            occurrence,
            [Counts("SEARCH_SOURCES", near="alpha"), Counts("LOOKUP_SOURCES", near="beta")],
            occurrences=1,
        )
        assert index is None and "exactly one must" in complaint


class TestThisFileCountsItself:
    """The table's subject includes the table, which is how the dash table in
    `CLAUDE.md` was wrong four times, once in the act of being corrected."""

    def test_the_docstring_states_both_counts_of_the_cardinality_table(self):
        """**Names and distinct sizes are two numbers and the file needs both.**

        Six names over four sizes, because three of the six are 9. The prose
        said "six live cardinalities" and was checked against `len(CARDINALITIES)`,
        which is the name count, while `live_cardinalities()` two hundred lines
        below uses the same word for the size count. The test passed and the
        sentence was ambiguous, which is the narrower half of the same defect
        this file exists to catch.
        """
        named = re.search(r"are \*\*(\w+)\*\* named sets", _DOC or "")
        sizes = re.search(r"only \*\*(\w+)\*\* distinct sizes", _DOC or "")
        assert named is not None, "the docstring no longer states the name count"
        assert sizes is not None, "the docstring no longer states the size count"
        assert SPELLED.get(named.group(1).lower()) == len(CARDINALITIES), (
            f"the docstring says {named.group(1)} named sets; CARDINALITIES holds "
            f"{len(CARDINALITIES)}"
        )
        assert SPELLED.get(sizes.group(1).lower()) == len(live_cardinalities()), (
            f"the docstring says {sizes.group(1)} distinct sizes; there are "
            f"{len(live_cardinalities())}"
        )

    def test_the_docstring_states_what_the_binding_count_carries(self):
        """The third stated number in this file, and the one that was wrong twice.

        **Recomputed by driving the mutation, not by reading the code.** The
        binding count is neutered in a copy of this module and the constructions
        are re-driven: whatever stops being refused is what that assertion holds
        up. Reading the arms instead is how the figure came out six and then
        seven against a real four, because three of the forms counted were named
        in the source and were never carried by the count at all.
        """
        module = BACKEND / "tests" / "test_roster_counts.py"
        source = module.read_text()
        anchor = "    assert bindings == 1, ("
        # **Bounded, and the count asserted.** The anchor appears twice: the real
        # assertion, and this test's own copy of it as a string. An unbounded
        # `replace` rewrites both, which is harmless only because the mutant's
        # copy of this test never runs, and is the anchor class that once
        # duplicated 345 lines in this repository.
        assert source.count(anchor) == 2, (
            f"the mutation anchor appears {source.count(anchor)} times, not the "
            "real assertion plus this test's own copy of it"
        )
        mutant = source.replace(anchor, "    assert bindings >= 1, (", 1)
        assert mutant != source, "the binding assertion has been reworded"
        # The count above is a pre-flight check and weakening it changes nothing
        # observable, so it is pinned from the other side: exactly one of the two
        # survives a bounded replace, and none survives an unbounded one.
        assert mutant.count(anchor) == 1, (
            "the replace was not bounded, so it rewrote this test's own copy of "
            "the anchor as well as the assertion under test"
        )
        namespace: dict = {"__name__": "roster_mutant", "__file__": str(module)}
        exec(compile(mutant, "<mutant>", "exec"), namespace)
        neutered = namespace["claims_keys_in"]
        cases = namespace["TestEveryRosterCountInTheTreeIsAccountedFor"]

        assert all(len(neutered(c)) == 2 for c in cases.ALLOWED.values()), (
            "the mutation broke something other than the binding count, so the "
            "count below would be measuring the wrong thing"
        )
        released = 0
        for construction in cases.REFUSED.values():
            try:
                keys = neutered(construction)
            except AssertionError:
                continue
            if len(keys) == len(set(keys)):
                released += 1

        doc = (
            TestEveryRosterCountInTheTreeIsAccountedFor
            .test_a_table_it_cannot_audit_is_refused.__doc__
            or ""
        )
        stated = re.search(r"\*\*(\w+) of these are carried by the binding count", doc)
        assert stated is not None, "that docstring no longer states the count"
        assert SPELLED.get(stated.group(1).lower()) == released, (
            f"the docstring says {stated.group(1)}; neutering the binding count "
            f"releases {released} of {len(cases.REFUSED)}"
        )

    def test_the_docstring_states_how_many_occurrences_are_not_a_roster_count(self):
        """Recomputed rather than reread, and **counting what the sentence says**.

        It counted `NotTheRoster` and `KnownStale` together while the prose said
        "count something that is not the roster". A `KnownStale` **is** a roster
        count: a wrong one nobody here could correct, and a bare scan flagging it
        would be right. So the instrument was answering a wider question than the
        claim, the two disagreed by one, and the prose was edited to match the
        instrument rather than the instrument corrected to match the prose. The
        unit was wrong, not the range.
        """
        stated = re.search(r"\*\*(\d+)\*\* of its occurrences count something", _DOC or "")
        assert stated is not None, "the docstring no longer states the count"
        counted = sum(1 for _, v in verdicts() if isinstance(v, NotTheRoster))
        assert int(stated.group(1)) == counted
        repeated = re.findall(r"fails (\d+) times on its first run", _DOC or "")
        assert repeated == [str(counted)], (
            "the same sentence carries this number twice and only the first was "
            f"recomputed; the second reads {repeated}"
        )


def test_a_file_that_declares_itself_internal_is_out_of_scope():
    """Pinned without naming one, because their names are stripped paths.

    **Over the whole candidate set, not the root markdown corner of it**, which
    was the first version and pinned two of the six. Whichever files carry the
    declaration, none may be in scope: they are unpublished, so a count in one
    is unpublished too, and one of them is deleted when the wave that wrote it
    ends.
    """
    declared = [p for p in candidates() if declares_itself_internal(p)]
    assert declared, (
        "nothing in the candidate set declares itself internal any more, so this "
        "rule now guards nothing and the reason in `_INTERNAL` is stale"
    )
    assert not [p for p in declared if p in set(scope())]


#: The exclusions spelled out a second time, so widening one has to be written
#: twice.
#:
#: **A literal rather than `DATED_REGISTERS` itself**, which is the whole value
#: of the test below: deriving it would make deleting an entry silently delete
#: its pin too, and the pin exists so that a reader widening the scope has to
#: read the reason first.
PINNED_OUT_OF_SCOPE = ("CHANGELOG.md",)


@pytest.mark.parametrize("path", PINNED_OUT_OF_SCOPE)
def test_a_dated_register_is_out_of_scope(path):
    """Pinned because the exclusion is a judgement and a reader should see it
    fail if somebody widens it without reading `DATED_REGISTERS`' reason."""
    assert (REPO / path).exists(), f"{path} moved, so the exclusion is now silent"
    assert not any(str(p).endswith(path) for p in scope())


def test_every_excluded_register_is_pinned_above():
    """The other direction, which the literal alone does not give.

    A register added to `DATED_REGISTERS` and not to `PINNED_OUT_OF_SCOPE` would
    be excluded with nothing asserting it, so the pin would cover whatever
    somebody happened to write down first.
    """
    unpinned = sorted(set(DATED_REGISTERS) - set(PINNED_OUT_OF_SCOPE))
    assert not unpinned, (
        f"{unpinned} are excluded by DATED_REGISTERS and pinned by nothing"
    )


def test_the_register_states_the_partition_the_census_gives_it():
    """`docs/decisions.md` counts its own candidates, so this recomputes them.

    **That register is inside its own subject now**, the same way this module's
    docstring is, and the paragraph this reads was written in the commit that
    deleted three other figures from that file for going stale unrecounted. A
    fourth left uncounted in the same edit is the shape this repository keeps
    paying for.

    **The partition is asserted to sum**, which is the half a pair of equalities
    does not give: a `KnownStale` appearing in that file would make the total
    right and leave the sentence naming no verdict kind for it.
    """
    text = (REPO / "docs" / "decisions.md").read_text(encoding="utf-8")
    stated = re.search(
        r"census raises (\d+) candidates in it\. \*\*(\d+)\*\* are live claims "
        r"the guard now checks against `sources\.py`; \*\*(\d+)\*\* are not",
        re.sub(r"\s+", " ", text),
    )
    assert stated is not None, (
        "docs/decisions.md no longer states the partition this recomputes, so "
        "either the sentence was reworded or the section was deleted"
    )
    total, counted, not_counted = (int(g) for g in stated.groups())
    rows = [verdict for occurrence, verdict in verdicts()
            if occurrence.path == "docs/decisions.md"]
    # **The total first, then the sum.** A wrong total also breaks the sum, so
    # checking the sum first diagnoses a stale number as a new verdict kind,
    # which sends the next reader looking for a `KnownStale` that is not there.
    assert total == len(rows), (
        f"the sentence says the census raises {total} candidates there; it raises "
        f"{len(rows)}"
    )
    assert counted + not_counted == total, (
        f"the sentence says {counted} and {not_counted} of {total}, which is not "
        "a partition, so a verdict kind it names nothing for has appeared"
    )
    assert counted == sum(1 for v in rows if isinstance(v, Counts)), (
        f"the sentence says {counted} are live claims; "
        f"{sum(1 for v in rows if isinstance(v, Counts))} are"
    )
    assert not_counted == sum(1 for v in rows if isinstance(v, NotTheRoster)), (
        f"the sentence says {not_counted} are not; "
        f"{sum(1 for v in rows if isinstance(v, NotTheRoster))} are"
    )


def test_the_register_of_decisions_is_read():
    """The exclusion this file used to carry, pinned from the other side.

    `docs/decisions.md` was out of scope until 2026-09-03 and the reason is
    written out at `DATED_REGISTERS`. Re-excluding it would drop a verdict pass
    over a ten thousand line register and every failure it holds up, and would
    do it by deleting one string. This is what goes red instead.
    """
    read = [p for p in scope() if str(p).endswith("docs/decisions.md")]
    assert read, "docs/decisions.md is out of scope again; see DATED_REGISTERS"
    judged = [o for o, _ in verdicts() if o.path == "docs/decisions.md"]
    assert judged, "docs/decisions.md is in scope and no verdict judges anything in it"
