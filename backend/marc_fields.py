"""How MARC21 spells a bibliographic value, and nothing about where it came from.

**A closed vocabulary with three readers.** `metadata._dnb_record` and
`metadata._k10plus_record` are two catalogue profiles and `marc._record` is a
third for a file somebody uploads; all three read the same fields and must not
drift. Before this module they could not share without one reaching past the
other's door: `marc.py` read 17 private names of `metadata.py` at 21 sites, the
only module to module private read in the backend.

**The membership test is one sentence: a rule about how MARC21 writes a value.**
What that value **means** once it is out of the serialisation is
`bibliographic.py`, which this module reads and does not own: an extent's page
count, whether a title is a placeholder, how a catalogue orders a personal name.
What a **source** does with a record, which profile refuses a volume slot and
which ranks a digitisation below a print, is `metadata.py`. What this app's own
records look like on the way **out**, and what an uploaded file is allowed to
cost, is `marc.py`.

**Six names, where a straight move would have published twenty two.** Two of
the six are the values: `Fields` is one record's datafields and `Subfields` is
one field's subfields, so a reader is a question asked of the thing that answers
it rather than a name a caller has to learn. The other four are `NAMESPACE`,
`RECORD_TAG`, `GND_PREFIX` and `is_component_part`, which is a free function
because it reads the leader to decide whether a record is worth parsing at all.
`marc.py` names five of the six. `Fields` carries the record node as well as
its datafields, because the leader and the control fields answer whether the
record is a book at all and a caller holding the two separately is a caller who
can pass one record's node beside another's fields.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Final
from xml.etree import ElementTree

import ddc
from bibliographic import (
    LANGUAGES,
    flip_catalogue_name,
    is_physical_book,
    split_title_statement,
    strip_isbd_punctuation,
)
from catalogue import AuthorityAssertion, Heading, Subject
from enums import AuthorityScheme, ClassificationScheme, HeadingKind
from isbn import parse as parse_isbn

#: MARCXML's namespace, defined once for the reader and the writer.
#:
#: **One definition and not two.** `marc.py` writes this as the default
#: namespace on `<collection>` and reads records back through `RECORD_TAG`; a
#: reader and a writer disagreeing about it produce a file this app cannot read
#: back, and the round trip test would be the only thing that noticed.
NAMESPACE: Final = "http://www.loc.gov/MARC21/slim"

#: The qualified `record` element, which is the only qualified tag anybody
#: outside this module needs: everything below it is read here.
RECORD_TAG: Final = f"{{{NAMESPACE}}}record"

#: Every other element is read here, so the prefix stays private.
_MARC: Final = f"{{{NAMESPACE}}}"


#: The GND's code in MARC's `$0`, which is what says the identifier beside it
#: is a GND number rather than some other authority file's.
GND_PREFIX: Final = "(DE-588)"


#: Subject fields whose headings are authority controlled, in the order they
#: are read.
#:
#: **689 is the RSWK chain and restates what the others said**, so reading all
#: five double counts by design and the repeats are folded by `catalogue.Record`
#: rather than chosen between. Choosing would lose headings either way: measured
#: over 85 live records, 10 of the 13 600 fields carry a heading no other field
#: carries, and 3 of the 13 689 chains do.
_DNB_SUBJECT_TAGS: Final = ("650", "651", "655", "689", "600")


#: The `$2` codes that say a field is asserting something other than a subject.
#:
#: **Only those two, and the omissions are the rule rather than a short list.**
#: A code this map does not name leaves `Heading.kind` null, and a null reads as
#: a subject, so `gnd` and `lcsh` are deliberately absent. `enums.HeadingKind`
#: says why writing the word costs something rather than merely being
#: redundant; `ck_classifications_kind` is what refuses it.
#:
#: **This is not a second `ClassificationScheme`.** It maps a code onto what the
#: record was doing, never onto a vocabulary: `gnd`, `gnd-content` and
#: `gnd-carrier` are all the GND, so all three still write `scheme=gnd`. Twelve
#: distinct `$2` codes turned up in one day's sampling of four catalogues
#: against a MARC source code list holding hundreds, and reading any of the rest
#: as a kind would be the crosswalk #134 refuses. `catalogue.Subject` carries
#: the code itself for anybody who wants to read it.
_KIND_BY_VOCABULARY: Final[dict[str, HeadingKind]] = {
    "gnd-content": HeadingKind.CONTENT,
    "gnd-carrier": HeadingKind.CARRIER,
}


#: MARC relator codes for somebody who wrote the thing. Translators (`trl`) and
#: editors (`edt`) arrive in the same field and must not become the author.
#:
#: **A `700` stating no role at all is not an author either, and that is a
#: measurement rather than a default.** 28 of 581 live `700` fields carry no
#: `$4`, measured 2026-09-06 over 624 records from the five MARC sources. The 9
#: distinct records pairing such a field with a `100` name an illustrator, a
#: translator or an editor in 7 of them and a co-author in 2, so admitting a
#: bare `700` trades a credit line that is short for one that is wrong. Where a
#: record credits nobody with writing it, `Fields.credited_names` still names
#: everybody the record names, which is the case that fallback exists for.
_AUTHOR_RELATORS: Final = ("aut", "cre")


#: MARC's non-sorting delimiters. A record brackets a leading article with
#: these so a catalogue can file `Die Deutschen und die USA` under D.
#:
#: **Two spellings of one convention, because the catalogues do not agree on
#: which characters to use.** The DNB writes U+0098 and U+009C, which is what
#: MARC21 specifies. ÖNB writes `<<` and `>>`, and writes U+0098 nowhere at
#: all. Measured over live 245 `$a` values on 2026-08-27: 21 of 189 DNB carry
#: U+0098 and 0 carry `<<`; 21 of 150 ÖNB carry `<<` and 0 carry U+0098;
#: K10plus carries neither in 200.
#:
#: **Stripped wherever they appear rather than only at the front**, which is
#: how the MARC characters were already treated and is also what the data
#: needs: 28 of the 111 bracketed runs in 21,760 live ÖNB subfields are not at
#: the start, because the same device marks a nobiliary particle inside a
#: personal name (`Einem, Gottfried <<von>>`). So this reaches `100 $a`, 21
#: occurrences, as well as `245 $a`, 52.
#:
#: **Safe to apply to every source rather than to ÖNB alone**, and that is a
#: measurement rather than a hope: `<<` and `>>` appear in 0 of 32,038 live DNB
#: subfields and 0 of 45,710 K10plus subfields. Scoping it to one parser would
#: mean `_marc_text` doing different things depending on who called it, which
#: is the invisible kind of rule this function exists to avoid.
_NON_SORTING: Final = ("\x98", "\x9c", "<<", ">>")


def _marc_text(raw: str | None) -> str:
    """One subfield's text, as a person would write it.

    Three repairs, all measured against the live DNB on 2026-08-24, and none
    needed under Dublin Core because that crosswalk had already done them.
    **All three are invisible in a terminal**, which is why they are done here
    for every subfield rather than field by field where somebody would
    eventually read a diff and see nothing wrong.

    * **The non-sorting delimiters are stripped**, in both the spellings
      `_NON_SORTING` lists. They are a filing device and not part of the title,
      and they carry through into whatever is stored: 28 of 85 live DNB records
      hold at least one, and one live ÖNB title in seven.
    * **Internal whitespace is collapsed.** MARC pads subfields, which
      `ClassificationIn.tidy_number` already says and already fixes for one
      column. `245 $a` on the reference record 9783446249974 reads
      `Reisen im  Licht der Sterne`, a real double space, where that record's
      own `776 $t` spells it with one.
    * **The text is normalised to NFC.** The DNB serves MARC21 decomposed and
      Dublin Core composed, so `Müller` arrives as `u` plus a combining
      diaeresis: 83 of the same 85 records are affected. It renders identically
      and compares unequal, which is enough to store two spellings of one
      author and to defeat `_duplicate_key`, which casefolds and collapses
      whitespace and does not normalise. Not enough to duplicate a
      classification: `uq_classifications_book_scheme_number` is on `number`,
      which is digits in DDC and digits and hyphens in GND.
    """
    text = raw or ""
    for delimiter in _NON_SORTING:
        text = text.replace(delimiter, "")
    return " ".join(unicodedata.normalize("NFC", text).split())


def _fix_non_filing_space(title: str) -> str:
    """`L' étranger` becomes `L'étranger`.

    MARC records put the space after an elided article so that sorting can skip
    it. It is a filing device, not how the title is printed.
    """
    return re.sub(r"(\w')\s+(\w)", r"\1\2", title)


def _subject_kind(vocabulary: str | None) -> HeadingKind | None:
    """What a `$2` says the field asserts, or None where it says nothing this reads.

    Takes the lower cased code `Subfields.subject_vocabulary` already produced
    rather than the field, so the case folding is not spelled twice and this
    cannot be handed an `082` whose `$2` is a Dewey edition.
    """
    return _KIND_BY_VOCABULARY.get(vocabulary) if vocabulary else None


class Subfields(dict[str, str]):
    """One MARC field's subfields: the first value per code, repeats kept.

    Indexing gives the first occurrence, because a scalar read wants one value
    and MARC writes the primary one first. `all()` gives every occurrence, and
    the reads below need it. **Remove it and every one of them goes quiet rather
    than failing**, which is why it is a type rather than a call at each site.

    * `082 $a` repeats. The DNB puts the Dewey number and its own Sachgruppe
      letter in one field, `$a=830 $a=B`, in 10 of 85 live records measured
      2026-08-24. Keeping the last value reads the number as `B`,
      `ddc.notation` refuses it, and the record stores no classification at all.
    * `$0` repeats wherever a heading is authority controlled. The DNB writes
      `(DE-588)118181505`, then `https://d-nb.info/gnd/118181505`, then
      `(DE-101)118181505`, so keeping the last takes one library's house number
      where the GND identifier is the point.
    * `$4` repeats where one person had two roles: `$4=edt $4=aut` is an editor
      who also wrote a chapter, and keeping the first drops them from the credit
      line. `_relator_codes` carries the count.

    A `dict[str, str]` subclass rather than `dict[str, list[str]]`, so the
    scalar reads elsewhere in this file keep working unchanged: repeats are the
    exception and `entry.get("a")` is the rule.
    """

    def __init__(self, pairs: Iterable[tuple[str, str]]) -> None:
        repeats: dict[str, list[str]] = {}
        for code, value in pairs:
            repeats.setdefault(code, []).append(value)
        super().__init__({code: values[0] for code, values in repeats.items()})
        self._repeats = repeats

    def all(self, code: str) -> list[str]:
        """Every value under one code, in the order the record wrote them."""
        return self._repeats.get(code, [])

    def gnd_identifier(self) -> str | None:
        """The GND number a field's `$0` carries, or None if it carries none.

        Stored bare. `(DE-588)` is MARC naming the scheme, the scheme is already a
        column of its own, and keeping the prefix would let one heading arrive
        under two spellings that `uq_classifications_book_scheme_number` cannot
        collapse.

        A record without one is ordinary rather than broken: 33 of 70 live 655
        fields and 21 of 73 live 100 fields carry no `(DE-588)` at all, measured
        over 85 records on 2026-08-24.

        **This searches every `$0` where `subject_identifier` takes the first, and
        the two are different questions rather than one rule spelled twice.** This
        one asks whether the field names a record in the GND, because the answer
        decides whether a `classifications` row is written and that row's `scheme`
        column is a closed four member set: a `(DE-101)` number filed under `gnd`
        would be an identifier that resolves to nothing. That one asks what the
        record gave as this heading's identifier, whatever file it is in, and takes
        the first because that is where every catalogue measured puts the authority
        file's own number.

        **It no longer discards what it refuses.** Before #134 a `$0` this returned
        None for was the end of that identifier: measured 2026-08-31, 27 of the 718
        live subject fields carrying a `$0` have no `(DE-588)`, and **11 of 11** on
        the National Library of Greece, whose every identifier is a
        `urn:nbn:gr:nlg:`. Those now reach `Subject.identifier` and only the
        classification row is still GND only.
        """
        for value in self.all("0"):
            if value.startswith(GND_PREFIX):
                return value[len(GND_PREFIX) :].strip() or None
        return None

    def subject_identifier(self) -> str | None:
        """The identifier a subject field's `$0` carries, whole, or None.

        **The first `$0` that has a value**, which is a measurement plus one shape
        the measurement could not see. Measured 2026-08-31 over 718 live subject
        fields carrying a `$0`, across the DNB, the OENB, the NLG and K10plus.

        Where a field carries a `(DE-588)` at all, it is the **first** of that
        field's `$0` values, **691 of 691**: the DNB writes `(DE-588)`, then a
        `d-nb.info` URL, then its own `(DE-101)` house number, and K10plus writes
        `(DE-588)`, then `(DE-627)`, then `(DE-576)`. The house numbers and the URL
        always follow, so taking the first never takes a duplicate standing in front
        of the authority number. The other **27** fields carry exactly one `$0` each
        and no `(DE-588)`: `(DE-101)` beside `$2 gatbeg` on the DNB, `(AT-FHV)` and
        `(AT-VLB)` on the OENB, `urn:nbn:gr:nlg:` on the NLG, `(OCoLC)fst` on
        K10plus. So a prefix list has nothing to do here, and it would be the
        enumerating guard this repository keeps paying for.

        **An empty value is skipped, and "691 of 691" is not the reason.** That
        figure counts values **as served**, and says nothing about an element with
        no text standing in front of them, because an empty `$0` is not something a
        catalogue writes: it is what `_marc_text` makes of `<subfield code="0"/>`,
        turning a childless element into `""`. Recounted on the same sample for
        this: **0 of the 718** fields carry an empty `$0` anywhere, so the
        measurement could not have shown the trap and did not.

        `values[0] or None` therefore answered None on a field whose second `$0`
        held the number, where `gnd_identifier` scanned past the empty one and
        found it. Two readers of one subfield disagreeing about whether the field
        has an identifier at all is worse than either answer alone.

        **Whole, prefix included, where `gnd_identifier` strips it.** The prefix is
        not a duplicate of `$2`: `$2 gatbeg` arrives with `$0 (DE-101)1010008188`,
        naming the DNB's genre list and the DNB's own file, which are two answers.
        Strip it and the number resolves to nothing.
        """
        return next((value for value in self.all("0") if value), None)

    def subject_vocabulary(self, tag: str) -> str | None:
        """The vocabulary a subject field's `$2` names, lower cased, or None.

        **`tag` is taken and checked, and that is the rule rather than a
        parameter.** `$2` does not mean the same thing on every field: on `082` it
        is the Dewey **edition**, which the three MARC fixtures in
        `tests/test_metadata.py` spell `23sdnb`, `22/ger` and `21`, so a caller
        handing this an `082` would record a vocabulary called "21". Nothing about
        the subfield says which it is; only the field does.

        **This used to be enforced by a comment and it was not enforced.** The
        docstring said "read on a subject field only" and cited a house rule as the
        pin, but that rule counted **readers of the subfield** and never saw which
        field was passed, so `fields["082"][0].subject_vocabulary()` with no tag was legal, was
        exactly the failure described, and left the guard green. The check is now
        the signature, which no source scan can be evaded past, and the house rule
        is left the one job it can actually do: see
        `test_house_rules.py::TestOneReaderPerAmbiguousSubfield`.

        `_DNB_SUBJECT_TAGS` is the membership test rather than a second list, so
        adding a tag there admits it here in the same edit. A tag outside it raises,
        because no live path can reach that: `Fields.controlled_subjects` iterates that tuple
        and the other two callers pass `"650"` as a literal. It is a guard against the
        next edit, not against a record.

        **Lower cased, and the reason is `marc._extra_headings` rather than the
        catalogues.** That function tests `== "lcsh"` to decide whether an uploaded
        `650` becomes an LCSH heading, so an uploaded file writing `$2 LCSH` loses
        every one of them, silently, with the record otherwise intact. The
        catalogues measured do **not** motivate it: 0 of the twelve codes seen on
        2026-08-31 appeared in two cases, and the two upper case ones are each
        written by one catalogue only, `VLK` by the OENB and `DLC` by K10plus. So
        the folding is protecting an equality comparison in this repository, not
        reconciling two spellings anybody has served.
        """
        if tag not in _DNB_SUBJECT_TAGS:
            raise ValueError(f"$2 is not a subject vocabulary on MARC {tag}")
        value = self.get("2")
        return value.lower() if value else None

    def _relator_codes(self) -> list[str]:
        """Every role one `100` or `700` states, as bare relator codes.

        **Every `$4` rather than the first, because one field states more than one
        role.** 2 of the same 581 live `700` fields read `$4=edt $4=aut`, and the
        first value is the one that is not an author, so reading `entry["4"]` alone
        dropped somebody the record credits with writing the book.

        **A relator URI is the same statement in a different spelling.** The NLG and
        the ÖNB write `http://id.loc.gov/vocabulary/relators/aut` where the rest
        write `aut`: 19 of the 581 `700` fields carry one. **The last path segment
        of any `$4` is taken, whatever vocabulary it names**, rather than one stem
        matched: `$4` is defined as a relator, so its final segment is a relator
        code, and a list of stems is the enumeration this would otherwise become.

        **That arm moved no credit line in the sample, and it is not decoration.**
        Every ÖNB `700` spelling a relator as a URI writes the bare code beside it,
        and the one `700` whose only relator is a URI says `trl`, which is still
        refused. What it changes is why: without it a URI is refused for not being
        in `_AUTHOR_RELATORS` rather than for what it says, so the rule reads as a
        role test and behaves as a spelling test. The NLG writes a URI as the only
        relator on a `100` in 2 of the 44 records read from it, and which tag that
        lands on is a matter of which record was asked for.
        """
        return [value.rsplit("/", 1)[-1].strip().lower() for value in self.all("4")]


#: MARC leader/07, the bibliographic level, for a record that is part of
#: something else rather than a thing on a shelf: `a` is a monographic
#: component part and `b` a serial component part.
#:
#: **These two, because these are the levels the sample actually held.** The 280
#: records measured on 2026-08-27 carried `a` (155), `m` (122) and `c` (3), so
#: `b` is here on the MARC definition rather than on evidence and nothing else
#: is here at all. A later live page turned up one `s`, a serial, which is
#: neither a component part nor a book: it is **not** refused, because refusing
#: serials is a decision about what this app catalogues rather than a correction
#: to this one, and widening a frozenset is the quietest possible place to take
#: a decision like that.
#:
#: **Over half of what an ÖNB title search returns is one of these**, and
#: nothing already here catches them. Measured over 8 title searches on
#: 2026-08-27, 280 records: 155 (55.4%) are level `a`, journal articles and
#: book chapters with a 773 host item entry and usually no 300 extent at all.
#: `is_physical_book` tests the extent for an online form and the title for a
#: volume slot, and an absent extent passes both, so every one of the 155 would
#: have reached the picker as a book.
#:
#: **The leader decides rather than the 773**, and the difference was measured
#: on the same 280 records: the leader catches 155 of 155 and loses **0** of
#: the 122 monographs, where refusing anything carrying a 773 catches the same
#: 155 and loses 3 monographs that carry a host entry legitimately.
_COMPONENT_PART_LEVELS: Final = frozenset({"a", "b"})


def is_component_part(record: ElementTree.Element) -> bool:
    """Whether this MARC record describes an article or a chapter.

    Reads the leader off the record node, because `Fields` maps `datafield` only
    and the leader is neither a datafield nor a controlfield. A free function
    rather than a method, because `metadata._marc_nodes` asks this to decide
    which nodes are worth parsing at all: building a `Fields` first would parse
    every datafield of every record it is about to drop.

    A leader shorter than eight characters is not a component part. A truncated
    leader is a broken record rather than an article, and the fields below
    decide it on their own merits.
    """
    leader = record.findtext(f"{_MARC}leader") or ""
    return len(leader) > 7 and leader[7] in _COMPONENT_PART_LEVELS


#: MARC's own codes for the two things `bibliographic._NOT_A_BOOK` refuses in prose, so that
#: no MARC source needs prose in any language.
#:
#: **The languages are an open set and the schemas are not**, which is the whole
#: argument. `bibliographic._NOT_A_BOOK` is written in German and English, so a Czech online
#: resource reached a shelf (#124) and a French one would have. Lengthening the
#: alternation buys one language at a time forever; these three sets are closed,
#: published, and say the same two things the alternation says.
#:
#: Measured over 2,605 live MARC records on 2026-09-03, from ISBN lookups and
#: title searches across the four MARC sources `targets.SEEDED` held that day,
#: which is five now: **65 describe something that is
#: not a physical book and `bibliographic._NOT_A_BOOK` passes every one**, and **0** are
#: refused by `bibliographic._NOT_A_BOOK` and passed here, so nothing the prose caught is
#: given up.
#:
#: **The language framing predicts 20 of that 65 and no more.** 43 carry no
#: `300 $a` at all, so no extent rule in any language reaches them. 2 carry an
#: extent that counts pages, `XVIII, 222 Seiten` and `24, 358 Seiten, 5
#: ungezählte Seiten Tafeln`, because they are online resources quoting the
#: **printed original's** collation, and an extent rule cannot refuse those
#: without refusing books. The remaining **20** are the ones a longer alternation
#: could have caught, and catching them would have needed `CD-ROM`, `Track`,
#: `Schallplatte`, `Tonie-Figur` and `E-BOOK`, none of which is a language this
#: rule was missing: `CD-ROM` is absent from `bibliographic._DISC_FORMS` in English too.
#:
#: Each code is one of the two halves rather than a widening:
#:
#: | set | codes | what it is the code for |
#: |---|---|---|
#: | 007/00 | `c` | an electronic resource, `bibliographic._ONLINE_FORMS` |
#: | 007/00 | `s`, `v` | a sound recording and a videorecording, `bibliographic._DISC_FORMS` |
#: | leader/06 | `m` | a computer file, `bibliographic._ONLINE_FORMS` |
#: | leader/06 | `i`, `j`, `g` | sound recordings and projected media, `bibliographic._DISC_FORMS` |
#: | 008/23 | `o`, `q`, `s` | online, direct electronic and electronic |
#:
#: **The 008/23 row is not load bearing today and is kept anyway**, which is the
#: reason `metadata._marc_nodes` gives for keeping a component part filter that catches
#: nothing at that source: measured over the same 2,605 records, it refuses **0**
#: that the 007 and the leader do not already refuse. It stays because `007` is
#: optional and 195 of those 2,605 carry none, so a catalogue that codes the form
#: of item and omits the carrier is ordinary MARC that this sample happens not to
#: hold. `s` has never been observed here at all and is in the set on MARC's
#: definition, like `b` at `_COMPONENT_PART_LEVELS`.
#:
#: **What is deliberately not here**: every other leader/06. Refusing them would
#: catch 35 more of those 2,605, of which 20 are graphics, **12 are notated
#: music**, 2 are maps and 1 is a three dimensional object. The music is why it
#: is not one decision: `Gabriel Fauré, Catalogue des œuvres`, `LII, 496 Seiten`,
#: is a book K10plus files as music, and `1 Partitur (101 Seiten)` is a printed
#: score somebody may well shelve. Whether this app takes printed scores, maps or
#: photographs is a decision about what it catalogues rather than a correction to
#: this rule, which is the reason `_COMPONENT_PART_LEVELS` gives for not refusing
#: serials, and widening a frozenset is the quietest possible place to take one.
_NOT_A_BOOK_CARRIERS: Final = frozenset({"c", "s", "v"})
_NOT_A_BOOK_RECORD_TYPES: Final = frozenset({"g", "i", "j", "m"})
_NOT_A_BOOK_FORMS_OF_ITEM: Final = frozenset({"o", "q", "s"})


#: MARC 007/00 for text. A record carrying one is a text whatever else it also
#: carries, which is the clause the ÖNB's digitisations turn on.
_TEXT_CARRIER: Final = "t"


#: leader/06 and 008/23, the two fixed positions read below. Named because a
#: bare `6` and `23` in an index expression say nothing about which of MARC's
#: forty positions is meant.
_RECORD_TYPE_POSITION: Final = 6
_FORM_OF_ITEM_POSITION: Final = 23


def _marc_carrier_is_book(record: ElementTree.Element) -> bool:
    """Whether this record's own codes say it is a thing on a shelf.

    Reads the leader and the control fields off the record node, because
    `Fields` maps `datafield` only and neither of these is one. That is
    `is_component_part`'s reason and it now has seven callers rather than the
    one that argued against widening the field map; see that function.

    **A field too short to index decides nothing**, which is the rule
    `is_component_part` already applies to the leader, and a stronger one here
    because two of the three fields are read at a fixed offset. A truncated
    leader or a short `008` is a broken record rather than a disc, and the
    prose test and the fields below decide it on their own merits. `007` is
    read by prefix rather than by offset, so an empty one yields `""` and
    matches nothing.

    **Every `007`, and a text one wins.** The field is repeatable, one per
    carrier, and 48 of the 2,605 records measured carry two: `cr` beside `tu`.
    Refusing on any electronic `007` refuses all 48, and they are **real books**:
    every one is an Austrian Books Online record (`856 $x ONB-ABO $3 Volltext`)
    for a 19th century print the ÖNB holds, with the print's imprint in the 264
    and its collation in the 300. Their `008/23` is blank or `#` on all 48, which
    is MARC's own answer that the **item** is not electronic; the `cr` describes
    the scan beside it. So a `tu` is decisive and this reads all of them rather
    than the first, which would have passed or refused whichever the cataloguer
    happened to write first.

    **It rescues from the 007 test only**, which the shape of this function
    states and its prose did not: the leader and the 008 have returned already,
    so a `tu` does not outrank either. That is deliberate rather than
    incidental, because a text carrier beside a projected medium leader is a
    record contradicting itself, where a text carrier beside an electronic one
    is a digitisation describing two things truthfully. It also costs nothing on
    the evidence: all 48 carry leader/06 `a` and an 008/23 that is blank or `#`,
    so none of them reaches the question.

    That was the first draft of this function and a critic caught it. It is the
    shape CLAUDE.md names: a replacement better in the dimension it was designed
    for and silently weaker in one nobody re-checked.

    The other worry, a printed book with an accompanying CD-ROM, does not need
    this clause and would not have been saved by it: accompanying material goes
    in `300 $e`, and both records in the sample that carry one (`1 CD`,
    `Zsfassung + 1 CD-ROM`) carry `007 tu` and nothing else.
    """
    leader = record.findtext(f"{_MARC}leader") or ""
    if (
        len(leader) > _RECORD_TYPE_POSITION
        and leader[_RECORD_TYPE_POSITION] in _NOT_A_BOOK_RECORD_TYPES
    ):
        return False

    carriers: list[str] = []
    for control in record.findall(f"{_MARC}controlfield"):
        # `control.text` and never `_marc_text`, which collapses whitespace.
        # A control field is fixed length and its blanks are data. Measured over
        # 2,605 live records, every one of which carries an 008, and counted in
        # **records** rather than in distinct values, which is where the first
        # three versions of this comment went wrong: `_marc_text` alters the 008
        # of 2,043 of them (78.4%) and moves what sits at position 23 on 1,859.
        # So a rule reading this field through the subfield reader refuses 31
        # records where it should refuse 854, and says nothing about it. 5 more
        # collapse below 24 characters, which the length test below turns into a
        # pass rather than an `IndexError`.
        value = control.text or ""
        tag = control.get("tag")
        if tag == "007":
            carriers.append(value[:1])
        elif (
            tag == "008"
            and len(value) > _FORM_OF_ITEM_POSITION
            and value[_FORM_OF_ITEM_POSITION] in _NOT_A_BOOK_FORMS_OF_ITEM
        ):
            return False

    # **A record that declares a text carrier is a text**, whatever other `007`
    # it also carries. Not whatever else it declares: the 008 and the leader have
    # returned already, above, and a `tu` does not outrank either. See the two
    # 007 note in the docstring for why that asymmetry is deliberate, and for the
    # measurement that it costs nothing, 0 of the 1,484 records carrying a text
    # 007 also carry a refusing leader/06 or 008/23. Without this clause the 48
    # Austrian Books Online records are refused, and they are real prints.
    return _TEXT_CARRIER in carriers or not any(
        carrier in _NOT_A_BOOK_CARRIERS for carrier in carriers
    )


class Fields:
    """One MARC record's datafields, and every question this app asks of them.

    **Built from the record node and keeps it**, because the leader and the
    control fields answer whether the record is a book at all and this map holds
    `datafield` only. Holding the two apart is how a caller ends up asking one
    record's node about another record's fields: `describes_a_book` needed all
    three of a node, a field map and a title until they lived here.
    """

    def __init__(self, record: ElementTree.Element) -> None:
        self._record = record
        fields: dict[str, list[Subfields]] = {}
        for datafield in record.findall(f"{_MARC}datafield"):
            tag = datafield.get("tag")
            if tag is None:
                continue
            fields.setdefault(tag, []).append(
                Subfields(
                    (subfield.get("code") or "", _marc_text(subfield.text))
                    for subfield in datafield.findall(f"{_MARC}subfield")
                )
            )
        self._fields = fields

    def get(self, tag: str) -> list[Subfields]:
        """Every occurrence of one tag, in the order the record wrote them.

        Empty where the record has none, so a reader is a loop rather than a
        loop and a default. `marc.py` reads `050` and `650` through this for the
        two schemes no catalogue here sends.
        """
        return self._fields.get(tag, [])

    def title_statement(self) -> tuple[str, str | None, str | None, float | None]:
        """The 245 field as title, subtitle, series name and series number.

        **The field is picked here rather than by each caller.** All three MARC
        profiles wanted the first 245 and an empty field where there is none, and
        spelling that at each call site is three chances to write the fallback
        differently.

        `$n` and `$p` are the part designation and part title, which is how a
        catalogue records a numbered volume: `$a=Harry Potter`, `$n=[1]`,
        `$p=Harry Potter and the philosopher's stone`. The part title is the book
        somebody is holding, so it becomes the title, and the collective title
        becomes the series. Without this the whole series is catalogued seven
        times under one name.

        **A subfield that was never split gets split here.** An older record puts
        the whole statement in one subfield, subtitle and statement of
        responsibility and all: DNB record 900329866 (ISBN 9783442002009) reads
        `$p=Der Zinker : Kriminalroman / [aus d. Engl. übertr. von Gregor
        Müller]`. Taking it whole puts a translator credit in the title, which is
        what the Dublin Core parser existed to prevent, so where MARC supplied no
        `$b` the title goes through the same splitter. Only where there is no
        `$b`: a record that did subfield itself has already answered this
        question, and a title with a colon in it is then the title.
        """
        entry = (self.get("245") or [Subfields(())])[0]
        main = strip_isbd_punctuation(entry.get("a", ""))
        part_title = strip_isbd_punctuation(entry.get("p", ""))
        subtitle = strip_isbd_punctuation(entry.get("b", "")) or None

        series_name: str | None = None
        series_index: float | None = None
        if part_title:
            series_name = main or None
            number = re.search(r"\d+", entry.get("n", ""))
            series_index = float(number.group()) if number else None
            title = part_title
        else:
            title = main

        if subtitle is None:
            title, subtitle = split_title_statement(title)

        return _fix_non_filing_space(title), subtitle, series_name, series_index

    def describes_a_book(self, title: str | None) -> bool:
        """The whole refusal for a MARC source: the codes, then the prose.

        **The one door.** Every MARC parse path asks this and none asks
        `bibliographic.is_physical_book` directly, so a source added later gets
        the carrier test by construction rather than by remembering to add it.
        `tests/test_metadata.py::TestTheCarrierTestIsTheOnlyWayIn` is what keeps
        that true.

        **Named for the record and not for the rule underneath it, because the
        two are different questions and one of them is guarded by name.**
        `tests/test_bibliographic.py::TestTheProseRuleIsReachedOnlyThroughACarrierAwareDoor`
        counts callers of `is_physical_book` by the name at the call site, so a
        method of that name here makes every caller of **this** look like a
        caller of **that**, and the guard reports three doors that are not doors.
        Measured: it did, on the first draft of this module.

        Both halves, because neither subsumes the other. The codes reach the 43
        records that state no extent; the prose reaches a record whose catalogue
        coded it wrongly, which the DNB does, writing `338 $a Band` on three
        records whose 007, 008 and extent all say online.
        """
        return _marc_carrier_is_book(self._record) and is_physical_book(
            self.extent(), title
        )

    def controlled_subjects(self) -> tuple[list[Subject], list[Heading]]:
        """The controlled subject headings, as plain subjects and as GND rows.

        **A subject heading never enters the DDC path**, and that is load bearing
        rather than tidy. `ddc.parse_heading` accepts any three digit token, so
        "100 Jahre Bauhaus" as a 650 heading would be stored as DDC 100 and
        suggest the Philosophy tag. Dublin Core made that unreachable by accident,
        because `dc:subject` carried only Sachgruppen; MARC puts free text and
        Dewey in different fields, so the rule is now structural: 082 is the only
        field this module hands to `ddc`, and the headings here are GND or nothing.

        **The GND number is the half that does not move**, the way a Dewey number
        is: `(DE-588)4203576-4` names one heading whatever a record captions it.
        Unlike Dewey that is untested here rather than measured, the DNB being the
        only supplier and every caption German. It is stored bare, under its own
        scheme, with the heading text as the caption.

        **Repeats are not folded here, and they used to be.** A record restates
        itself: 689 repeats the 600, 650 and 651 headings it was built from, so the
        reference record 9783446249974 names Stevenson, Samoainseln and Schatz
        twice each. `Record` folds both collections at construction, keeping the
        first of each, which is what this function used to do with two dictionaries
        of its own. Deleting them is the point of the seam being typed: the rule has
        one owner, and the next source added inherits it rather than copying it.

        **`$2` and `$0` are read since #134. What a `$2` decides is the kind, never
        the scheme.** A subject carries the vocabulary the record declared and the
        identifier it gave, whatever file that identifier is in. What decides
        whether a `classifications` row is written at all is still
        `Subfields.gnd_identifier` alone, because that table's `scheme` is a closed four member set and a `$2`
        naming the Greek national authority file is not one of its members. So the
        Greek `651` that prompted the ticket keeps its label **and** its
        `urn:nbn:gr:nlg:` identifier, and still writes no heading. Storing it is
        #143.

        **The `$2` does decide `Heading.kind`, and that is what stops a disc being
        a subject.** `655 $2 gnd-carrier $0 (DE-588)4139307-7 $a CD-ROM` carries a
        GND number like any other, so it became a heading about what the book is
        about. It is still a heading and still `scheme=gnd`, because the number is
        a GND number and resolves as one; what changed is that it now says it is a
        carrier. Refusing the field instead was the obvious fix and is wrong: the
        same vocabulary carries `Fiktionale Darstellung`, which is why `655` is on
        the tag list at all, and it is stored nowhere else.

        **Which is why nothing here maps a `$2` onto a scheme.** Twelve distinct
        codes turned up in one day's sampling of four catalogues and the MARC source
        code list holds hundreds; a table from those to `ClassificationScheme` is a
        crosswalk, and #134 refuses one in as many words. `catalogue.Subject` lists
        the twelve.

        **Two catalogues through this one parser disagree about which tag
        declares.** Measured 2026-08-31: the DNB's `650` declares `gnd` on 130 of
        134 while the OENB's declares nothing on 17 of 29, and both arrive here
        through `metadata._dnb_record`. That is the whole argument for reading the subfield
        rather than inferring from the tag, and it is made entirely of fields this
        function actually sees.

        **K10plus is the sharper illustration and is not the evidence.** Its `689`
        declares `gnd` on all 113 and its `650` on 3 of 133, an exact mirror of the
        DNB. But `metadata._k10plus_record` reads `650` alone and never calls this, so those
        113 fields reach no reader in this app: quoting them here would rest a rule
        on data nothing reads.
        """
        subjects: list[Subject] = []
        headings: list[Heading] = []
        for tag in _DNB_SUBJECT_TAGS:
            for entry in self.get(tag):
                heading = strip_isbd_punctuation(entry.get("a", ""))
                if not heading:
                    continue
                vocabulary = entry.subject_vocabulary(tag)
                subjects.append(
                    Subject(heading, vocabulary, entry.subject_identifier())
                )
                number = entry.gnd_identifier()
                if number is not None:
                    headings.append(
                        Heading(
                            ClassificationScheme.GND,
                            number,
                            heading,
                            _subject_kind(vocabulary),
                        )
                    )
        return subjects, headings

    def _isbn_entries(self) -> list[Subfields]:
        """The 020 entries that identify this record's own book.

        **Unqualified entries where a record has any, and all of them where it has
        none.** One rule, read by `claims_isbn` and `isbn`, so "which
        ISBN is this record's" has one answer.

        **A subfield `q` is a qualifier**, such as "amerik. Original" or "Hardback".
        The first is a cross reference to a different edition, and taking it as
        identity is how a scan of one printing answers with another. The second is
        harmless. **Nothing distinguishes them by shape**, so the rule is positional
        rather than lexical: prefer what is unqualified, and fall back to everything
        only when there is nothing else, because a record whose every ISBN is
        qualified is still a record about a book.
        """
        entries = [entry for entry in self.get("020") if "a" in entry]
        unqualified = [entry for entry in entries if "q" not in entry]
        return unqualified or entries

    def claims_isbn(self, isbn: str) -> bool:
        """Whether 020 names this book, rather than merely mentioning it.

        Which entries count is `_isbn_entries`. The other trap is here: 020 often
        holds the **ISBN-10** even when the search was by ISBN-13, so both sides are
        canonicalised rather than compared as strings.
        """
        return any(
            parse_isbn(entry.get("a", "")) == isbn for entry in self._isbn_entries()
        )

    def _author_entries(self) -> list[tuple[str, Subfields]]:
        """The 100 main entry plus any 700 that actually wrote something, with its field.

        **The field is returned beside the name so that the credit line and the
        authority identifiers cannot be built from two different sets of people.**
        `authors` joins the names and `author_identifiers` reads `$0`
        off the same entries, so every identifier this module produces is filed
        under a spelling that is in this record's own `author` string. Two loops
        testing the same three conditions would make that alignment a comment, and a
        comment is what would drift the day a relator code is added to one of them.

        **Which `700` counts is `_AUTHOR_RELATORS`, and a field stating no role at
        all does not**, which is the answer to a `700` beside a `100` losing a
        co-author. The measurement that settles it, and the fallback that covers the
        record crediting nobody, are on that constant.

        Order preserved, repeats dropped: 100 and 700 can name the same person, and
        the first field naming them is the one whose `$0` is read.
        """
        entries: list[tuple[str, Subfields]] = []
        for entry in self.get("100"):
            if entry.get("a"):
                entries.append((flip_catalogue_name(entry["a"]), entry))
        for entry in self.get("700"):
            # `t` marks an added entry for a *work*, not a person: the row exists
            # to link the original title, and its name is the original author's.
            if (
                entry.get("a")
                and "t" not in entry
                and any(code in _AUTHOR_RELATORS for code in entry._relator_codes())
            ):
                entries.append((flip_catalogue_name(entry["a"]), entry))
        seen: dict[str, Subfields] = {}
        for name, entry in entries:
            seen.setdefault(name, entry)
        return list(seen.items())

    def authors(self) -> str | None:
        """The 100 main entry plus any 700 that actually wrote something."""
        return ", ".join(name for name, _ in self._author_entries()) or None

    def author_identifiers(self) -> list[AuthorityAssertion]:
        """Which GND record each credited author is, where the record says so.

        **The same `$0` `Subfields.gnd_identifier` reads for a subject heading, in a field
        that means something else.** 600 says a person is what the book is *about*
        and 100 says they wrote it, so the identifier is the same kind of string
        with a different subject, and the two go to different stores. See
        `enums.AuthorityScheme`.

        **A record with no `$0` is ordinary rather than broken**: 21 of 73 live 100
        fields carry no `(DE-588)` at all, measured over 85 records on 2026-08-24,
        which is the same measurement `Subfields.gnd_identifier` records.

        Nothing here decides whether the assertion is trustworthy. That is the
        path's question and not the parser's, and `catalogue.AuthorityAssertion`
        says why it cannot be answered here.
        """
        return [
            AuthorityAssertion(name, AuthorityScheme.GND, number)
            for name, entry in self._author_entries()
            if (number := entry.gnd_identifier()) is not None
        ]

    def credited_names(self) -> str | None:
        """Every person the record names, whatever role it gives them.

        **The fallback for a record that credits nobody with writing the book**,
        which is what an edited volume looks like in MARC: no 100 at all, and the
        editors in 700 with `$4=edt`. `authors` answers None there, and
        naming the editors beats naming nobody, which is the same call the Dublin
        Core parser made when no `dc:creator` carried `[Verfasser]`.

        Measured over 74 live DNB lookups on 2026-08-24: without this, 8 of the 53
        that still return a record lose an author the Dublin Core path answers with
        today.

        Used only where `authors` came back empty. Reading it first would put
        a translator in the credit line of every book that has one.
        """
        names: dict[str, None] = {}
        for tag in ("100", "700"):
            for entry in self.get(tag):
                # `$t` marks an added entry for a *work* rather than a person: the
                # row links the original title and carries its author's name.
                if entry.get("a") and "t" not in entry:
                    names.setdefault(flip_catalogue_name(entry["a"]), None)
        return ", ".join(names) or None

    def year(self) -> int | None:
        """The publication year, from 264 or the older 260.

        `$c` is free text and really does arrive as `2000 (copyright)`, so the
        first four-digit run is taken rather than the whole field.
        """
        for tag in ("264", "260"):
            for entry in self.get(tag):
                match = re.search(r"\d{4}", entry.get("c", ""))
                if match:
                    return int(match.group())
        return None

    def publisher(self) -> str | None:
        """The publisher, from the RDA 264 or the older 260."""
        return next(
            (
                entry["b"].rstrip(",")
                for tag in ("264", "260")
                for entry in self.get(tag)
                if entry.get("b")
            ),
            None,
        )

    def language(self) -> str | None:
        """The first 041 code this app has a two letter equivalent for."""
        for entry in self.get("041"):
            language = LANGUAGES.get(entry.get("a", "").lower())
            if language:
                return language
        return None

    def extent(self) -> str | None:
        """300 `$a`: the page count, and whether this is a book at all.

        Two readers, and they are not the same question: `pages_from_extent`
        wants the number, `is_physical_book` wants to know whether the string
        says "Online-Ressource".
        """
        return next((entry.get("a") for entry in self.get("300")), None)

    def description(self) -> str | None:
        """520 `$a`, the summary note, on the rare record that carries one."""
        return next((entry["a"] for entry in self.get("520") if entry.get("a")), None)

    def ddc_headings(self) -> list[Heading]:
        """082 as Dewey headings, and the one field this module hands to `ddc`.

        082 is the Dewey number and normally nothing else: MARC carries the
        notation and the printed schedule carries the caption, so the label is
        usually null rather than filled in from our own mapping. A record often
        holds two numbers at different precisions (`005.133` and `004`, measured
        2026-08-23), and both are kept: they are two catalogues' answers, not a
        duplicate.

        Through `ddc.parse_heading` like every other source path, which is what
        strips MARC's segmentation prime: 53 of 463 live K10plus `$a` values
        (11.4%, measured 2026-08-23) arrive as `005.13/3` where the DNB stores
        `005.133`, and storing both spellings makes two rows out of one heading
        that `uq_classifications_book_scheme_number` cannot collapse.

        **Every `$a` in the field, not the first.** The DNB writes the Dewey
        number and its own Sachgruppe letter into one 082 (`$a=830 $a=B`, 10 of 85
        live records measured 2026-08-24). The letter is not a Dewey number and
        `parse_heading` drops it; reading a single `$a` would drop the number
        instead on whichever of the two came second.
        """
        return [
            Heading(ClassificationScheme.DDC, number, label)
            for entry in self.get("082")
            for value in entry.all("a")
            for heading in [ddc.parse_heading(value)]
            if heading is not None
            for number, label in [heading]
        ]

    def isbn(self) -> str | None:
        """The record's own ISBN, ignoring cross references to other editions.

        Which entries are the record's own is `_isbn_entries`, and this is the
        second reader of that rule: the first decides whether a record answers a
        lookup, this decides what is stored on it. They were one rule spelled twice
        until 2026-08-30, and the copy here was the one the MARC importer reads
        through `marc.py`, so a Greek or Spanish file imported by hand lost its ISBN
        for the same reason a lookup missed it.

        **The two readers ask different questions and only one of them can be
        wrong here.** `claims_isbn` matches against an ISBN somebody already
        holds. This one **chooses**, and where a record has no unqualified entry
        there is nothing to choose on but catalogue order. On a K10plus record whose
        three entries are `ePUB`, `PDF` and `Broschur` this returns the ePUB's, and
        that is the ambiguity of the record rather than of the rule: one record
        describes three saleable forms and MARC gives no field saying which the
        record is *for*.

        **Refused rather than fixed, and the reason is worth more than the fix would
        be.** Separating them means a list of format words, `ePUB` and `PDF` and
        `e-book` and `EPUB`, which is the enumerating guard this repository has paid
        for several times: it goes stale without failing, in a language nobody here
        reads, on a catalogue that adds a spelling. What this replaced stored
        **no ISBN at all** for such a record, so an ambiguous identifier is the
        improvement over none, and the lookup path is unaffected because
        `metadata._dnb_record` is handed the ISBN that was asked for. A design critic raised
        it; `docs/decisions.md` carries the decision.
        """
        for entry in self._isbn_entries():
            parsed = parse_isbn(entry.get("a", ""))
            if parsed is not None:
                return parsed
        return None
