"""MARC21 records in and out, as pure functions over bytes.

**Field reading is not written here.** `marc_fields.py` already parses MARCXML
for four catalogues, and a second parser would be a second set of field
decisions to keep in step. This module reuses it, through the door rather than
past it: what is left here is the upload's own policy, which refuses a record
with no title and nothing else.

**What the writer emits is deliberately narrow.** It carries the bibliographic
fields this app stores and nothing about the copy: no shelf mark, no price, no
acquisition source. That is what lets the SRU server reuse it for a public record,
and `tests/test_sru.py` pins the property so adding one fails there.

**Round tripping is the test and it is the strongest available**: export a book,
import it into an empty catalogue, compare. A field the writer forgets and the
reader ignores is invisible to any other check.

**Nothing here touches the database.** Pure functions over bytes, which is why
both an export and an SRU response can call them.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from xml.etree import ElementTree

import bibliographic
import marc_fields
import metadata
from catalogue import Heading, Record
from enums import ClassificationScheme
from marc_fields import Fields, Subfields

if TYPE_CHECKING:  # pragma: no cover
    from models import Book

logger = logging.getLogger("endpaper.marc")


class MarcError(Exception):
    """The upload cannot be read as MARC at all.

    Distinct from a record this reader skipped: one bad record costs one
    record, and this is the whole file being the wrong thing. Mirrors
    `csv_import.ImportError_`, which the route turns into a 400 for the same
    reason: "0 books imported" tells somebody who picked the wrong file
    nothing.
    """


#: The most records one upload may carry.
#:
#: **Refused past this rather than truncated, which is the opposite of
#: `csv_import.MAX_ROWS` and is deliberate.** A truncated reading history is a
#: partial reading history and the rows that were dropped are still that
#: person's own. A truncated catalogue exchange is an institution being told it
#: transferred its holdings when 20,000 of them arrived and the rest did not,
#: silently. The cataloguer can split the file; nobody can notice a silence.
#:
#: The same 20,000 the CSV reader allows, so one upload cannot become an
#: unbounded import by changing format.
MAX_RECORDS: Final = 20_000

#: How many Books the export holds at once.
#:
#: **A bound on the server's memory, not on the size of the shelf**, and that
#: is the whole difference between this and `MAX_RECORDS` above. An upload is
#: volume a stranger chose and the cataloguer can split the file. A shelf is
#: the member's own and there is nothing for them to split, so refusing past a
#: count would take the export away from exactly the deployment library mode
#: exists for: the library in library mode is the instance with the most
#: books.
#:
#: **100 is a query page, and what it costs at the worst is measured rather
#: than assumed.**
#: `tests/routers/test_imports_marc.py::TestThePageSizeThatBoundsTheExport`
#: builds the widest record a write through the API can produce, reading every
#: bound off its declaration rather than retyping it, and fails past 12 MiB a
#: page:
#:
#: | a record of | one record | a page of 100 |
#: |---|---|---|
#: | `w`, one byte a character | 16,611 B | 1.58 MiB |
#: | `ä`, two | 31,201 B | 2.98 MiB |
#: | `&`, which `ElementTree` writes as five | 74,971 B | 7.15 MiB |
#: | `&` and 250 credited names | 102,107 B | 9.74 MiB |
#:
#: **Widest is two questions, and the second is the one that bites.** How wide
#: a field may be is a `max_length`, and a `max_length` counts characters
#: where a page counts bytes, which is the first three rows. **How many fields
#: a record has is not a length at all**: `700` repeats once per credited
#: name, `_credited_names` splits `author` on commas, and nothing bounds the
#: count inside `AUTHOR_LINE_MAX`, so 500 characters is up to 250 names and
#: each one costs its scaffolding rather than its bytes. That is the last row,
#: 36% over a ceiling taken on the third, and both critic seats found it
#: independently in the round that had just fixed the first question.
#:
#: **The 12 MiB is a tripwire on the record's shape, not a platform limit.**
#: Nothing enforces it at runtime and no deployment was measured against it.
#: What it does is fail when a field is added to the writer, or made
#: repeatable, or given a wider bound, so that the numbers above stop being
#: quietly wrong. The room it leaves is **a quarter**, not a half: 12 MiB
#: admits 123 of today's widest record against the 100 written here, which is
#: the same 1.23 either way.
#:
#: **The page's bytes are not its peak.** Building it holds every record's
#: string and the joined result at once, measured at 24.01 MiB for the 9.74
#: MiB worst case, 2.47 times. The route table below is a typical page rather
#: than this one, so the worst case for one export is of the order of 25 MB of
#: strings plus its page of rows, and it does not move with the shelf, which
#: is the property the paging is for.
#:
#: **A stored row beats all of it, and the bound is on writes.** Two of these
#: numbers are ceilings the API applies and the restore path does not, because
#: `backup.py` inserts through Core: `DESCRIPTION_MAX` is a `max_length` on
#: the schema over a `Text` column, deliberately, so it needs no migration and
#: cannot make a stored book uneditable, and `MAX_CLASSIFICATIONS_PER_BOOK` is
#: checked on every API path and on no restored row. `models.py` records a
#: 3,000,256 byte description that reached the table before its ceiling
#: existed, and 32 classification rows on an otherwise widest record is 13.75
#: MiB a page. Neither is a shape this number defends against, and no count
#: would be.
#:
#: **What paging buys, measured through the route** on one node, single
#: process, real ORM over SQLite, `Loading.PUBLISHED`, `tracemalloc` peak
#: above the baseline, descriptions of 200 characters:
#:
#: | books | whole shelf | paged |
#: |---|---|---|
#: | 10,000 | 55.05 MiB | 1.02 MiB |
#: | 20,000 | 109.67 MiB | 1.03 MiB |
#: | 40,000 | 219.06 MiB | 1.05 MiB |
#:
#: One rises with the shelf and the other does not. **A smaller page costs
#: queries and almost no wall clock**: over 40,000 books, database work only,
#: the walk is 4.19 seconds in pages of 500 and 6.03 in pages of 100, against
#: roughly 32 seconds of serialisation either way.
#:
#: **What it does not bound is the download and the time.** A shelf of any
#: size still serialises in full, because the alternatives are a refusal and a
#: silence. See `docs/decisions.md` §The MARCXML export is paged rather than
#: capped for why that trade was taken and what each of the others would have
#: cost.
EXPORT_PAGE_RECORDS: Final = 100

#: The leader every record this app writes carries, 24 characters.
#:
#: Positions, per the MARC21 Bibliographic specification, "Leader":
#:
#: | 00 to 04 | `00000` | record length, computed by an ISO 2709 writer and meaningless in MARCXML |
#: | 05 | `n` | status: new |
#: | 06 | `a` | type: language material |
#: | 07 | `m` | bibliographic level: monograph |
#: | 08 | space | type of control: none |
#: | 09 | `a` | character coding: Unicode |
#: | 10 | `2` | indicator count |
#: | 11 | `2` | subfield code count |
#: | 12 to 16 | `00000` | base address of data, as 00 to 04 |
#: | 17 | `3` | encoding level: abbreviated |
#: | 18 | space | descriptive cataloguing form: non ISBD |
#: | 19 | space | multipart resource record level: not specified |
#: | 20 to 23 | `4500` | entry map, fixed by the standard |
#:
#: **17 is `3` and that is an honest claim rather than a default.** A record
#: this app writes carries a title, an author, a publisher and a date. It
#: carries no physical description beyond a page count, no notes field, no
#: series statement in `490` and no `008`. That is an abbreviated level record,
#: and coding it as full level (space) would tell the receiving cataloguer they
#: need not check it.
LEADER: Final = "00000nam a22000003  4500"

#: MARCXML's namespace, which `marc_fields` reads and this writes.
#:
#: Written as the default namespace on `<collection>` so a record reads as the
#: specification prints it. Taken from `marc_fields.NAMESPACE` rather than
#: spelled again: a reader and a writer disagreeing about the namespace produce
#: a file this app cannot read back, and the round trip test would be the only
#: thing that noticed.
NAMESPACE: Final = marc_fields.NAMESPACE

#: How a GND number is written back into `$0`, and the scheme name for `$2`.
#:
#: `marc_fields.GND_PREFIX` is the reader's half. Stored bare in
#: `classifications.number`, so the prefix is put back on the way out: `$0`
#: without it names no authority file and the reader drops it.
_GND_PREFIX: Final = marc_fields.GND_PREFIX

#: `$2` values naming the vocabulary a `650` heading came from.
#:
#: Required whenever the second indicator is `7`, which is what "source
#: specified in subfield $2" means. Without it a receiving system has a heading
#: string and no way to know which thesaurus authorised it.
_SUBJECT_SOURCE: Final[dict[ClassificationScheme, str]] = {
    ClassificationScheme.GND: "gnd",
    ClassificationScheme.LCSH: "lcsh",
}


#: Characters XML 1.0 cannot carry, whatever the encoding.
#:
#: **A guard on the writer rather than on the column, and it is the file's
#: validity at stake rather than a display glitch.** `ElementTree` serialises a
#: control character verbatim into the output, so one `\x0c` anywhere in a
#: member typed description produces a download no XML parser will read,
#: including this app's own reader. Nothing upstream refuses them: a
#: description is `Text` with no character class, and a catalogue's `520` is
#: whatever that catalogue sent.
#:
#: Tab, newline and carriage return are legal and are left alone. Everything
#: else below U+0020, plus the surrogate and non-character code points, is
#: dropped.
_ILLEGAL_XML: Final = re.compile(
    "[^\x09\x0a\x0d\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]"
)


def _text(value: object) -> str:
    """One subfield's value, as MARCXML may carry it.

    Normalised to NFC, because `marc_fields` normalises what it reads:
    a round trip through two different normal forms compares unequal while
    rendering identically, which is the defect that measurement records for the
    DNB. Control characters dropped: see `_ILLEGAL_XML`.
    """
    text = "" if value is None else str(value)
    return _ILLEGAL_XML.sub("", unicodedata.normalize("NFC", text))


def _datafield(
    tag: str, ind1: str, ind2: str, subfields: Iterable[tuple[str, object]]
) -> ElementTree.Element | None:
    """One `<datafield>`, or None if every subfield of it is empty.

    A field with no content is not a field. Returning None rather than an empty
    element keeps the caller a flat list of mappings instead of a chain of
    conditionals, and it means a Book with no publisher writes no `264` rather
    than one whose publisher is the empty string.
    """
    written = [(code, _text(value)) for code, value in subfields if _text(value)]
    if not written:
        return None
    field = ElementTree.Element(
        # A dict rather than keyword arguments: `Element`'s own first parameter
        # is called `tag`, so `tag=` would be the element name and not the
        # attribute MARCXML wants.
        "datafield",
        {"tag": tag, "ind1": ind1, "ind2": ind2},
    )
    for code, value in written:
        ElementTree.SubElement(field, "subfield", {"code": code}).text = value
    return field


def _credited_names(author: str | None) -> list[str]:
    """The `author` column split back into the people it names.

    **The exact inverse of `Fields.authors`**, which joins the names it
    read with `", "`. So a record this app wrote, read back and written again
    names the same people in the same order.

    The ambiguity this cannot resolve is worth stating rather than hiding: the
    column is one free text field, so `"Williams, John"` is either one person
    typed in catalogue order or two people called Williams and John.
    `bibliographic.flip_catalogue_name` has already turned every name **this app
    parsed** into direct order, so a comma in a stored value is the multiple
    author case for everything the app itself wrote. A member who typed a name
    in catalogue order is split, and that is the cost of the column being one
    string rather than a table.

    **Duplicates are kept where `authors.split_authors` drops them**, so a
    stored `"Tolkien, Tolkien"` is one author on a card and two `700` fields
    here. Left as it is: this serialises the column and the column says what
    it says, and a writer quietly disagreeing with the card would be a second
    answer to who wrote the book. It is also what makes the repeated field
    `EXPORT_PAGE_RECORDS` is measured against reachable.
    """
    return [name.strip() for name in (author or "").split(",") if name.strip()]


def _record_element(book: Book) -> ElementTree.Element:
    """One Book as a `<record>`.

    The mapping, in the order MARC prints it. Every row names the reader that
    takes it back, because a field written with no reader is a field the round
    trip cannot prove and the next person cannot trust.

    | Field | From | Read back by |
    |---|---|---|
    | `001` | `books.id` | nothing: it identifies the record in this system |
    | `020 $a` | `isbn` | `Fields.isbn` |
    | `041 0# $a` | `language` | `Fields.language` |
    | `050 #4 $a` | an `lcc` classification | this module's `_classifications` |
    | `082 04 $a` | a `ddc` classification | `Fields.ddc_headings` |
    | `100 0# $a` | the first credited name | `Fields.authors` |
    | `245 10 $a $b $n $p` | `title`, `subtitle`, `series_index`, `series_name` | `Fields.title_statement` |
    | `264 #1 $b $c` | `publisher`, `year` | `Fields.publisher`, `Fields.year` |
    | `300 ## $a` | `page_count` | `bibliographic.pages_from_extent` |
    | `520 ## $a` | `description` | `Fields.description` |
    | `650 #7 $a $0 $2` | a `gnd` or `lcsh` classification | `Fields.controlled_subjects`, this module |
    | `700 0# $a $4` | every credited name after the first | `Fields.authors` |

    **`100` and `700` carry first indicator `0`, "forename".** That is the
    specification's name for a personal name in direct order, which is what
    `books.author` holds: `bibliographic.flip_catalogue_name` turns
    `Williams, John` into `John Williams` on the way in, and nothing here can
    turn it back without guessing which word is the surname. Coding it `1`,
    "surname", would tell a receiving cataloguer the name is inverted when it
    is not, and their filing would be wrong for every author with more than one
    forename.

    **`700` carries `$4 aut`.** `Fields` reads a `700`
    only when its relator code says the person wrote the thing, since
    translators and editors arrive in the same field. Without `$4` every author
    after the first is dropped on the way back in, and the batch would look
    correct: one author instead of three, with nothing failing.

    **`245` uses `$n` and `$p` for a series, which is what the reader does.**
    `Fields.title_statement` treats `$a` as the collective title and `$p` as the
    part somebody is holding, so a Book with a series writes the series name in
    `$a` and its own title in `$p`. Writing the title in `$a` and the series
    somewhere else would read back as a book whose title is the series.

    **The second indicator of `245` is `0`, not the number of non-filing
    characters.** `marc_fields` strips the non-sorting delimiters on the
    way in, so a stored title begins at its first character and there is nothing
    for a receiving system to skip. A non-zero count here would make it skip
    real letters.
    """
    record = ElementTree.Element("record")
    ElementTree.SubElement(record, "leader").text = LEADER
    ElementTree.SubElement(record, "controlfield", {"tag": "001"}).text = str(book.id)

    names = _credited_names(book.author)
    language = bibliographic.BIBLIOGRAPHIC_CODES.get((book.language or "").lower())

    fields = [
        _datafield("020", " ", " ", [("a", book.isbn)]),
        _datafield("041", "0", " ", [("a", language)]),
        *_classifications(book),
        _datafield("100", "0", " ", [("a", names[0] if names else None)]),
        _datafield(
            "245",
            # First indicator 1 whenever a 1XX exists, which is what it means:
            # "the title is also an added entry because the main entry is
            # somebody's name". 0 on a Book with no author at all.
            "1" if names else "0",
            "0",
            (
                [
                    ("a", book.series_name),
                    ("n", _series_number(book.series_index)),
                    ("p", book.title),
                    ("b", book.subtitle),
                ]
                if book.series_name
                else [("a", book.title), ("b", book.subtitle)]
            ),
        ),
        _datafield("264", " ", "1", [("b", book.publisher), ("c", book.year)]),
        _datafield("300", " ", " ", [("a", _extent(book.page_count))]),
        _datafield("520", " ", " ", [("a", book.description)]),
        *_subject_fields(book),
        *(
            _datafield("700", "0", " ", [("a", name), ("4", "aut")])
            for name in names[1:]
        ),
    ]
    for field in fields:
        if field is not None:
            record.append(field)
    return record


def _series_number(index: float | None) -> str | None:
    """A series index as `245 $n` writes it.

    Whole numbers without the decimal point, because `3.0` is not how a volume
    is numbered and `Fields.title_statement` reads the first digit run anyway, so
    `3.5` reads back as 3. **A fractional index does not survive the round
    trip**, and that is a property of `$n` being free text rather than something
    this writer can fix: the field carries `Bd. 3` and `[1]` in real records.
    """
    if index is None:
        return None
    return str(int(index)) if index == int(index) else str(index)


def _extent(page_count: int | None) -> str | None:
    """A page count as `300 $a` writes it.

    `bibliographic.pages_from_extent` requires the unit and takes the digit run
    before it, so the string has to name pages rather than being a bare number:
    a bare number reads back as nothing at all.
    """
    return None if page_count is None else f"{page_count} pages"


def _classifications(book: Book) -> Iterator[ElementTree.Element | None]:
    """The shelf notations: `082` for Dewey, `050` for Library of Congress.

    Separate fields rather than one, because they are separate schedules and a
    receiving system shelves by one of them. Repeatable: a book often carries
    two Dewey numbers at different precisions from two catalogues, and both are
    the catalogues' answers rather than a duplicate.
    """
    for entry in book.classifications:
        # **Coerced, never compared raw.** `classifications.scheme` is a plain
        # `String(20)` column, so a stored row hands back a `str` and not a
        # `ClassificationScheme`. `is` against the enum is then False for every
        # row and the export writes no call number at all, with a 200 and
        # nothing in the log. `classifications.add_headings` states the same
        # trap from the writing side; this is the reading side of it.
        scheme = ClassificationScheme(entry.scheme)
        if scheme is ClassificationScheme.DDC:
            # ind1 `0`: full edition. ind2 `4`: assigned by an agency other
            # than the Library of Congress, which is what this app is.
            yield _datafield("082", "0", "4", [("a", entry.number)])
        elif scheme is ClassificationScheme.LCC:
            yield _datafield("050", " ", "4", [("a", entry.number)])


def _subject_fields(book: Book) -> Iterator[ElementTree.Element | None]:
    """The subject headings: `650`, with `$2` naming the vocabulary.

    **`$a` is the caption and `$0` is the identifier, which is the same split
    the table stores.** A GND row keeps its number in `$0` with the
    `(DE-588)` prefix put back on, because that prefix is how MARC says which
    authority file a number belongs to and `Subfields.gnd_identifier` reads
    nothing without it.

    **A GND row with no caption writes no field, and cannot.** `650` without
    `$a` is a heading with no heading; `Fields.controlled_subjects` skips it, and so
    does every other reader. `Classification.label` is nullable and a MARC `082`
    supplies none, so this is reachable: a Book whose GND row arrived without a
    caption exports without that subject. Writing the number into `$a` instead
    would put an identifier where a receiving catalogue prints a phrase.
    """
    for entry in book.classifications:
        # Coerced for `_classifications`'s reason: a stored scheme is a `str`.
        scheme = ClassificationScheme(entry.scheme)
        source = _SUBJECT_SOURCE.get(scheme)
        if source is None:
            continue
        # LCSH stores the authorised heading string itself as `number`, since
        # the record carries no identifier for one. So the caption is the
        # number there and the label everywhere else, which is
        # `ClassificationScheme` saying the same thing from the other side.
        caption = entry.number if scheme is ClassificationScheme.LCSH else entry.label
        identifier = (
            f"{_GND_PREFIX}{entry.number}" if scheme is ClassificationScheme.GND else None
        )
        # ind2 `7`: the source of the heading is named in `$2`.
        yield _datafield(
            "650", " ", "7", [("a", caption), ("0", identifier), ("2", source)]
        )


def record_element(book: Book) -> ElementTree.Element:
    """One Book as a `<record>` that carries its own namespace declaration.

    For a caller embedding a single record in a document of its own, which is
    what `sru.py` does: SRU wraps each record in its own `<recordData>` rather
    than handing over a `<collection>`.

    **The namespace goes on the record and not on the caller's root**, because
    the caller's root is in a different namespace. Written as a plain `xmlns`
    attribute for the reason `write` declares it the same way: everything
    `_record_element` builds carries an unqualified tag, so a parent whose own
    elements are namespace qualified would otherwise swallow the whole MARC
    subtree into the parent's default namespace with nothing failing.

    Nothing here filters, for the same reason nothing in `write` does. The
    caller resolved the Book through the Shelf.
    """
    record = _record_element(book)
    record.set("xmlns", NAMESPACE)
    return record


def _wrapper() -> tuple[str, str]:
    """The two halves of the `<collection>` a streamed export is written into.

    **Cut out of the empty document rather than spelled.** A streaming writer
    never holds the whole element, which is the point of it, so the wrapper has
    to be produced without one. Writing it as a literal would put the XML
    declaration's quoting, the attribute's quoting and the namespace in a
    second place to keep in step with `ElementTree`, and this repository has
    paid repeatedly for a rule that lists the spellings of something it could
    derive. So the empty collection is serialised once, at import, by the same
    call that serialises every record, and split at its closing tag.

    `short_empty_elements=False` is what makes that split exist: without it an
    element with no children is written `<collection ... />` and there is no
    closing tag to cut at. It is also why `write([])` now ends in an explicit
    closing tag where it used to self close. The same document, and the only
    difference this derivation makes to any output.
    """
    empty = ElementTree.tostring(
        ElementTree.Element("collection", {"xmlns": NAMESPACE}),
        encoding="unicode",
        xml_declaration=True,
        short_empty_elements=False,
    )
    cut = empty.rindex("</")
    return empty[:cut], empty[cut:]


_COLLECTION_OPEN, _COLLECTION_CLOSE = _wrapper()


def stream(pages: Iterable[Iterable[Book]]) -> Iterator[str]:
    """A shelf as one MARCXML `<collection>`, a page of Books at a time.

    Takes Books somebody else resolved, which for the export route means
    `Shelf.seen_by`. Nothing here filters, and nothing here may: a serialiser
    that decided visibility would be a second answer to the question
    `shelf.py` exists to answer once.

    **No `<collection>` element is ever built**, so the peak is one page of
    XML rather than a tree over the whole shelf, which was the other half of
    the cost: an `Element` tree is several times the size of the string it
    prints to.

    **Pages rather than a flat sequence of Books, because the page is the
    chunk.** One string is yielded per page and not one per record: a
    `StreamingResponse` over a sync iterator hands every chunk to
    `anyio.to_thread.run_sync`, one ASGI `send` and two more hops through this
    app's `SecurityHeadersMiddleware`. Measured over 20,000 records, that
    dispatch is 3,064 ms in total when the chunk is a record against 5.7 ms
    when it is a page. **Nothing here reads a page's length**, so this
    signature asks the caller to have chosen one rather than enforcing a size:
    `write` below hands over the whole shelf as a single page and is right to.

    **Any failure is loud at the receiver, and that is a property of writing
    the closing tag last.** The opening tag is yielded before `pages` is
    touched at all, and a `StreamingResponse` sends its status line before it
    pulls a chunk, so **every** failure from here on answers 200: not only one
    part way through, but the walk's very first query coming back an error.
    What each leaves is a `<collection>` that is never closed, which no XML
    parser accepts, so a half written catalogue exchange is a parse error on
    the cataloguer's side rather than a short file that reads as complete.
    That is the silence `docs/decisions.md` refuses for an oversized upload,
    and it is the trade streaming makes: a clean 500 for a body that cannot be
    mistaken for a whole one. Anything watching this route has to read the
    body rather than the status.

    A record's tags are unqualified and the namespace is declared once on the
    wrapper, so a record serialised on its own here is correct only inside
    that wrapper. `record_element` is the function for a caller that needs a
    record to stand alone.
    """
    yield _COLLECTION_OPEN
    for page in pages:
        yield "".join(
            ElementTree.tostring(_record_element(book), encoding="unicode")
            for book in page
        )
    yield _COLLECTION_CLOSE


def write(books: Iterable[Book]) -> str:
    """A shelf as one MARCXML `<collection>`, whole.

    **No production caller, and that is the state of it rather than an
    omission.** The export route reached for this and was the defect: a
    function that materialises a document has no bound, and the shelf it was
    handed had none either. `sru.py` embeds one record at a time through
    `record_element`. What is left is `tests/test_marc.py`, which exports a
    Book and reads it back through the parser that reads live DNB and K10plus
    answers, and needs a document to do it.

    **A route wanting MARCXML wants `stream`.** That is not advice this
    docstring can enforce, so it is enforced next to it:
    `tests/routers/test_imports_marc.py::TestNoProductionModuleWritesAWholeCollection`
    parses every module outside the tests and fails on a call to this.

    One page handed to `stream`, so there is one serialisation of a collection
    here and not two to keep in step.
    """
    return "".join(stream([books]))


# ── Reading ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ParsedMarc:
    """What an uploaded file turned out to hold.

    `skipped` is the count of records this reader could not turn into a book,
    which is almost always a record with no `245 $a`. Counted rather than
    dropped silently, so the summary adds up to the number of records in the
    file and a cataloguer can tell "we took 400 of 400" from "we took 400 of
    412".
    """

    records: tuple[Record, ...]
    skipped: int

    @property
    def total(self) -> int:
        return len(self.records) + self.skipped


#: How much of the file is sniffed for the two shapes that are refused outright.
#:
#: A prolog and a doctype are both in the first few hundred bytes of any real
#: file. The scan is over the whole content for the doctype and over this
#: prefix for the encoding check, because the second is about how the bytes are
#: encoded and the answer is decided by the first four of them.
_SNIFF: Final = 1024

#: `metadata.DOCTYPE` as bytes, because an upload is parsed from bytes.
#:
#: **From that constant rather than spelled again.** It is the same construct
#: being refused for the same reason, and two spellings of it would let one be
#: tightened while the other stayed as it was.
_DOCTYPE_BYTES: Final = metadata.DOCTYPE.encode("ascii")


def _parsed(content: bytes) -> ElementTree.Element:
    """The upload as an element tree, refusing what makes its size a lie.

    **Parsed from bytes, not from text, and that is load bearing rather than a
    convenience.** `ElementTree.fromstring` raises `ValueError` on a `str`
    carrying an encoding declaration, and every MARCXML file in the world
    carries one, including the ones this module writes. Decoding first and
    parsing the result would fail on the app's own export.

    Two refusals, in this order:

    * **A NUL byte in the first kilobyte.** That is a UTF-16 or UTF-32 file,
      and it is refused rather than supported for one reason: the doctype check
      below is a byte scan, so it is exact for the ASCII compatible encodings
      and blind to the others. Refusing the encodings the scan cannot see is
      what makes the scan a guarantee rather than a guess. No catalogue writes
      MARCXML in UTF-16.
    * **A doctype anywhere.** `xml.etree` expands internal entities, so a
      5 MB upload carrying one can define an entity worth a thousand times its
      own bytes, and the upload cap stops bounding the cost. `metadata._parsed`
      records the measurement: ten characters nested six deep expand to a
      million. An upload is a larger surface than a catalogue response, not a
      smaller one, so this is the same refusal applied where it matters more.
    """
    if b"\x00" in content[:_SNIFF]:
        raise MarcError(
            "That file is not text this reader can take. MARCXML is written in "
            "UTF-8."
        )
    if _DOCTYPE_BYTES in content:
        raise MarcError("That file carries a document type declaration, which is refused.")
    try:
        return ElementTree.fromstring(content)  # noqa: S314  doctype refused above, bytes capped
    except (ElementTree.ParseError, ValueError) as error:
        # **`ValueError` as well as `ParseError`, and it is not defensive.**
        # `ElementTree.fromstring` raises `ValueError("multi-byte encodings are
        # not supported")` for any XML declaration naming one, EUC-JP, Shift_JIS,
        # gb2312, big5 and UTF-7 among them. Measured through the route: without
        # this arm a 92 byte body is a **500** with a traceback, where the
        # documented answer to an encoding this reader refuses is a 400.
        raise MarcError(f"That file is not XML this reader can take: {error}") from error


#: The source name a record read out of an uploaded file carries.
#:
#: `Record.source` names the catalogue that made the assertion. Here that is
#: whoever wrote the file, whom this app cannot know, so it names the format
#: instead. It is deliberately not a catalogue name: writing `"dnb"` on a
#: record somebody uploaded would attribute a stranger's cataloguing to the
#: German National Library.
SOURCE: Final = "marc"


def _call_number(entry: Subfields) -> str | None:
    """An `050` field as one Library of Congress call number.

    `$a` is the classification and `$b` the item number, and they are one
    notation split across two subfields rather than two assertions: `QA76.73`
    and `.P98 2021` name a shelf position together and neither means anything
    alone. Joined with a space, which is how the notation is printed and how
    `classifications.number` already holds one.
    """
    parts = [part for part in (entry.get("a"), entry.get("b")) if part]
    return " ".join(parts) or None


def _extra_headings(fields: Fields) -> list[Heading]:
    """The two schemes `marc_fields.py` has no reader for.

    It reads Dewey from `082` and GND from the subject fields, because those are
    what the catalogues it queries send. A file a library hands over carries the
    other two, and this app has columns for both:

    * `050` is the Library of Congress call number, which is the field a MARC
      export exists to carry: it is what the receiving library shelves by.
    * `650` with `$2 lcsh` and no `$0` is a Library of Congress subject
      heading. `Fields.controlled_subjects` puts its `$a` in `subjects` and writes
      no heading, because it looks for a GND number and there is none. The
      authorised string **is** the identifier for LCSH, which is
      `ClassificationScheme` saying so, so it goes in `number`.

    **The `$2` reader is `Subfields.subject_vocabulary` since #134**, where this
    module used to hold a second copy called `_uncontrolled_source`. Both lower
    cased and both existed to make one vocabulary one string; two copies of that
    is one rule that can drift, and the case folding is exactly the half a
    reader would quietly leave out of the second copy.

    Ordered call number first, which is `classifications.SCHEME_ORDER`
    saying the same thing: a shelf classification outranks a subject heading
    when a book runs out of room.
    """
    headings = [
        Heading(ClassificationScheme.LCC, number)
        for entry in fields.get("050")
        for number in [_call_number(entry)]
        if number
    ]
    headings += [
        Heading(ClassificationScheme.LCSH, heading)
        for entry in fields.get("650")
        if entry.subject_vocabulary("650") == "lcsh"
        and entry.gnd_identifier() is None
        for heading in [bibliographic.strip_isbd_punctuation(entry.get("a", ""))]
        if heading
    ]
    return headings


def _record(fields: Fields) -> Record | None:
    """One MARC record as evidence about a book, or None if it names none.

    **Every scalar is read by `marc_fields.py`**, so a record this app imports
    is read exactly as a record this app looks up is. What is here
    rather than there is the policy that differs, and there are three pieces of
    it.

    **A record with no title is the only thing refused.** `metadata._dnb_record`
    also refuses a title that names a volume slot and refuses a disc, and both
    refusals are right where they are and wrong here. They exist because the
    DNB's `num=` index matches cross references, so the catalogue answers with a
    record about a different object and taking it poisons the entry. An upload
    is a cataloguer handing over their own file. `Bd. 3` may be exactly what
    they catalogued, and a reader that drops rows they will never be told about
    is worse than one that imports a thin record they can see and fix.

    **Author identifiers are not read**, though the field is the same `100 $0`.
    `_k10plus_record` states the rule and `_dnb_record` repeats it: a catalogue
    is not read for a person's identifier until somebody has compared it live.
    Nobody can compare an arbitrary uploaded file, and writing an
    `author_identifiers` entry would put an unverified assertion into the
    authority store where every other entry has been checked.

    **`700` needs `$4 aut` to count as an author**, which is
    `marc_fields.Fields`'s rule and not this reader's. Where nothing
    is credited with writing the book, `Fields.credited_names` names everybody
    the record names, which is what an edited volume looks like in MARC.

    **A fourth divergence is known and not fixed here, because the fix is in
    `marc_fields.py`.** `Fields.isbn` drops the commonest legacy `020 $a` spelling:
    measured, `9783161484100`, `978-3-16-148410-0` and `9783161484100 :` all
    parse, and `9783161484100 (pbk.)` returns None. The ISBD colon is stripped
    and a parenthesised qualifier is not, because that parser was written
    against the DNB and K10plus, which put the qualifier in `$q`. A file another
    library hands over is exactly where the inline spelling lives, and the ISBN
    is this importer's primary match key, so such a record silently falls back
    to the weaker key. Raised as an issue rather than worked around here:
    stripping the qualifier in `marc.py` would be a second notion of what an
    `020` says, which is what this module exists not to build.
    """
    title, subtitle, series_name, series_index = fields.title_statement()
    if not title:
        return None

    subjects, gnd = fields.controlled_subjects()

    # `from_upload`, not `Record(...)`: an over-wide string in a file somebody
    # handed over is cut to the column rather than dropped, because
    # `books.title` is NOT NULL and a dropped title costs the row. The reason in
    # full, and the network path it differs from, are on that classmethod.
    return Record.from_upload(
        source=SOURCE,
        isbn=fields.isbn(),
        title=title,
        subtitle=subtitle,
        author=fields.authors() or fields.credited_names(),
        publisher=fields.publisher(),
        year=fields.year(),
        description=fields.description(),
        language=fields.language(),
        page_count=bibliographic.pages_from_extent(fields.extent()),
        series_name=series_name,
        series_index=series_index,
        subjects=tuple(subjects),
        headings=tuple(fields.ddc_headings() + _extra_headings(fields) + gnd),
    )


def read(content: bytes) -> ParsedMarc:
    """An uploaded MARCXML file as records, counting what it could not read.

    **One unreadable record costs one record.** A file a library hands over is
    the product of years and is not uniformly clean; failing the batch on the
    first record with no `245` would throw away every good one and give the
    cataloguer nothing to act on. This is `csv_import.ParsedFile.skipped`
    applied to a different format for the same reason.

    **The file being the wrong thing entirely is a different answer**, and is
    `MarcError`: no XML, a doctype, an encoding this reader refuses, no
    `<record>` element anywhere, or more records than `MAX_RECORDS`.

    **A scalar is bounded here and a heading is not**, and the two are not one
    rule. `_record` builds through `catalogue.Record.from_upload`, so a title,
    subtitle, author, publisher, description or series name too wide for its
    column is cut to it, and a URL, volume id or language code that a cut would
    rename is dropped instead. `catalogue.Heading` is deliberately unbounded, because a
    400 character heading is a real thing to have parsed and a bad thing to have
    raised on halfway through a file; `classifications.bounded_headings` is
    where an unusable entry is dropped, one layer later, with the whole record
    in hand.
    """
    root = _parsed(content)

    # `iter` rather than `findall`, so a `<record>` reached through a wrapper
    # is found: an SRU response nests them under `<recordData>`, and a
    # cataloguer exporting from their own system may hand over either shape.
    nodes = list(root.iter(marc_fields.RECORD_TAG))
    if not nodes:
        # A bare `<record>` with no namespace is the other real shape, and it
        # is worth naming rather than reporting an empty file: several tools
        # write MARCXML without declaring the namespace, and the difference is
        # invisible in a text editor.
        if root.tag.endswith("record") or any(
            node.tag.endswith("record") for node in root.iter()
        ):
            raise MarcError(
                "That file has records but no MARCXML namespace on them. "
                f"Records must be in {NAMESPACE}."
            )
        raise MarcError("That file holds no MARC records.")

    if len(nodes) > MAX_RECORDS:
        raise MarcError(
            f"That file holds {len(nodes)} records and the limit is "
            f"{MAX_RECORDS}. Split it and import the parts."
        )

    records = []
    skipped = 0
    for node in nodes:
        record = _record(Fields(node))
        if record is None:
            skipped += 1
        else:
            records.append(record)
    if skipped:
        logger.info("Skipped %d MARC records with no title", skipped)
    return ParsedMarc(records=tuple(records), skipped=skipped)
