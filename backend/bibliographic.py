"""What a bibliographic value means, whatever serialisation carried it.

A catalogue answers in MARC21, in Dublin Core, in MODS or in its own JSON, and
the same rules decide what the values inside mean: which language a code names,
how many pages an extent statement claims, whether a title is a volume slot
rather than a work, whether a person's name is in catalogue order. Every decoder
in `metadata.py` and `marc.py` reads a `catalogue.Record` into existence and none
of them owns these.

**The membership test is one sentence: a rule about what a bibliographic value
means, independent of the serialisation it arrived in.** It admits everything
here. It excludes `marc_fields.Subfields`, `marc_fields.Fields` and
`marc_fields.Subfields.subject_vocabulary`, which are MARC subfield readers
wearing generic names, and it excludes every refusal a single catalogue states
for itself, such as `metadata._NKP_ONLINE`.

**Why it is one module rather than a helper beside each decoder.** Seven of the
nine are not MARC helpers that other formats borrow. Counted by an `ast` pass
over `metadata.py`'s functions at the commit that created this file, by how many
read each name and are not a MARC decoder: `LANGUAGES` five,
`pages_from_extent`, `is_physical_book`, `is_placeholder_title` and
`flip_catalogue_name` three each, `split_title_statement` two,
`strip_isbd_punctuation` one. A rule with that many readers and no home is a
rule that gets a second copy: the frontend grew seven readers applying three
different publication year rules before `plausibleYear` gave that one a home,
and `docs/decisions.md` records what it cost. This is the same finding on the
backend, and the same fix.

**The other two score zero on that count and are here for the other half of the
rule, which is that a fact belongs in one place.** `BIBLIOGRAPHIC_CODES` has one
reader, `marc.py`'s writer, and is here because it is `LANGUAGES` inverted:
apart they are two tables that drift the first time one gains a language.
`is_a_disc` has one reader, `metadata._dnb_record`, and is here because its
alternation is half of `is_physical_book`'s: apart they are two spellings of one
refusal, and the alternative was publishing a regex fragment.

**Not `fields.py`.** The module this serves is full of MARC datafields and
subfields, and the one place that needs both names is the wrong place to
economise on one of them.

`authors.py` is the precedent: the pure rules underneath `authorship.py`, with
no database and no transport. These are the pure rules underneath the decoders,
and `catalogue.Record` is the thing they are rules about.
"""

import re
from typing import Final

from models import MAX_PAGE_NUMBER_IN_A_BOOK

#: ISO 639-2/B, which is what every MARC derived source emits, to the 639-1
#: codes stored elsewhere.
#:
#: Read by six decoders across four serialisations, which is why it is here
#: rather than beside any one of them.
LANGUAGES: Final[dict[str, str]] = {
    "ger": "de",
    "deu": "de",
    "eng": "en",
    "fre": "fr",
    "fra": "fr",
    "ita": "it",
    "spa": "es",
    "dut": "nl",
    "nld": "nl",
    "pol": "pl",
    "rus": "ru",
    "por": "pt",
    "swe": "sv",
    "dan": "da",
    "nor": "no",
    "fin": "fi",
    "cze": "cs",
    "gre": "el",
    "tur": "tr",
    "jpn": "ja",
    "chi": "zh",
    "ukr": "uk",
    "lat": "la",
}

#: The three languages `LANGUAGES` holds twice, and which of the two codes is
#: written back out.
#:
#: ISO 639-2 gives some languages a bibliographic code and a terminological one.
#: `LANGUAGES` holds both, because a catalogue may send either. A writer has to
#: pick one, and the MARC Code List for Languages takes the **bibliographic**
#: code, so `de` writes `ger` and never `deu`, `fr` writes `fre` and never
#: `fra`, and `nl` writes `dut` and never `nld`.
#:
#: **Pinned rather than taken from the order `LANGUAGES` happens to be written
#: in.** Both orderings round trip, since either code reads back as the same two
#: letter one, so a reordering above would silently start writing a code MARC
#: does not use and every test would stay green.
_BIBLIOGRAPHIC_PREFERRED: Final[dict[str, str]] = {"de": "ger", "fr": "fre", "nl": "dut"}

