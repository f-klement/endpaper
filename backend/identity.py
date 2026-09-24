"""What makes two books the same book.

**Every rule here is two things welded together, and separating them is the
subject of this module**: a *fold*, which is how text becomes comparable, and a
*predicate*, which is how many fields take part.

**Two folds over one idea, and they differ in three places on purpose.**
`fold_title` and `fold_credit`. Both fold case and collapse spacing, and neither
knows which caller is asking. Where they part:

| | title | credit |
|---|---|---|
| punctuation | deleted, closing a gap | becomes a space, opening one |
| accents | composed and kept | erased |
| a leading article | removed | kept, because `Das Gupta` is a surname |

Each difference is a decision and each carries an arm. The reason for the credit
column is `authors.py`'s, which owns what folds automatically.

**Three predicates, and each is a decision about what a wrong answer costs.**

`reading_history_title`  a title normalised but not folded. The worst case is
                         everything a matched Book takes landing on the wrong
                         one: not only a reading status but the gaps
                         `importing._fill_gaps` and `_fill_opds_gaps` fill, the
                         tags, the review, and an ownership flag. Naming the
                         status alone understates it, and `Shelf.seen_by`
                         admits another member's Book that is not private, so
                         the wrong one need not be the importer's own.
`work_key`               title and first credit, folded. The worst case is two
                         different books merged into one catalogue entry, which
                         a cataloguer discovers months later with no record of
                         what was lost.
`printing_key`           a work and its year. The worst case is five printings
                         of one book shown as one row, which is the answer the
                         edition picker exists to give.

**The predicates do not collapse into each other and the fold is why they
look as though they should.** A single predicate cannot serve all three: at the
two import sites and the picker a looser answer is the dangerous one, and at the
preview that tells a member what an upload would skip a **stricter** answer
raises the count of records it reports as refused, which is an already accepted
disclosure whose size is not a free parameter. No one direction is safe
everywhere, so the direction is chosen once per site and stated there.

**`reading_history_title` takes the half of the fold that cannot merge two
books and refuses the half that can.** It is the outlier and it stays one, for
a reason stated here rather than pointed at.

Case, composition and spacing say nothing about which book this is under any
spelling, so it takes those. **Interior punctuation and a leading article do
say something.** Two titles differing only there are usually one book, but
*which* book is what a credit decides, and this predicate has no credit to
decide it with, so it keeps both. That asymmetry is why one predicate can want
half a fold and not the other half.

**What separates the two halves is where the mark sits, not what it is.** A
mark at the edge of a title is one a catalogue put there; a mark inside it is
one somebody meant. `_EDGE_MARKS` holds the first set and says what it was
measured against.

All of it matters at this predicate's sites more than elsewhere, because an
OPDS feed supplies the title from outside the household and the match it wins
writes without anybody pressing anything.

**Text in, text out.** Nothing here takes a session, a Book or a record, so no
question of who may see what can be asked here, let alone answered wrongly.
Every caller bounds its values before calling: matching on an unbounded value
while storing a bounded one means the key a duplicate is looked up by is not the
key that was stored.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

import authors

#: Words a **title** may start with that say nothing about which book it is.
#:
#: Not applied to a credit. `Das Gupta` and `Die Ost` are surnames, and folding
#: the first word off one collides two different people under one key.
_ARTICLES: Final = ("the ", "a ", "an ", "der ", "die ", "das ", "ein ", "eine ")

_PUNCTUATION = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WHITESPACE = re.compile(r"\s+")

#: Marks a catalogue writes at the **edge** of a title without meaning them.
#:
#: MARC 245 carries ISBD punctuation by convention, so `Ulysses :` is an
#: ordinary spelling of `Ulysses` rather than an odd one, and square brackets
#: are how a cataloguer marks data supplied rather than transcribed.
#:
#: **An enumeration, and it is a residue rather than a taste.** ISBD gives a
#: meaning at a title's edge to eight characters: `: / ; . ,` and `[ ]`, which
#: are **seven of these**, plus `=` for a parallel title, which is not. `=` is
#: **refused**, because `C+` against `C-` is one of the titles whose punctuation
#: is what the title is about and a rule admitting one of that family admits the
#: rest. `+` is refused on the same measurement, and is not in the eight at all:
#: it is ISBD punctuation elsewhere, before accompanying material in the physical
#: description area, so the standard never offers it at a title's edge.
#:
#: **Round parentheses are the other two members, and the standard does not
#: supply them.** ISBD prescribes square brackets for data supplied from outside
#: the source, and uses parentheses elsewhere, for a series and for
#: qualifications. They are here on a measured case alone, `(Dubliners)` against
#: `Dubliners`.
#:
#: Seven from the standard's title edge, one refused from it, two added by
#: measurement: that is the nine. **The scoring is this set's falsifier rather
#: than its author**, and calling the set a subset of a standard, as an earlier
#: version of this comment did, would license a tenth character on the standard's
#: authority alone. The one it would admit first is `=`, which the measurement
#: refused.
#:
#: **No counts here.** The figures written at this site had already drifted
#: against the arm they described. `C++`, `C#`, `C`, `C+`, `C-`, `B#` and their
#: interior case are the family that makes a wider rule wrong, and
#: `test_punctuation_a_title_is_about_is_not_stripped` is where they are
#: enforced rather than described;
#: `test_a_catalogue_spelling_reaches_the_title_it_spells` is the other half.
#:
#: **What a wider rule costs is everything a matched Book takes**, which this
#: module's own docstring lists, at a site that takes its titles from outside
#: the household and writes with nobody present. That is why the measurement is
#: against harmful merges rather than against how many spellings a rule tidies.
#:
#: **Both edges carry a case this gets wrong, so the two are not asymmetric.**
#: `.hack` keys as `hack` at the leading edge, and `V.` keys as `V` at the
#: trailing one, where a title ending in an initial is a real book and not an
#: ISBD artefact. Neither case discriminates between this subset and the ISBD
#: marks alone, which merge both identically, so neither is an argument about
#: brackets. They are the price of stripping an edge at all, and they are
#: recorded rather than fixed because the alternative measured worse.
#:
#: **The set is matched after NFC, so it reaches one character it does not
#: list.** U+037E, the Greek question mark, canonically decomposes to `;`, so a
#: Greek interrogative title strips where its Latin equivalent does not: `?` is
#: not a member and cannot arrive as one. Listed characters are not the whole
#: of what this removes, and an arm pins that.
#:
#: **Editing this constant is not the only way to widen the rule**, which is why
#: `test_what_comes_off_an_edge_is_exactly_what_the_constant_allows` exists: the
#: strip is spelled separately, and adding a character there rather than here
#: changed the behaviour and passed every other arm. That arm partitions every
#: codepoint and names none, so it holds whatever this set becomes.
_EDGE_MARKS: Final = ":/;.,()[]"

#: What separates a key's parts, and the property is that no fold can emit it.
#:
#: Neither is a word character nor whitespace, so `fold_title` deletes both and
#: `authors.author_key` turns both into a space. That is what stops a long title
#: and a short credit keying the same as a short title and a long credit.
#:
#: **What keeps a work key and a printing key apart is the count, not the
#: characters.** Because no fold can emit either, **and the year renders as
#: digits**, a work key carries exactly one separator and a printing key exactly
#: two, so the two sets are disjoint whatever characters these are. That third
#: premise is stated because it is the one the folds do not cover: the year is
#: an `int`, not folded text, and `catalogue` is what keeps it in range.
#: Nothing holds both kinds in one dictionary either. They are two constants
#: because a key is read more easily than it is parsed, and not because one
#: character would collide.
_KEY_SEPARATOR: Final = "|"
_YEAR_SEPARATOR: Final = ":"


def _casefolded(text: str | None) -> str:
    """Case folded and composed to NFC, in that order, which is load bearing.

    **Case is folded before the composition, never after.** Some codepoints
    casefold to a decomposed sequence, and composing first leaves that sequence
    uncomposed: `J̌ules` keys as `ǰules` under this order and as a `j`, a
    combining caron and `ules` under `normalize("NFC", text).casefold()`, so one
    title reaches two keys depending on which spelling a catalogue sent.

    **One home for the ordering because two callers now share it.**
    `fold_title` then hands the result to a deletion that would eat the
    combining mark the wrong order leaves behind, which is the same bug one
    step worse; `reading_history_title` keeps the mark and merely keys twice.
    Open coding it at both sites is what would let a tidy reorder one of them
    with nothing red.
    """
    return unicodedata.normalize("NFC", (text or "").casefold())


def fold_title(title: str | None) -> str:
    """A title reduced to what two catalogues spelling it differently share.

    Deliberately lossy: case, accents, punctuation and spacing carry no
    information about which book this is, and two catalogues spell one book six
    ways.

    **Composed to NFC before anything is deleted.** A combining mark is
    punctuation to `[^\\w\\s]`, so on a decomposed string the accent is deleted
    and the letter survives bare: `Les Misérables` arrives from a MARC or
    Z39.50 record in either form and would otherwise key two ways, one of which
    collides with a genuinely different spelling. `_casefolded` owns that
    composition and the ordering inside it, which this function is the harsher
    of the two callers of: a mark left uncomposed here is deleted rather than
    merely keyed twice.

    **Whitespace is stripped after punctuation is removed, never before.** A
    mark that is separated from the first word leaves its own space behind, so
    `Ulysses :` keyed differently from `Ulysses` and the leading article was no
    longer at the start of `( The Dune )`. MARC 245 carries that punctuation by
    convention, so this was the ordinary case rather than the odd one.
    """
    text = _WHITESPACE.sub(" ", _PUNCTUATION.sub("", _casefolded(title))).strip()
    for article in _ARTICLES:
        if text.startswith(article):
            return text[len(article) :]
    return text


def fold_credit(author: str | None) -> str:
    """The first person credited, folded the way an author page folds them.

    **Only the first**, because `Terry Pratchett` and `Terry Pratchett, Neil
    Gaiman` are one book credited differently on two editions.

    **`authors` owns both halves and this borrows them rather than restating
    them.** `split_authors` knows the credit line is comma separated and that a
    blank segment is nobody, so `", , Jane Doe"` yields Jane Doe rather than an
    empty key. `author_key` knows punctuation folds to a space rather than to
    nothing, which is what puts `J.R.R. Tolkien` and `J. R. R. Tolkien`
    together instead of driving them apart.
    """
    credited = authors.split_authors(author)
    return authors.author_key(credited[0]) if credited else ""


def work_key(title: str | None, author: str | None) -> str:
    """What two editions of one book share.

    The predicate behind every destructive answer: whether an imported record
    is the book this library already holds, and which stored rows are offered
    as duplicates of each other.

    **Opaque: compare it, never take it apart.** Splitting it back on the
    separator retypes a character that has already misled two tests, and the
    components are `fold_title` and `fold_credit`, which a caller wanting one
    should call directly.
    """
    return f"{fold_title(title)}{_KEY_SEPARATOR}{fold_credit(author)}"


def printing_key(title: str | None, author: str | None, year: int | None) -> str:
    """A work and the year that tells two printings of it apart.

    **Not a substitute for an ISBN**, which is the one thing that identifies a
    printing. This exists for rows that have no ISBN to be told apart by.

    **Looser than the rule it replaced, on purpose, and worth stating because
    this is a site where looser is the dangerous direction.** It folds a leading
    article and folds credit punctuation, neither of which the picker's former
    key did, so two answers spelling one book `The Hobbit` and `Hobbit` now
    share a row where they used to be two. Three things bound that: the year
    still discriminates, merging two answers fills gaps rather than overwriting,
    and the language refusal still fires. A reader tempted to tighten it back
    should know it was widened knowingly.
    """
    return f"{work_key(title, author)}{_YEAR_SEPARATOR}{year or ''}"


def reading_history_title(title: str) -> str:
    """A title as a catalogue spelled it, with no credit in the key at all.

    **The deliberately weak one.** A CSV export is somebody's reading history
    and an OPDS feed is a list of what a server says a household owns; both are
    matched on ISBN first and fall back to this. Two editions of one title
    collide, which is acceptable for a status and would not be for anything
    destructive.

    **Author blind on purpose**, by the owner's instruction of 2026-09-05,
    which is amended rather than reversed: what moved on 2026-09-24 is the
    normalisation alone, and the credit is still to hand at both call sites
    rather than missing.

    **It takes the half of `fold_title` that cannot merge two books.** Case,
    composition and spacing, yes; interior punctuation and a leading article,
    no. See this module's docstring for why the halves part where they do, and
    `_EDGE_MARKS` for what counts as an edge and what that was measured
    against.

    **Stripping marks and spaces together is not a third rule.** The earlier
    strip has already taken any edge whitespace, so the space term only ever
    fires on a space a mark was sitting next to: `[ Ulysses ]` reaches it with
    the space between the bracket and the text, and `Dune : [ ]` with one
    between two marks. Both, not only the second.

    **A title is never nothing, which is the one bound not in the rule above.**
    A title of nothing but edge marks would otherwise strip to the empty key,
    and that key is not inert: `create_missing` stores a Book titled `.` on the
    first sync that sees one, `Book.is_private` defaults false so it enters
    every member's `Shelf.seen_by`, and every later punctuation-only title from
    any source then matches it and takes the whole write set above. How many
    titles that is, and that they key apart now, is recomputed by
    `test_a_title_of_nothing_but_marks_is_not_the_empty_key` rather than written
    here. Under the `.lower()` this replaced the empty key had no live source,
    since both call sites refuse a title that is genuinely empty, so the
    degeneracy would be new rather than inherited.

    **The fallback cannot collide with a stripped key, and that is why it is the
    collapsed text rather than a sentinel.** A stripped key is non-empty only if
    it begins and ends with a character outside the set, and a key that reached
    the fallback consists of set members alone, so no title can reach another's
    key by this branch. `""` stays reachable from a blank title and from nothing
    else. Anything narrower, a first character or a sentinel, merges the
    punctuation-only titles among themselves instead, which is the same defect
    one size smaller.
    """
    text = _WHITESPACE.sub(" ", _casefolded(title)).strip()
    return text.strip(_EDGE_MARKS + " ") or text
