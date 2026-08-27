"""The Dewey Decimal Classification, and how a library reads one.

Two jobs, and they are the two halves of one heading. `parse_heading` splits
`"004 Informatik"` into the number and the label a catalogue supplied.
`tag_names` then projects the **number** onto this library's own vocabulary.

**Matching on the number is the whole point.** `004` is "Informatik" in a
German record and "Computing" in an English one, so a rule that reads the label
matches on the least portable part of the record. Measured against the DNB on
2026-08-23, ten German ISBNs: eight carried a DDC heading, and not one of the
eight labels matched any of the 105 seeded tag names, because every one of them
was in German. Projecting the numbers instead resolves all eight.

**The projection is division level**, the 100 published three digit numbers
ending in zero. Finer would need the full schedule, which is not free to
redistribute; coarser (the ten classes) puts every novel and every work of
literary criticism under one tag. A division is also what the DNB actually
emits: its Sachgruppen are division aligned, so `830 Deutsche Literatur`
arrives already at the granularity this maps.

The result is a **suggestion**: no endpoint here writes a tag from it. What the
web client then does with it is a separate question, answered in
`serialisation.suggested_tag_ids` and argued in `docs/decisions.md`.
"""

import re
from collections.abc import Iterable
from typing import Final

#: A DDC notation: three digits, optionally a decimal fraction. Three is the
#: floor because a Dewey number always has three, and that bound is load
#: bearing: the DNB writes its own Sachgruppe letter into the same 082 as the
#: number (`$a=830 $a=B`, live on 9783446249974), and K10plus 082 values are not
#: all notations either. A looser pattern would store `B` as a classification.
#:
#: It used to guard something else, which is worth knowing because the guard is
#: now somewhere else: `dc:subject` mixed headings like `20. Jahrhundert` in
#: with the Dewey ones, and a looser pattern read that as the number `20.` with
#: the caption `Jahrhundert`. Nothing hands this a subject heading any more.
#: `metadata._dnb_subjects` says why that separation is structural rather than
#: left to this regex.
_NOTATION: Final = re.compile(r"^\d{3}(?:\.\d+)?$")

#: A heading is one token then, optionally, a caption. The token is put through
#: `notation`, so what separates a heading from a subject heading is the shape
#: of the notation and not the shape of the line.
_HEADING: Final = re.compile(r"^(\S+)(?:\s+(.*))?$")

#: MARC's segmentation prime. 082 `$a` marks where a library may cut the number
#: short for its own shelves (`005.13/3`); it is a printing instruction, not
#: part of the notation, and the DNB stores the same heading as `005.133`.
#:
#: **Stripped, never rejected.** Measured against K10plus on 2026-08-23 over
#: 463 live 082 `$a` values, 53 of them (11.4%) carry one. Refusing those would
#: throw away an eighth of what that catalogue supplies, and keeping them raw
#: leaves two spellings of one heading that
#: `uq_classifications_book_scheme_number` cannot collapse.
_SEGMENTATION_PRIME: Final = "/"


def notation(raw: str) -> str | None:
    """A catalogue's DDC number, canonicalised, or None if it is not one.

    **The single normaliser, and every source path goes through it.** Three
    parsers used to have three notions of what a number is: the DNB path split
    on a regex, the K10plus path admitted anything whose first three characters
    were digits and then stored the whole subfield, and the Library of Congress
    path stored the element text untouched. The column exists to hold a
    language independent notation, and three answers to "what is one" is the
    same flattened string this table was built to stop storing.
    """
    cleaned = raw.strip().replace(_SEGMENTATION_PRIME, "")
    return cleaned if _NOTATION.match(cleaned) else None


def parse_heading(raw: str) -> tuple[str, str | None] | None:
    """`"004 Informatik"` as `("004", "Informatik")`, or None if it is not one.

    A bare number is a heading with no caption, which is what MARC 082 carries:
    the field holds the number and the schedule holds the words.
    """
    match = _HEADING.match(raw.strip())
    if match is None:
        return None
    number = notation(match.group(1))
    if number is None:
        return None
    label = (match.group(2) or "").strip()
    return number, label or None


def division(number: str) -> str | None:
    """The division a DDC number falls in: `004` and `005.133` both give `000`.

    None when the string is not a DDC number at all, so a caller can hand this
    whatever a catalogue supplied. Through `notation`, so `004 Informatik` is
    not read as the division `000` with the caption thrown away.
    """
    canonical = notation(number)
    if canonical is None:
        return None
    return canonical[:2] + "0"


def tag_names(numbers: Iterable[str]) -> list[str]:
    """The curated tag names these classification numbers suggest.

    Deduplicated, in the order the numbers arrived, because a book classified
    at 004 and at 005.133 is one suggestion of Computing and not two.
    """
    names: dict[str, None] = {}
    for number in numbers:
        key = division(number)
        if key is None:
            continue
        name = DIVISION_TAGS.get(key)
        if name is not None:
            names.setdefault(name, None)
    return list(names)