#: The two letter code this app stores, as the three letter code a catalogue is
#: written back out in.
#:
#: **Derived from `LANGUAGES` rather than retyped, and it lives beside it rather
#: than beside the writer.** Two tables would drift the first time one of them
#: gained a language, and the only thing that would notice is a round trip
#: nobody ran. `tests/test_bibliographic.py` pins the inversion in both
#: directions.
BIBLIOGRAPHIC_CODES: Final[dict[str, str]] = {
    **{code_639_1: code_639_2 for code_639_2, code_639_1 in LANGUAGES.items()},
    **_BIBLIOGRAPHIC_PREFERRED,
}


def split_title_statement(raw: str) -> tuple[str, str | None]:
    """Pull a title and subtitle out of a whole title statement.

    **Two serialisations reach this and that is why it is not called after
    either.** The BnF writes the statement of responsibility into `dc:title`,
    and a MARC record that did not subfield itself puts the whole statement in
    `245 $a`, so `metadata._marc_title` falls back to this whenever `245`
    carries no `$b`. It was the DNB's Dublin Core parser until the DNB moved to
    MARC21; the example below is the DNB record it was written against.

    A record carries one string holding as much as:

        [Docker: up & running] ; Praxiswissen Docker : Grundlagen und Best
        Practices ... / Sean P. Kane mit Karl Matthias ; deutsche Übersetzung
        von Thomas Demmig

    which is, in order: the original title of a translation in brackets, the
    German title, a colon and the subtitle, then a slash and the statement of
    responsibility. Everything after the slash duplicates `dc:creator`, and the
    bracketed part is a different book's title, so both are dropped.
    """
    title = raw.strip()

    # The statement of responsibility. Split on the first " / " only: a title
    # may legitimately contain a slash later on.
    title = title.split(" / ", 1)[0].strip()

    # A leading "[original title] ; " on a translation.
    title = re.sub(r"^\[[^\]]*\]\s*;\s*", "", title).strip()

    # Anything still separated by " ; " is a second work in the same volume.
    title = title.split(" ; ", 1)[0].strip()

    if " : " in title:
        main, subtitle = title.split(" : ", 1)
        return main.strip(), subtitle.strip() or None
    return title, None


def strip_isbd_punctuation(raw: str) -> str:
    """Drop the ISBD punctuation that introduces the *next* subfield.

    Catalogue records end a subfield with the separator for the one after it,
    so `$a` reads `Stoner :` when a subtitle follows. Leaving it in puts a
    stray colon at the end of half the titles in the library.

    **ISBD and not MARC**, which the callers say: the Czech National Library
    writes the same punctuation into un-namespaced Dublin Core, and this is
    what reads it there too. The cataloguing standard is the rule's subject and
    the serialisation is not.
    """
    return raw.strip().rstrip("/:;,=").strip()


def pages_from_extent(raw: str | None) -> int | None:
    r"""`390 Seiten`, `348 S.` and `528 p.` all become a number.

    Read by every MARC derived source, by both Dublin Core dialects and by
    MODS. **The unit is required rather than optional**, because an extent
    statement also carries plate counts and dimensions, so a bare number would
    sometimes be the wrong one.

    **The digit run is bounded, and that is a fix for a 500.** CPython refuses an
    int conversion of more than `sys.get_int_max_str_digits()` digits and raises
    **`ValueError`**, which is neither `httpx.HTTPError` nor
    `ElementTree.ParseError`, so no SRU handler caught it: one record carrying
    4,301 digits in its `300 $a` turned search and lookup into a 500 for every
    MARC source at once.

    **`fetch.MAX_RESPONSE_BYTES` cannot reach it**, because the poisoned envelope
    is smaller than the smallest honest response that source sends.

    **The lookbehind makes it a refusal rather than a guess**: a bare digit run
    matches across a separator and invents a page count. The range is
    `MAX_PAGE_NUMBER_IN_A_BOOK`.

    This **extracts**, where `is_physical_book` **refuses**, which is why a per
    source phrasing belongs there and not here. Only spellings actually measured
    are listed.
    """
    if not raw:
        return None
    match = re.search(
        r"(?<!\d)(\d{1,6})\s*(?:Seiten|Bl\.|S\.|pages|p\.|pp\.|stran)", raw
    )
    if not match:
        return None
    pages = int(match.group(1))
    return pages if 0 < pages <= MAX_PAGE_NUMBER_IN_A_BOOK else None


