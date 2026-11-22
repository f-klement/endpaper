"""The accession number: the code that names one physical copy, and its rules.

A Book row is the copy (`docs/data-model.md`, Copies), so the code is a column
on `books`, minted from the row id by `mint` and by nothing else. Pure: no
database, no application import, so `models` can take its width from here and
`frontend/src/lib/accession.ts` can mirror it line for line.
`conformance/cases/accession.json` pins the two to the same answers.

## The shape: nine ASCII digits, `2`, a seven digit serial, a Damm check digit

* **Nine long.** Every length a book or retail barcode carries is excluded: 6
  and 8 (UPC-E, EAN-8, ISSN), 10 (ISBN-10), 12 (UPC-A), 13 (EAN-13). So a
  scanned string is told from an ISBN by its length before any lookup.
* **Lead digit `2`** reserves the minted range. A typed scheme for labels a
  library already has can take another lead digit later and is refused inside
  `2`, so it can never collide with a minted code.
* **The serial is the zero padded row id.** Ids are never reused
  (`sqlite_autoincrement`, revision `0850786d1753`), so a code is unique for
  life with no counter of its own and no lock. **Unique for life holds across a
  restore** (owner, 2026-11-22): a backup archive carries the books counter's
  highest issued id, and a restore onto a fresh database raises the counter to
  it, so a purged copy's code is never minted again. `backup._issued_marks`
  says what an archive taken before that mark existed gives up.
* **Damm, not Luhn.** Damm misses no single digit error and no adjacent
  transposition; Luhn misses `09`/`90`, measured at 289 of 14441
  transpositions over nine digit codes.

**The check digit is the data's, not the symbol's.** A keyboard wedge drops the
barcode's own checksum, and a person keys the digits by hand when a label is
torn; this digit is what refuses a mistyped code at the desk rather than
resolving it to another copy.

**Digits are ASCII only.** Python's `\\d` and `str.isdigit()` admit an Arabic
Indic zero that JavaScript's `[0-9]` refuses; `conformance/README.md` has the
measurement from the ISBN side.
"""

import re
from typing import Final, Literal

import isbn

#: What a minted code starts with. A second scheme takes another digit.
#:
#: **An int, not the one character string.** A module level `"2"` is what
#: `test_house_rules.py::TestOneReaderPerAmbiguousSubfield` refuses, since in
#: MARC it is the subfield code whose meaning depends on its field, and that
#: rule admits no `<module>` site.
LEAD: Final = 2
#: Ten million codes per installation.
SERIAL_DIGITS: Final = 7
#: Where the serial starts in a code, counted from 0: after the lead digit.
SERIAL_START: Final = len(str(LEAD))
#: The width of `books.accession`: lead, serial, check digit.
ACCESSION_LENGTH: Final = SERIAL_START + SERIAL_DIGITS + 1

#: What `classify` drops from either end: ASCII space and every C0 control.
#:
#: **Pinned, not `str.strip()`**, because Python's and JavaScript's sets differ
#: both ways: `strip()` drops U+001C to U+001F and keeps U+FEFF, and `trim()`
#: does the opposite. A keyboard wedge sends U+001D for a Code 128 FNC1, so with
#: either default the server and the browser would classify one scan two ways.
_WEDGE_NOISE: Final = "".join(map(chr, range(ord(" ") + 1)))

#: The symbologies a label may carry, in the conformance case's spelling. Code
#: 128 packs digit pairs and is narrower; Code 39 is what older scanners and
#: many label stocks assume. Which one a label prints is the label stock's
#: (owner, 2026-11-22), so the camera has to read both: `ACCESSION_FORMATS` in
#: `frontend/src/pages/ScanPage/components/BarcodeScanner.tsx` is that set, and
#: both conformance runners hold it and this to the case file. **Nothing prints
#: from this yet and nothing reads that**: they are what ticket 31's label
#: printer must print from and ticket 26's label reader must read, and until
#: both do, the guard holds two declarations together rather than a printer to
#: a camera.
LABEL_SYMBOLOGIES: Final[tuple[str, ...]] = ("code128", "code39")

#: Damm's quasigroup of order 10, weakly totally antisymmetric: the table every
#: published Damm implementation uses.
_DAMM: Final[tuple[tuple[int, ...], ...]] = (
    (0, 3, 1, 7, 5, 9, 8, 6, 4, 2),
    (7, 0, 9, 2, 1, 5, 4, 8, 6, 3),
    (4, 2, 0, 6, 8, 7, 1, 3, 5, 9),
    (1, 7, 5, 0, 9, 8, 3, 4, 2, 6),
    (6, 1, 2, 3, 0, 4, 5, 9, 7, 8),
    (3, 6, 7, 4, 2, 0, 9, 5, 8, 1),
    (5, 8, 6, 9, 7, 2, 0, 1, 3, 4),
    (8, 9, 4, 5, 3, 6, 2, 0, 1, 7),
    (9, 4, 3, 8, 6, 1, 7, 2, 0, 5),
    (2, 5, 8, 1, 4, 3, 6, 7, 9, 0),
)

#: `re.ASCII` is what makes `[0-9]` mean what it says here: see the module docstring.
_SHAPE: Final = re.compile(rf"{LEAD}[0-9]{{{ACCESSION_LENGTH - 1}}}", re.ASCII)

#: The largest row id a code can carry.
MAX_SERIAL: Final = 10**SERIAL_DIGITS - 1

#: What a scanned or typed string is, before any lookup.
Reading = Literal["accession", "isbn", "unreadable"]


def _damm(digits: str) -> int:
    interim = 0
    for digit in digits:
        interim = _DAMM[interim][int(digit)]
    return interim


def mint(book_id: int) -> str:
    """The accession number of the Book with this id.

    Raises past `MAX_SERIAL` rather than widening, because a tenth digit would
    make a code ten long, which is an ISBN-10's length and the one property the
    shape exists for. `routers/books._bulk_assign_accession` skips such a row.
    """
    if not 0 < book_id <= MAX_SERIAL:
        raise ValueError(f"{book_id} is outside the range an accession number can carry")
    body = str(LEAD) + str(book_id).zfill(SERIAL_DIGITS)
    return body + str(_damm(body))


def is_accession(text: str) -> bool:
    """Whether `text` is, exactly, a minted accession number with a sound check digit."""
    return _SHAPE.fullmatch(text) is not None and _damm(text) == 0


def classify(text: str) -> Reading:
    """What a scanned or typed string names: a copy, a book by ISBN, or nothing.

    `_WEDGE_NOISE` is dropped from either end, since a keyboard wedge ends its
    digits with a newline and may open them with a group separator. Nothing
    inside is: a code with a space inside it was not printed by this app. The
    two answers cannot overlap, because no ISBN is nine characters long.
    """
    stripped = text.strip(_WEDGE_NOISE)
    if is_accession(stripped):
        return "accession"
    if isbn.parse(stripped) is not None:
        return "isbn"
    return "unreadable"