#: DDC division to the seeded tag it is closest to, or absent for no tag.
#:
#: **Absent is a real answer.** 040 is unassigned in the schedule, 080 is
#: quotations and 310 is general statistics, and there is no tag in
#: `PREDEFINED_TAGS` that any of them means. Inventing one would be the failure
#: this whole design avoids: a machine derived tag that nobody chose, sitting
#: in a list the library thinks it curated.
#:
#: Every value here must be a name in `PREDEFINED_TAGS`.
#: `tests/test_ddc.py::test_every_mapped_tag_name_is_a_seeded_tag` pins that,
#: because a typo would otherwise produce a suggestion that silently matches
#: nothing.
#:
#: **A name, still, and not a `TagKey`, which costs a renamed tag its
#: suggestion.** `serialisation.suggested_tag_ids` looks the value up against
#: `tags.name`, so a household that renamed Computing gets no suggestion for
#: DDC 004: not an error anywhere, exactly as above. The key beside that column
#: would fix it and would also change what a suggestion means, since a renamed
#: row is deliberately no longer the seeded tag anywhere else in the app. Left
#: as it is because the language work that added the key changed display only;
#: this is where to start if it is ever picked up.
#:
#: The 800s all map to Fiction rather than to a genre. A division there is a
#: literature by language (`830` is German literature), which says nothing
#: about whether the book is a novel, a play or a work of criticism. Fiction is
#: the coarse claim the number actually supports; 870 and 880 are Classic
#: because a Latin or a Greek literature is one by the time it reaches a shelf.
DIVISION_TAGS: Final[dict[str, str]] = {
    # 000 Computer science, information and general works
    "000": "Computing",
    "010": "Reference",
    "020": "Reference",
    "030": "Reference",
    # 040 is unassigned in the schedule.
    "050": "Journalism",
    # 060 is associations and museums, which no seeded tag means.
    "070": "Journalism",
    # 080 quotations and 090 rare books describe a format, not a subject.
    # 100 Philosophy and psychology
    "100": "Philosophy",
    "110": "Philosophy",
    "120": "Philosophy",
    "130": "Paranormal",
    "140": "Philosophy",
    "150": "Psychology",
    "160": "Philosophy",
    "170": "Ethics",
    "180": "Philosophy",
    "190": "Philosophy",
    # 200 Religion
    "200": "Religion",
    "210": "Religion",
    "220": "Religion",
    "230": "Religion",
    "240": "Religion",
    "250": "Religion",
    "260": "Religion",
    "270": "Religion",
    "280": "Religion",
    "290": "Religion",
    # 300 Social sciences
    "300": "Sociology",
    # 310 is collections of general statistics.
    "320": "Politics",
    "330": "Economics",
    "340": "Law",
    "350": "Politics",
    "360": "Sociology",
    "370": "Education",
    "380": "Business",
    "390": "Folklore",
    # 400 Language
    "400": "Language",
    "410": "Linguistics",
    "420": "Language",
    "430": "Language",
    "440": "Language",
    "450": "Language",
    "460": "Language",
    "470": "Language",
    "480": "Language",
    "490": "Language",
    # 500 Science
    "500": "Science",
    "510": "Mathematics",
    "520": "Astronomy",
    "530": "Physics",
    "540": "Chemistry",
    "550": "Science",
    "560": "Biology",
    "570": "Biology",
    "580": "Biology",
    "590": "Biology",
    # 600 Technology
    "600": "Technology",
    "610": "Medicine",
    "620": "Technology",
    # 630 is agriculture, whose library facing half is 635, garden crops.
    "630": "Gardening",
    # 640 is home and family management, and 641, food and drink, is most of it.
    "640": "Cooking",
    "650": "Business",
    "660": "Chemistry",
    "670": "Technology",
    "680": "Technology",
    "690": "Architecture",
    # 700 Arts and recreation
    "700": "Art",
    "710": "Urbanism",
    "720": "Architecture",
    "730": "Art",
    "740": "Design",
    "750": "Art",
    "760": "Art",
    "770": "Photography",
    "780": "Music",
    "790": "Sports",
    # 800 Literature
    "800": "Fiction",
    "810": "Fiction",
    "820": "Fiction",
    "830": "Fiction",
    "840": "Fiction",
    "850": "Fiction",
    "860": "Fiction",
    "870": "Classic",
    "880": "Classic",
    "890": "Fiction",
    # 900 History and geography
    "900": "History",
    "910": "Travel",
    "920": "Biography",
    "930": "History",
    "940": "History",
    "950": "History",
    "960": "History",
    "970": "History",
    "980": "History",
    "990": "History",
}