#: Titles that are a position in a multi-volume set rather than a book.
#:
#: The DNB's `num=` index matches any identifier anywhere in a record,
#: including the "also published as" cross references a collected edition
#: carries for its parts. Searching a French ISBN therefore returned a German
#: multi-volume record whose whole title was `[Hauptbd.].`, and the chain
#: accepted it, because it had a title and a date and looked like a hit.
#:
#: Measured: `9782070360024` (Gallimard, L'Étranger) returns exactly that.
_PLACEHOLDER_TITLES: Final = re.compile(
    r"^\[?\s*(Hauptbd|Haupt-Bd|Bd|Band|Teil|Vol|Volume|Reg|Register)\b", re.IGNORECASE
)


def is_placeholder_title(title: str) -> bool:
    """Whether a title names a volume slot rather than a work."""
    stripped = title.strip().strip("[].").strip()
    return not stripped or bool(_PLACEHOLDER_TITLES.match(title.strip()))


#: Extents that mean the record is not a physical book. A digitised copy of a
#: novel is a real catalogue record and a wrong answer to "which book am I
#: holding", and it is the single largest source of noise in the SRU sources.
#: It named both spellings when there were two of them; counted on `|` at paren
#: depth zero there are eight alternatives now, so it names none.
#:
#: **Written as two halves on 2026-08-24, because the DNB lookup treats them
#: differently.** An online resource is this book in another form, and the DNB
#: answers with one for an ISBN whose printed record it also holds, so the DNB lookup
#: ranks it below a physical record and takes it rather than reporting a miss.
#: A disc is a different object, so `metadata._dnb_record` refuses it outright
#: through `is_a_disc`. Both halves are still one refusal everywhere else,
#: `is_physical_book` being what the search paths and K10plus ask.
#:
#: **This is the fallback now, and a code test stands in front of it.**
#: `is_physical_book` is reached from nine sources, the whole roster less the
#: two that never ask it: the DNB, K10plus, the OENB, the NLG, the BNE, the NKP,
#: the BNA, the BnF and the Library of Congress. Six of them state the carrier
#: in codes and are asked those first, the five MARC ones through
#: `marc_fields.Fields.describes_a_book` and the Library of Congress through
#: `metadata._loc_carrier_is_book`. The three Dublin Core sources decide it from
#: prose alone, and two of them state their own, `metadata._NKP_ONLINE` and
#: `metadata._BNF_ONLINE`. **The BNA states none, deliberately**: none of the
#: ten records measured there is an online resource, so there is nothing
#: measured to write a Spanish pattern against, and `metadata`'s Argentine block
#: carries that refusal to guess.
#:
#: **So a reader who has met a new wording should not lengthen this.** Widening
#: it still changes what all nine refuse, and #124 is the record of what that
#: buys: the wording is a property of the language, the language list is open,
#: and six of the nine never needed the wording at all.
_ONLINE_FORMS: Final = (
    r"online[- ]?(?:ressource|resource)|elektronische ressource|streaming"
)
_DISC_FORMS: Final = r"audio disc|sound (?:disc|recording)|videodisc|dvd|blu-?ray"

_NOT_A_BOOK: Final = re.compile(f"{_ONLINE_FORMS}|{_DISC_FORMS}", re.IGNORECASE)

_IS_A_DISC: Final = re.compile(_DISC_FORMS, re.IGNORECASE)


def is_physical_book(extent: str | None, title: str | None) -> bool:
    """Whether a record's prose describes something that can sit on a shelf.

    Both arguments are optional because a `Record`'s are: an untitled record is
    one a catalogue answered thinly, not one naming a volume slot, so it fails
    the placeholder test rather than passing it.

    **This is the fallback and no longer the whole rule.** A MARC record states
    its carrier in codes, so the five MARC sources ask
    `marc_fields.Fields.describes_a_book` and reach this through it, and the Library
    of Congress reads the MODS spelling of the same codes. What is left here is
    Dublin Core, which carries no such vocabulary at all, in two dialects across
    three sources. `metadata._marc_carrier_is_book` says why.
    """
    if extent and _NOT_A_BOOK.search(extent):
        return False
    return not is_placeholder_title(title or "")


def is_a_disc(extent: str | None) -> bool:
    """Whether an extent statement names a disc rather than a book.

    The disc half of `is_physical_book` on its own, because the DNB lookup
    refuses a disc outright where it only ranks an online resource down: a disc
    is a different object and an online resource is this book in another form.
    `metadata._dnb_record` is the one caller and carries the measurement of how
    little this catches.

    **Published beside the rule it is half of rather than left in the decoder**,
    so the alternation it shares with `is_physical_book` stays one string. The
    alternative was publishing `_DISC_FORMS`, which is a regex fragment and not
    a rule anybody can ask a question of.
    """
    return bool(extent and _IS_A_DISC.search(extent))


