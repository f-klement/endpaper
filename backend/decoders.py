"""What a decoder is, and it is never told how the bytes arrived.

A **decoder** turns one record of one serialisation into this application's
model. `Reader` is the closed set of them and `Decoding` is the whole of what
one is told. The implementations are in `metadata.py`; this module is the
contract they are held to.

## The contract, and both families are held to it

**One output type.** A decoder answers with `catalogue.Record`, or with `None`
for a record it refuses. Nothing else.

**One bad record fails alone and never the batch.** A record a decoder cannot
read is dropped and its neighbours are still returned, because the alternative
is one malformed row in somebody else's catalogue costing a member every result.

**One capability vocabulary**, `enums.Capability`, which is what a source
declares it can be asked for.

Those three are shared by catalogue sources and by ebook importers.
`enums.SourceFamily` is what is **not** shared, and says why.

## What a decoder may not mention

**A decoder names what it decodes and never how it was fetched.** No URL, no
HTTP status, no file handle, no zip entry, no database cursor, and no
`targets.Target`, which carries an address and a query grammar. It is handed a
parsed record and a `Decoding`.

**The demand is near term rather than hypothetical.** OPF metadata is both what
an EPUB carries inside its zip and what sits loose beside a book in a Calibre
library: one decoder, two interactions, neither of them a catalogue. Weld the
decoder to the source and every new transport multiplies by every format.

**The test the seam is held to** is that a decoder written for a catalogue works
on a file unchanged, and it is run rather than asserted:
`tests/test_decoders.py::TestADecoderWorksOnAFile` reads one MARC record off
disk, builds a `Decoding` by hand with no `Target` anywhere, and gets the record
the live path gets.

## Why there are seven readers and five serialisations

The serialisations are MARC21, Dublin Core, MODS, Open Library's JSON and Google
Books'. Two of them are read two ways.

MARC21 is two profiles here rather than one. `metadata._dnb_record` harvests GND
identified headings across five tags and refuses a title that names a volume
slot; `metadata._k10plus_record` joins `650 $a` and `$x` into one subject, reads
no author identifiers and refuses no volume slot. Folding them would be a
behaviour change dressed as a refactor. Dublin Core is likewise two, namespaced
and bare, because the Czech National Library writes `<record-list><dc-record>`
with no namespace at all and the BnF's selector returns zero against it.

## Why a decoder is a function and not a stylesheet

Koha makes this half data, with `add_xslt`, and this project deliberately does
not: a stylesheet cannot refuse a digitisation that shares an ISBN with the
book. The refusals a row could not express are the decoder's whole reason to be
code: `_marc_claims_isbn`, `_is_placeholder_title`, `_is_physical_book`, the non
sorting bracket conventions, `_isbn_entries`.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class Reader(StrEnum):
    """The parser a source's records are read with.

    Closed, and adding a member is the only part of adding a source that is
    still code. See the module docstring for why MARC21 and Dublin Core are two
    members each.

    **Keyed on here rather than on the source**, which is what makes one decoder
    serve several sources: `MARC_GND` reads the DNB, the ÖNB, the NLG and the
    BNE through one function. It is also what will let one decoder serve two
    families, since a family is a property of the source and not of the parser.
    """

    #: MARC21 through `metadata._dnb_record`: GND identified headings, volume
    #: slot titles refused.
    MARC_GND = "marc_gnd"
    #: MARC21 through `metadata._k10plus_record`.
    MARC_PLAIN = "marc_plain"
    #: Namespaced Dublin Core, `metadata._bnf_record`.
    DUBLIN_CORE = "dublin_core"
    #: Un-namespaced Dublin Core, `metadata._nkp_record`. The Czech National
    #: Library writes `<record-list><dc-record><title>` with no namespace, so
    #: the BnF's selector returns zero against it.
    DUBLIN_CORE_BARE = "dublin_core_bare"
    #: MODS, `metadata._loc_record`.
    MODS = "mods"
    #: Open Library's own JSON.
    OPEN_LIBRARY = "open_library"
    #: The Google Books volumes API.
    GOOGLE_BOOKS = "google_books"


#: The readers that read MARC21, so the two knobs that only a MARC reader can
#: act on, `refuses_component_parts` and `reads_author_identifiers`, can be
#: refused on a row that does not read MARC at all.
#:
#: **Two and not three**, which is the count `Decoding.__post_init__` and
#: `targets.Target._check_no_marc_knobs` both enforce. `requires_isbn_claim` is
#: the third knob and is **not** MARC only: `metadata._dublin_core_bare_lookup`
#: reads it for the Czech National Library, whose reader is `DUBLIN_CORE_BARE`.
MARC_READERS: Final = frozenset({Reader.MARC_GND, Reader.MARC_PLAIN})


@dataclass(frozen=True)
class Decoding:
    """Everything a decoder is told, and the point is what is not here.

    **No address, no transport, no query, no handle.** `targets.Target` carries
    all four and is therefore not what a decoder takes: a signature naming it
    would weld every format to the one way this application currently reaches
    it. `Target.decoding` is the projection, and it is the only place in the
    application that builds one of these from a catalogue row. A file, a zip
    entry or a member's library builds one directly, which is the whole point.

    **`source` is a `str` rather than a `CatalogueSource`**, deliberately and
    load bearing. `catalogue.Record.source` is a string already, and an OPF
    decoder reading a file has no member of that enum to name: typing this field
    as the catalogue registry's key space would put a catalogue's identity into
    the one contract both families share, which is the merge
    `enums.SourceFamily` exists to refuse.

    The three knobs below are the decoder's own settings, and each is measured
    on `targets.Target`'s field of the same name. They are here because a
    decoder reads them and nowhere else does.
    """

    #: What the produced `catalogue.Record` is labelled with.
    source: str
    reader: Reader
    #: Refuse a record whose MARC leader/07 says it is a component part.
    refuses_component_parts: bool = False
    #: Refuse a record that does not name the asked ISBN itself, rather than
    #: ranking it below one that does.
    requires_isbn_claim: bool = True
    #: Read `100 $0` for a GND author identifier.
    reads_author_identifiers: bool = False

    def __post_init__(self) -> None:
        """A MARC knob on a reader that reads no MARC is refused here too.

        **`targets.Target` refuses the same pairing and that was not enough**,
        which a critic measured: `Decoding(source="opf",
        reader=Reader.DUBLIN_CORE, refuses_component_parts=True)` constructed.
        Nothing was reachable on the catalogue path, where `Target.decoding` is
        the only builder and the row is validated first, so the gap was on
        exactly the side this module exists for: a decoding built directly, from
        a file or a member's library, which no row has checked.

        A validated value object is what lets a decoder read a knob without
        asking whether the knob means anything for it.
        """
        if self.reader not in MARC_READERS and (
            self.refuses_component_parts or self.reads_author_identifiers
        ):
            raise ValueError(
                f"{self.source}: a MARC knob on a reader that reads no MARC"
            )