#: What a catalogue hangs off a person's name. The BnF writes
#: `Zafón, Carlos (1964-2020). Auteur du texte`; MARC and MODS write
#: `Melville, Herman, 1819-1891`. None of it is part of the name.
_PERSON_NOISE: Final = re.compile(
    r"\s*\(\s*\d{3,4}\s*[-–]?\s*\d{0,4}\s*\)"  # (1964-2020)
    r"|\s*\.\s*(Auteur|Autrice|Éditeur|Editeur|Traducteur|Traductrice|"
    r"Illustrateur|Illustratrice|Préfacier|Compilateur)[^.]*\.?\s*$"
    # The `\.?` before the anchor is what lets this arm fire on its own.
    # Without it `Melville, Herman, 1819-1891.` matches nothing, and the dates
    # came off only because a caller removed the full stop first and ran the
    # substitution again, which is a coupling that put the stop removal in the
    # wrong function for six years.
    r"|,\s*\d{4}\s*[-–]\s*\d{0,4}\s*\.?\s*$",  # , 1819-1891
    re.IGNORECASE,
)

#: A trailing initial, which is the one full stop in a name that is part of it.
#: `Pohl, Robert O.` loses its meaning as `Robert O`, and the ISBD full stop
#: `_drop_isbd_stop` takes off `Melville, Herman.` looks exactly the same to a
#: regex.
#: Measured: 2 of 53 live DNB records credit an author with a trailing initial.
_TRAILING_INITIAL: Final = re.compile(r"(?:^|[\s.])[A-Za-z]\.$")


def _strip_person_noise(raw: str) -> str:
    """Drop life dates and role words from a catalogue person string.

    Neither is part of the name whatever the caller means to do with the cell,
    so this runs on every branch. The terminal full stop is `_drop_isbd_stop`
    and deliberately not here: it is the one piece of noise a reader cannot
    tell from the name.
    """
    cleaned = raw
    for _ in range(3):  # A name can carry both, in either order.
        stripped = _PERSON_NOISE.sub("", cleaned).strip().rstrip(",;")
        if stripped == cleaned:
            break
        cleaned = stripped
    return cleaned


def _drop_isbd_stop(name: str) -> str:
    """The full stop a catalogue puts at the end of a heading.

    **Only for a cell that is about to be rewritten anyway.** ISBD punctuation
    and an abbreviation are spelled identically, and which one a cell carries
    is a fact about where the cell came from rather than about the string: a
    MARC `$a` ends in ISBD punctuation, and a `Primary Author` column somebody
    typed ends in `Dr.`, `Jr.`, `Co.` or `Inc.`. So a cell handed back in the
    order it arrived keeps its stop, and only the branch that reorders the name
    takes it off.
    """
    if name.endswith(".") and not _TRAILING_INITIAL.search(name):
        return name[:-1].strip()
    return name


def flip_catalogue_name(raw: str) -> str:
    """`Williams, John` becomes `John Williams`.

    One comma means a person in catalogue order. None, or more than one, means
    something else (a corporate body, a compound credit) and is left alone.

    **Left alone means the order and the full stop, not the noise and not the
    spacing.** Life dates and a role word are not part of a corporate name
    either, so they come off whichever branch runs, and the commas are counted
    after they do: `Melville, Herman, 1819-1891` carries two of them until the
    dates go. Runs of whitespace are collapsed on both branches too, for the
    reason below. What only the flipping branch may take is the terminal full
    stop, which `_drop_isbd_stop` explains.
    """
    # Whitespace is collapsed before any regex runs, and that is a bound rather
    # than tidying. Two of `_PERSON_NOISE`'s three arms are a `\s*` in front of
    # a rare literal, which is quadratic over a run of spaces: measured on a
    # worker node, 1.28 ms at 500 characters and 353 ms at 8,000. This function
    # is on the CSV import path, and one 5 MB upload of 10,464 rows whose
    # author cell was 498 spaces measured 17.96 s of CPU for that column alone
    # before this line. No name means anything by a run of spaces.
    #
    # Nothing trims a trailing comma here: `_strip_person_noise` rstrips `,;`
    # on its own first pass, so a second one at this site would be dead.
    name = _strip_person_noise(" ".join(raw.split()))
    if name.count(",") != 1:
        return name
    surname, forenames = (part.strip() for part in _drop_isbd_stop(name).split(","))
    return f"{forenames} {surname}" if surname and forenames else name
