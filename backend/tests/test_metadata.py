"""Tests for backend/metadata.py.

Four things are worth pinning here and none of them is the happy path.

The **source order** is what makes a shelf catalogueable at all. The two
catalogues that measured fastest also measured most complete, so both are asked
together on every lookup and the broad, slow, metered ones only answer when
neither knows the book. A test that only checks "a lookup returns a book" would
pass with that reversed, and the reader would wait three seconds for a thinner
record.

The **merge** is where record quality comes from. Nothing is overwritten, only
filled in, so a page count from one catalogue and a subject heading from the
other end up on the same book.

The **identity checks** are what stop a wrong book being catalogued. Both
remaining SRU sources match an ISBN mentioned anywhere in a record, including
cross references to other editions, and both were observed returning a
different book because of it.

The **outcome** is what stops the reader being lied to. A throttled source and
a genuinely uncatalogued book both used to be "not found", which sends someone
to type in a record that was going to resolve by itself.

Every HTTP call is intercepted with respx, so nothing here reaches a real
catalogue.
"""

import ast
import asyncio
import itertools
import logging
import math
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import httpx
import pytest
import respx

import covers
import fetch
import google_books
import metadata
import sources
import targets
import z3950
from catalogue import AuthorityAssertion, Heading, Record, Subject
from enums import AuthorityScheme, CatalogueSource, ClassificationScheme
from isbn import registration_group
from metadata import (
    Outcome,
    _dc_title_statement,
    _dnb_subjects,
    _flip_catalogue_name,
    _is_placeholder_title,
    _loc_record,
    _loc_subjects,
    _marc_author_identifiers,
    _marc_authors,
    _marc_fields,
    _pages_from_extent,
    _parsed,
    _subject_identifier,
    _subject_vocabulary,
)
from schemas import MAX_CLASSIFICATIONS_PER_BOOK
from schemas.book import BookLookup
from tests.helpers import (
    silence_covers,
    silence_nkp,
    silence_nlg,
    silence_oenb,
    silence_open_library,
)

#: The `backend/` directory, so a doc guard can reach the repository root.
BACKEND = Path(__file__).resolve().parent.parent

#: Every catalogue enabled, in the order a new install asks them.
#:
#: **These four wrappers exist so that `plan` can stay a required argument.**
#: `metadata.lookup` and its three siblings take it keyword only with no
#: default, so mypy refuses any production call site that forgets to apply the
#: library's provider list. That is the property worth having and it is worth
#: more than the convenience of a default, so the convenience lives here
#: instead, in the one file that does not care which sources are on.
#:
#: What this file tests is what the catalogues answer and how their records are
#: parsed and merged. What the plan itself does belongs to `test_sources.py`,
#: and which module may hold a source order belongs to `test_house_rules.py`.
#: A test here that wanted a narrower plan passes `plan=` and this gets out of
#: the way.
ALL_SOURCES = sources.DEFAULT_PLAN


def patch_lookup_adapters(
    monkeypatch: pytest.MonkeyPatch, table: dict[CatalogueSource, Any]
) -> None:
    """Stand a `{source: adapter}` table in front of the one SRU door.

    The adapters were a dispatch table keyed on a source and are one function
    driven by a row. A test that wants to answer for one source therefore
    replaces the door and dispatches on `target.source`, which is the same
    question the old `monkeypatch.setattr(metadata, "_SOURCES", ...)` asked.

    **`KeyError` rather than a default**, deliberately: a test whose table misses
    a source the plan asks about should fail loudly rather than record a miss.
    """

    async def door(target: Any, isbn: str, api_key: str) -> metadata.Lookup:
        return await table[target.source](isbn, api_key)

    monkeypatch.setattr(metadata, "_lookup_one", door)



def _nlg_search(query: str, limit: int):
    """The NLG's title search, which is now the shared SRU door plus a row."""
    return metadata._search_one(
        targets.SEEDED[CatalogueSource.NLG], query, limit, ""
    )


def _nkp_query(value: str) -> str:
    """The NKP's PQF lookup query, built from its row's use attribute."""
    return targets.SEEDED[CatalogueSource.NKP].isbn_query(value)



async def lookup(*args: Any, plan: sources.Plan = ALL_SOURCES, **kwargs: Any):
    return await metadata.lookup(*args, plan=plan, **kwargs)


async def search(*args: Any, plan: sources.Plan = ALL_SOURCES, **kwargs: Any):
    return await metadata.search(*args, plan=plan, **kwargs)


async def editions(*args: Any, plan: sources.Plan = ALL_SOURCES, **kwargs: Any):
    return await metadata.editions(*args, plan=plan, **kwargs)


async def candidates(*args: Any, plan: sources.Plan = ALL_SOURCES, **kwargs: Any):
    return await metadata.candidates(*args, plan=plan, **kwargs)


OPEN_LIBRARY = "https://openlibrary.org/"
GOOGLE_BOOKS = "https://www.googleapis.com/books/v1/volumes"
DNB = "https://services.dnb.de/sru/dnb"
K10PLUS = "https://sru.k10plus.de/opac-de-627"

GERMAN_ISBN = "9783960092353"
ENGLISH_ISBN = "9780743273565"
#: A real Greek registration group, 978-960. Named because
#: `sources.SERVES_GROUPS` makes a lookup's chain depend on the group, so a test
#: that wants the NLG asked has to hand it a book the NLG could hold.
GREEK_ISBN = "9789602118962"

#: One DNB MARC21 record, in the shape the live endpoint returns since the
#: switch away from Dublin Core. Copied from ISBN 9783446249974's real response
#: and re-labelled onto the book the rest of this file uses, so the subfields,
#: the repeated `$0`, the repeated `082 $a` and the non-sorting delimiters are
#: the catalogue's own and not a guess about them.
DNB_RECORD = """<?xml version="1.0" encoding="UTF-8"?>
<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">
 <records><record><recordData>
  <record xmlns="http://www.loc.gov/MARC21/slim" type="Bibliographic">
   <leader>00000nam a2200000uc 4500</leader>
   <datafield tag="020" ind1=" " ind2=" ">
    <subfield code="a">9783960092353</subfield>
   </datafield>
   <datafield tag="041" ind1=" " ind2=" ">
    <subfield code="a">ger</subfield>
   </datafield>
   <datafield tag="082" ind1="7" ind2="4">
    <subfield code="a">004</subfield>
    <subfield code="a">B</subfield>
    <subfield code="2">23sdnb</subfield>
   </datafield>
   <datafield tag="100" ind1="1" ind2=" ">
    <subfield code="0">(DE-588)1042243212</subfield>
    <subfield code="0">https://d-nb.info/gnd/1042243212</subfield>
    <subfield code="0">(DE-101)1042243212</subfield>
    <subfield code="a">Kane, Sean P.</subfield>
    <subfield code="e">Verfasser</subfield>
    <subfield code="4">aut</subfield>
   </datafield>
   <datafield tag="245" ind1="1" ind2="0">
    <subfield code="a">Praxiswissen Docker</subfield>
    <subfield code="b">Grundlagen und Best Practices</subfield>
    <subfield code="c">Sean P. Kane mit Karl Matthias</subfield>
   </datafield>
   <datafield tag="264" ind1=" " ind2="1">
    <subfield code="a">Heidelberg</subfield>
    <subfield code="b">O'Reilly</subfield>
    <subfield code="c">2024</subfield>
   </datafield>
   <datafield tag="300" ind1=" " ind2=" ">
    <subfield code="a">390 Seiten</subfield>
   </datafield>
   <datafield tag="650" ind1=" " ind2="7">
    <subfield code="0">(DE-588)4026894-9</subfield>
    <subfield code="0">https://d-nb.info/gnd/4026894-9</subfield>
    <subfield code="a">Informatik</subfield>
    <subfield code="2">gnd</subfield>
   </datafield>
   <datafield tag="689" ind1="0" ind2="0">
    <subfield code="0">(DE-588)4026894-9</subfield>
    <subfield code="D">s</subfield>
    <subfield code="a">Informatik</subfield>
   </datafield>
   <datafield tag="700" ind1="1" ind2=" ">
    <subfield code="a">Matthias, Karl</subfield>
    <subfield code="4">aut</subfield>
   </datafield>
   <datafield tag="700" ind1="1" ind2=" ">
    <subfield code="a">Demmig, Thomas</subfield>
    <subfield code="4">trl</subfield>
   </datafield>
  </record>
 </recordData></record></records>
</searchRetrieveResponse>
"""

DNB_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">
 <numberOfRecords>0</numberOfRecords><records/>
</searchRetrieveResponse>
"""

OPEN_LIBRARY_RECORD = {
    "title": "The Great Gatsby",
    "publishers": ["Scribner"],
    "publish_date": "April 10, 1925",
    "subjects": ["Literary Fiction"],
}

GOOGLE_VOLUME = {
    "items": [
        {
            "id": "gbid-1",
            "volumeInfo": {
                "title": "Dune",
                "authors": ["Frank Herbert"],
                "publishedDate": "1965",
                "pageCount": 412,
                "language": "en",
                "industryIdentifiers": [
                    {"type": "ISBN_13", "identifier": "9780441013593"}
                ],
            },
        }
    ]
}


def _marc(*records: str) -> str:
    """An SRU envelope around zero or more MARCXML records."""
    body = "".join(
        f"<zs:record><zs:recordData>{record}</zs:recordData></zs:record>"
        for record in records
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<zs:searchRetrieveResponse xmlns:zs="http://www.loc.gov/zing/srw/">'
        f"<zs:records>{body}</zs:records></zs:searchRetrieveResponse>"
    )


def _marc_record(
    *,
    isbn: str = "9780743273565",
    isbn_qualifier: str = "",
    title: str = '<subfield code="a">The Great Gatsby</subfield>',
    extra: str = "",
) -> str:
    qualifier = f'<subfield code="q">{isbn_qualifier}</subfield>' if isbn_qualifier else ""
    return (
        '<record xmlns="http://www.loc.gov/MARC21/slim">'
        f'<datafield tag="020"><subfield code="a">{isbn}</subfield>{qualifier}</datafield>'
        f'<datafield tag="245">{title}</datafield>'
        '<datafield tag="100"><subfield code="a">Fitzgerald, F. Scott</subfield>'
        '<subfield code="4">aut</subfield></datafield>'
        '<datafield tag="264"><subfield code="b">Scribner</subfield>'
        '<subfield code="c">1925 (copyright)</subfield></datafield>'
        '<datafield tag="300"><subfield code="a">218 S.</subfield></datafield>'
        '<datafield tag="041"><subfield code="a">eng</subfield></datafield>'
        f"{extra}</record>"
    )


K10PLUS_RECORD = _marc(_marc_record())
K10PLUS_EMPTY = _marc()


def _oenb_envelope(*records: str) -> str:
    """An ÖNB SRU envelope around zero or more MARCXML records.

    Not `_marc`, and the difference is one the fixtures below would otherwise
    misrepresent: K10plus prefixes the SRU namespace `zs:` and ÖNB declares it
    as the default. Neither parser cares, because both iterate the MARC
    namespace and never name the envelope, but a fixture that says it was
    copied from a live response should look like one.
    """
    body = "".join(
        f"<record><recordSchema>marcxml</recordSchema>"
        f"<recordData>{record}</recordData></record>"
        for record in records
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>'
        '<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">'
        "<version>1.2</version>"
        f"<numberOfRecords>{len(records)}</numberOfRecords>"
        f"<records>{body}</records></searchRetrieveResponse>"
    )


OENB = "https://obv-at-oenb.alma.exlibrisgroup.com/view/sru/43ACC_ONB"

#: The National Library of Greece. Plaintext HTTP on port 210, which is what
#: the catalogue offers: see `targets.SEEDED[CatalogueSource.NLG]`.
NLG = "http://catalogue.nlg.gr:210/biblios"

#: A real NLG record, trimmed to the fields this app reads.
#:
#: Captured live 2026-08-30 from `dc.title=ιστορία`, control number 434736.
#: **Its only 020 is qualified**, `$q (τ.1)`, which is the case the whole source
#: turns on: under the rule before `_isbn_entries` this record answered nothing.
#: Its `$0` values are `urn:nbn:gr:nlg:` rather than `(DE-588)`, which is why the
#: headings below are subjects and not GND rows.
NLG_RECORD = _marc(
    '<record xmlns="http://www.loc.gov/MARC21/slim">'
    "<leader>01665nam a2200385 a 4500</leader>"
    '<datafield tag="020" ind1=" " ind2=" ">'
    '<subfield code="a">9789602118962</subfield>'
    '<subfield code="q">(τ.1)</subfield></datafield>'
    '<datafield tag="041" ind1="1" ind2=" ">'
    '<subfield code="a">gre</subfield><subfield code="h">eng</subfield></datafield>'
    '<datafield tag="082" ind1="0" ind2="4">'
    '<subfield code="a">940</subfield><subfield code="2">21</subfield></datafield>'
    '<datafield tag="100" ind1="1" ind2=" ">'
    '<subfield code="a">Davies, Norman,</subfield>'
    '<subfield code="d">1939-</subfield>'
    '<subfield code="4">aut</subfield></datafield>'
    '<datafield tag="245" ind1="1" ind2="0">'
    '<subfield code="a">Ιστορία της Ευρώπης /</subfield>'
    '<subfield code="c">Norman Davies</subfield></datafield>'
    '<datafield tag="260" ind1=" " ind2=" ">'
    '<subfield code="a">Αθήνα :</subfield>'
    '<subfield code="b">Νεφέλη,</subfield>'
    '<subfield code="c">2009-</subfield></datafield>'
    '<datafield tag="300" ind1=" " ind2=" ">'
    '<subfield code="a">640 σ. ;</subfield>'
    '<subfield code="c">26εκ.</subfield></datafield>'
    '<datafield tag="651" ind1=" " ind2="7">'
    '<subfield code="a">Ευρώπη</subfield>'
    '<subfield code="0">urn:nbn:gr:nlg:01-A273635</subfield>'
    '<subfield code="2">nlgaf</subfield></datafield>'
    "</record>"
)

#: The same catalogue answering about a different book, which is what a wrong
#: index or a forged reply on a plaintext connection looks like from here.
NLG_WRONG_BOOK = _marc(
    '<record xmlns="http://www.loc.gov/MARC21/slim">'
    "<leader>01665nam a2200385 a 4500</leader>"
    '<datafield tag="020" ind1=" " ind2=" ">'
    '<subfield code="a">9789600426656</subfield></datafield>'
    '<datafield tag="245" ind1="1" ind2="0">'
    '<subfield code="a">Σημίνα, είσαι αστέρι</subfield></datafield>'
    '<datafield tag="300" ind1=" " ind2=" ">'
    '<subfield code="a">30 σ.</subfield></datafield>'
    "</record>"
)

NLG_EMPTY = _marc()


#: The Czech National Library. Plaintext HTTP on 9991, and the `/NKC` path is
#: part of the address: the host alone answers "database does not exist".
NKP = "http://aleph.nkp.cz:9991/NKC"


def _nkp_envelope(*records: str, empty_stubs: int = 0) -> str:
    """An NKP SRU envelope, including the empty stubs this target really sends.

    **`empty_stubs` is not a contrivance.** Measured 2026-08-31, this server
    renders exactly one populated record per response and pads the rest of the
    page with `zs:record` elements carrying a packing and a position and no
    `recordData` at all: 391 of 400 records over eight searches. A fixture
    without them would test a response shape this target does not produce.
    """
    stubs = "".join(
        f"<zs:record><zs:recordPacking>xml</zs:recordPacking>"
        f"<zs:recordPosition>{i + 1}</zs:recordPosition></zs:record>"
        for i in range(empty_stubs)
    )
    body = "".join(
        f"<zs:record><zs:recordPacking>xml</zs:recordPacking>"
        f"<zs:recordData><record-list>{record}</record-list></zs:recordData>"
        f"<zs:recordPosition>{empty_stubs + i + 1}</zs:recordPosition></zs:record>"
        for i, record in enumerate(records)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<zs:searchRetrieveResponse xmlns:zs="http://www.loc.gov/zing/srw/">'
        "<zs:version>1.1</zs:version>"
        f"<zs:numberOfRecords>{len(records)}</zs:numberOfRecords>"
        f"<zs:records>{stubs}{body}</zs:records></zs:searchRetrieveResponse>"
    )


#: A real NKP record, trimmed to what this app reads.
#:
#: Captured live 2026-08-31. Its shape carries three of this source's four
#: surprises: the elements are **un-namespaced**, there is **no `creator`** and
#: the people are `contributor`, and the identifier is hyphenated as printed.
NKP_RECORD = (
    "<dc-record>"
    "<type>text</type>"
    "<language>cze</language>"
    "<identifier>978-80-257-1294-8</identifier>"
    "<contributor>Hrabal, Bohumil, 1914-1997</contributor>"
    "<contributor>Argo (firma)</contributor>"
    "<title>Ostře sledované vlaky /</title>"
    "<publisher>Argo,</publisher>"
    "<date>2018</date>"
    "<format>96 stran ;</format>"
    "<subject>česká próza</subject>"
    "</dc-record>"
)

NKP_EMPTY = _nkp_envelope()

#: One live ÖNB record, ISBN 9783552058217, `Das angehaltene Leben`, Zsolnay.
#:
#: **Copied from the live response rather than written to suit the test**, so
#: every trap in it is the catalogue's own. Four are load bearing here.
#:
#: * `245 $a` is `<<Das>> angehaltene Leben`. ÖNB writes MARC's non-sorting
#:   delimiters as `<<` and `>>` where the DNB writes U+0098 and U+009C, and
#:   writes U+0098 nowhere: 21 of 150 live 245 `$a` values carry a bracketed
#:   run, measured 2026-08-27.
#: * `082` carries a real Dewey number, so the DDC path is exercised.
#: * `655` carries a `(DE-588)` heading and a second entry naming a different
#:   vocabulary with no `$0`, so the GND path is exercised on a record where
#:   only one of the two headings is identified.
#: * `700` is the translator, `$4 trl`. It is not an author relator, so it must
#:   not reach the author string. The live record is the reason to check: a
#:   translated Italian novel is exactly the shape a naive 700 reader spoils.
#:
#: `041` carries `$h ita`, the language translated from, beside `$a ger`.
OENB_RECORD = _oenb_envelope(
    '<record xmlns="http://www.loc.gov/MARC21/slim">'
    "<leader>01533nam a2200505 c 4500</leader>"
    '<datafield tag="020" ind1=" " ind2=" ">'
    '<subfield code="a">9783552058217</subfield>'
    '<subfield code="c">Festeinband : EUR 22,70</subfield></datafield>'
    '<datafield tag="041" ind1=" " ind2=" ">'
    '<subfield code="a">ger</subfield><subfield code="h">ita</subfield></datafield>'
    '<datafield tag="082" ind1="0" ind2="4">'
    '<subfield code="a">853.92</subfield><subfield code="2">22/ger</subfield></datafield>'
    '<datafield tag="084" ind1=" " ind2=" ">'
    '<subfield code="a">18.27</subfield><subfield code="2">bkl</subfield></datafield>'
    '<datafield tag="100" ind1="1" ind2=" ">'
    '<subfield code="a">Torchio, Maurizio</subfield>'
    '<subfield code="d">1970-</subfield>'
    '<subfield code="0">(DE-588)138150680</subfield>'
    '<subfield code="4">aut</subfield></datafield>'
    '<datafield tag="245" ind1="1" ind2="0">'
    "<subfield code=\"a\">&lt;&lt;Das&gt;&gt; angehaltene Leben</subfield>"
    '<subfield code="b">Roman</subfield></datafield>'
    '<datafield tag="264" ind1=" " ind2="1">'
    '<subfield code="a">Wien</subfield>'
    '<subfield code="b">Paul Zsolnay Verlag</subfield>'
    '<subfield code="c">[2017]</subfield></datafield>'
    '<datafield tag="300" ind1=" " ind2=" ">'
    '<subfield code="a">237 Seiten</subfield>'
    '<subfield code="c">21 cm</subfield></datafield>'
    '<datafield tag="655" ind1=" " ind2="7">'
    '<subfield code="a">Fiktionale Darstellung</subfield>'
    '<subfield code="0">(DE-588)1071854844</subfield>'
    '<subfield code="2">gnd-content</subfield></datafield>'
    '<datafield tag="655" ind1=" " ind2="7">'
    '<subfield code="a">Roman</subfield>'
    '<subfield code="2">bellobv</subfield></datafield>'
    '<datafield tag="700" ind1="1" ind2=" ">'
    '<subfield code="a">Kopetzki, Annette</subfield>'
    '<subfield code="4">trl</subfield></datafield>'
    "</record>"
)

#: One live ÖNB record for an Austrian imprint that the DNB and K10plus both
#: miss, ISBN 9783700316206, Braumüller, Vienna 2007.
#:
#: **One of the three that the whole item turns on.** 50 ISBNs, five each from
#: ten Austrian presses, taken off live ÖNB records printed after 2005 and put
#: to all three catalogues on 2026-08-27: ÖNB held 50, the DNB 47, K10plus 39,
#: and 3 were held by ÖNB and by neither of the German pair. This is one of
#: those 3. That 6% is a floor rather than an estimate, because every ISBN in
#: the sample came off an ÖNB record that carried one, from ten well known
#: presses, which is the half of Austrian publishing the German catalogues are
#: likeliest to hold too.
OENB_AUSTRIAN_ONLY = _oenb_envelope(
    '<record xmlns="http://www.loc.gov/MARC21/slim">'
    "<leader>01201nam a2200349 cc4500</leader>"
    '<datafield tag="020" ind1=" " ind2=" ">'
    '<subfield code="a">9783700316206</subfield></datafield>'
    '<datafield tag="041" ind1=" " ind2=" ">'
    '<subfield code="a">ger</subfield></datafield>'
    '<datafield tag="245" ind1="1" ind2="0">'
    '<subfield code="a">?Kunst!</subfield></datafield>'
    '<datafield tag="264" ind1=" " ind2="1">'
    '<subfield code="a">Wien</subfield>'
    '<subfield code="b">Braumüller</subfield>'
    '<subfield code="c">2007</subfield></datafield>'
    '<datafield tag="300" ind1=" " ind2=" ">'
    '<subfield code="a">III, 272 S.</subfield></datafield>'
    "</record>"
)

#: One live ÖNB record that is a **journal article**, not a book: leader/07 is
#: `a`, a monographic component part, and the 773 names the volume it sits in.
#:
#: Copied whole from the first row of the live title search
#: `alma.title=klavierspielerin and alma.title=jelinek`, whose entire first page
#: of five records is articles like this one.
#:
#: **It has a title, an author and a year, and no 300 at all**, which is exactly
#: why the leader has to be read: `_is_physical_book` tests the extent for an
#: online form and the title for a volume slot, and an absent extent passes
#: both. Measured over 8 live title searches, 155 of 280 records are this shape.
OENB_ARTICLE = (
    '<record xmlns="http://www.loc.gov/MARC21/slim">'
    "<leader>00733naa a2200229zc 4500</leader>"
    '<controlfield tag="001">990006303820603338</controlfield>'
    '<datafield tag="041" ind1=" " ind2=" ">'
    '<subfield code="a">eng</subfield></datafield>'
    '<datafield tag="100" ind1="1" ind2=" ">'
    '<subfield code="a">DeMeritt, Linda C.</subfield>'
    '<subfield code="4">aut</subfield></datafield>'
    '<datafield tag="245" ind1="1" ind2="0">'
    "<subfield code=\"a\">&lt;&lt;A&gt;&gt; \"healthier marriage\"</subfield>"
    "<subfield code=\"b\">Elfriede Jelinek's marxist feminism</subfield></datafield>"
    '<datafield tag="264" ind1=" " ind2="1">'
    '<subfield code="c">1994</subfield></datafield>'
    '<datafield tag="773" ind1="0" ind2="8">'
    '<subfield code="i">Enthalten in</subfield>'
    '<subfield code="t">Elfriede Jelinek</subfield></datafield>'
    "</record>"
)

#: A whole publication, leader/07 `m`, to sit beside the article above so a
#: search fixture can show which of the two survives.
#:
#: **The `100` carries its `(DE-588)` on purpose.** The live record does, 75.6%
#: of live ÖNB `100 $a` fields do, and without it the test asserting that a
#: search row carries no author identifier would pass whether the source is read
#: for them or not. A fixture that cannot fail is the shape a review caught in
#: this file once already.
OENB_MONOGRAPH = (
    '<record xmlns="http://www.loc.gov/MARC21/slim">'
    "<leader>01533nam a2200505 c 4500</leader>"
    '<datafield tag="020" ind1=" " ind2=" ">'
    '<subfield code="a">9783552058217</subfield></datafield>'
    '<datafield tag="245" ind1="1" ind2="0">'
    "<subfield code=\"a\">&lt;&lt;Das&gt;&gt; angehaltene Leben</subfield></datafield>"
    '<datafield tag="100" ind1="1" ind2=" ">'
    '<subfield code="a">Torchio, Maurizio</subfield>'
    '<subfield code="0">(DE-588)138150680</subfield>'
    '<subfield code="4">aut</subfield></datafield>'
    '<datafield tag="264" ind1=" " ind2="1">'
    '<subfield code="c">2017</subfield></datafield>'
    '<datafield tag="300" ind1=" " ind2=" ">'
    '<subfield code="a">237 Seiten</subfield></datafield>'
    "</record>"
)

OENB_SEARCH = _oenb_envelope(OENB_ARTICLE, OENB_MONOGRAPH)

#: A whole publication by its leader, and an **online resource** by its extent.
#:
#: The leader test passes it, so this is the record that shows `_is_physical_book`
#: is doing separate work from `_is_component_part`. Deleting either refusal
#: leaves the other in place and this row reaching the picker.
OENB_ONLINE = (
    '<record xmlns="http://www.loc.gov/MARC21/slim">'
    "<leader>01533nam a2200505 c 4500</leader>"
    '<datafield tag="245" ind1="1" ind2="0">'
    '<subfield code="a">Nur online</subfield></datafield>'
    '<datafield tag="264" ind1=" " ind2="1">'
    '<subfield code="c">2019</subfield></datafield>'
    '<datafield tag="300" ind1=" " ind2=" ">'
    '<subfield code="a">1 Online-Ressource (240 Seiten)</subfield></datafield>'
    "</record>"
)

OENB_SEARCH_WITH_ONLINE = _oenb_envelope(OENB_ONLINE, OENB_MONOGRAPH)


OENB_EMPTY = _oenb_envelope()

#: What the endpoint answers a query it will not run: **HTTP 200**, a well
#: formed envelope, a `diag:diagnostic`, and no records at all.
#:
#: Copied from the live answer to `alma.title=wien geschichte`, which is refused
#: because a bare multi-word term is not valid CQL there. Kept as a fixture
#: rather than as a code path, because the right handling is to have none: the
#: body parses, no record is found, and the source reports no results.
OENB_DIAGNOSTIC = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/"
  xmlns:diag="http://www.loc.gov/zing/srw/diagnostic/">
  <version>1.2</version>
  <diagnostics>
    <diag:diagnostic>
      <diag:uri>200812</diag:uri>
      <diag:message>Invalid query</diag:message>
    </diag:diagnostic>
  </diagnostics>
</searchRetrieveResponse>
"""

#: What a **mistyped index name** answers, and the reason this source needs
#: `_marc_claims_isbn` more than any other here.
#:
#: Measured live 2026-08-27: `alma.isbn=9783825354077` returns 1 record and both
#: `alma.isbn13=9783825354077` and `zzz.qqq=9783825354077` return **7,793,152**,
#: the whole catalogue, HTTP 200, no diagnostic. So the failure mode of a wrong
#: index is not an empty result, it is arbitrary records that parse perfectly.
#: This stands in for that: a well formed record for a completely different book.
OENB_WRONG_BOOK = _oenb_envelope(
    '<record xmlns="http://www.loc.gov/MARC21/slim">'
    "<leader>00731nam a2200277 c 4500</leader>"
    '<datafield tag="020" ind1=" " ind2=" ">'
    '<subfield code="a">9783701716678</subfield></datafield>'
    '<datafield tag="245" ind1="1" ind2="0">'
    '<subfield code="a">Ein ganz anderes Buch</subfield></datafield>'
    '<datafield tag="264" ind1=" " ind2="1">'
    '<subfield code="c">1860</subfield></datafield>'
    "</record>"
)


def _marc_element(datafields: str) -> ElementTree.Element:
    """One MARC record element, built from the datafields a test cares about."""
    return ElementTree.fromstring(
        '<record xmlns="http://www.loc.gov/MARC21/slim">'
        f"{datafields}</record>"
    )


def _xml(body: str) -> httpx.Response:
    return httpx.Response(200, text=body, headers={"content-type": "text/xml"})


@pytest.fixture(autouse=True)
def _clear_cache():
    """The cache is process-global, so one test's answer would serve the next."""
    metadata.clear_cache()
    yield
    metadata.clear_cache()


class TestSourceOrder:
    @pytest.mark.asyncio
    async def test_a_german_isbn_asks_the_dnb_first(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            dnb = mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            open_library = mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            result = await lookup(GERMAN_ISBN)

        assert result.source == "dnb"
        assert dnb.called
        # Reaching Open Library at all would mean the order is wrong, since the
        # fast pair already answered.
        assert not open_library.called

    @pytest.mark.asyncio
    async def test_a_non_german_isbn_also_starts_with_the_fast_pair(self):
        """Open Library used to be first here, and it is the wrong first.

        Measured over ten ISBNs it answered most often and answered worst: 2.7
        of 5 fields against K10plus's 3.5, at 1.64s against 0.36s. Leading with
        it cost a second of latency to get a thinner record.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_RECORD)
            )
            open_library = mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(200, json=OPEN_LIBRARY_RECORD)
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(ENGLISH_ISBN)

        assert result.source == "k10plus"
        assert not open_library.called

    @pytest.mark.asyncio
    async def test_open_library_answers_when_the_fast_pair_misses(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_oenb(mock)
            silence_nkp(mock)
            silence_nlg(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(200, json=OPEN_LIBRARY_RECORD)
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(ENGLISH_ISBN)

        assert result.source == "open_library"

    @pytest.mark.asyncio
    async def test_the_fast_pair_is_asked_together_not_in_turn(self):
        """Both are asked even when the first would have answered.

        That is the trade this makes: one extra free request per scan, for a
        merged record and a wall clock equal to the slower of the two rather
        than the sum of the chain.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            k10plus = mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            dnb = mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            await lookup(GERMAN_ISBN)

        assert dnb.called
        assert k10plus.called

    @pytest.mark.asyncio
    async def test_google_is_tried_after_open_library_misses(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_oenb(mock)
            silence_nkp(mock)
            silence_nlg(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json=GOOGLE_VOLUME)
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(ENGLISH_ISBN)

        assert result.source == "google_books"
        assert result.record is not None
        assert result.record.title == "Dune"

    @pytest.mark.asyncio
    async def test_the_google_fallback_keeps_the_page_count_and_the_language(self):
        """Both were dropped on the way out of this source until 2026-08-27.

        `google_books._volume_to_fields` has read `pageCount` and `language`
        all along; the dictionary this adapter built out of them named neither,
        so a Google fallback answered without two of the seven fields
        `Record.completeness` scores, and a refresh of a Google-only book left
        its page count empty. The same omission was found and fixed for Open
        Library on 2026-08-24. `google_books_id` was dropped the same way and is
        the one field only this source has.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_oenb(mock)
            silence_nkp(mock)
            silence_nlg(mock)
            mock.get(url__startswith=K10PLUS).mock(return_value=_xml(K10PLUS_EMPTY))
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json=GOOGLE_VOLUME)
            )
            result = await lookup(ENGLISH_ISBN)

        assert result.record is not None
        assert result.record.page_count == 412
        assert result.record.language == "en"
        assert result.record.google_books_id == "gbid-1"

    @pytest.mark.asyncio
    async def test_the_google_request_carries_the_api_key(self):
        """The bug this module replaced: a second hand-rolled request without it.

        Every fallback lookup went to the unauthenticated endpoint, which is
        throttled per source address, so a library behind one address got a
        429 and a "book not found" for every scan.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_oenb(mock)
            silence_nkp(mock)
            silence_nlg(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            google = mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json=GOOGLE_VOLUME)
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            await lookup(ENGLISH_ISBN, "secret-key")

        assert google.calls.last.request.url.params["key"] == "secret-key"


class TestOutcome:
    @pytest.mark.asyncio
    async def test_a_throttled_source_is_reported_as_rate_limited(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_oenb(mock)
            silence_nkp(mock)
            silence_nlg(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(429)
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(ENGLISH_ISBN)

        assert result.outcome is Outcome.RATE_LIMITED

    @pytest.mark.asyncio
    async def test_being_throttled_outranks_a_genuine_miss(self):
        """One source having no record does not make the answer "no such book".

        With two sources reporting nothing and one throttled, the useful advice
        is to try again, not to start typing.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_oenb(mock)
            silence_nkp(mock)
            silence_nlg(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(429)
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(ENGLISH_ISBN)

        assert result.outcome is Outcome.RATE_LIMITED

    @pytest.mark.asyncio
    async def test_every_source_answering_nothing_is_not_found(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_oenb(mock)
            silence_nkp(mock)
            silence_nlg(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(ENGLISH_ISBN)

        assert result.outcome is Outcome.NOT_FOUND

    @pytest.mark.asyncio
    async def test_a_network_failure_is_unavailable_not_missing(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_oenb(mock)
            silence_nkp(mock)
            silence_nlg(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                side_effect=httpx.ConnectError("no route")
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                side_effect=httpx.ConnectError("no route")
            )
            mock.get(url__startswith=DNB).mock(
                side_effect=httpx.ConnectError("no route")
            )
            result = await lookup(ENGLISH_ISBN)

        assert result.outcome is Outcome.UNAVAILABLE

    @pytest.mark.asyncio
    async def test_a_string_that_is_not_an_isbn_costs_no_request(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            any_call = mock.get(url__regex=r".*").mock(
                return_value=httpx.Response(200, json={})
            )
            result = await lookup("not-an-isbn")

        assert result.outcome is Outcome.NOT_FOUND
        assert not any_call.called


class TestCache:
    @pytest.mark.asyncio
    async def test_a_repeat_lookup_reuses_the_record(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            route = mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            await lookup(GERMAN_ISBN)
            await lookup(GERMAN_ISBN)

        assert route.call_count == 1

    @pytest.mark.asyncio
    async def test_the_hyphenated_form_hits_the_same_entry(self):
        """Canonicalising before the cache is what makes one book one entry."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            route = mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            await lookup(GERMAN_ISBN)
            await lookup("978-3-96009-235-3")

        assert route.call_count == 1

    @pytest.mark.asyncio
    async def test_clearing_the_cache_lets_a_source_answer_again(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            route = mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            await lookup(GERMAN_ISBN)
            metadata.clear_cache()
            await lookup(GERMAN_ISBN)

        assert route.call_count == 2


class TestDnbRecord:
    """The DNB record, read as MARC21 since 2026-08-24.

    Dublin Core packed a whole catalogue statement into each field and carried
    no identifier at all. What is pinned here is that the fields that worked
    under it still work, and that the identifiers it never had now arrive.
    """

    @pytest.mark.asyncio
    async def test_maps_the_record_onto_book_fields(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            result = await lookup(GERMAN_ISBN)

        assert result.record is not None
        assert result.record.title == "Praxiswissen Docker"
        assert result.record.subtitle == "Grundlagen und Best Practices"
        assert result.record.publisher == "O'Reilly"
        assert result.record.year == 2024
        assert result.record.language == "de"
        assert result.record.page_count == 390

    @pytest.mark.asyncio
    async def test_keeps_the_authors_and_drops_the_translator(self):
        """A translator credited as the author is worse than no author at all."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            result = await lookup(GERMAN_ISBN)

        assert result.record is not None
        assert result.record.author == "Sean P. Kane, Karl Matthias"

    @pytest.mark.asyncio
    async def test_the_subject_heading_is_the_caption_without_its_number(self):
        """A heading reaches `subjects` as words, so a tag name can match it."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            result = await lookup(GERMAN_ISBN)

        assert result.record is not None
        assert result.record.subject_labels == ["Informatik"]

    @pytest.mark.asyncio
    async def test_the_same_heading_in_650_and_689_is_one_subject(self):
        """A record restates its 650 headings in the 689 chain."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            result = await lookup(GERMAN_ISBN)

        assert result.record is not None
        assert len(result.record.headings) == 2

    @pytest.mark.asyncio
    async def test_the_subject_heading_arrives_with_its_gnd_number(self):
        """The identifier is the whole reason this source reads MARC."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            result = await lookup(GERMAN_ISBN)

        assert result.record is not None
        assert Heading(ClassificationScheme.GND, "4026894-9", "Informatik") in result.record.headings

    @pytest.mark.asyncio
    async def test_the_dewey_number_comes_before_the_subject_headings(self):
        """`_headings` keeps the first eight, and the Dewey number is the one
        a tag suggestion is projected from."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            result = await lookup(GERMAN_ISBN)

        assert result.record is not None
        assert result.record.headings[0] == Heading(ClassificationScheme.DDC, "004")

    @pytest.mark.asyncio
    async def test_the_sachgruppe_letter_does_not_hide_the_dewey_number(self):
        """082 carries `$a=004` and `$a=B` in one field, in that order.

        Reading a single `$a` per field would take whichever came second.
        """
        record = DNB_RECORD.replace(
            '<subfield code="a">004</subfield>\n    <subfield code="a">B</subfield>',
            '<subfield code="a">B</subfield>\n    <subfield code="a">004</subfield>',
        )
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(record))
            result = await lookup(GERMAN_ISBN)

        assert result.record is not None
        assert [
            entry.number
            for entry in result.record.headings
            if entry.scheme is ClassificationScheme.DDC
        ] == ["004"]

    @pytest.mark.asyncio
    async def test_a_free_text_heading_starting_with_three_digits_is_not_dewey(self):
        """"100 Jahre Bauhaus" is a subject heading, and `ddc.parse_heading`
        would read it as Dewey 100 with the caption "Jahre Bauhaus".

        The floor in `ddc` cannot tell the two apart, so the separation is
        structural: 082 is the only field handed to `ddc`, and a subject field
        never is. Remove that and this book is filed under Philosophy.
        """
        record = DNB_RECORD.replace(
            '<subfield code="a">Informatik</subfield>',
            '<subfield code="a">100 Jahre Bauhaus</subfield>',
        )
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(record))
            result = await lookup(GERMAN_ISBN)

        assert result.record is not None
        assert [
            entry.number
            for entry in result.record.headings
            if entry.scheme is ClassificationScheme.DDC
        ] == ["004"]
        assert Heading(ClassificationScheme.GND, "4026894-9", "100 Jahre Bauhaus") in result.record.headings

    @staticmethod
    def _two_records(first: str, second: str) -> str:
        """One DNB answer holding two records, which `maximumRecords=5` allows.

        No fixture held more than one before, so the ranking in the DNB lookup was
        exercised by nothing.
        """
        head, _, tail = DNB_RECORD.partition("<records>")
        body = tail.replace("</records>\n</searchRetrieveResponse>\n", "")
        return (
            head
            + "<records>"
            + body.replace('<subfield code="a">390 Seiten</subfield>', first)
            + body.replace('<subfield code="a">390 Seiten</subfield>', second)
            + "</records>\n</searchRetrieveResponse>\n"
        )

    @pytest.mark.asyncio
    async def test_a_printed_edition_outranks_the_online_one(self):
        """`num=` matches the ebook record through its "also published as" note,
        and the DNB answers with it first. The extra four records are what let
        the printed edition win."""
        answer = self._two_records(
            '<subfield code="a">Online-Ressource</subfield>',
            '<subfield code="a">390 Seiten</subfield>',
        )
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(answer))
            result = await lookup(GERMAN_ISBN)

        assert result.record is not None
        assert result.record.page_count == 390

    @pytest.mark.asyncio
    async def test_an_online_record_is_taken_rather_than_reporting_a_miss(self):
        """Dublin Core carried no `dc:format` on an online record, so every one
        of them was accepted. Refusing now would turn 21 of 74 live lookups into
        misses for records that name the scanned ISBN in their own 020."""
        answer = DNB_RECORD.replace(
            '<subfield code="a">390 Seiten</subfield>',
            '<subfield code="a">Online-Ressource</subfield>',
        )
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(answer))
            result = await lookup(GERMAN_ISBN)

        assert result.outcome is Outcome.FOUND
        assert result.record is not None
        assert result.record.title == "Praxiswissen Docker"

    @pytest.mark.asyncio
    async def test_a_disc_is_refused_rather_than_ranked_down(self):
        """A DVD is a different object, not this book in another form, and the
        Dublin Core parser refused it whenever `dc:format` was present."""
        answer = DNB_RECORD.replace(
            '<subfield code="a">390 Seiten</subfield>',
            '<subfield code="a">1 DVD-Video</subfield>',
        )
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_oenb(mock)
            silence_nkp(mock)
            silence_nlg(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(answer))
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            result = await lookup(GERMAN_ISBN)

        assert result.outcome is Outcome.NOT_FOUND

    @pytest.mark.asyncio
    async def test_the_author_identifier_reaches_the_record(self):
        """`100 $0` is carried now, where it used to be thrown away.

        This replaces `test_the_author_identifier_is_read_by_nothing`, which
        pinned the opposite and pinned it for a stated reason: there was nowhere
        correct to put a person. `author_identifiers` is that place, and it is a
        store keyed on a spelling rather than the person table §30g says to
        decide on first.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            result = await lookup(GERMAN_ISBN)

        assert result.record is not None
        assert result.record.author_identifiers == (
            AuthorityAssertion("Sean P. Kane", AuthorityScheme.GND, "1042243212"),
        )

    @pytest.mark.asyncio
    async def test_the_author_identifier_is_not_in_the_draft_a_client_posts_back(self):
        """`BookLookup` is a draft a client sends straight back, so a value in
        it is a value a member could retype. The assertion reaches the store
        from the `Record` the server fetched instead, which is what makes
        `CATALOGUE` provenance mean anything."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            result = await lookup(GERMAN_ISBN)

        assert result.record is not None
        assert "1042243212" not in str(result.record.as_lookup())
        assert "1042243212" not in str(result.record.as_match())

    @pytest.mark.asyncio
    async def test_an_empty_result_set_is_a_miss_not_an_outage(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_oenb(mock)
            silence_nkp(mock)
            silence_nlg(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            result = await lookup(GERMAN_ISBN)

        assert result.outcome is Outcome.NOT_FOUND


class TestTitleStatement:
    """The BnF still writes a whole statement into `dc:title`, and so does a
    MARC record old enough not to have subfielded itself."""

    def test_drops_the_statement_of_responsibility(self):
        assert _dc_title_statement("Dune / Frank Herbert") == ("Dune", None)

    def test_splits_the_subtitle_off_the_colon(self):
        assert _dc_title_statement("Docker : eine Einfuehrung") == (
            "Docker",
            "eine Einfuehrung",
        )

    def test_drops_the_bracketed_original_title_of_a_translation(self):
        """The brackets hold a different book's title, in another language."""
        assert _dc_title_statement("[Docker: up and running] ; Praxiswissen Docker") == (
            "Praxiswissen Docker",
            None,
        )

    def test_keeps_a_colon_that_is_part_of_the_title(self):
        """Only " : " separates a subtitle. A bare colon is punctuation."""
        assert _dc_title_statement("Docker: up and running") == (
            "Docker: up and running",
            None,
        )

    def test_drops_a_second_work_bound_into_the_same_volume(self):
        assert _dc_title_statement("Erstes Werk ; Zweites Werk") == ("Erstes Werk", None)


class TestSearchMatches:
    """`Record.match_headings` is what bounds a row before the picker sees it."""

    def test_a_match_carries_no_more_headings_than_the_schema_accepts(self):
        """`BookMatch` refuses a ninth entry and `main.py` catches no
        `ValidationError`, so an unbounded match is a 500 waiting for the next
        endpoint that builds one without a guard. That is not hypothetical: it
        is what `GET /{id}/enrich/candidates` did while the search endpoint was
        being fixed.

        The routers bound it again, which is deliberate rather than an
        oversight: this is the bound that travels with the record, and theirs is
        the one that also drops an entry the column cannot hold.
        """
        record = Record(
            source="dnb",
            title="Ein Buch",
            headings=tuple(
                Heading(ClassificationScheme.GND, f"{index}", "x")
                for index in range(12)
            ),
        )

        assert len(record.match_headings()) == MAX_CLASSIFICATIONS_PER_BOOK


class TestCatalogueXml:
    """Every catalogue response goes through one reader."""

    @pytest.mark.asyncio
    async def test_a_response_carrying_a_doctype_is_refused(self):
        """`xml.etree` expands internal entities, so a doctype is a body whose
        size says nothing about what it costs to parse: ten characters nested
        three deep expand to 1,000. It degrades to "unavailable", not a 500."""
        hostile = (
            '<?xml version="1.0"?>'
            '<!DOCTYPE searchRetrieveResponse [<!ENTITY a "aaaaaaaaaa">]>'
            '<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">'
            "<records/></searchRetrieveResponse>"
        )
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_oenb(mock)
            silence_nkp(mock)
            silence_nlg(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(hostile))
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            result = await lookup(GERMAN_ISBN)

        assert result.outcome is not Outcome.FOUND

    def test_an_ordinary_response_still_parses(self):
        """225 live DNB and K10plus responses carry no doctype, so the refusal
        above costs nothing."""
        assert _parsed(DNB_RECORD).tag.endswith("searchRetrieveResponse")


class TestTheResponseSizeCap:
    """The other half of the doctype refusal, from the wire side.

    The doctype guard bounds what a body costs to parse. This bounds the body.
    Neither substitutes for the other, and until 2026-08-26 only the first
    existed: a catalogue answering with an endless stream filled a pod limited
    to 512Mi, where a 1.8 GB peak has already caused an OOMKill once.

    What these check is not that the cap works, which `tests/test_fetch.py`
    does. It is that going over lands in the handler a timeout already lands
    in, at the call sites, rather than escaping as a 500.
    """

    #: Small, because the cap is patched down rather than the body built up.
    #: `fetch.get` resolves `MAX_RESPONSE_BYTES` at call time for exactly this
    #: reason; while it was a default argument these tests each carried a 1.1 MB
    #: module level string to reach it.
    ENORMOUS = "<x>" + "y" * 4096 + "</x>"

    @pytest.fixture(autouse=True)
    def _tiny_cap(self, monkeypatch):
        monkeypatch.setattr(fetch, "MAX_RESPONSE_BYTES", 1024)

    # ── One boundary fixture per XML SRU caller ──────────────────────────────
    #
    # **Every body below would parse to a real record if the cap let it
    # through**, and that clause is the whole point of this block. The test
    # this replaces looked like the K10plus fixture and asserted `rows == []`
    # against a body of `<x>yyy</x>`, which yields no records whether the cap
    # holds or not: it passed with the cap defeated. Measured by raising each
    # caller's own `limit` to 200,000,000 and running the file, only the DNB
    # and ÖNB lookups noticed; six callers had no fixture that could fail.
    #
    # Each body is a valid record for that caller's own schema, padded past the
    # patched cap with a comment. If the cap stops working, the record arrives,
    # the assertion sees a row, and the test fails.

    #: Padding that survives the parser, so the body is over the cap without
    #: being malformed. A comment rather than junk text: `_parsed` would still
    #: parse trailing character data, but a comment cannot be mistaken for a
    #: record by anything downstream.
    @staticmethod
    def _padded(body: str, closing: str) -> str:
        filler = f"<!--{'p' * 4096}-->"
        return body.replace(closing, filler + closing)

    def _marc_over_cap(self) -> str:
        return self._padded(_marc(_marc_record()), "</zs:records>")

    def _oenb_over_cap(self) -> str:
        return self._padded(
            _oenb_envelope(OENB_MONOGRAPH), "</records>"
        )

    def _nkp_over_cap(self) -> str:
        """The Czech envelope, which is neither `_marc` nor the BnF's."""
        return self._padded(
            _nkp_envelope(
                "<dc-record><type>text</type>"
                "<identifier>9780743273565</identifier>"
                "<title>The Great Gatsby</title>"
                "<date>1925</date>"
                "<format>218 p.</format></dc-record>"
            ),
            "</zs:records>",
        )

    def _dublincore_over_cap(self) -> str:
        return self._padded(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<srw:searchRetrieveResponse xmlns:srw="http://www.loc.gov/zing/srw/"'
            ' xmlns:dc="http://purl.org/dc/elements/1.1/">'
            "<srw:records><srw:record><srw:recordData>"
            "<dc:dc>"
            "<dc:title>Le Comte de Monte-Cristo</dc:title>"
            "<dc:type>texte imprime</dc:type>"
            "<dc:publisher>Gallimard (Paris)</dc:publisher>"
            "<dc:date>1998</dc:date>"
            "<dc:format>500 p.</dc:format>"
            "</dc:dc>"
            "</srw:recordData></srw:record></srw:records>"
            "</srw:searchRetrieveResponse>",
            "</srw:records>",
        )

    def _mods_over_cap(self) -> str:
        return self._padded(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<zs:searchRetrieveResponse xmlns:zs="http://www.loc.gov/zing/srw/">'
            "<zs:records><zs:record><zs:recordData>"
            '<mods xmlns="http://www.loc.gov/mods/v3">'
            "<typeOfResource>text</typeOfResource>"
            "<titleInfo><title>Cien anos de soledad</title></titleInfo>"
            "<physicalDescription><extent>417 p.</extent></physicalDescription>"
            "</mods>"
            "</zs:recordData></zs:record></zs:records>"
            "</zs:searchRetrieveResponse>",
            "</zs:records>",
        )

    def test_every_body_below_would_parse_if_the_cap_let_it_through(self):
        """The fixtures' own precondition, checked rather than asserted in prose.

        Without this, a typo in any body silently turns its cap test back into
        the vacuous shape this block exists to replace: the row would be absent
        because the record never parsed, not because the cap refused it.
        """
        # Bound and narrowed before the call: `find` answers `Element | None`,
        # and passing that straight in is a type error rather than a check.
        marc_record = _parsed(self._marc_over_cap()).find(f".//{metadata._MARC}record")
        assert marc_record is not None
        assert _marc_fields(marc_record)
        assert _parsed(self._oenb_over_cap()).find(f".//{metadata._MARC}record") is not None
        assert (
            _parsed(self._dublincore_over_cap()).find(f".//{metadata._DC}title")
            is not None
        )
        assert _parsed(self._mods_over_cap()).find(f".//{metadata._MODS}mods") is not None
        assert _parsed(self._nkp_over_cap()).find(".//dc-record") is not None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "host, body, isbn",
        [
            (DNB, "_marc_over_cap", ENGLISH_ISBN),
            (K10PLUS, "_marc_over_cap", ENGLISH_ISBN),
            # **An ISBN each source is asked about, which is not one ISBN any
            # more.** `sources.SERVES_GROUPS` skips a national catalogue on the
            # lookup path for a registration group outside its remit, so the two
            # restricted sources are handed a book from their own group. With
            # `ENGLISH_ISBN` they are never asked, the cap is never reached, and
            # this test passes with the handler deleted.
            (OENB, "_oenb_over_cap", GERMAN_ISBN),
            (NLG, "_marc_over_cap", GREEK_ISBN),
            (NKP, "_nkp_over_cap", ENGLISH_ISBN),
        ],
    )
    async def test_an_oversized_lookup_answer_costs_that_source(
        self, host, body, isbn
    ):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            for other in (DNB, K10PLUS, OENB, NLG, NKP):
                mock.get(url__startswith=other).mock(
                    return_value=_xml(
                        getattr(self, body)() if other == host else OENB_EMPTY
                    )
                )
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            result = await lookup(isbn)

        name = {
            DNB: "dnb", K10PLUS: "k10plus", OENB: "oenb", NLG: "nlg", NKP: "nkp"
        }[host]
        assert (name, Outcome.UNAVAILABLE) in result.attempts
        assert result.outcome is not Outcome.FOUND

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "host, body",
        [
            (DNB, "_marc_over_cap"),
            (K10PLUS, "_marc_over_cap"),
            (OENB, "_oenb_over_cap"),
            (NLG, "_marc_over_cap"),
            ("https://catalogue.bnf.fr", "_dublincore_over_cap"),
            ("http://lx2.loc.gov", "_mods_over_cap"),
        ],
    )
    async def test_an_oversized_search_answer_costs_that_source_its_rows(
        self, host, body
    ):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            for other, empty in (
                (DNB, DNB_EMPTY),
                (K10PLUS, K10PLUS_EMPTY),
                (OENB, OENB_EMPTY),
                (NLG, NLG_EMPTY),
                ("https://catalogue.bnf.fr", DNB_EMPTY),
                ("http://lx2.loc.gov", DNB_EMPTY),
            ):
                mock.get(url__startswith=other).mock(
                    return_value=_xml(
                        getattr(self, body)() if other == host else empty
                    )
                )
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(200, json={"docs": []})
            )
            rows = await search("clean code")

        assert rows == []

    @pytest.mark.asyncio
    async def test_an_enormous_catalogue_answer_is_unavailable_not_a_500(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_oenb(mock)
            silence_nkp(mock)
            silence_nlg(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_EMPTY)
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(self.ENORMOUS))
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            result = await lookup(GERMAN_ISBN)

        assert ("dnb", Outcome.UNAVAILABLE) in result.attempts

    @pytest.mark.asyncio
    async def test_one_enormous_source_does_not_cost_the_others(self):
        """The margin over the largest honest page is 1.52x, so a cap set a
        little low has to be survivable. It is: the other sources answer."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(self.ENORMOUS))
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_RECORD)
            )
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            result = await lookup(ENGLISH_ISBN)

        assert result.source == "k10plus"



class TestMarcSubfields:
    """What a MARC record carries that a Dublin Core crosswalk had cleaned up."""

    def test_a_repeated_subfield_keeps_every_value(self):
        """082 holds `$a=830 $a=B`, and the letter is not a Dewey number."""
        fields = _marc_fields(_marc_element('''
          <datafield tag="082" ind1="7" ind2="4">
           <subfield code="a">830</subfield><subfield code="a">B</subfield>
          </datafield>'''))
        assert fields["082"][0].all("a") == ["830", "B"]

    def test_indexing_a_repeated_subfield_gives_the_first_value(self):
        """`$0` arrives as the GND number, then two URIs for the same thing."""
        fields = _marc_fields(_marc_element('''
          <datafield tag="100" ind1="1" ind2=" ">
           <subfield code="0">(DE-588)118181505</subfield>
           <subfield code="0">https://d-nb.info/gnd/118181505</subfield>
           <subfield code="a">Capus, Alex</subfield>
          </datafield>'''))
        assert fields["100"][0]["0"] == "(DE-588)118181505"

    def test_the_non_sorting_delimiters_are_stripped(self):
        """MARC brackets a leading article so it can be skipped when filing.

        They are invisible in a terminal, and 28 of 85 live records hold one.
        """
        fields = _marc_fields(_marc_element(
            '<datafield tag="245" ind1="1" ind2="0">'
            '<subfield code="a">\x98Die\x9c Deutschen</subfield></datafield>'
        ))
        assert fields["245"][0]["a"] == "Die Deutschen"

    def test_padding_inside_a_subfield_is_collapsed(self):
        """MARC pads subfields. `245 $a` on the live record 9783446249974 reads
        `Reisen im  Licht der Sterne`, where that record's own `776 $t` spells
        it with one space."""
        fields = _marc_fields(_marc_element(
            '<datafield tag="245" ind1="1" ind2="0">'
            '<subfield code="a">Reisen im  Licht der Sterne</subfield>'
            "</datafield>"
        ))
        assert fields["245"][0]["a"] == "Reisen im Licht der Sterne"

    def test_decomposed_text_is_normalised(self):
        """The DNB serves MARC21 decomposed and Dublin Core composed.

        Two spellings of one author is enough to store the same person twice.
        """
        fields = _marc_fields(_marc_element(
            '<datafield tag="100" ind1="1" ind2=" ">'
            '<subfield code="a">Mu\u0308ller, Hans</subfield></datafield>'
        ))
        assert fields["100"][0]["a"] == "M\u00fcller, Hans"


class TestASubjectCarriesTheVocabularyTheRecordDeclared:
    """#134: the `$2` and the `$0`, which were both discarded before it.

    Everything here is a parser test on a field, because that is where the
    ticket's whole change is. Nothing is stored: a subject reaches
    `books.categories` as words and nothing else, and giving the vocabulary a
    column is #143. What these pin is that the stamp survives as far as the
    seam, and that nothing is invented on the way.
    """

    @staticmethod
    def _subjects(datafields: str) -> list[Subject]:
        subjects, _ = _dnb_subjects(_marc_fields(_marc_element(datafields)))
        return subjects

    def test_the_declared_vocabulary_and_the_identifier_are_both_kept(self):
        """The DNB's ordinary `650`: `$2 gnd` with a `(DE-588)` in `$0`."""
        assert self._subjects(
            '<datafield tag="650" ind1=" " ind2="7">'
            '<subfield code="0">(DE-588)4026894-9</subfield>'
            '<subfield code="a">Informatik</subfield>'
            '<subfield code="2">gnd</subfield></datafield>'
        ) == [Subject("Informatik", "gnd", "(DE-588)4026894-9")]

    def test_the_greek_authority_identifier_is_kept_whole(self):
        """The field the ticket was written around. `_gnd_identifier` drops
        this, and measured 2026-08-31 it drops **11 of 11** of the National
        Library of Greece's identifiers, because none is a `(DE-588)`."""
        assert self._subjects(
            '<datafield tag="651" ind1=" " ind2="7">'
            '<subfield code="a">Ευρώπη</subfield>'
            '<subfield code="0">urn:nbn:gr:nlg:01-A273635</subfield>'
            '<subfield code="2">nlgaf</subfield></datafield>'
        ) == [Subject("Ευρώπη", "nlgaf", "urn:nbn:gr:nlg:01-A273635")]

    def test_a_record_declaring_nothing_leaves_the_vocabulary_null(self):
        """Null and never guessed at, which is 199 of 199 live DNB `689`
        fields and 130 of 133 live K10plus `650` fields."""
        assert self._subjects(
            '<datafield tag="650" ind1=" " ind2=" ">'
            '<subfield code="a">Kochbuch</subfield></datafield>'
        ) == [Subject("Kochbuch", None, None)]

    def test_an_identifier_with_no_vocabulary_beside_it_is_still_kept(self):
        """K10plus writes `$0 (OCoLC)fst…` with no `$2` at all, on 3 of 133
        live `650` fields. The ticket asks for the identifier *whatever* the
        scheme, and a missing `$2` is not a reason to drop one."""
        assert self._subjects(
            '<datafield tag="650" ind1=" " ind2=" ">'
            '<subfield code="a">Psychology</subfield>'
            '<subfield code="0">(OCoLC)fst01081447</subfield></datafield>'
        ) == [Subject("Psychology", None, "(OCoLC)fst01081447")]

    def test_a_vocabulary_with_no_identifier_beside_it_is_still_kept(self):
        """The OENB's `655 $2 bellobv`, which carries no `$0`."""
        assert self._subjects(
            '<datafield tag="655" ind1=" " ind2="7">'
            '<subfield code="a">Roman</subfield>'
            '<subfield code="2">bellobv</subfield></datafield>'
        ) == [Subject("Roman", "bellobv", None)]

    def test_the_vocabulary_code_is_lower_cased(self):
        """Two of the twelve codes measured are upper case, `VLK` on the OENB
        and `DLC` on K10plus. Unfolded, one vocabulary is two strings."""
        assert self._subjects(
            '<datafield tag="650" ind1=" " ind2="7">'
            '<subfield code="a">Drittes Reich</subfield>'
            '<subfield code="2">VLK</subfield></datafield>'
        ) == [Subject("Drittes Reich", "vlk", None)]

    def test_the_identifier_keeps_the_prefix_a_classification_drops(self):
        """`Classification.number` stores a GND number bare because the row has
        a scheme column. Here there is none, and `$2` does not supply one: this
        field names the DNB's genre list and the DNB's own authority file, which
        are two different answers."""
        assert self._subjects(
            '<datafield tag="655" ind1=" " ind2="7">'
            '<subfield code="a">Lyrik</subfield>'
            '<subfield code="0">(DE-101)1010836315</subfield>'
            '<subfield code="2">gatbeg</subfield></datafield>'
        ) == [Subject("Lyrik", "gatbeg", "(DE-101)1010836315")]

    def test_an_empty_leading_dollar_zero_does_not_lose_the_identifier(self):
        """The shape the live measurement could not see, because no catalogue
        writes it: `_marc_text` turns `<subfield code="0"/>` into `""`, so the
        first value is empty and the number sits behind it. 0 of the 718 live
        fields carry an empty `$0` anywhere, which is exactly why "the first
        `$0`" read as safe.

        **The two readers disagreeing is the defect, not the None.**
        `_gnd_identifier` scans every `$0`, so it found the number and wrote a
        classification row, while the subject beside it carried no identifier at
        all off the same field.
        """
        entry = _marc_fields(_marc_element(
            '<datafield tag="650" ind1=" " ind2="7">'
            '<subfield code="a">Informatik</subfield>'
            '<subfield code="0"/>'
            '<subfield code="0">(DE-588)4026894-9</subfield>'
            '<subfield code="2">gnd</subfield></datafield>'
        ))["650"][0]

        assert entry.all("0") == ["", "(DE-588)4026894-9"]
        assert _subject_identifier(entry) == "(DE-588)4026894-9"
        assert metadata._gnd_identifier(entry) == "4026894-9"

    def test_a_field_whose_only_identifier_is_empty_has_none(self):
        """The diagonal for the test above: skipping empties must not invent
        one. Without this, a reader returning the last value would pass the
        test above and fail here."""
        entry = _marc_fields(_marc_element(
            '<datafield tag="650" ind1=" " ind2="7">'
            '<subfield code="a">Informatik</subfield>'
            '<subfield code="0"/></datafield>'
        ))["650"][0]

        assert _subject_identifier(entry) is None

    def test_the_first_identifier_is_the_one_taken(self):
        """Where a live subject field carries a `(DE-588)` it is the first of
        its `$0` values, 691 of 691, and the `d-nb.info` URL and the `(DE-101)`
        house number follow. This is that order, and taking the last would file
        the DNB's own shelf number where the GND identifier is the point."""
        assert self._subjects(
            '<datafield tag="650" ind1=" " ind2="7">'
            '<subfield code="0">(DE-588)4026894-9</subfield>'
            '<subfield code="0">https://d-nb.info/gnd/4026894-9</subfield>'
            '<subfield code="0">(DE-101)4026894-9</subfield>'
            '<subfield code="a">Informatik</subfield>'
            '<subfield code="2">gnd</subfield></datafield>'
        ) == [Subject("Informatik", "gnd", "(DE-588)4026894-9")]

    def test_a_dewey_edition_number_is_never_read_as_a_vocabulary(self):
        """`$2` means something else on `082`: it is the Dewey **edition**, and
        the three fixtures in this file spell it `23sdnb`, `22/ger` and `21`.

        **This test used to assert the trap open.** It read
        `_subject_vocabulary(fields["082"][0]) == "21"` to show the field really
        carries a readable `$2`, which was true and was also the call the
        docstring claimed was impossible. The reader now takes the tag and
        raises, so the same demonstration is a `pytest.raises`, and the
        anti vacuity it was there for is unchanged: without it the two
        assertions below pass on a record with no subject field, which is every
        record.
        """
        fields = _marc_fields(_marc_element(
            '<datafield tag="082" ind1="0" ind2="4">'
            '<subfield code="a">940</subfield>'
            '<subfield code="2">21</subfield></datafield>'
        ))
        subjects, headings = _dnb_subjects(fields)

        with pytest.raises(ValueError, match="082"):
            _subject_vocabulary("082", fields["082"][0])
        assert subjects == []
        assert headings == []
        assert [heading.number for heading in metadata._marc_ddc(fields)] == ["940"]

    def test_a_classification_row_is_still_written_for_the_gnd_alone(self):
        """The half that deliberately did not change. A `classifications` row
        names a scheme from a closed four member set, so the Greek authority
        file cannot be one however well the record declares it."""
        greek = (
            '<datafield tag="651" ind1=" " ind2="7">'
            '<subfield code="a">Ευρώπη</subfield>'
            '<subfield code="0">urn:nbn:gr:nlg:01-A273635</subfield>'
            '<subfield code="2">nlgaf</subfield></datafield>'
        )
        german = (
            '<datafield tag="650" ind1=" " ind2="7">'
            '<subfield code="0">(DE-588)4026894-9</subfield>'
            '<subfield code="a">Informatik</subfield>'
            '<subfield code="2">gnd</subfield></datafield>'
        )
        _, headings = _dnb_subjects(_marc_fields(_marc_element(greek + german)))

        assert headings == [
            Heading(ClassificationScheme.GND, "4026894-9", "Informatik")
        ]

    def test_the_689_restatement_folds_into_the_field_that_declared(self):
        """A whole DNB record, through the parser and the seam. `650` declares
        `gnd` and `689` restates the same words declaring nothing, on 199 of 199
        live fields, and the record must carry the heading once."""
        node = next(_parsed(DNB_RECORD).iter(f"{metadata._MARC}record"))
        record = metadata._dnb_record(_marc_fields(node), "9783960092353")

        assert record is not None
        assert record.subjects == (
            Subject("Informatik", "gnd", "(DE-588)4026894-9"),
        )


class TestASubfieldReaderIsNotTwoReaders:
    """The two `$0` questions, which look like one rule and are not."""

    def test_the_vocabulary_reader_answers_none_where_there_is_no_dollar_two(self):
        entry = _marc_fields(_marc_element(
            '<datafield tag="650"><subfield code="a">X</subfield></datafield>'
        ))["650"][0]

        assert _subject_vocabulary("650", entry) is None

    def test_the_identifier_reader_answers_none_where_there_is_no_dollar_zero(self):
        entry = _marc_fields(_marc_element(
            '<datafield tag="650"><subfield code="a">X</subfield></datafield>'
        ))["650"][0]

        assert _subject_identifier(entry) is None

    def test_the_gnd_reader_still_searches_past_a_leading_house_number(self):
        """`_gnd_identifier` asks whether the field names a GND record, so it
        looks at every `$0`. `_subject_identifier` asks what the record led
        with, so it looks at one. A field written in the other order separates
        them, and no live catalogue writes that order: this pins the difference
        rather than the data."""
        entry = _marc_fields(_marc_element(
            '<datafield tag="650" ind1=" " ind2="7">'
            '<subfield code="0">(DE-101)1010836315</subfield>'
            '<subfield code="0">(DE-588)4026894-9</subfield>'
            '<subfield code="a">Informatik</subfield></datafield>'
        ))["650"][0]

        assert metadata._gnd_identifier(entry) == "4026894-9"
        assert _subject_identifier(entry) == "(DE-101)1010836315"


class TestTheAuthorsAuthorityIdentifier:
    """`100 $0` and `700 $0`, which say which GND record wrote this book.

    The subject fields carry the identical subfield and go somewhere else: 600
    says a person is what the book is *about*. That split is
    `enums.AuthorityScheme`.
    """

    @staticmethod
    def _fields(*datafields: str):
        return _marc_fields(_marc_element("".join(datafields)))

    MAIN = (
        '<datafield tag="100" ind1="1" ind2=" ">'
        '<subfield code="0">(DE-588)1042243212</subfield>'
        '<subfield code="a">Kane, Sean P.</subfield>'
        '<subfield code="4">aut</subfield></datafield>'
    )

    def test_the_main_entry_identifier_is_stored_bare(self):
        """Without `(DE-588)`: the scheme is a column, and keeping the prefix
        would let one identifier arrive under two spellings the unique index
        cannot collapse. The same rule `_gnd_identifier` states for a heading."""
        assert _marc_author_identifiers(self._fields(self.MAIN)) == [
            AuthorityAssertion("Sean P. Kane", AuthorityScheme.GND, "1042243212")
        ]

    def test_a_record_with_no_identifier_produces_none(self):
        """21 of 73 live 100 fields carry no `(DE-588)` at all, measured over 85
        records on 2026-08-24. Ordinary, not broken."""
        fields = self._fields(
            '<datafield tag="100" ind1="1" ind2=" ">'
            '<subfield code="a">Kane, Sean P.</subfield></datafield>'
        )

        assert _marc_author_identifiers(fields) == []

    def test_a_700_that_wrote_the_book_is_read(self):
        fields = self._fields(
            self.MAIN,
            '<datafield tag="700" ind1="1" ind2=" ">'
            '<subfield code="0">(DE-588)1042243213</subfield>'
            '<subfield code="a">Matthias, Karl</subfield>'
            '<subfield code="4">aut</subfield></datafield>',
        )

        assert _marc_author_identifiers(fields) == [
            AuthorityAssertion("Sean P. Kane", AuthorityScheme.GND, "1042243212"),
            AuthorityAssertion("Karl Matthias", AuthorityScheme.GND, "1042243213"),
        ]

    def test_a_700_that_only_translated_it_is_not(self):
        """`$4=trl` is a translator. Reading it would file a translator's GND
        under a name that is not in this Book's credit line at all."""
        fields = self._fields(
            self.MAIN,
            '<datafield tag="700" ind1="1" ind2=" ">'
            '<subfield code="0">(DE-588)9999</subfield>'
            '<subfield code="a">Meier, Eva</subfield>'
            '<subfield code="4">trl</subfield></datafield>',
        )

        assert [row.identifier for row in _marc_author_identifiers(fields)] == [
            "1042243212"
        ]

    def test_an_added_entry_for_a_work_is_not_a_person_here(self):
        """`$t` links the original title, and the name beside it is that work's
        author rather than a second author of this book."""
        fields = self._fields(
            self.MAIN,
            '<datafield tag="700" ind1="1" ind2=" ">'
            '<subfield code="0">(DE-588)9999</subfield>'
            '<subfield code="a">Melville, Herman</subfield>'
            '<subfield code="t">Moby Dick</subfield>'
            '<subfield code="4">aut</subfield></datafield>',
        )

        assert [row.identifier for row in _marc_author_identifiers(fields)] == [
            "1042243212"
        ]

    def test_every_identifier_is_filed_under_a_name_in_the_credit_line(self):
        """The property `_marc_author_entries` exists to make structural.

        Two loops testing the same three conditions would let the credit line
        and the identifiers drift apart, and the symptom would be a row filed
        under a spelling no Book carries: invisible, undeletable through the UI,
        and never matched by anything.
        """
        fields = self._fields(
            self.MAIN,
            '<datafield tag="700" ind1="1" ind2=" ">'
            '<subfield code="0">(DE-588)1042243213</subfield>'
            '<subfield code="a">Matthias, Karl</subfield>'
            '<subfield code="4">aut</subfield></datafield>',
            '<datafield tag="700" ind1="1" ind2=" ">'
            '<subfield code="0">(DE-588)9999</subfield>'
            '<subfield code="a">Meier, Eva</subfield>'
            '<subfield code="4">trl</subfield></datafield>',
        )

        credited = _marc_authors(fields) or ""
        for row in _marc_author_identifiers(fields):
            assert row.name in credited

    def test_one_person_named_by_both_100_and_700_is_asserted_once(self):
        fields = self._fields(
            self.MAIN,
            '<datafield tag="700" ind1="1" ind2=" ">'
            '<subfield code="0">(DE-588)1042243212</subfield>'
            '<subfield code="a">Kane, Sean P.</subfield>'
            '<subfield code="4">aut</subfield></datafield>',
        )

        assert len(_marc_author_identifiers(fields)) == 1


class TestPersonName:
    def test_turns_catalogue_order_into_a_readable_name(self):
        assert _flip_catalogue_name("Kane, Sean P.") == "Sean P. Kane"

    def test_keeps_the_full_stop_that_belongs_to_an_initial(self):
        """`Pohl, Robert O.` means nothing as `Robert O`, and the ISBD full stop
        stripped off `Melville, Herman.` looks the same to a regex."""
        assert _flip_catalogue_name("Pohl, Robert O.") == "Robert O. Pohl"

    def test_drops_the_life_dates_a_catalogue_hangs_off_a_name(self):
        assert _flip_catalogue_name("Melville, Herman, 1819-1891") == "Herman Melville"

    def test_leaves_a_corporate_name_alone(self):
        """Two commas is not "Surname, Forenames" and reordering would mangle it."""
        assert (
            _flip_catalogue_name("Springer Verlag, Berlin, Heidelberg")
            == "Springer Verlag, Berlin, Heidelberg"
        )


class TestPageCount:
    """Shared by the DNB and K10plus parsers, which spell the extent differently."""

    def test_reads_the_german_form(self):
        assert _pages_from_extent("390 Seiten") == 390

    def test_reads_the_english_form(self):
        assert _pages_from_extent("412 pages") == 412

    def test_returns_nothing_for_an_extent_it_cannot_parse(self):
        assert _pages_from_extent("1 Online-Ressource") is None

    def test_reads_the_abbreviated_form_k10plus_uses(self):
        assert _pages_from_extent("348 S.") == 348

    def test_ignores_the_dimensions_that_follow_the_extent(self):
        """A bare first number picks up "23 cm" as a page count."""
        assert _pages_from_extent("528 p. : ill. ; 23 cm") == 528

    def test_returns_nothing_for_an_absent_field(self):
        assert _pages_from_extent(None) is None


class TestK10plusIdentity:
    """Matching an ISBN is not the same as being the book it belongs to."""

    @pytest.mark.asyncio
    async def test_a_qualified_isbn_beside_the_records_own_is_a_cross_reference(self):
        """`020 $q` beside an unqualified entry names another edition.

        Observed live: searching Dune's American ISBN returned a Ukrainian
        translation whose record carries `9780441013593 $q amerik. Original`.

        **The record carries its own ISBN too, and this fixture used to leave it
        out.** Re-read live on 2026-08-30, `pica.isb=9780441013593` returns two
        records: the translation, `9786171276895` with the American ISBN beside
        it as `$q amerik. Original`, and the American edition itself, both of
        whose entries read `$q : pbk.`. Both halves of `_isbn_entries` are in
        that one answer, which is why the two tests here are its two arms: the
        translation is refused because it names its own ISBN plainly, and the
        edition below is taken because it names nothing else.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_oenb(mock)
            silence_nkp(mock)
            silence_nlg(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(
                    _marc(
                        _marc_record(
                            isbn=ENGLISH_ISBN,
                            isbn_qualifier="amerik. Original",
                            title='<subfield code="a">Velykyj Hetsbi</subfield>',
                            extra=(
                                '<datafield tag="020">'
                                '<subfield code="a">9786171276895</subfield>'
                                "</datafield>"
                            ),
                        )
                    )
                )
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            result = await lookup(ENGLISH_ISBN)

        assert result.outcome is Outcome.NOT_FOUND

    @pytest.mark.asyncio
    async def test_a_record_whose_every_isbn_is_qualified_is_still_this_book(self):
        """A binding is not a cross reference, and refusing it lost the book.

        The qualifier here is what a Greek record writes on a fifth of the books
        it holds. Measured 2026-08-30 over 500 distinct NLG records drawn from
        ten title searches: 317 carry an 020 and **63 of those name their ISBN
        only in a qualified entry**. The K10plus figure from the same probe is
        159 of 231.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_oenb(mock)
            silence_nkp(mock)
            silence_nlg(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(
                    _marc(_marc_record(isbn=ENGLISH_ISBN, isbn_qualifier="χαρτόδετο"))
                )
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(ENGLISH_ISBN)

        assert result.outcome is Outcome.FOUND
        assert result.source == "k10plus"

    @pytest.mark.asyncio
    async def test_matches_a_record_holding_the_isbn_10_form(self):
        """020 often holds the ISBN-10 even for a search by ISBN-13.

        Comparing the strings would miss the record, which is most of what a
        pre-2007 printing is catalogued under.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(_marc_record(isbn="0743273567"))
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(ENGLISH_ISBN)

        assert result.source == "k10plus"
        assert result.record is not None
        assert result.record.title == "The Great Gatsby"

    @pytest.mark.asyncio
    async def test_prefers_the_fullest_of_several_printings(self):
        """One ISBN returns a handful of near-identical records."""
        sparse = _marc_record(title='<subfield code="a">The Great Gatsby</subfield>')
        full = _marc_record(
            title='<subfield code="a">The Great Gatsby</subfield>',
            extra='<datafield tag="520"><subfield code="a">Long Island, 1922.</subfield></datafield>',
        )
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(_marc(sparse, full))
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(ENGLISH_ISBN)

        assert result.record is not None
        assert result.record.description == "Long Island, 1922."


class TestK10plusRecord:
    """MARC packs the shape of a catalogue card, not the shape of a book."""

    async def _lookup(self, record: str, isbn: str = ENGLISH_ISBN):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(return_value=_xml(_marc(record)))
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(isbn)
        assert result.record is not None
        return result.record

    @pytest.mark.asyncio
    async def test_maps_the_record_onto_book_fields(self):
        data = await self._lookup(_marc_record())
        assert data.title == "The Great Gatsby"
        assert data.author == "F. Scott Fitzgerald"
        assert data.publisher == "Scribner"
        assert data.year == 1925
        assert data.page_count == 218
        assert data.language == "en"

    @pytest.mark.asyncio
    async def test_reads_the_year_out_of_a_free_text_date(self):
        """`$c` really does arrive as "1925 (copyright)"."""
        data = await self._lookup(_marc_record())
        assert data.year == 1925

    @pytest.mark.asyncio
    async def test_drops_the_punctuation_that_introduces_the_next_subfield(self):
        """A record ends `$a` with the separator for `$b`, so titles carry a colon."""
        data = await self._lookup(
            _marc_record(
                title=(
                    '<subfield code="a">The Great Gatsby :</subfield>'
                    '<subfield code="b">a novel</subfield>'
                )
            )
        )
        assert data.title == "The Great Gatsby"
        assert data.subtitle == "a novel"

    @pytest.mark.asyncio
    async def test_closes_the_filing_space_after_an_elided_article(self):
        """`L' etranger` is a sorting device, not how the title is printed."""
        data = await self._lookup(
            _marc_record(title="<subfield code=\"a\">L' etranger</subfield>")
        )
        assert data.title == "L'etranger"

    @pytest.mark.asyncio
    async def test_a_numbered_volume_becomes_a_title_and_a_series(self):
        """`$a` is the collective title and `$p` the book somebody is holding.

        Without this the whole series is catalogued seven times under one name.
        """
        data = await self._lookup(
            _marc_record(
                title=(
                    '<subfield code="a">Harry Potter</subfield>'
                    '<subfield code="n">[1]</subfield>'
                    '<subfield code="p">The philosopher\'s stone</subfield>'
                )
            )
        )
        assert data.title == "The philosopher's stone"
        assert data.series_name == "Harry Potter"
        assert data.series_index == 1

    @pytest.mark.asyncio
    async def test_keeps_the_author_and_drops_the_translator(self):
        """A translator arrives in the same field as an author, marked `$4`."""
        data = await self._lookup(
            _marc_record(
                extra=(
                    '<datafield tag="700"><subfield code="a">Robben, Bernhard</subfield>'
                    '<subfield code="4">trl</subfield></datafield>'
                )
            )
        )
        assert data.author == "F. Scott Fitzgerald"

    @pytest.mark.asyncio
    async def test_ignores_an_added_entry_for_the_original_work(self):
        """A 700 carrying `$t` links a title, and its name is already the author's."""
        data = await self._lookup(
            _marc_record(
                extra=(
                    '<datafield tag="700"><subfield code="a">Fitzgerald, F. Scott</subfield>'
                    '<subfield code="t">The Great Gatsby</subfield>'
                    '<subfield code="4">aut</subfield></datafield>'
                )
            )
        )
        assert data.author == "F. Scott Fitzgerald"

    @pytest.mark.asyncio
    async def test_leaves_a_corporate_name_in_catalogue_order(self):
        """Two commas is not "Surname, Forenames", and flipping it mangles it."""
        data = await self._lookup(
            '<record xmlns="http://www.loc.gov/MARC21/slim">'
            f'<datafield tag="020"><subfield code="a">{ENGLISH_ISBN}</subfield></datafield>'
            '<datafield tag="245"><subfield code="a">A report</subfield></datafield>'
            '<datafield tag="100">'
            '<subfield code="a">Springer, Berlin, Heidelberg</subfield>'
            '<subfield code="4">aut</subfield></datafield></record>'
        )
        assert data.author == "Springer, Berlin, Heidelberg"


class TestCrossReferenceGuard:
    """The DNB's identifier index matches a mention, not an identity."""

    def test_a_volume_slot_is_not_a_title(self):
        assert _is_placeholder_title("[Hauptbd.].")
        assert _is_placeholder_title("Bd. 3")
        assert _is_placeholder_title("Volume 2")
        assert _is_placeholder_title("")

    def test_a_real_title_is_kept(self):
        assert not _is_placeholder_title("Stoner")
        # "Band" is a prefix of this and must not match it.
        assert not _is_placeholder_title("Banditen")

    @pytest.mark.asyncio
    async def test_a_placeholder_record_is_a_miss_so_another_source_can_answer(self):
        """Observed live: a French ISBN returned a German set titled `[Hauptbd.].`

        Accepting it poisons the catalogue entry for good, and the record it
        displaced was sitting in the other source all along.
        """
        placeholder = DNB_RECORD.replace(
            '<subfield code="a">Praxiswissen Docker</subfield>',
            '<subfield code="a">[Hauptbd.].</subfield>',
        )
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(_marc(_marc_record(isbn=GERMAN_ISBN)))
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(placeholder))
            result = await lookup(GERMAN_ISBN)

        assert result.source == "k10plus"


class TestMerge:
    """Taking the first hit and stopping left fields empty that the other had."""

    @pytest.mark.asyncio
    async def test_fills_gaps_from_the_other_catalogue(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(
                    _marc(
                        _marc_record(
                            isbn=GERMAN_ISBN,
                            extra=(
                                '<datafield tag="520">'
                                '<subfield code="a">Long Island, 1922.</subfield>'
                                "</datafield>"
                            ),
                        )
                    )
                )
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            result = await lookup(GERMAN_ISBN)

        assert result.record is not None
        # The DNB leads for a German ISBN and keeps its own title.
        assert result.record.title == "Praxiswissen Docker"
        # The blurb exists only on the K10plus record. A DNB record never
        # carries one, so this is the field that proves a merge happened.
        assert result.record.description == "Long Island, 1922."
        assert result.source == "dnb+k10plus"

    @pytest.mark.asyncio
    async def test_a_field_that_is_already_set_is_never_overwritten(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(
                    _marc(
                        _marc_record(
                            isbn=GERMAN_ISBN,
                            title='<subfield code="a">Wrong title</subfield>',
                        )
                    )
                )
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            result = await lookup(GERMAN_ISBN)

        assert result.record is not None
        assert result.record.title == "Praxiswissen Docker"

    @pytest.mark.asyncio
    async def test_subjects_are_unioned_because_both_feed_the_tag_guess(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(
                    _marc(
                        _marc_record(
                            isbn=GERMAN_ISBN,
                            extra=(
                                '<datafield tag="650"><subfield code="a">Science Fiction</subfield>'
                                "</datafield>"
                            ),
                        )
                    )
                )
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            result = await lookup(GERMAN_ISBN)

        assert result.record is not None
        assert set(result.record.subject_labels) == {"Informatik", "Science Fiction"}

    @pytest.mark.asyncio
    async def test_a_classification_is_kept_whole_and_its_caption_too(self):
        """Both halves, because they catch opposite records.

        The caption is what a substring match against an English tag name
        needs; the number is what a German record has instead. Dropping either
        narrows the suggestion rather than sharpening it.

        **What supplies which half moved on 2026-08-24.** Under Dublin Core the
        DNB captioned its Dewey number, `830 Deutsche Literatur`; MARC 082
        carries the number alone, and it is the GND subject heading that now
        arrives with words attached.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(return_value=_xml(K10PLUS_EMPTY))
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            result = await lookup(GERMAN_ISBN)

        assert result.record is not None
        assert result.record.headings == (
            Heading(ClassificationScheme.DDC, "004"),
            Heading(ClassificationScheme.GND, "4026894-9", "Informatik"),
        )

    @pytest.mark.asyncio
    async def test_a_marc_dewey_number_arrives_with_no_caption(self):
        """082 carries the notation and the printed schedule carries the words,
        so a caption here would be ours rather than the catalogue's."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(
                    _marc(
                        _marc_record(
                            isbn=GERMAN_ISBN,
                            extra=(
                                '<datafield tag="082"><subfield code="a">005.133</subfield>'
                                "</datafield>"
                            ),
                        )
                    )
                )
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(GERMAN_ISBN)

        assert result.record is not None
        assert result.record.headings == (
            Heading(ClassificationScheme.DDC, "005.133"),
        )

    @pytest.mark.asyncio
    async def test_the_marc_segmentation_prime_is_stripped(self):
        """`005.13/3` is how K10plus spells what the DNB stores as `005.133`.
        Measured live 2026-08-23: 53 of 463 082 `$a` values carry the prime, so
        storing it raw makes two rows for one heading."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(
                    _marc(
                        _marc_record(
                            isbn=GERMAN_ISBN,
                            extra=(
                                '<datafield tag="082"><subfield code="a">005.13/3</subfield>'
                                "</datafield>"
                            ),
                        )
                    )
                )
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(GERMAN_ISBN)

        assert result.record is not None
        assert result.record.headings == (
            Heading(ClassificationScheme.DDC, "005.133"),
        )

    @pytest.mark.asyncio
    async def test_a_marc_field_that_is_not_a_dewey_number_is_dropped(self):
        """084 holds RVK and BK notations in the same shape. A number whose
        scheme nothing here reads cannot be sorted, matched or shown."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(
                    _marc(
                        _marc_record(
                            isbn=GERMAN_ISBN,
                            extra=(
                                '<datafield tag="082"><subfield code="a">ST 250</subfield>'
                                "</datafield>"
                            ),
                        )
                    )
                )
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            result = await lookup(GERMAN_ISBN)

        assert result.record is not None
        assert result.record.headings == ()

    @pytest.mark.asyncio
    async def test_k10plus_leads_for_a_non_german_isbn(self):
        """The DNB holds foreign books mostly as cross references, not records."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(_marc(_marc_record(isbn=ENGLISH_ISBN)))
            )
            mock.get(url__startswith=DNB).mock(
                return_value=_xml(
                    DNB_RECORD.replace("Praxiswissen Docker", "Etwas anderes")
                )
            )
            result = await lookup(ENGLISH_ISBN)

        assert result.record is not None
        assert result.record.title == "The Great Gatsby"


class TestSearchTerms:
    """A typed query goes into a query language, so it has to be made safe."""

    def test_splits_on_whitespace(self):
        assert metadata._search_terms("moby dick melville") == [
            "moby",
            "dick",
            "melville",
        ]

    def test_strips_cql_metacharacters(self):
        """No book's title depends on an unbalanced quote."""
        assert '"' not in "".join(metadata._search_terms('moby "dick" =(x)'))

    def test_drops_boolean_keywords(self):
        """A search for "black and white" must not become an operator."""
        assert metadata._search_terms("black and white") == ["black", "white"]

    def test_drops_single_letters(self):
        """Initials and articles are noise in a catalogue index."""
        assert metadata._search_terms("j k rowling") == ["rowling"]

    def test_an_empty_query_yields_nothing(self):
        assert metadata._search_terms("   ") == []


class TestDenoising:
    """What the catalogues return that is not a book on a shelf."""

    @pytest.mark.parametrize(
        "extent",
        [
            "1 Online-Ressource (100 Seiten)",
            "1 online resource",
            "1 audio disc",
            "1 sound recording",
        ],
    )
    def test_a_digitised_or_recorded_copy_is_not_a_book(self, extent):
        assert not metadata._is_physical_book(extent, "Der Zauberberg")

    def test_a_printed_extent_is_a_book(self):
        assert metadata._is_physical_book("992 Seiten", "Der Zauberberg")

    def test_a_record_with_no_extent_is_allowed(self):
        """Plenty of good records omit it, and refusing them loses real books."""
        assert metadata._is_physical_book(None, "Der Zauberberg")

    def test_a_volume_slot_is_still_rejected(self):
        assert not metadata._is_physical_book("992 Seiten", "[Hauptbd.].")


class TestPersonNames:
    """Catalogues hang life dates and roles off a name. None of it is the name."""

    def test_strips_bnf_life_dates_and_role(self):
        assert (
            metadata._flip_catalogue_name("Zafón, Carlos (1964-2020). Auteur du texte")
            == "Carlos Zafón"
        )

    def test_strips_marc_life_dates(self):
        assert metadata._flip_catalogue_name("Melville, Herman, 1819-1891") == (
            "Herman Melville"
        )

    def test_leaves_an_ordinary_name_alone(self):
        assert metadata._flip_catalogue_name("Mann, Thomas") == "Thomas Mann"

    def test_leaves_a_corporate_name_in_catalogue_order(self):
        assert (
            metadata._flip_catalogue_name("Springer, Berlin, Heidelberg")
            == "Springer, Berlin, Heidelberg"
        )


class TestAccentsAndNearSpellings:
    """Half the shelf is not English and phone keyboards have no umlauts."""

    def test_folds_accents(self):
        assert metadata._normalise_words("Schätzing") == {"schatzing"}

    def test_matches_an_unaccented_spelling(self):
        assert metadata._matches_any("schatzing", {"schatzing"})

    def test_matches_a_genitive(self):
        """`Manns` against `mann`, which an exact set membership missed."""
        assert metadata._matches_any("manns", {"mann"})

    def test_does_not_match_a_different_word(self):
        assert not metadata._matches_any("code", {"coder", "encode"})


class TestRanking:
    """The catalogues return catalogue order, so the ranking here is the ranking."""

    def match(self, **overrides: Any) -> Record:
        """One row, defaulting to a primary source so the penalty is opt in."""
        overrides.setdefault("source", "open_library")
        return Record(**overrides)

    def rank(self, matches, query, prefer_language=None):
        terms = metadata._search_terms(query)
        return sorted(
            matches,
            key=lambda match: metadata._relevance(match, terms, prefer_language),
            reverse=True,
        )

    def test_the_novel_outranks_a_book_about_it(self):
        """The study guide carries the author's name inside its own title.

        Weighting a title match above an author match let it win, which is why
        they are worth the same and why the precision term exists.
        """
        novel = self.match(title="Der Zauberberg", author="Thomas Mann")
        guide = self.match(
            title="Textanalyse und Interpretation zu Thomas Manns Der Zauberberg",
            author="Nadine Heckner",
        )
        assert self.rank([guide, novel], "der zauberberg thomas mann")[0] is novel

    def test_a_row_matching_both_title_and_author_wins(self):
        """How people search: the title, then who wrote it."""
        novel = self.match(title="L'etranger", author="Albert Camus")
        study = self.match(title="L'Etranger, Camus", author="Pierre Louis Rey")
        assert self.rank([study, novel], "l'etranger camus")[0] is novel

    def test_a_complete_row_never_outranks_a_matching_one(self):
        """"Christmas at Hogwarts" came second for "harry potter" this way."""
        matching = self.match(title="Harry Potter and the Philosopher's Stone")
        unrelated = self.match(
            title="Christmas at Hogwarts",
            author="J. K. Rowling",
            year=2024,
            publisher="Bloomsbury",
            page_count=100,
            isbn="9780747532699",
            cover_url="https://example.test/cover.jpg",
        )
        ranked = self.rank([unrelated, matching], "harry potter philosopher stone")
        assert ranked[0] is matching

    def test_completeness_breaks_a_tie_between_equal_matches(self):
        sparse = self.match(title="Dune", author="Frank Herbert")
        full = self.match(
            title="Dune",
            author="Frank Herbert",
            year=1965,
            publisher="Chilton",
            page_count=412,
            isbn="9780441013593",
        )
        assert self.rank([sparse, full], "dune herbert")[0] is full

    def test_the_readers_language_breaks_a_tie(self):
        german = self.match(title="Der Schwarm", author="Frank Schätzing", language="de")
        english = self.match(title="Der Schwarm", author="Frank Schätzing", language="en")
        assert self.rank([english, german], "der schwarm schatzing", "de")[0] is german

    def test_the_readers_language_does_not_outrank_a_title_match(self):
        """A German library searching an English title still gets it."""
        wanted = self.match(title="Moby Dick", author="Herman Melville", language="en")
        other = self.match(title="Etwas anderes", author="Herman Melville", language="de")
        assert self.rank([other, wanted], "moby dick melville", "de")[0] is wanted

    def test_a_regional_only_row_ranks_below_an_equal_primary_one(self):
        primary = self.match(title="Dune", author="Frank Herbert", source="open_library")
        regional = self.match(title="Dune", author="Frank Herbert", source="loc")
        assert self.rank([regional, primary], "dune herbert")[0] is primary

    def test_a_regional_row_a_primary_also_found_is_not_penalised(self):
        """Being confirmed by a second catalogue is not a reason to demote."""
        confirmed = self.match(
            title="Der Schwarm", author="Frank Schätzing", source="bnf+k10plus",
            isbn="9783596164530",
        )
        thin = self.match(title="Der Schwarm", author="Frank Schätzing", source="k10plus")
        assert self.rank([thin, confirmed], "der schwarm schatzing")[0] is confirmed

    def test_a_subtitle_does_not_dilute_the_score(self):
        """It counts for matching and not for precision.

        Including it in the denominator put "Clean Code: A Handbook of Agile
        Software Craftsmanship" three points below a reprint with no subtitle.
        """
        with_subtitle = self.match(
            title="Clean Code",
            subtitle="A Handbook of Agile Software Craftsmanship",
            author="Robert C. Martin",
            year=2008,
            isbn="9780132350884",
            publisher="Prentice Hall",
            page_count=444,
        )
        without = self.match(title="Clean Code", author="Robert Martin", year=2025)
        assert self.rank([without, with_subtitle], "clean code robert martin")[0] is (
            with_subtitle
        )

    def test_a_row_matching_nothing_scores_zero(self):
        unrelated = self.match(title="Something else", author="Nobody")
        assert metadata._relevance(unrelated, ["dune"], None)[0] == 0


class TestAHostileSourceCostsItsOwnRows:
    """One source misbehaving must not take `GET /api/books/search` down.

    Seven are asked at once through `_within_deadline`, whose `task.result()`
    re-raises whatever a source raised. Eight of the thirteen `try` blocks that
    wrap a call into `fetch` catch `(httpx.HTTPError, ElementTree.ParseError)`
    and nothing else, so anything outside that pair becomes a 500 for the whole
    search rather than a missing tier.
    """

    #: An extent whose page count is too long for CPython to turn into an int.
    #:
    #: `int()` refuses a string of more than `sys.get_int_max_str_digits()`
    #: digits, 4,300 by default, and raises **`ValueError`**, which is neither
    #: `httpx.HTTPError` nor `ElementTree.ParseError`. Every MARC source runs its
    #: `300 $a` through `_pages_from_extent`, so one poisoned record 500s the
    #: whole request for all of them.
    #:
    #: **The response cap cannot reach this.** The poisoned envelope is 4,870
    #: bytes without an ISBN and 4,964 with one, 0.23% of
    #: `fetch.MAX_RESPONSE_BYTES` either way. More usefully, it is **larger than
    #: the smallest honest response this source sends**, an ÖNB lookup floor of
    #: 4,585 bytes measured over 50 live lookups, so no cap that still admits a
    #: real lookup could refuse it. It is a parser bound, not a transport one.
    POISONED_EXTENT = "9" * 4301 + " Seiten"

    def _poisoned_marc(self, isbn: str = "") -> str:
        """One MARC record whose only fault is an unparsable extent.

        **`isbn` is not decoration.** The lookup path drops any record whose own
        020 does not carry the ISBN asked for, so a poisoned record without one
        never reaches the parser and a test using it passes for the wrong
        reason. This one did, on the first attempt.
        """
        isbn_field = (
            f'<datafield tag="020" ind1=" " ind2=" ">'
            f'<subfield code="a">{isbn}</subfield></datafield>'
            if isbn
            else ""
        )
        return _oenb_envelope(
            '<record xmlns="http://www.loc.gov/MARC21/slim">'
            "<leader>01533nam a2200505 c 4500</leader>"
            f"{isbn_field}"
            '<datafield tag="245" ind1="1" ind2="0">'
            "<subfield code=\"a\">Poisoned</subfield></datafield>"
            '<datafield tag="300" ind1=" " ind2=" ">'
            f'<subfield code="a">{self.POISONED_EXTENT}</subfield></datafield>'
            "</record>"
        )

    @pytest.mark.asyncio
    async def test_an_unparsable_page_count_is_not_a_500(self):
        """A 4,870 byte record must cost its own row, not the whole search.

        The Library of Congress is reached over **plaintext HTTP**, so this
        needs no compromised catalogue: it is the same on-path attacker
        `fetch.RedirectedOffHost` exists for, and the same one the test above
        records. User story 6 asks for exactly this.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_nlg(mock)
            silence_nkp(mock)
            mock.get(url__startswith=K10PLUS).mock(return_value=_xml(K10PLUS_EMPTY))
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            mock.get(url__startswith="https://openlibrary.org/search.json").mock(
                return_value=httpx.Response(200, json={"docs": []})
            )
            mock.get(url__startswith="https://catalogue.bnf.fr").mock(
                return_value=httpx.Response(500)
            )
            mock.get(url__startswith="http://lx2.loc.gov").mock(
                return_value=httpx.Response(500)
            )
            oenb = mock.get(url__startswith=OENB).mock(
                return_value=_xml(self._poisoned_marc())
            )
            rows = await search("poisoned")

        assert oenb.called
        # **The row survives, and that is the right answer rather than a
        # concession.** Only the extent was unusable, so only the page count is
        # lost: the record still names a book somebody may want. Dropping the
        # row would let one bad subfield cost a real search result.
        assert [row.title for row in rows] == ["Poisoned"]
        assert rows[0].page_count is None

    @pytest.mark.asyncio
    async def test_an_unparsable_page_count_does_not_500_a_lookup(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_nlg(mock)
            silence_nkp(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            mock.get(url__startswith=K10PLUS).mock(return_value=_xml(K10PLUS_EMPTY))
            mock.get(url__startswith=OENB).mock(
                return_value=_xml(self._poisoned_marc("9783700316206"))
            )
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            result = await lookup("9783700316206")

        assert result.outcome is Outcome.FOUND
        assert result.record is not None
        assert result.record.page_count is None

    @pytest.mark.parametrize(
        "extent, expected",
        [
            ("390 Seiten", 390),
            ("348 S.", 348),
            ("528 p.", 528),
            ("III, 272 S.", 272),
            # The bound `_open_library_pages` has always applied, now applied
            # here too: a page count out of range is no page count.
            ("999999 Seiten", None),
            ("0 Seiten", None),
            # The digit run is refused whole rather than having its tail read
            # as a page count, which is what a bare `\d{1,6}` would have done.
            ("9" * 4301 + " Seiten", None),
            ("9" * 12 + " Seiten", None),
            # **This is the case that actually pins the lookbehind**, and the
            # two above are not: with `\d{1,6}` and no lookbehind they match
            # the last six digits, `999999`, which the range check rejects
            # anyway, so both still answer None with the guard removed. Here
            # the tail is a plausible page count, so dropping the lookbehind
            # invents 350 out of the end of an attack. Measured: the mutation
            # survived the whole file until this row existed.
            ("1" * 20 + "000350 Seiten", None),
            # Still not a page count.
            ("23 cm", None),
            (None, None),
        ],
    )
    def test_a_page_count_is_bounded_at_both_ends(self, extent, expected):
        assert metadata._pages_from_extent(extent) == expected

    @pytest.mark.asyncio
    async def test_a_redirect_naming_an_unusable_host_is_not_a_500(self):
        """The one that got through, and it needed no compromised catalogue.

        httpx builds the redirect request inside `send()` even with
        `follow_redirects=False`, so `URL.host` calls `idna.decode` before the
        hop guard runs. `idna.IDNAError` is a `UnicodeError`, so
        `location: http://xn--a.gov/x` came out of the Library of Congress title search as a bare
        `ValueError`. Plain ASCII on the wire, and the Library of Congress is
        the one source reached over plaintext HTTP.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_oenb(mock)
            silence_nkp(mock)
            silence_nlg(mock)
            mock.get(url__startswith=K10PLUS).mock(return_value=_xml(K10PLUS_EMPTY))
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            mock.get(url__startswith="https://openlibrary.org/search.json").mock(
                return_value=httpx.Response(200, json={"docs": []})
            )
            mock.get(url__startswith="https://catalogue.bnf.fr").mock(
                return_value=httpx.Response(500)
            )
            loc = mock.get(url__startswith="http://lx2.loc.gov").mock(
                return_value=httpx.Response(
                    302, headers={"location": "http://xn--a.gov/x"}
                )
            )
            rows = await search("anything at all")

        assert loc.called
        assert rows == []


class TestSearchDeadline:
    """Up to eight sources are asked at once, so the slowest one sets the wall clock.

    **"Up to", because the default fan out is the roster minus
    `sources.SLOW_SEARCHES`.** Eight is right today and stays right as a bound
    whatever that set holds, where a bare "eight" becomes false the day it gains
    a member. The two words keep the sentence inside the roster census's grammar
    at the same value, so the verdict pinning it needs no edit.
    """

    @pytest.mark.asyncio
    async def test_a_slow_catalogue_is_dropped_rather_than_waited_for(self):
        """The deadline is the argument, and this passes its own.

        It used to monkeypatch `metadata.SEARCH_DEADLINE_SECONDS` and call this
        with one argument, which pinned the constant rather than the mechanism.
        Now that there are two deadlines the mechanism is the thing worth
        pinning, and which constant a caller hands it belongs at the caller.
        """

        async def quick() -> list[Record]:
            return [Record(title="Fast")]

        # **0.5s and not 5s, and that is the difference between a test and a
        # decoration.** Against a `_within_deadline` that ignored its argument
        # and used the 4.0s constant, a 5s sleeper is still pending at 4.0s and
        # is cancelled, so the assertion below held, the bug passed, and the run
        # cost 4.0s. It was written that way and a critic caught it. Half a
        # second is past this call's own deadline and well inside any constant
        # the module carries, so only a call that honours the argument passes.
        async def slow() -> list[Record]:
            await asyncio.sleep(0.5)
            return [Record(title="Slow")]

        results = await metadata._within_deadline([quick(), slow()], 0.05)

        assert results == [[Record(title="Fast")]]

    @pytest.mark.asyncio
    async def test_everything_that_answers_in_time_is_kept_in_order(self):
        async def first() -> list[Record]:
            return [Record(title="One")]

        async def second() -> list[Record]:
            await asyncio.sleep(0.01)
            return [Record(title="Two")]

        # Order matters downstream: the merge reads source precedence from the
        # order rows arrive in, and `asyncio.wait` returns an unordered set.
        results = await metadata._within_deadline(
            [first(), second()], metadata.SEARCH_DEADLINE_SECONDS
        )

        assert results == [[Record(title="One")], [Record(title="Two")]]


class TestLibraryOfCongressClassifications:
    """The one source that returns two schemes for one book.

    `<classification authority="lcc">QA76.73.P98 V53 2021</classification>`
    beside `authority="ddc"`, measured against the live endpoint on 2026-08-23.
    That pair is why the store carries a scheme column rather than a Dewey
    column.
    """

    MODS = (
        '<mods xmlns="http://www.loc.gov/mods/v3">'
        "<typeOfResource>text</typeOfResource>"
        "<titleInfo><title>Clean Code</title></titleInfo>"
        "<physicalDescription><extent>464 p.</extent></physicalDescription>"
        '<classification authority="lcc">QA76.73.P98 V53 2021</classification>'
        '<classification authority="ddc" edition="23">005.133</classification>'
        '<classification authority="rvk">ST 250</classification>'
        "</mods>"
    )

    def _classifications(self) -> tuple[Heading, ...]:
        parsed = _loc_record(ElementTree.fromstring(self.MODS))
        assert parsed is not None
        return parsed.headings

    def test_both_schemes_are_kept(self):
        assert self._classifications() == (
            Heading(ClassificationScheme.LCC, "QA76.73.P98 V53 2021"),
            Heading(ClassificationScheme.DDC, "005.133"),
        )

    def test_a_dewey_number_goes_through_the_same_normaliser(self):
        """MODS carries the prime too, so the LoC path must not be the one
        source that stores a spelling the others normalise away."""
        mods = self.MODS.replace(
            '<classification authority="ddc" edition="23">005.133</classification>',
            '<classification authority="ddc" edition="23">005.13/3</classification>',
        )
        parsed = _loc_record(ElementTree.fromstring(mods))
        assert parsed is not None
        numbers = [
            entry.number
            for entry in parsed.headings
            if entry.scheme is ClassificationScheme.DDC
        ]

        assert numbers == ["005.133"]

    def test_an_authority_with_no_reading_here_is_dropped(self):
        """RVK is a German shelving scheme this app has no mapping for, and a
        number nothing can read is a string pretending to be a citation."""
        schemes = {entry.scheme for entry in self._classifications()}

        assert ClassificationScheme.DDC in schemes
        assert "rvk" not in schemes


class TestLibraryOfCongressSubjectHeadings:
    """LCSH out of the record the search path already fetches.

    A parser extension rather than a source: `<subject authority="lcsh">` sits
    beside the `<classification>` elements the class above reads, in the same
    MODS document, so it costs no request. Measured over 900 live records on
    2026-08-24: 769 of them carry at least one, 1,559 headings in all.
    """

    MODS = (
        '<mods xmlns="http://www.loc.gov/mods/v3">'
        "<typeOfResource>text</typeOfResource>"
        "<titleInfo><title>Clean Code</title></titleInfo>"
        "<physicalDescription><extent>464 p.</extent></physicalDescription>"
        '<classification authority="lcc">QA76.73.P98 V53 2021</classification>'
        '<classification authority="ddc" edition="23">005.133</classification>'
        '<subject authority="lcsh"><topic>Computer programming</topic></subject>'
        '<subject authority="lcsh"><topic>Computer software</topic>'
        "<topic>Development</topic></subject>"
        '<subject authority="rvm"><topic>Genie logiciel</topic></subject>'
        "</mods>"
    )

    def _classifications(self, mods: str | None = None) -> tuple[Heading, ...]:
        parsed = _loc_record(ElementTree.fromstring(mods or self.MODS))
        assert parsed is not None
        return parsed.headings

    def _lcsh(self, mods: str | None = None) -> list[str]:
        return [
            str(entry.number)
            for entry in self._classifications(mods)
            if entry.scheme is ClassificationScheme.LCSH
        ]

    def test_a_heading_becomes_a_row_under_its_own_scheme(self):
        assert Heading(ClassificationScheme.LCSH, "Computer programming") in self._classifications()

    def test_a_subdivided_heading_is_one_row_and_not_two(self):
        """`Computer software` alone is a different heading with a different
        set of books under it, so the subdivisions belong in the string."""
        assert "Computer software -- Development" in self._lcsh()
        assert "Computer software" not in self._lcsh()

    def test_the_heading_is_the_number_and_no_caption_is_stored(self):
        """The record supplies no identifier, so the string is the access
        point. Writing it into `label` as well would store one fact twice."""
        rows = [
            entry
            for entry in self._classifications()
            if entry.scheme is ClassificationScheme.LCSH
        ]

        assert rows
        assert all(entry.label is None for entry in rows)

    def test_a_vocabulary_this_app_has_no_reading_for_is_dropped(self):
        """The Library of Congress mixes 23 authority values into one record.
        `rvm` is the French one; `fast` and `lcshac` are separate authority
        files whose headings are not LCSH's, so folding them in would make the
        scheme name a lie."""
        crowded = self.MODS.replace(
            "</mods>",
            '<subject authority="fast"><topic>Software engineering</topic></subject>'
            '<subject authority="lcshac"><topic>Computers</topic></subject>'
            "</mods>",
        )

        assert self._lcsh(crowded) == self._lcsh()

    def test_a_subject_with_no_authority_at_all_is_dropped(self):
        """289 of 2,280 live `<subject>` elements name no authority. A heading
        whose vocabulary is unstated cannot be matched against another
        catalogue, which is the only thing this store is for."""
        anonymous = self.MODS.replace(
            "</mods>", "<subject><topic>Uncontrolled</topic></subject></mods>"
        )

        assert self._lcsh(anonymous) == self._lcsh()

    def test_a_work_named_as_a_subject_reads_its_nested_title(self):
        """`<titleInfo>` nests a `<title>` rather than carrying text, which is
        one of the two nested shapes. 21 of 1,559 live headings are it."""
        about_a_work = self.MODS.replace(
            "</mods>",
            '<subject authority="lcsh"><titleInfo>'
            "<title>Microsoft Windows (Computer file)</title>"
            "</titleInfo></subject></mods>",
        )

        assert "Microsoft Windows (Computer file)" in self._lcsh(about_a_work)

    def test_a_person_named_as_a_subject_keeps_their_name(self):
        """`<name>` nests one to four `<namePart>` elements, and reading it as
        empty does not drop the heading, it shortens it: `Catholic Church --
        History` would arrive as `History`, which asserts a different thing
        about the book. 116 of 1,559 live LCSH elements are that shape."""
        about_a_person = self.MODS.replace(
            "</mods>",
            '<subject authority="lcsh"><name type="personal">'
            "<namePart>S\u00fcssheim, Karl,</namePart>"
            '<namePart type="date">1878-1947</namePart></name>'
            "<topic>Sources</topic></subject></mods>",
        )

        assert "S\u00fcssheim, Karl, 1878-1947 -- Sources" in self._lcsh(about_a_person)

    def test_a_subject_element_with_no_text_yields_no_row(self):
        empty = self.MODS.replace(
            "</mods>", '<subject authority="lcsh"><topic>  </topic></subject></mods>'
        )

        assert self._lcsh(empty) == self._lcsh()

    def test_a_subject_heading_is_never_read_as_a_dewey_number(self):
        """`ddc.parse_heading` accepts any three digit token, so a heading that
        opens with one would be stored as a Dewey number and would suggest a
        curated tag from it. The guard is structural: `<classification>` is
        the only element handed to `ddc`, and this path does not import it."""
        numeric = self.MODS.replace(
            "<topic>Computer programming</topic>",
            "<topic>004 Jahre Bauhaus</topic>",
        )
        dewey = [
            entry.number
            for entry in self._classifications(numeric)
            if entry.scheme is ClassificationScheme.DDC
        ]

        assert dewey == ["005.133"]
        assert "004 Jahre Bauhaus" in self._lcsh(numeric)

    def test_the_shelf_classifications_come_before_the_subject_headings(self):
        """Which is load bearing rather than tidy. `Record.match_headings`
        slices this list to eight and `routers/books._headings` applies
        `_SCHEME_ORDER` only afterwards, so on the search path a record's own
        order is the only thing keeping its Dewey number. One live record
        carries 14 LCSH headings against at most two classifications."""
        crowded = self.MODS.replace(
            "</mods>",
            "".join(
                f'<subject authority="lcsh"><topic>Thema {index}</topic></subject>'
                for index in range(14)
            )
            + "</mods>",
        )
        record = Record(source="loc", title="x", headings=self._classifications(crowded))
        schemes = [entry.scheme for entry in record.match_headings()]

        assert schemes[:2] == [ClassificationScheme.LCC, ClassificationScheme.DDC]
        assert ClassificationScheme.LCSH in schemes


# ── Open Library, deepened ────────────────────────────────────────────────────
#
# Open Library is the only source here that clusters printings under a work,
# and the only one whose subjects are a folksonomy rather than a vocabulary.
# Both facts are load bearing and both are pinned below.

OL_ISBN = "https://openlibrary.org/isbn/"
OL_WORKS = "https://openlibrary.org/works/"
OL_AUTHORS = "https://openlibrary.org/authors/"

#: One edition record, in the shape the live endpoint returns.
OL_EDITION = {
    "title": "Introduction to Algorithms",
    "publishers": ["MIT Press"],
    "publish_date": "2009",
    "number_of_pages": 1292,
    "languages": [{"key": "/languages/eng"}],
    "works": [{"key": "/works/OL4781294W"}],
    "authors": [{"key": "/authors/OL23919A"}],
    "dewey_decimal_class": ["005.1"],
    # Four spellings of one call number, which is what a live record carries.
    "lc_classifications": [
        "QA76.6 .I5858 2009",
        "QA76.6.I5858 2009",
        "QA76.6 .C662 2009",
    ],
}

OL_WORK = {
    "title": "Introduction to Algorithms",
    "subjects": ["Computer algorithms", "Algorithms", "open_syllabus_project"],
    "authors": [{"author": {"key": "/authors/OL23919A"}}],
}

class TestWhatEachReaderCanSupply:
    """#134 is bounded by the formats, and the bound is worth pinning.

    Two of the six shapes carry no stamp at all and one carries only half, so a
    subject with a null vocabulary is the ordinary case rather than a gap in a
    parser. Measured 2026-08-31 against the live endpoints: the BnF's 153
    `dc:subject` elements in 200 records carry `xml:lang` and nothing else, the
    NKP's 17 in 5 carry no attribute at all, and MODS names an authority on 399
    of 432 while carrying `valueURI` on **0**.
    """

    def test_mods_supplies_the_vocabulary_and_never_an_identifier(self):
        mods = ElementTree.fromstring(
            '<mods xmlns="http://www.loc.gov/mods/v3">'
            '<subject authority="lcsh"><topic>Computer programming</topic></subject>'
            "</mods>"
        )

        assert _loc_subjects(mods) == (Subject("Computer programming", "lcsh"),)

    def test_an_authority_this_app_has_no_reading_for_is_still_a_subject(self):
        """`_loc_subject_headings` drops everything but `lcsh`, because a
        `classifications` row needs a scheme from a closed set. A subject has no
        such requirement, and dropping `fast` here would throw away a heading
        the record gave us for nothing."""
        mods = ElementTree.fromstring(
            '<mods xmlns="http://www.loc.gov/mods/v3">'
            '<subject authority="fast"><topic>Software engineering</topic></subject>'
            "</mods>"
        )

        assert _loc_subjects(mods) == (Subject("Software engineering", "fast"),)

    def test_a_mods_subject_naming_no_authority_leaves_the_vocabulary_null(self):
        """33 of 432 live elements, and null is the honest answer."""
        mods = ElementTree.fromstring(
            '<mods xmlns="http://www.loc.gov/mods/v3">'
            "<subject><topic>Uncontrolled</topic></subject></mods>"
        )

        assert _loc_subjects(mods) == (Subject("Uncontrolled", None),)

    def test_a_mods_authority_is_lower_cased(self):
        mods = ElementTree.fromstring(
            '<mods xmlns="http://www.loc.gov/mods/v3">'
            '<subject authority="LCSH"><topic>Programming</topic></subject></mods>'
        )

        assert _loc_subjects(mods) == (Subject("Programming", "lcsh"),)

    def test_an_empty_mods_topic_is_not_a_subject(self):
        mods = ElementTree.fromstring(
            '<mods xmlns="http://www.loc.gov/mods/v3">'
            '<subject authority="lcsh"><topic>  </topic></subject></mods>'
        )

        assert _loc_subjects(mods) == ()

    def test_the_subdivisions_stay_separate_words_here(self):
        """`_loc_subject_headings` joins them into the authorised heading,
        because that is what LCSH files a book under. A subject feeds a tag
        guess and a `categories` string, where the parts are the useful shape,
        and that is what this reader did before #134."""
        mods = ElementTree.fromstring(
            '<mods xmlns="http://www.loc.gov/mods/v3">'
            '<subject authority="lcsh"><topic>Computer software</topic>'
            "<topic>Development</topic></subject></mods>"
        )

        assert _loc_subjects(mods) == (
            Subject("Computer software", "lcsh"),
            Subject("Development", "lcsh"),
        )

    def test_dublin_core_supplies_neither_half(self):
        """Both dialects, in one test, because it is the format and not the
        catalogue: the BnF's is namespaced and the NKP's is not."""
        bnf = metadata._bnf_record(
            ElementTree.fromstring(
                '<record xmlns:dc="http://purl.org/dc/elements/1.1/">'
                "<dc:title>Un livre</dc:title>"
                "<dc:type>text</dc:type>"
                "<dc:format>200 p.</dc:format>"
                '<dc:subject xml:lang="fre">Roman francais</dc:subject>'
                "</record>"
            )
        )
        nkp = metadata._nkp_record(
            ElementTree.fromstring(
                "<dc-record><title>Kniha</title><type>text</type>"
                "<format>200 s.</format><subject>Roman</subject></dc-record>"
            ),
            "9788072033034",
        )

        assert bnf is not None
        assert bnf.subjects == (Subject("Roman francais", None, None),)
        assert nkp is not None
        assert nkp.subjects == (Subject("Roman", None, None),)

    def test_k10plus_reads_the_same_two_subfields(self):
        """3 of 133 live `650` fields carry either, and both are read anyway:
        a reader that is correct only while a catalogue's habits hold is the
        thing #134 exists to stop."""
        record = metadata._k10plus_record(
            _marc_fields(_marc_element(
                '<datafield tag="650" ind1=" " ind2="7">'
                "<subfield code=\"a\">Psychology</subfield>"
                '<subfield code="0">(OCoLC)fst01081447</subfield>'
                '<subfield code="2">DLC</subfield></datafield>'
            ))
        )

        assert record.subjects == (
            Subject("Psychology", "dlc", "(OCoLC)fst01081447"),
        )

    def test_a_k10plus_subdivision_shares_the_fields_one_vocabulary(self):
        """`$x` subdivides the `$a` above it rather than being a heading of its
        own, so the joined string takes the field's one `$2`."""
        record = metadata._k10plus_record(
            _marc_fields(_marc_element(
                '<datafield tag="650" ind1=" " ind2="7">'
                "<subfield code=\"a\">Frankreich</subfield>"
                "<subfield code=\"x\">Geschichte</subfield>"
                '<subfield code="2">gnd</subfield></datafield>'
            ))
        )

        assert record.subjects == (Subject("Frankreich Geschichte", "gnd", None),)


OL_AUTHOR = {"name": "Thomas H. Cormen"}


def _ol_edition(**overrides: object) -> dict[str, object]:
    return {**OL_EDITION, **overrides}


def _open_library_routes(mock: respx.Router, **parts: httpx.Response) -> None:
    """Register one route per Open Library path shape.

    One catch-all would answer the edition, the work and the author with the
    same body, which is exactly the confusion these tests exist to rule out.
    """
    mock.get(url__startswith=OL_ISBN).mock(
        return_value=parts.get("edition", httpx.Response(404))
    )
    mock.get(url__startswith=OL_AUTHORS).mock(
        return_value=parts.get("author", httpx.Response(404))
    )
    mock.get(url__startswith=OL_WORKS).mock(
        return_value=parts.get("work", httpx.Response(404))
    )


class TestMergingTwoSearchRows:
    """`_merge_matches` when one row has headings and the other does not."""

    def test_a_populated_list_beats_an_empty_one(self):
        """The regression this was written for, measured live before fixing.

        Every scalar a catalogue omits arrives as None, so "fill where the value
        `is None`" was the whole rule until the classifications became the one
        list valued key a match carried. A source that found nothing wrote `[]`,
        which is not None, so it beat a populated list from the next source.
        Over 30 live title searches, 6 of the 10 merged rows whose Library of
        Congress half carried LCSH lost every heading, and in 6 of 6 the leading
        row's list was empty. `Record.filled_from` now tests the collections and
        the scalars separately, so the two cannot be confused again.
        """
        leading = Record(source="bnf", title="Les Miserables")
        following = Record(
            source="loc",
            title="Les Miserables",
            headings=(Heading(ClassificationScheme.LCSH, "France -- History"),),
        )

        merged = metadata._merge_matches([leading, following])

        assert len(merged) == 1
        assert merged[0].headings == (
            Heading(ClassificationScheme.LCSH, "France -- History"),
        )

    def test_a_zero_is_a_value_and_not_an_absence(self):
        """A scalar is tested with `is None`, pinned.

        Falsiness would reclassify a `series_index` of 0.0 and any empty string
        from present to absent, and the next source would overwrite them.

        This was asserted on a `page_count` of 0 until 2026-09-03, when
        `catalogue._NUMBER_RANGES` began clearing a number outside the range
        the request bodies already carry, which puts 0 and a `year` of 0 out of
        reach of this rule. `series_index` is bounded at 0 inclusive, so it is
        the scalar that still arrives here falsy.
        """
        leading = Record(source="bnf", title="A pamphlet", series_index=0.0)
        following = Record(source="loc", title="A pamphlet", series_index=4.0)

        merged = metadata._merge_matches([leading, following])

        assert merged[0].series_index == 0.0

    def test_a_populated_list_is_not_replaced_by_a_later_one(self):
        """Only absence is filled. Unioning two populated lists is the lookup
        path's rule and deliberately not this one: a search row is bounded at
        `MAX_CLASSIFICATIONS_PER_BOOK` before it becomes a `BookMatch`, so
        unioning two full rows would cost the row rather than the heading.
        """
        leading = Record(
            source="open_library",
            title="Les Miserables",
            headings=(Heading(ClassificationScheme.DDC, "843.7"),),
        )
        following = Record(
            source="loc",
            title="Les Miserables",
            headings=(Heading(ClassificationScheme.LCSH, "France -- History"),),
        )

        merged = metadata._merge_matches([leading, following])

        assert merged[0].headings == (Heading(ClassificationScheme.DDC, "843.7"),)


class TestTheOpenLibraryLookup:
    """What the edition record, the work record and the author call each add."""

    @staticmethod
    async def _lookup(mock: respx.Router) -> metadata.Lookup:
        return await metadata._open_library(ENGLISH_ISBN, "")

    @pytest.mark.asyncio
    async def test_the_work_record_supplies_the_subjects_the_edition_lacks(self):
        """Measured over nine live editions: two carried subjects, seven did not
        while their work did. Reading only the edition is why Open Library used
        to contribute nothing to the tag suggestion."""
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(200, json=_ol_edition()),
                work=httpx.Response(200, json=OL_WORK),
                author=httpx.Response(200, json=OL_AUTHOR),
            )
            result = await self._lookup(mock)

        assert result.found
        assert result.record is not None
        assert result.record.subject_labels == [
            "Computer algorithms",
            "Algorithms",
            "open_syllabus_project",
        ]

    @pytest.mark.asyncio
    async def test_a_subject_list_is_bounded(self):
        """A live work carries up to 137 subjects, and every one of them is
        another chance to pre-select a tag nobody meant."""
        crowded = {"subjects": [f"subject {index}" for index in range(50)]}
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(200, json=_ol_edition()),
                work=httpx.Response(200, json=crowded),
                author=httpx.Response(200, json=OL_AUTHOR),
            )
            result = await self._lookup(mock)

        assert result.record is not None
        assert len(result.record.subjects) == metadata._OPEN_LIBRARY_MAX_SUBJECTS

    @pytest.mark.asyncio
    async def test_the_editions_own_subjects_come_first(self):
        """The printing's cataloguer beats the work's crowd where both spoke."""
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(
                    200, json=_ol_edition(subjects=["Set theory"])
                ),
                work=httpx.Response(200, json=OL_WORK),
                author=httpx.Response(200, json=OL_AUTHOR),
            )
            result = await self._lookup(mock)

        assert result.record is not None
        assert result.record.subject_labels[0] == "Set theory"

    @pytest.mark.asyncio
    async def test_a_subject_is_never_a_classification(self):
        """The decision this round turned on. Open Library subjects are
        uncontrolled strings (`open_syllabus_project`, `fiction classics`), and
        §30i's rule for the store is an assertion from a published scheme."""
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(
                    200,
                    json=_ol_edition(dewey_decimal_class=None, lc_classifications=None),
                ),
                work=httpx.Response(200, json=OL_WORK),
                author=httpx.Response(200, json=OL_AUTHOR),
            )
            result = await self._lookup(mock)

        assert result.record is not None
        assert result.record.subjects
        assert result.record.headings == ()

    @pytest.mark.asyncio
    async def test_a_dewey_number_and_one_call_number_become_classifications(self):
        """The controlled half, and only the first LC value: the repeats are one
        call number written several ways, not several assertions."""
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(200, json=_ol_edition()),
                work=httpx.Response(200, json=OL_WORK),
                author=httpx.Response(200, json=OL_AUTHOR),
            )
            result = await self._lookup(mock)

        assert result.record is not None
        assert result.record.headings == (
            Heading(ClassificationScheme.DDC, "005.1"),
            Heading(ClassificationScheme.LCC, "QA76.6 .I5858 2009"),
        )

    @pytest.mark.asyncio
    async def test_a_dewey_value_that_is_not_a_number_is_dropped(self):
        """Through `ddc.parse_heading` like every other source path."""
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(
                    200,
                    json=_ol_edition(
                        dewey_decimal_class=["[Fic]"], lc_classifications=None
                    ),
                ),
                work=httpx.Response(200, json=OL_WORK),
                author=httpx.Response(200, json=OL_AUTHOR),
            )
            result = await self._lookup(mock)

        assert result.record is not None
        assert result.record.headings == ()

    @pytest.mark.asyncio
    async def test_the_work_supplies_the_author_the_edition_does_not_credit(self):
        """Measured over five live lookups: four credited nobody on the edition
        and every one of the four credited somebody on the work."""
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(200, json=_ol_edition(authors=None)),
                work=httpx.Response(200, json=OL_WORK),
                author=httpx.Response(200, json=OL_AUTHOR),
            )
            result = await self._lookup(mock)

        assert result.record is not None
        assert result.record.author == "Thomas H. Cormen"

    @pytest.mark.asyncio
    async def test_the_page_count_and_the_language_are_read(self):
        """Both were missing entirely until this round, so a fallback lookup
        answered without two of the seven fields `Record.completeness`
        scores."""
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(200, json=_ol_edition()),
                work=httpx.Response(200, json=OL_WORK),
                author=httpx.Response(200, json=OL_AUTHOR),
            )
            result = await self._lookup(mock)

        assert result.record is not None
        assert result.record.page_count == 1292
        assert result.record.language == "en"

    @pytest.mark.asyncio
    async def test_a_key_that_is_not_open_librarys_is_never_fetched(self):
        """A key out of a third party response goes into a URL, and
        `@example.com/` moves the host rather than the path. The request that
        would make is ours, from our network position.

        **The author key here is `/authors/OL1A@example.com/`, deliberately.** A
        bare `@example.com/` is refused by `match`, `search` and `fullmatch`
        alike, so a regression from `fullmatch` to one of the other two would
        reopen the hole with this test still green. Only `fullmatch` refuses a
        key that *starts* with a valid one.
        """
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(
                    200,
                    json=_ol_edition(
                        authors=[{"key": "/authors/OL1A@example.com/"}],
                        works=[{"key": "/works/OL1W/../../evil"}],
                    ),
                ),
            )
            elsewhere = mock.get(url__startswith="https://example.com").mock(
                return_value=httpx.Response(200, json={"name": "Nobody"})
            )
            result = await self._lookup(mock)

        assert result.record is not None
        assert result.record.author is None
        assert not elsewhere.called

    @pytest.mark.asyncio
    async def test_a_work_refusing_with_a_status_costs_the_subjects_only(self):
        """A failure in either extra call costs that field, not the record."""
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(200, json=_ol_edition()),
                work=httpx.Response(500),
                author=httpx.Response(200, json=OL_AUTHOR),
            )
            result = await self._lookup(mock)

        assert result.found
        assert result.record is not None
        assert result.record.title == "Introduction to Algorithms"
        assert result.record.subjects == ()

    @pytest.mark.asyncio
    async def test_a_work_timing_out_costs_the_subjects_only(self):
        """The half a 500 does not reach, and the one that mattered.

        All three requests used to share one `try`, so a timeout on the work
        fetch discarded an edition record that had already answered 200, and
        `_remember` cached that miss for `_MISS_TTL_SECONDS`: one blip made the
        ISBN uncatalogueable for five minutes. A stubbed 500 is the one failure
        the code always handled, so it passed while this did not.
        """
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OL_ISBN).mock(
                return_value=httpx.Response(200, json=_ol_edition())
            )
            mock.get(url__startswith=OL_AUTHORS).mock(
                return_value=httpx.Response(200, json=OL_AUTHOR)
            )
            mock.get(url__startswith=OL_WORKS).mock(
                side_effect=httpx.ReadTimeout("too slow")
            )
            result = await self._lookup(mock)

        assert result.found
        assert result.record is not None
        assert result.record.title == "Introduction to Algorithms"
        assert result.record.subjects == ()

    @pytest.mark.asyncio
    async def test_an_author_timing_out_costs_the_author_only(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OL_ISBN).mock(
                return_value=httpx.Response(200, json=_ol_edition())
            )
            mock.get(url__startswith=OL_WORKS).mock(
                return_value=httpx.Response(200, json=OL_WORK)
            )
            mock.get(url__startswith=OL_AUTHORS).mock(
                side_effect=httpx.ReadTimeout("too slow")
            )
            result = await self._lookup(mock)

        assert result.found
        assert result.record is not None
        assert result.record.author is None
        assert result.record.subjects

    @pytest.mark.asyncio
    async def test_a_body_that_is_valid_json_but_not_an_object_is_not_a_500(self):
        """`[]` and `null` parse cleanly and then raise `AttributeError` on
        `.get`, which is a `ValueError` in no `except` clause on this path. A
        CDN error page served as `application/json` is enough to reach it."""
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(200, json=["not", "a", "record"]),
            )
            result = await self._lookup(mock)

        assert not result.found
        # `UNAVAILABLE`, not `NOT_FOUND`: a fault at the other end is not an
        # absence, and the two send the reader to different actions.
        assert result.outcome is Outcome.UNAVAILABLE

    @pytest.mark.asyncio
    async def test_a_work_body_that_is_not_an_object_costs_the_subjects_only(self):
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(200, json=_ol_edition()),
                work=httpx.Response(200, json=["nope"]),
                author=httpx.Response(200, json=OL_AUTHOR),
            )
            result = await self._lookup(mock)

        assert result.found
        assert result.record is not None
        assert result.record.subjects == ()

    @pytest.mark.asyncio
    async def test_a_page_count_no_book_could_have_is_dropped(self):
        """`BookLookup.page_count` is unbounded and `PUT /{id}/refresh` writes
        it straight onto a column with no CHECK: `10**19` raises
        `OverflowError` on the commit, and 100,001 upward stores silently past
        the app's own ceiling. Open Library is a wiki and this field is
        editable by any account."""
        with respx.mock(assert_all_called=False) as mock:
            _open_library_routes(
                mock,
                edition=httpx.Response(
                    200, json=_ol_edition(number_of_pages=10**19)
                ),
                work=httpx.Response(200, json=OL_WORK),
                author=httpx.Response(200, json=OL_AUTHOR),
            )
            result = await self._lookup(mock)

        assert result.record is not None
        assert result.record.page_count is None


#: An editions listing, in the shape `/works/{key}/editions.json` returns.
OL_EDITIONS = {
    "size": 3,
    "entries": [
        {
            "title": "Introduction to Algorithms",
            "publishers": ["MIT Press"],
            "publish_date": "2009",
            "number_of_pages": 1320,
            "languages": [{"key": "/languages/eng"}],
            "isbn_13": ["9780262270830"],
            "authors": [{"key": "/authors/OL23919A"}],
            "covers": [12345],
            "dewey_decimal_class": ["005.1"],
        },
        {
            "title": "Algorithmen: Eine Einfuehrung",
            "publishers": ["Oldenbourg"],
            "publish_date": "2010",
            "languages": [{"key": "/languages/ger"}],
            "isbn_13": ["9783486590029"],
        },
        {
            "title": "Introduction to Algorithms",
            "publish_date": "1990",
        },
    ],
}


class TestTheEditionCluster:
    """`thingISBN` clustering, without LibraryThing's terms attached."""

    @staticmethod
    def _routes(mock: respx.Router, listing: object = OL_EDITIONS) -> None:
        mock.get(url__startswith=OL_ISBN).mock(
            return_value=httpx.Response(200, json=_ol_edition())
        )
        mock.get(url__regex=r"https://openlibrary\.org/works/[^/]+/editions\.json.*").mock(
            return_value=httpx.Response(200, json=listing)
        )
        mock.get(url__startswith=OL_AUTHORS).mock(
            return_value=httpx.Response(200, json=OL_AUTHOR)
        )

    @pytest.mark.asyncio
    async def test_the_cluster_answers_with_the_other_printings(self):
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            rows = await editions(ENGLISH_ISBN, 5)

        assert [row.isbn for row in rows] == [
            "9780262270830",
            "9783486590029",
            None,
        ]

    @pytest.mark.asyncio
    async def test_the_most_complete_printing_leads(self):
        """`Record.completeness`, the same score `_merge` uses to choose
        between printings: a row with a publisher, a year and a page count is
        one somebody can recognise their copy from."""
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            rows = await editions(ENGLISH_ISBN, 5)

        assert rows[0].page_count == 1320
        assert rows[-1].publisher is None

    @pytest.mark.asyncio
    async def test_a_printing_in_another_language_is_not_a_candidate(self):
        """A work spans translations. An English printing of a German book is
        the same work and cannot fill in that copy's publisher or page count."""
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            rows = await editions(ENGLISH_ISBN, 5, prefer_language="de")

        assert [row.isbn for row in rows] == ["9783486590029", None]

    @pytest.mark.asyncio
    async def test_a_printing_declaring_the_wanted_language_leads(self):
        """The blocking defect of this round, and a filter alone did not fix it.

        22% to 33% of live entries declare no language, so a cluster whose
        foreign printings are unlabelled passed the filter whole and filled
        every row: King's *Es* (`9783453435773`) showed Turkish, Spanish,
        English and French, while the one printing declaring `ger` ranked fifth
        and was never shown. The language match is the first term of the sort,
        ahead of completeness, which is what puts it back on the page.
        """
        listing = {
            "size": 2,
            "entries": [
                # More complete, and unlabelled: it wins on completeness alone.
                {
                    "title": "Es, Turkish printing",
                    "publishers": ["Altin Kitaplar"],
                    "publish_date": "2019",
                    "number_of_pages": 900,
                    "isbn_13": ["9789751027788"],
                },
                {
                    "title": "Es",
                    "publish_date": "1988",
                    "languages": [{"key": "/languages/ger"}],
                },
            ],
        }
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock, listing)
            rows = await editions(ENGLISH_ISBN, 5, prefer_language="de")

        assert [row.title for row in rows] == ["Es", "Es, Turkish printing"]

    @pytest.mark.asyncio
    async def test_a_printing_declaring_no_language_survives_the_filter(self):
        """110 of 129 live entries declare one, and both German printings in
        the Der Zinker cluster are among the 19 that do not."""
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            rows = await editions(ENGLISH_ISBN, 5, prefer_language="fr")

        assert [row.title for row in rows] == ["Introduction to Algorithms"]
        assert rows[0].language is None

    @pytest.mark.asyncio
    async def test_one_author_request_serves_every_row(self):
        """A cluster names its authors by key and the keys repeat, so resolving
        each row's own would be one request per row."""
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            author = mock.get(url__startswith=OL_AUTHORS).mock(
                return_value=httpx.Response(200, json=OL_AUTHOR)
            )
            rows = await editions(ENGLISH_ISBN, 5)

        assert author.call_count == 1
        assert rows[0].author == "Thomas H. Cormen"

    @pytest.mark.asyncio
    async def test_a_classification_on_a_sibling_printing_is_carried(self):
        """24 of 129 live entries carry a Dewey number, and a picked one is
        applied to the book by `POST /{id}/enrich/apply`."""
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            rows = await editions(ENGLISH_ISBN, 5)

        assert rows[0].headings == (
            Heading(ClassificationScheme.DDC, "005.1"),
        )

    @pytest.mark.asyncio
    async def test_an_isbn_that_is_not_one_asks_nothing(self):
        with respx.mock(assert_all_called=False) as mock:
            edition = mock.get(url__startswith=OL_ISBN).mock(
                return_value=httpx.Response(200, json=_ol_edition())
            )
            rows = await editions("not-an-isbn", 5)

        assert rows == []
        assert not edition.called

    @pytest.mark.asyncio
    async def test_a_listing_that_is_not_an_object_costs_no_rows(self):
        """From `editions` an `AttributeError` escapes `_work_cluster`, which
        catches `TimeoutError` only, and then `candidates`' bare `gather`, so it
        answers 500 for the whole page rather than losing the cluster."""
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock, ["not", "a", "listing"])
            rows = await editions(ENGLISH_ISBN, 5)

        assert rows == []

    @pytest.mark.asyncio
    async def test_an_edition_body_that_is_not_an_object_costs_no_rows(self):
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            mock.get(url__startswith=OL_ISBN).mock(
                return_value=httpx.Response(200, json="just a string")
            )
            rows = await editions(ENGLISH_ISBN, 5)

        assert rows == []

    @pytest.mark.asyncio
    async def test_a_book_open_library_does_not_hold_costs_no_rows(self):
        """Open Library returns 404 for a good deal of German publishing,
        including round 2's own reference record."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OL_ISBN).mock(return_value=httpx.Response(404))
            rows = await editions(GERMAN_ISBN, 5)

        assert rows == []


class TestTheCandidates:
    """The cluster and the search, and the rule between them."""

    @staticmethod
    def _routes(mock: respx.Router) -> None:
        TestTheEditionCluster._routes(mock)
        mock.get(url__startswith=K10PLUS).mock(return_value=_xml(K10PLUS_EMPTY))
        mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
        mock.get(url__startswith="https://openlibrary.org/search.json").mock(
            return_value=httpx.Response(200, json={"docs": []})
        )
        mock.get(url__startswith="https://catalogue.bnf.fr").mock(
            return_value=httpx.Response(500)
        )
        mock.get(url__startswith="http://lx2.loc.gov").mock(
            return_value=httpx.Response(500)
        )
        silence_oenb(mock)
        silence_nlg(mock)

    @pytest.mark.asyncio
    async def test_the_cluster_leads(self):
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            rows = await candidates(
                "Introduction to Algorithms", isbn=ENGLISH_ISBN, limit=5
            )

        assert rows[0].isbn == "9780262270830"

    @pytest.mark.asyncio
    async def test_the_cluster_never_takes_the_whole_page(self):
        """A work merged wrongly must not be the entire answer: the search row
        underneath it is the way out."""
        crowded = {
            "size": 9,
            "entries": [
                {"title": f"Printing {index}", "publish_date": str(2000 + index)}
                for index in range(9)
            ],
        }
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            mock.get(
                url__regex=r"https://openlibrary\.org/works/[^/]+/editions\.json.*"
            ).mock(return_value=httpx.Response(200, json=crowded))
            rows = await candidates(
                "Introduction to Algorithms", isbn=ENGLISH_ISBN, limit=5
            )

        assert len(rows) == 4

    @pytest.mark.asyncio
    async def test_a_search_row_sharing_a_title_and_an_author_is_still_a_row(self):
        """The bug a live run found. `_match_key` is title plus author, and
        every row on this page shares both by construction, so deduplicating on
        it collapsed a five row answer to one. Two printings of one book are
        exactly what this endpoint exists to show."""
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            mock.get(url__startswith="https://openlibrary.org/search.json").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "docs": [
                            {
                                "title": "Introduction to Algorithms",
                                "author_name": ["Thomas H. Cormen"],
                                "isbn": ["9780262046305"],
                            }
                        ]
                    },
                )
            )
            rows = await candidates(
                "Introduction to Algorithms", isbn=ENGLISH_ISBN, limit=5
            )

        assert rows[0].title == rows[-1].title
        assert "9780262046305" in [row.isbn for row in rows]

    @pytest.mark.asyncio
    async def test_a_search_row_repeating_a_cluster_isbn_is_dropped(self):
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            mock.get(url__startswith="https://openlibrary.org/search.json").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "docs": [
                            {
                                "title": "Introduction to Algorithms",
                                "author_name": ["Thomas H. Cormen"],
                                "isbn": ["9780262270830"],
                            }
                        ]
                    },
                )
            )
            rows = await candidates(
                "Introduction to Algorithms", isbn=ENGLISH_ISBN, limit=5
            )

        assert [row.isbn for row in rows].count("9780262270830") == 1

    @pytest.mark.asyncio
    async def test_a_book_with_no_isbn_still_gets_the_search(self):
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            mock.get(url__startswith="https://openlibrary.org/search.json").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "docs": [
                            {"title": "Introduction to Algorithms", "isbn": ["9780262046305"]}
                        ]
                    },
                )
            )
            rows = await candidates(
                "Introduction to Algorithms", isbn=None, limit=5
            )

        assert [row.isbn for row in rows] == ["9780262046305"]

    @pytest.mark.asyncio
    async def test_a_slow_cluster_costs_its_rows_and_not_the_response(
        self, monkeypatch
    ):
        """One live editions listing answered in 10.1s against a 0.64s to 2.19s
        norm, which is what the deadline is for."""
        with respx.mock(assert_all_called=False) as mock:
            self._routes(mock)
            mock.get(url__startswith="https://openlibrary.org/search.json").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "docs": [
                            {"title": "Introduction to Algorithms", "isbn": ["9780262046305"]}
                        ]
                    },
                )
            )

            async def _forever(
                isbn: str,
                limit: int,
                prefer_language: str | None = None,
                *,
                plan: sources.Plan,
            ) -> list[dict[str, object]]:
                await asyncio.sleep(30)
                return []

            monkeypatch.setattr(metadata, "editions", _forever)
            monkeypatch.setattr(metadata, "SEARCH_DEADLINE_SECONDS", 0.05)
            rows = await candidates(
                "Introduction to Algorithms", isbn=ENGLISH_ISBN, limit=5
            )

        assert [row.isbn for row in rows] == ["9780262046305"]
class TestTheAustrianNationalLibrary:
    """The third MARCXML source and the fifth SRU one, and what it is here for.

    The two counts differ because the schemas do: the DNB answers `MARC21-xml`,
    K10plus and the ÖNB answer `marcxml`, the BnF answers `dublincore` and the
    Library of Congress answers `mods`.

    **It is asked only after the fast pair miss.** The ticket's whole premise is
    that it holds Austrian imprints the German catalogues do not, which is worth
    a fallback request and not worth widening the pair everybody pays for.
    Measured 2026-08-27 over 50 ISBNs from ten Austrian presses: ÖNB held 50,
    the DNB 47, K10plus 39, and 3 were held by ÖNB and by neither of the pair.

    **A wrong index name is not caught by the endpoint**, so it has to be caught
    here. See `OENB_WRONG_BOOK`.

    **Its records are the DNB's profile**, so they go through the same parser,
    which is what `_dnb_record`'s `source` argument exists for.

    **Over half of what a title search returns is journal articles**, which
    nothing already in this module refuses. See `OENB_ARTICLE`.
    """

    @pytest.mark.asyncio
    async def test_the_fast_pair_answering_means_the_oenb_is_never_asked(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_RECORD))
            mock.get(url__startswith=K10PLUS).mock(return_value=_xml(K10PLUS_EMPTY))
            oenb = mock.get(url__startswith=OENB).mock(
                return_value=_xml(OENB_RECORD)
            )
            result = await lookup(GERMAN_ISBN)

        assert result.source == "dnb"
        assert not oenb.called

    @pytest.mark.asyncio
    async def test_an_austrian_imprint_neither_german_catalogue_holds_resolves(self):
        """The 3 of 50 the whole item turns on, as a test rather than a claim."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_open_library(mock)
            silence_nlg(mock)
            silence_nkp(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            mock.get(url__startswith=K10PLUS).mock(return_value=_xml(K10PLUS_EMPTY))
            mock.get(url__startswith=OENB).mock(
                return_value=_xml(OENB_AUSTRIAN_ONLY)
            )
            result = await lookup("9783700316206")

        assert result.outcome is Outcome.FOUND
        assert result.source == "oenb"
        assert result.record is not None
        assert result.record.title == "?Kunst!"
        assert result.record.publisher == "Braumüller"
        assert result.record.year == 2007

    @pytest.mark.asyncio
    async def test_open_library_is_asked_before_the_oenb(self):
        """Order inside the fallback list, and #115 reversed it on a measurement.

        **It used to be the other way and the reason was latency**, which was
        the wrong question: the tail is asked one at a time and stops at the
        first hit, so what it costs is a round trip to whoever does not answer,
        and what orders it is how often each one does. Of the 279 ISBNs in 500
        that the leading pair missed, Open Library answers 83 and the OENB
        answers 1, re-measured 2026-08-31 with the NLG in the roster and the
        `020` rule fixed. The frames are named in `sources.MEASURED`, the
        marginal counts in `sources.TAIL_MARGINAL`, and the rule is asserted in
        `tests/test_sources.py::TestTheOrderFollowsTheMeasurement`.

        The old reason is not wrong about the seconds, and the seconds are not
        what is being bought: the OENB is faster, and asking it first buys a
        fast answer once in 279 and a wasted round trip 278 times.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            mock.get(url__startswith=K10PLUS).mock(return_value=_xml(K10PLUS_EMPTY))
            oenb = mock.get(url__startswith=OENB).mock(
                return_value=_xml(OENB_AUSTRIAN_ONLY)
            )
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(200, json=OPEN_LIBRARY_RECORD)
            )
            result = await lookup("9783700316206")

        # Both halves are needed: the source alone would pass on a chain that
        # asked the OENB first and preferred Open Library's answer anyway.
        assert result.source == "open_library"
        assert not oenb.called

    @pytest.mark.asyncio
    async def test_a_record_for_a_different_book_is_refused(self):
        """A mistyped CQL index answers with the catalogue, not with nothing.

        `alma.isbn13=` and `zzz.qqq=` both returned all 7,793,152 records under
        HTTP 200 with no diagnostic, measured live. Without the 020 check this
        source would answer a member's scan with whichever record sorted first.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_nlg(mock)
            silence_nkp(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            mock.get(url__startswith=K10PLUS).mock(return_value=_xml(K10PLUS_EMPTY))
            mock.get(url__startswith=OENB).mock(
                return_value=_xml(OENB_WRONG_BOOK)
            )
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            result = await lookup("9783700316206")

        assert result.outcome is not Outcome.FOUND
        assert ("oenb", Outcome.NOT_FOUND) in result.attempts

    @pytest.mark.asyncio
    async def test_the_record_carries_its_classifications(self):
        """User story 3: confirming an ÖNB record enriches a Book like a DNB one."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_open_library(mock)
            silence_nlg(mock)
            silence_nkp(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            mock.get(url__startswith=K10PLUS).mock(return_value=_xml(K10PLUS_EMPTY))
            mock.get(url__startswith=OENB).mock(return_value=_xml(OENB_RECORD))
            result = await lookup("9783552058217")

        assert result.record is not None
        headings = result.record.headings
        assert Heading(ClassificationScheme.DDC, "853.92") in headings
        assert (
            Heading(
                ClassificationScheme.GND, "1071854844", "Fiktionale Darstellung"
            )
            in headings
        )

    @pytest.mark.asyncio
    async def test_a_heading_naming_another_vocabulary_is_not_a_classification(self):
        """`655 $a Roman $2 bellobv` has no `(DE-588)`, so it is a subject only.

        Same rule `_dnb_subjects` applies to the DNB: a value with no GND number
        cannot become a classification row, and reaches `subjects`, which is the
        field documented as weak evidence.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_open_library(mock)
            silence_nlg(mock)
            silence_nkp(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            mock.get(url__startswith=K10PLUS).mock(return_value=_xml(K10PLUS_EMPTY))
            mock.get(url__startswith=OENB).mock(return_value=_xml(OENB_RECORD))
            result = await lookup("9783552058217")

        assert result.record is not None
        assert "Roman" in result.record.subject_labels
        assert not [
            heading for heading in result.record.headings if heading.number == "Roman"
        ]

    @pytest.mark.asyncio
    async def test_no_author_identifier_is_taken_from_this_catalogue_yet(self):
        """A withheld decision, pinned so that taking it is deliberate.

        The fixture's `100` carries `(DE-588)138150680`, and the ÖNB carries one
        on 158 of 209 live `100 $a` fields, 75.6%, every one of them
        `(DE-588)`. So this is not absent for want of data. It is the rule
        `_k10plus_record` states: a catalogue is not read for a person's
        identifier until somebody has compared it live, and reusing the DNB's
        parser would otherwise have admitted a second source to that path as a
        side effect of a mapping.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_open_library(mock)
            silence_nlg(mock)
            silence_nkp(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            mock.get(url__startswith=K10PLUS).mock(return_value=_xml(K10PLUS_EMPTY))
            mock.get(url__startswith=OENB).mock(return_value=_xml(OENB_RECORD))
            result = await lookup("9783552058217")

        assert result.record is not None
        assert result.record.author_identifiers == ()

    @pytest.mark.asyncio
    async def test_the_translator_is_not_credited_as_an_author(self):
        """`700 $4 trl`. The live record is a novel translated from Italian."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_open_library(mock)
            silence_nlg(mock)
            silence_nkp(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            mock.get(url__startswith=K10PLUS).mock(return_value=_xml(K10PLUS_EMPTY))
            mock.get(url__startswith=OENB).mock(return_value=_xml(OENB_RECORD))
            result = await lookup("9783552058217")

        assert result.record is not None
        assert result.record.author == "Maurizio Torchio"

    @pytest.mark.asyncio
    async def test_the_lookup_asks_the_index_the_probe_established(self):
        """The one fact the whole item was blocked on, pinned.

        `alma.isbn` was confirmed by reading an ISBN off a live ÖNB record and
        putting it back through this index. The alternatives do not fail
        visibly: `alma.isbn13` and `zzz.qqq` both answer 200 with all 7,793,152
        records and no diagnostic, so a wrong value here is caught by
        `_marc_claims_isbn` turning every lookup into a miss rather than by
        anything raising. This says which index, so that the day it changes it
        changes here and not by accident.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_open_library(mock)
            silence_nlg(mock)
            silence_nkp(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            mock.get(url__startswith=K10PLUS).mock(return_value=_xml(K10PLUS_EMPTY))
            route = mock.get(url__startswith=OENB).mock(
                return_value=_xml(OENB_AUSTRIAN_ONLY)
            )
            await lookup("9783700316206")

        params = route.calls.last.request.url.params
        assert params["query"] == "alma.isbn=9783700316206"
        assert params["recordSchema"] == "marcxml"
        assert params["maximumRecords"] == "5"

    @pytest.mark.asyncio
    async def test_a_throttled_oenb_is_not_reported_as_a_missing_book(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_nlg(mock)
            silence_nkp(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            mock.get(url__startswith=K10PLUS).mock(return_value=_xml(K10PLUS_EMPTY))
            mock.get(url__startswith=OENB).mock(return_value=httpx.Response(429))
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            result = await lookup("9783700316206")

        assert ("oenb", Outcome.RATE_LIMITED) in result.attempts
        assert result.outcome is Outcome.RATE_LIMITED

    @pytest.mark.asyncio
    async def test_a_diagnostic_costs_the_source_its_rows_and_nothing_else(self):
        """Every error this endpoint reports arrives as HTTP 200.

        An invalid query answers with a well formed envelope carrying a
        `diag:diagnostic` and no records. The right handling is none: the body
        parses, no record is found, the source reports nothing, and a search
        still answers from the other six.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_nlg(mock)
            silence_nkp(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            mock.get(url__startswith=K10PLUS).mock(return_value=_xml(K10PLUS_EMPTY))
            mock.get(url__startswith=OENB).mock(
                return_value=_xml(OENB_DIAGNOSTIC)
            )
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            result = await lookup("9783700316206")

        assert ("oenb", Outcome.NOT_FOUND) in result.attempts

    @pytest.mark.asyncio
    async def test_an_enormous_oenb_answer_costs_the_oenb_and_nothing_else(self):
        """The response cap, at this source's own call site.

        `tests/test_fetch.py` proves the cap works. This proves going over lands
        in the handler a timeout already lands in rather than escaping as a 500,
        which is the same thing `TestTheResponseSizeCap` asks of the other four
        XML SRU callers.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_nlg(mock)
            silence_nkp(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            mock.get(url__startswith=K10PLUS).mock(return_value=_xml(K10PLUS_EMPTY))
            mock.get(url__startswith=OENB).mock(
                return_value=_xml("<x>" + "y" * 4096 + "</x>")
            )
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(404)
            )
            mock.get(url__startswith=GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(fetch, "MAX_RESPONSE_BYTES", 1024)
                result = await lookup("9783700316206")

        assert ("oenb", Outcome.UNAVAILABLE) in result.attempts


class TestTheAustrianNationalLibrarySearch:
    """Title search, and the noise that made it more than a fifth `_search`."""

    @staticmethod
    def _quiet(mock):
        """Every source but the ÖNB answering nothing."""
        silence_covers(mock)
        silence_nlg(mock)
        mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
        mock.get(url__startswith=K10PLUS).mock(return_value=_xml(K10PLUS_EMPTY))
        mock.get(url__startswith=OPEN_LIBRARY).mock(
            return_value=httpx.Response(200, json={"docs": []})
        )
        mock.get(url__startswith="https://catalogue.bnf.fr").mock(
            return_value=httpx.Response(500)
        )
        mock.get(url__startswith="http://lx2.loc.gov").mock(
            return_value=httpx.Response(500)
        )

    @pytest.mark.asyncio
    async def test_a_journal_article_is_not_offered_as_a_book(self):
        """55.4% of 280 live records over 8 title searches are this shape.

        The article in the fixture has a title, an author and a year and no
        extent at all, so every test already in this file would pass with it
        accepted. Only the leader says it is part of something else.
        """
        with respx.mock(assert_all_called=False) as mock:
            self._quiet(mock)
            mock.get(url__startswith=OENB).mock(return_value=_xml(OENB_SEARCH))
            rows = await search("angehaltene leben")

        assert [row.title for row in rows] == ["Das angehaltene Leben"]

    @pytest.mark.asyncio
    async def test_the_non_sorting_brackets_do_not_reach_the_title(self):
        """ÖNB writes MARC's non-sorting device as `<<` and `>>`.

        Untreated this row reads `<<Das>> angehaltene Leben`, and it would reach
        the picker and then the shelf that way: 21 of 150 live 245 `$a` values
        carry a bracketed run.
        """
        with respx.mock(assert_all_called=False) as mock:
            self._quiet(mock)
            mock.get(url__startswith=OENB).mock(return_value=_xml(OENB_SEARCH))
            rows = await search("angehaltene leben")

        assert rows[0].title == "Das angehaltene Leben"
        assert "<<" not in rows[0].title

    @pytest.mark.asyncio
    async def test_the_query_is_one_anded_term_per_word(self):
        """A bare multi-word term is refused by the endpoint, not merely loose.

        `alma.title=wien geschichte` answers 200 with diagnostic 200812
        `Invalid query`, measured live. So this is a correctness requirement
        where the same shape in the K10plus title search is a precision preference.
        """
        with respx.mock(assert_all_called=False) as mock:
            self._quiet(mock)
            route = mock.get(url__startswith=OENB).mock(
                return_value=_xml(OENB_EMPTY)
            )
            await search("angehaltene leben")

        query = route.calls.last.request.url.params["query"]
        assert query == "alma.title=angehaltene and alma.title=leben"

    @pytest.mark.asyncio
    async def test_a_row_names_the_catalogue_that_found_it(self):
        """The record's own `source`, which is not the same field as `Lookup.source`.

        **Found by mutating `_dnb_record` and watching nothing fail.** Every
        other test here reads `Lookup.source`, and `lookup` sets that from the
        name of the chain entry it asked rather than from the record, so
        hardcoding this parser back to `"dnb"` passed the whole file. The search
        path is where it shows: `Record.source` becomes `BookMatch.source`,
        which the picker prints, and it is what `_MATCH_PRECEDENCE` ranks on, so
        a mislabelled ÖNB row would be believed over K10plus for a shared field.
        """
        with respx.mock(assert_all_called=False) as mock:
            self._quiet(mock)
            mock.get(url__startswith=OENB).mock(return_value=_xml(OENB_SEARCH))
            rows = await search("angehaltene leben")

        assert rows[0].sources == {"oenb"}

    @pytest.mark.asyncio
    async def test_an_online_resource_is_not_offered_as_a_book(self):
        """`_is_physical_book` is a second refusal, not a spare one.

        This record's leader says monograph, so `_is_component_part` passes it,
        and it carries no control field at all, so `_marc_carrier_is_book` passes
        it too. Only the extent refuses it.

        That makes it the row proving the **prose half is not dead code at a MARC
        source** now that the carrier codes stand in front of it. It was written
        to show `_is_physical_book` doing separate work from `_is_component_part`
        and it is a third refusal in that path rather than a second, so the job it
        is named for is the one it still does and the ordinal was the stale part.
        """
        with respx.mock(assert_all_called=False) as mock:
            self._quiet(mock)
            mock.get(url__startswith=OENB).mock(
                return_value=_xml(OENB_SEARCH_WITH_ONLINE)
            )
            rows = await search("nur online")

        assert [row.title for row in rows] == ["Das angehaltene Leben"]

    @pytest.mark.asyncio
    async def test_a_search_row_carries_no_author_identifier_either(self):
        """The other half of the withheld decision, and it was unpinned.

        The lookup path is asserted elsewhere in this file. The **search** path
        was not, and a review found that deleting `read_author_identifiers=False`
        from the ÖNB title search failed nothing: a search row reaches the HTTP layer
        through `Record.as_match()`, which carries no identifiers at all, so
        there is nothing to observe from outside.

        There is something to observe *here*, because `metadata.search` returns
        `Record` objects rather than the wire dictionaries. So the assertion is
        made at the seam that still has the fact.
        """
        with respx.mock(assert_all_called=False) as mock:
            self._quiet(mock)
            mock.get(url__startswith=OENB).mock(return_value=_xml(OENB_SEARCH))
            rows = await search("angehaltene leben")

        assert rows[0].author_identifiers == ()

    @pytest.mark.asyncio
    async def test_a_broken_oenb_costs_its_own_rows_and_no_others(self):
        """User story 5, from the search side."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_nlg(mock)
            silence_nkp(mock)
            mock.get(url__startswith=OENB).mock(return_value=httpx.Response(500))
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_RECORD)
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(200, json={"docs": []})
            )
            mock.get(url__startswith="https://catalogue.bnf.fr").mock(
                return_value=httpx.Response(500)
            )
            mock.get(url__startswith="http://lx2.loc.gov").mock(
                return_value=httpx.Response(500)
            )
            rows = await search("great gatsby")

        assert [row.title for row in rows] == ["The Great Gatsby"]

    #: The deadline this test patches in, and the sleep it puts behind one source.
    #:
    #: **Both are scaled down from 4.0 and 5, and the ratio is what matters rather than
    #: the values.** The sleep must outlast the deadline by enough that a broken deadline
    #: misses the bound by a wide margin, and the deadline must be long enough that the
    #: five other mocked sources finish inside it.
    #:
    #: **The old numbers made this test nearly unable to fail.** It slept 5 against the
    #: real 4.0 deadline and asserted `elapsed < 5`. A working deadline returns at about
    #: 4.0, so there was a second of headroom and no false failure to worry about; the
    #: defect was the other way round. **A completely broken deadline returns at about
    #: 5.0, against a bound of 5**, so the test failed only by however much
    #: `asyncio.sleep(5)` overshoots 5.000, which is scheduler noise. Its whole ability
    #: to detect the regression it was written for rested on that overshoot being
    #: positive. That is the recorded shape of a bound that stops guarding without ever
    #: failing, met from the other side.
    #:
    #: It also spent four seconds of real wall clock on every suite run.
    _DEADLINE = 0.5
    _SLOWER_THAN_THE_DEADLINE = 2.0

    #: What the five mocked sources, the merge and the ranking are allowed on top of the
    #: deadline.
    #:
    #: **Chosen so the two failure directions have the same slack**, which is what the old
    #: bound did not have. A working deadline returns at about `_DEADLINE` and has this
    #: much room before the bound; a broken one returns at about
    #: `_SLOWER_THAN_THE_DEADLINE` and misses the bound by 1.05s, measured. Every source
    #: here is a mock that answers instantly, so this is slack against a loaded worker
    #: rather than against any real work.
    _MARGIN = 0.5

    @pytest.mark.asyncio
    async def test_a_slow_oenb_does_not_extend_the_shared_deadline(self, monkeypatch):
        """User story 5. The deadline degrades the results, never the latency.

        **Bounded against the deadline, not against the sleep.** A broken deadline now
        misses by 1.05s rather than by microseconds, and the number in the assertion says
        what is being tested. `_MARGIN` is the slack for five mocked sources and the
        merge, and it is far below the 1.5s a regression would cost.

        **Proved to discriminate rather than asserted to**: with the deadline raised
        above the sleep, this test is the one that fails, and it fails on the elapsed
        bound rather than on the row assertion.
        """
        monkeypatch.setattr(metadata, "SEARCH_DEADLINE_SECONDS", self._DEADLINE)

        async def _crawl(request):
            await asyncio.sleep(self._SLOWER_THAN_THE_DEADLINE)
            return _xml(OENB_SEARCH)

        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_nlg(mock)
            silence_nkp(mock)
            mock.get(url__startswith=OENB).mock(side_effect=_crawl)
            mock.get(url__startswith=K10PLUS).mock(
                return_value=_xml(K10PLUS_RECORD)
            )
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                return_value=httpx.Response(200, json={"docs": []})
            )
            mock.get(url__startswith="https://catalogue.bnf.fr").mock(
                return_value=httpx.Response(500)
            )
            mock.get(url__startswith="http://lx2.loc.gov").mock(
                return_value=httpx.Response(500)
            )
            started = asyncio.get_running_loop().time()
            rows = await search("great gatsby")
            elapsed = asyncio.get_running_loop().time() - started

        assert elapsed < self._DEADLINE + self._MARGIN, (
            f"the search took {elapsed:.3f}s against a deadline of {self._DEADLINE}s; "
            f"a source sleeping {self._SLOWER_THAN_THE_DEADLINE}s was waited for"
        )
        assert [row.title for row in rows] == ["The Great Gatsby"]


class TestTheNationalLibraryOfGreece:
    """The fourth MARCXML source, and the first outside German language Europe.

    **It is here because the chain held nothing for Greek publishing**, which is
    the same argument that put the ÖNB in it: a legal deposit library holds the
    domestic edition under the domestic ISBN, and that is exactly the book the
    other seven miss.

    Three things made it cheap, all measured 2026-08-30 and all recorded beside
    the constants they decided: it speaks SRU, its records are MARC21, and its
    p90 lookup is a fifth of a second.

    **One thing made it not cheap**, and it is the reason this class exists
    rather than a line in the ÖNB's: `_marc_claims_isbn` refused the records
    that prove it works. See `_isbn_entries`.

    **A wrong index name is diagnosed here**, unlike at the ÖNB, and the identity
    check is kept regardless: this is a plaintext connection, so the record that
    arrives is not necessarily the record the catalogue sent.
    """

    ISBN = "9789602118962"

    @pytest.mark.asyncio
    async def test_a_greek_book_whose_only_isbn_is_qualified_resolves(self):
        """The finding the ticket was written around, as a test.

        Measured 2026-08-30 over 500 distinct NLG records drawn from ten title
        searches: 317 carry an 020 and 63 of those name their ISBN only in a
        qualified entry. **A different sample from the 400 records
        `metadata._marc_nodes` cites for the NLG**, which is eight searches and answers a
        different question, the bibliographic level. Refusing those refuses a
        fifth of the catalogue.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            silence_open_library(mock)
            silence_oenb(mock)
            silence_nkp(mock)
            mock.get(url__startswith=DNB).mock(return_value=_xml(DNB_EMPTY))
            mock.get(url__startswith=K10PLUS).mock(return_value=_xml(K10PLUS_EMPTY))
            mock.get(url__startswith=NLG).mock(return_value=_xml(NLG_RECORD))
            result = await lookup(self.ISBN)

        assert result.outcome is Outcome.FOUND
        assert result.source == "nlg"
        assert result.record is not None
        assert result.record.title == "Ιστορία της Ευρώπης"
        assert result.record.author == "Norman Davies"
        assert result.record.publisher == "Νεφέλη"
        assert result.record.year == 2009
        assert result.record.language == "el"

    @pytest.mark.asyncio
    async def test_the_dewey_number_is_read_and_the_greek_authority_is_not(self):
        """`082` is Dewey wherever it appears, and `$0` is a GND number only
        where it says so. The NLG writes `urn:nbn:gr:nlg:` in `$0`, and reading
        that as an identifier would file a Greek authority record's number under
        the German one's scheme."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=NLG).mock(return_value=_xml(NLG_RECORD))
            result = await metadata._lookup_one(targets.SEEDED[CatalogueSource.NLG], self.ISBN, "")

        assert result.record is not None
        assert [
            (heading.scheme, heading.number) for heading in result.record.headings
        ] == [(ClassificationScheme.DDC, "940")]
        assert "Ευρώπη" in result.record.subject_labels

    @pytest.mark.asyncio
    async def test_a_record_that_names_another_isbn_is_refused(self):
        """The identity check, which here guards a plaintext connection rather
        than an index name: anyone on the path can answer for this catalogue,
        and what stops that becoming a member's book is that the record has to
        name the ISBN that was scanned."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=NLG).mock(return_value=_xml(NLG_WRONG_BOOK))
            result = await metadata._lookup_one(targets.SEEDED[CatalogueSource.NLG], self.ISBN, "")

        assert result.outcome is Outcome.NOT_FOUND

    @pytest.mark.asyncio
    async def test_the_isbn_index_is_the_one_that_was_probed(self):
        """`dc.isbn`, established by probing and confirmed by round trip. The
        alternatives answer an SRU diagnostic rather than the catalogue, which
        is stated beside the constant; this pins what is actually sent."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            route = mock.get(url__startswith=NLG).mock(return_value=_xml(NLG_EMPTY))
            await metadata._lookup_one(targets.SEEDED[CatalogueSource.NLG], self.ISBN, "")

        assert route.calls[0].request.url.params["query"] == f"dc.isbn={self.ISBN}"

    @pytest.mark.asyncio
    async def test_an_empty_answer_is_not_found_rather_than_unavailable(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=NLG).mock(return_value=_xml(NLG_EMPTY))
            result = await metadata._lookup_one(targets.SEEDED[CatalogueSource.NLG], self.ISBN, "")

        assert result.outcome is Outcome.NOT_FOUND

    @pytest.mark.asyncio
    async def test_a_component_part_is_not_a_book(self):
        """Measured zero times of 400 live records, and kept: an article is
        never a book, and the leader is one read."""
        article = NLG_RECORD.replace(
            "01665nam a2200385 a 4500", "01665naa a2200385 a 4500"
        )
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=NLG).mock(return_value=_xml(article))
            result = await metadata._lookup_one(targets.SEEDED[CatalogueSource.NLG], self.ISBN, "")

        assert result.outcome is Outcome.NOT_FOUND


class TestTheNationalLibraryOfGreeceSearch:
    """The title path, which is the same shape as the two SRU sources above."""

    @pytest.mark.asyncio
    async def test_terms_are_anded_over_the_title_index(self):
        """One term per index reference. Measured 2026-08-30 against the live
        endpoint, `dc.title=zorba` answers 15 and `dc.title=zorba and
        dc.title=xyzzyqq` answers 0, so the second term is applied."""
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__startswith=NLG).mock(return_value=_xml(NLG_EMPTY))
            await _nlg_search("moby dick", 5)

        assert route.calls[0].request.url.params["query"] == (
            "dc.title=moby and dc.title=dick"
        )

    @pytest.mark.asyncio
    async def test_the_request_is_bounded_because_the_endpoint_bounds_nothing(self):
        """This target returns 200 records when asked for 200, where the ÖNB
        silently caps at 50. So the cap in the request is the only one there is
        short of `fetch.MAX_RESPONSE_BYTES`."""
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__startswith=NLG).mock(return_value=_xml(NLG_EMPTY))
            await _nlg_search("ιστορία", 100)

        assert route.calls[0].request.url.params["maximumRecords"] == "50"

    @pytest.mark.asyncio
    async def test_a_search_result_is_parsed_as_a_book(self):
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__startswith=NLG).mock(return_value=_xml(NLG_RECORD))
            rows = await _nlg_search("ιστορία", 5)

        assert route.called
        assert [row.title for row in rows] == ["Ιστορία της Ευρώπης"]
        assert [row.source for row in rows] == ["nlg"]

    @pytest.mark.asyncio
    async def test_a_query_of_nothing_but_noise_asks_nobody(self):
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__startswith=NLG).mock(return_value=_xml(NLG_EMPTY))
            rows = await _nlg_search("a", 5)

        assert rows == []
        assert not route.called


def _unescaped(text: str, character: str) -> int:
    """How many of `character` are not escaped by a preceding backslash.

    Walks rather than matching, because a backslash can escape a backslash: in
    `a\\\\@b` the `@` is unescaped, and a regex for "not preceded by a
    backslash" reports it as escaped.
    """
    count = 0
    index = 0
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == character:
            count += 1
        index += 1
    return count


class TestTheNkpQueryIsQuotedByThePqfRule:
    """The injection control for the one source whose query is not CQL.

    **This class used to test a second PQF rule, and the rule was wrong.** The
    adapter carried its own `_pqf_literal`, which removed the double quote and
    nothing else, and the fixtures below were chosen to agree with it: the
    operator list carried `@attr` with a space and a comment saying the ticket's
    `@1=1016` was *not* one of the shapes that mattered. It is the shape that
    matters most. `z3950.pqf_term` was measured on 2026-08-28 with `p_query_rpn`
    and records that an `@` followed by a digit is read before the quoted run,
    so it survives quoting and takes the pinned use attribute with it.

    The fixtures are now that measurement's, and the assertions are about the
    query the adapter builds rather than about a helper of its own.
    """

    #: Shapes that reach a PQF parser as something other than text unless escaped.
    #:
    #: The first three are `z3950.pqf_term`'s own measured table, which the old
    #: local rule failed on two of three. The rest survive `_search_terms`, which
    #: strips `=` and so cannot reassemble `@attr 1=4`, but PQF's operators need
    #: no `=`.
    HOSTILE = (
        '@1=1016 praha',
        'praha\\',
        'moby" @attr 1=1016 "x',
        "@and",
        "@or",
        "@not",
        "@set",
        "@attrset",
        "@attr",
    )

    def test_the_cql_sanitiser_leaves_every_pqf_operator_intact(self):
        """The measurement the source's quoting rests on, as an assertion.

        A CQL constant that happens to cover PQF is a coincidence, not a control.
        If this fails because `targets.CQL_STRUCTURE` grew an arm, the arm is the finding.
        """
        for operator in ("@and", "@or", "@not", "@set", "@attrset", "@attr"):
            assert operator in metadata._search_terms(f"{operator} 1=1016 praha")

    def test_the_isbn_query_puts_the_attribute_outside_the_literal(self):
        """`@attr 1=7` is the adapter's, the term is the caller's, and the quote
        is the boundary between them."""
        assert _nkp_query("9788025712948") == '@attr 1=7 "9788025712948"'

    @pytest.mark.parametrize("hostile", HOSTILE)
    def test_nothing_hostile_reaches_the_parser_as_structure(self, hostile):
        """One quoted run, and the adapter's attribute is the only thing outside it.

        Structural rather than a comparison against an expected string: the
        injected text is still in there, and that is the point. It is inside the
        quotes, where PQF reads it as characters to match. What must hold is that
        it cannot get **out**.
        """
        built = _nkp_query(hostile)

        prefix, quote, rest = built.partition('"')
        assert prefix == "@attr 1=7 "
        assert quote == '"'
        # Every `"` and `@` inside the run is escaped, so the only unescaped
        # quote left is the closing one. Counting quotes would pass on the old
        # rule, which reached two by deleting the character instead.
        assert rest.endswith('"')
        assert _unescaped(rest[:-1], '"') == 0
        assert _unescaped(rest[:-1], "@") == 0

    def test_a_trailing_backslash_cannot_escape_the_closing_quote(self):
        """The arm the deleted local rule missed in full.

        `praha\\` quoted without escaping is `"praha\\"`, whose closing quote is
        escaped, so the term runs on into whatever follows.
        """
        assert _nkp_query("praha\\") == '@attr 1=7 "praha\\\\"'

    def test_an_at_sign_before_a_digit_cannot_repin_the_use_attribute(self):
        """The shape the old rule's docstring named and dismissed.

        `parse_isbn` does now yield thirteen ASCII digits or nothing, and until
        this was written it did not: it gated on `str.isdigit()`, which admits
        every Unicode digit. Pinned because the guard here is `z3950.pqf_term`
        and the next caller of this builder may not be `parse_isbn` at all.
        """
        assert _nkp_query("@1=1016 praha") == '@attr 1=7 "\\@1=1016 praha"'

    def test_the_whole_query_is_the_z3950_rule_rather_than_a_copy_of_it(self):
        """One PQF rule in the repository, not two that agree today.

        **Both halves, because the fix for the term half left the attribute half
        duplicated.** `_NKP_ISBN_ATTRIBUTE = "@attr 1=7"` sat beside
        `z3950.USE_ISBN = 7` in a module whose `isbn_query` already names this
        catalogue in its own measurement, so guarding only the term would have
        pinned the smaller of the two copies.

        The defect was two rules rather than one wrong rule: the local copy was
        defensible in isolation and disagreed with the measured one on two shapes
        out of three.
        """
        assert not hasattr(metadata, "_pqf_literal")
        assert not hasattr(metadata, "_NKP_ISBN_ATTRIBUTE")
        for hostile in self.HOSTILE:
            assert _nkp_query(hostile) == z3950.isbn_query(hostile)


class TestTheCzechNationalLibrary:
    """The fifth SRU source, the first that is lookup only, and the first whose
    query is not CQL.

    Three things here are this target's rather than SRU's, and each is measured
    beside the constant it decided: the query goes in `x-pquery` because `query`
    answers diagnostic 1/11, the database path `/NKC` is part of the address, and
    **one record per response is populated whatever page size is asked for**,
    which is why it answers no title search.
    """

    ISBN = "9788025712948"

    @pytest.mark.asyncio
    async def test_a_czech_book_resolves(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=NKP).mock(
                return_value=_xml(_nkp_envelope(NKP_RECORD))
            )
            result = await metadata._lookup_one(targets.SEEDED[CatalogueSource.NKP], self.ISBN, "")

        assert result.outcome is Outcome.FOUND
        assert result.record is not None
        assert result.record.title == "Ostře sledované vlaky"
        assert result.record.publisher == "Argo"
        assert result.record.year == 2018
        assert result.record.page_count == 96

    @pytest.mark.asyncio
    async def test_the_empty_stubs_this_target_pads_a_page_with_are_skipped(self):
        """391 of 400 records over eight live searches carried no `recordData`.

        A reader that assumed every `zs:record` has content would raise on the
        first page of the first query rather than on some rare shape.
        """
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=NKP).mock(
                return_value=_xml(_nkp_envelope(NKP_RECORD, empty_stubs=19))
            )
            result = await metadata._lookup_one(targets.SEEDED[CatalogueSource.NKP], self.ISBN, "")

        assert result.outcome is Outcome.FOUND

    @pytest.mark.asyncio
    async def test_the_first_contributor_is_the_author_and_the_firm_is_not(self):
        """This catalogue writes no `creator` at all, measured 0 of 400, and up
        to three contributors of which the trailing ones are the supply chain.
        `Argo (firma)` is a company."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=NKP).mock(
                return_value=_xml(_nkp_envelope(NKP_RECORD))
            )
            result = await metadata._lookup_one(targets.SEEDED[CatalogueSource.NKP], self.ISBN, "")

        assert result.record is not None
        # `_flip_catalogue_name` puts the forename first and `_PERSON_NOISE`
        # takes the life dates off, which is what every other source here gets.
        assert result.record.author == "Bohumil Hrabal"

    @pytest.mark.asyncio
    async def test_a_record_naming_another_isbn_is_refused(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=NKP).mock(
                return_value=_xml(
                    _nkp_envelope(
                        NKP_RECORD.replace("978-80-257-1294-8", "978-80-000-0000-0")
                    )
                )
            )
            result = await metadata._lookup_one(targets.SEEDED[CatalogueSource.NKP], self.ISBN, "")

        assert result.outcome is Outcome.NOT_FOUND

    @pytest.mark.asyncio
    async def test_the_hyphenated_identifier_matches_the_isbn_asked_for(self):
        """The catalogue prints `978-80-257-1294-8`; the scan is 13 digits."""
        assert metadata._nkp_claims_isbn(
            ElementTree.fromstring(NKP_RECORD), self.ISBN
        )

    @pytest.mark.asyncio
    async def test_the_query_goes_in_the_parameter_this_target_reads(self):
        """`query` answers SRU diagnostic 1/11 here and `queryType` answers 1/8,
        both measured live, so the parameter name is a fact about the target
        rather than a style."""
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            route = mock.get(url__startswith=NKP).mock(
                return_value=_xml(NKP_EMPTY)
            )
            await metadata._lookup_one(targets.SEEDED[CatalogueSource.NKP], self.ISBN, "")

        params = route.calls[0].request.url.params
        assert params["x-pquery"] == f'@attr 1=7 "{self.ISBN}"'
        assert "query" not in params

    @pytest.mark.asyncio
    async def test_one_record_is_asked_for_because_one_is_all_that_arrives(self):
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            route = mock.get(url__startswith=NKP).mock(
                return_value=_xml(NKP_EMPTY)
            )
            await metadata._lookup_one(targets.SEEDED[CatalogueSource.NKP], self.ISBN, "")

        assert route.calls[0].request.url.params["maximumRecords"] == "1"

    @pytest.mark.asyncio
    async def test_an_online_resource_is_refused_in_this_catalogues_own_words(self):
        """`_NOT_A_BOOK` is German and English and cannot see `online zdroj`."""
        online = NKP_RECORD.replace(
            "<format>96 stran ;</format>",
            "<format>1 online zdroj (106 pages) :</format>",
        )
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=NKP).mock(
                return_value=_xml(_nkp_envelope(online))
            )
            result = await metadata._lookup_one(targets.SEEDED[CatalogueSource.NKP], self.ISBN, "")

        assert result.outcome is Outcome.NOT_FOUND

    def test_the_shared_online_rule_is_left_alone(self):
        """The Czech phrasing is this source's constant and not a widening of
        `_NOT_A_BOOK`, which every other source is filtered by. Widening that on
        a phrase measured in one catalogue would change what six other sources
        refuse."""
        assert not metadata._NOT_A_BOOK.search("1 online zdroj (106 pages) :")
        assert metadata._NKP_ONLINE.search("1 online zdroj (106 pages) :")

    def test_it_answers_no_title_search(self):
        """The scope this ticket narrowed to, as an assertion rather than a
        sentence: the server renders one populated record per response whatever
        is asked for, so ten candidates would be ten requests."""
        assert CatalogueSource.NKP in sources.LOOKUP_SOURCES
        assert CatalogueSource.NKP not in sources.SEARCH_SOURCES
        assert not targets.SEEDED[CatalogueSource.NKP].answers_search


class TestTheComponentPartRefusal:
    """The leader test, alone, so its edges are visible.

    Measured over the same 280 live records: the leader catches 155 of 155
    component parts and loses 0 of 122 monographs, where refusing anything
    carrying a 773 catches the same 155 and loses 3 monographs.
    """

    @pytest.mark.parametrize(
        "leader, expected",
        [
            ("00733naa a2200229zc 4500", True),
            ("00733nab a2200229zc 4500", True),
            ("01533nam a2200505 c 4500", False),
            ("01533nac a2200505 c 4500", False),
            # A truncated leader is a broken record rather than an article, and
            # the fields decide it on their own merits.
            ("00733n", False),
            ("", False),
        ],
    )
    def test_the_bibliographic_level_decides(self, leader, expected):
        record = ElementTree.fromstring(
            '<record xmlns="http://www.loc.gov/MARC21/slim">'
            f"<leader>{leader}</leader></record>"
        )
        assert metadata._is_component_part(record) is expected


def _carrier_record(leader: str = "01533nam a2200505 c 4500", **fields: str) -> Any:
    """One MARC record node from a leader and any control fields it needs.

    Named for what it carries rather than for the schema: `_marc_record` above
    is a different thing, a whole record body, and defining a second function of
    that name here shadowed it and broke a size cap fixture two hundred lines
    away. The suite caught it; nothing else would have.
    """
    controls = "".join(
        f'<controlfield tag="{tag[:3]}">{value}</controlfield>'
        for tag, value in fields.items()
    )
    return ElementTree.fromstring(
        '<record xmlns="http://www.loc.gov/MARC21/slim">'
        f"<leader>{leader}</leader>{controls}</record>"
    )


class TestTheCarrierDecides:
    """The MARC codes, alone, so their edges are visible.

    **A diagonal, verified by deleting each code rather than by claiming it.**
    Every one of the ten codes in the three frozensets is pinned: drop any one
    and a row goes red. That is the whole point of the block and the first
    version of it did not have the property, while saying it did. A critic
    measured it: **7 of the 10 survived deletion with all 14 rows green**, since
    the two disc rows each carried two refusing features at once, `sd` on a `njm`
    leader and `vd` on a `ngm` leader, so each covered for the other and neither
    name was load bearing.

    **So the rows are of three kinds, and 9 plus 7 plus 5 is 21.** Both critics
    found the previous sentence separately: it said two kinds and accounted for
    16 of the rows, which is the shape CLAUDE.md predicts for a fix round, a
    corrected partition that does not sum. It replaced a claim that every row was
    live, which was false but at least total, so the correction was weaker in the
    dimension nobody re-checked.

    **9 live**, shapes seen in a catalogue during the September 2026 roster
    measurement. **7 constructed**, one per code that no live record refuses on
    its own, and they have to exist: over 2,605 records only two of the ten codes
    ever refuse a record by themselves, `007 c` on exactly one and leader/06 `m`
    on exactly one, so a table drawn only from live shapes cannot pin this rule.
    **5 edge**, none of them a live shape, which was checked rather than assumed:
    of those 2,605, none carries a leader under 8 characters, an 008 under 24, an
    empty `007`, or no control field at all.

    The 5 are not decoration, and they do **three** jobs rather than one. Strip
    the two length tests and **3 of them raise `IndexError`** where the other 18
    rows do not: the truncated leader, the empty leader and the 11 character 008.
    Change `value[:1]` to `value[0]` and leave both length tests alone and the
    empty `007` row is the **only** one of the 21 that goes red, so it is the
    sole pin for reading the carrier by prefix. The fifth, a record declaring
    nothing at all, pins that silence decides nothing. No row is idle, which is a
    better argument against trimming the table than a count of edges.

    **This paragraph has now been wrong twice, and the second time it said 4.**
    That 4 was a true measurement of the wrong thing: the script behind it
    stripped the length tests **and** changed the slice in one pass, so it
    counted a mutation nobody was describing. CLAUDE.md's line for it is that a
    measurement is only evidence about the configuration it was taken under, and
    the tell was available in the file: the row comment below already says an
    empty `007` matches nothing rather than raising, so the sentence contradicted
    a comment eleven lines away.

    Its remaining blind spot: it pins codes, not the vocabulary. A carrier code
    no catalogue here has written yet is invisible to it, and `008/23 s` is
    pinned only by a constructed row because it has never been observed, sitting
    in the constant on MARC's definition as `b` does in `_COMPONENT_PART_LEVELS`.
    """

    @pytest.mark.parametrize(
        "leader, controls, expected",
        [
            # An online resource: one electronic carrier and nothing else.
            ("01533nam a2200505 c 4500", {"007": "cr#|||||||||||"}, False),
            # An audiobook and a videodisc, by their carrier.
            ("01533njm a2200505 c 4500", {"007": "sd f||||||||||"}, False),
            ("01533ngm a2200505 c 4500", {"007": "vd |||||||||||"}, False),
            # A computer file, the NLG's `E-BOOK`, which carries no 007 at all.
            ("01533nmm a2200505 c 4500", {}, False),
            # ── Constructed, one per code no live record refuses alone ───────
            # The two live disc rows above carry a refusing carrier **and** a
            # refusing leader, so without these seven, seven of the ten codes
            # could be deleted with this table still green.
            ("01533nam a2200505 c 4500", {"007": "sd f||||||||||"}, False),
            ("01533nam a2200505 c 4500", {"007": "vd |||||||||||"}, False),
            ("01533ngm a2200505 c 4500", {}, False),
            ("01533nim a2200505 c 4500", {}, False),
            ("01533njm a2200505 c 4500", {}, False),
            (
                "01533nam a2200505 c 4500",
                {"008": "210224s2020    gw |||||q|||| 00||||ger  "},
                False,
            ),
            (
                "01533nam a2200505 c 4500",
                {"008": "210224s2020    gw |||||s|||| 00||||ger  "},
                False,
            ),
            # Form of item, where the carrier is absent. 195 of the 2,605
            # records measured carry no 007, so this is not a hypothetical.
            ("01533nam a2200505 c 4500", {"008": "210224s2020    gw |||||o|||| 00||||ger  "}, False),
            # A plain printed book: the text carrier, and a blank form of item.
            (
                "01533nam a2200505 c 4500",
                {"007": "tu", "008": "210224s2020    gw ||||| |||| 00||||ger  "},
                True,
            ),
            # **A text carrier beside an electronic one is a text.** 48 of those
            # 2,605 are Austrian Books Online records for real 19th century
            # prints, with the print's collation in the 300 and the scan in an
            # 856. Refusing on any electronic 007 refuses all 48.
            ("00796nam a2200265 cc4500", {"007": "cr#|||||||||||", "007a": "tu"}, True),
            # Nothing declared at all decides nothing, which is the common case:
            # a thin record is not a disc.
            ("01533nam a2200505 c 4500", {}, True),
            # A leader too short to index, and an 008 too short to reach 23.
            ("00733n", {}, True),
            ("", {}, True),
            ("01533nam a2200505 c 4500", {"008": "210224s2020"}, True),
            # An empty 007 is read by prefix and matches nothing rather than
            # raising, which is why the carrier is not read positionally.
            ("01533nam a2200505 c 4500", {"007": ""}, True),
            # The ÖNB writes `#` where the DNB writes a space, and `|` means no
            # attempt to code. 560 ÖNB **records** carry `#` here and the shipped
            # rule keeps **556** of them, so a rule testing "not blank" would
            # refuse 556 books outright.
            ("01533nam a2200505 c 4500", {"008": "000101|1568    |||           ||| | lat c"}, True),
            ("01533nam a2200505 c 4500", {"008": "210224s2020    gw ||||||||||| 00||||ger  "}, True),
        ],
    )
    def test_the_record_states_its_own_carrier(self, leader, controls, expected):
        assert metadata._marc_carrier_is_book(_carrier_record(leader, **controls)) is expected

    def test_a_control_field_is_read_raw_and_never_through_marc_text(self):
        """The blanks in an 008 are data, and collapsing them moves position 23.

        Measured over 2,605 live records, and counted in **records**: `_marc_text`
        alters the 008 of 2,043 of them and changes what sits at position 23 on
        1,859. 847 records carry `o` there and 817 of those lose it, this 008
        being one, so routing the control field through the shared subfield
        reader turns this refusal into a pass with nothing failing anywhere.

        **608 is what this paragraph said, and it is the count of distinct 008
        values among those 817 records rather than a count of records.** A
        critic caught it. The instrument had answered a narrower question than
        the prose asked, which is the failure CLAUDE.md names, and it sat here
        beside a comment in `metadata.py` that had the same slip twice over.
        """
        raw = "210224s2020    gw |||||o|||| 00||||ger  "
        assert raw[23] == "o"
        assert metadata._marc_text(raw)[23] != "o"
        assert metadata._marc_carrier_is_book(_carrier_record(**{"008": raw})) is False


class TestTheCarrierTestIsTheOnlyWayIn:
    """One door in front of every MARC parse path, enforced rather than asked.

    `_NOT_A_BOOK` was the whole rule and it is written in German and English, so
    it silently passed a Czech online resource (#124). The codes answer that, and
    the way a code test stops being applied is that somebody adds a source and
    parses it the way the neighbours do, minus one line. So the shape of the
    guard is the shape `TestTheShelfIsTheOnlyWayIn` uses for the privacy rule:
    the correct number of exceptions is a named few, so `ast` can count them.

    **What it cannot see**, listed here rather than left to be discovered. Both
    checks read plain `Name` calls, so an aliased call (`fields = _marc_fields`
    then `fields(node)`) and an attribute call (`metadata._marc_fields(node)`)
    are invisible to them; neither is a spelling this module uses anywhere, and
    the second is not a spelling a module uses on itself. `_fullest_physical`
    satisfies the first check for the three lookups that name it, and it only
    **ranks**, so a search path that ranked where it should refuse would pass
    while refusing nothing; that is not true of any path today. A path that calls
    the door and **discards the answer** satisfies both checks; that is the cheapest
    evasion of the four and it is not detectable by any guard keyed on call
    names, which is the same limit `TestTheShelfIsTheOnlyWayIn` lives with. And a
    source that parses MARC datafields without calling `_marc_fields` at all is
    outside the first check entirely: it would be a second reader of one format,
    which is a finding on its own before it is a hole here.
    """

    @staticmethod
    def _functions() -> dict[str, set[str]]:
        """Every function in `metadata.py`, by the plain names it calls."""
        tree = ast.parse((Path(metadata.__file__)).read_text(encoding="utf-8"))
        return {
            node.name: {
                call.func.id
                for call in ast.walk(node)
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            }
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }

    def test_a_marc_parse_path_cannot_skip_the_carrier_test(self):
        """Reading a MARC record's fields obliges you to ask about its carrier.

        No allowlist, because outside these the correct answer is zero:
        `_marc_fields` exists to turn one record into book fields, and a caller
        doing that without asking whether it is a book is the defect.

        **Two, where this said eight, and the drop is the ticket rather than a
        weakening.** The eight were five per source lookups and three per source
        searches, each reading `_marc_fields` in its own copy of the same four
        lines. They are `_marc_lookup` and `_marc_search`, driven by a row, so
        the surface a new source can get wrong went from eight hand written paths
        to none: a tenth catalogue that reads MARC adds a row and reaches these
        two. A number that fell because its subject was deleted is the shape this
        repository asks to be stated rather than quietly edited, so it is stated:
        nothing was exempted and nothing stopped being checked, there are two
        readers where there were eight.
        """
        readers = {
            name: calls
            for name, calls in self._functions().items()
            if "_marc_fields" in calls
        }
        assert len(readers) == 2, sorted(readers)
        # **`_marc_lookup` needs both names and not either, and that is a
        # regression this guard shipped for one round.** A critic deleted
        # `_marc_is_physical_book` from its ranking arm and all three checks in
        # this class stayed green: one function holds two policies now, so the
        # filtering arm's `_fullest_physical` satisfied an "either" test on the
        # ranking arm's behalf. Under the old shape the DNB lookup was its own function
        # naming only the door, so the same deletion failed. The mutation is a
        # live defect and not a cosmetic one: a DNB response holding a
        # digitisation and a printed record that both claim the ISBN answered
        # with the digitisation, `page_count` None against 300.
        required = {
            "_marc_lookup": {"_marc_is_physical_book", "_fullest_physical"},
        }
        assert not [
            name
            for name, calls in readers.items()
            if not calls
            >= required.get(name, set())
            or not calls & {"_marc_is_physical_book", "_fullest_physical"}
        ]

    def test_the_prose_rule_is_reached_only_through_a_carrier_aware_door(self):
        """`_is_physical_book` has four callers and each is a door of its own.

        One for MARC and one for each serialisation that carries no codes. A
        fifth is a MARC path that has skipped the carrier test, or a new source
        whose serialisation nobody classified.
        """
        callers = {
            name
            for name, calls in self._functions().items()
            if "_is_physical_book" in calls
        }
        assert callers == {
            "_marc_is_physical_book",
            "_bnf_record",
            "_loc_record",
            "_nkp_record",
        }

    def test_the_lookup_ranking_helper_is_itself_inside_the_door(self):
        """The check above is satisfied one hop early by the filtering arm.

        `_marc_lookup`'s filtering arm names `_fullest_physical` and not the
        door, so removing the carrier term from that helper's sort key would
        leave the checks above green for that arm. A critic measured it under the
        old shape, where the K10plus lookup, the ÖNB lookup and the NLG lookup were three functions doing
        it; the three are one arm of one function now and the hole is the same
        one. It is scope rather than a hole, because the ranking has tests of its
        own, and this closes it so the class docstring's claim is true of both
        arms.
        """
        assert "_marc_is_physical_book" in self._functions()["_fullest_physical"]


class TestTheLookupsRankAPhysicalRecordFirst:
    """`_fullest_physical`, which three lookups did without.

    They ranked on `completeness` alone, and a digitisation is usually the
    fuller record. Measured over 210 live K10plus ISBN lookups in the September
    2026 roster measurement: 9 answered with both kinds and 8 of the 9 returned
    the non physical one.
    """

    @staticmethod
    def _book(control: str, title: str, pages: str, extra: str = "") -> Any:
        node = ElementTree.fromstring(
            '<record xmlns="http://www.loc.gov/MARC21/slim">'
            "<leader>01533nam a2200505 c 4500</leader>"
            f'<controlfield tag="007">{control}</controlfield>'
            '<datafield tag="245" ind1="1" ind2="0">'
            f'<subfield code="a">{title}</subfield></datafield>'
            '<datafield tag="300" ind1=" " ind2=" ">'
            f'<subfield code="a">{pages}</subfield></datafield>'
            f"{extra}</record>"
        )
        fields = _marc_fields(node)
        return node, fields, metadata._k10plus_record(fields, "9783442267743")

    def _pair(self) -> Any:
        """A digitisation that is the fuller record, and a thinner printed one.

        **The page counts differ on purpose.** The first draft of this test gave
        both `992 Seiten`, because an online extent reads `1 Online-Ressource
        (992 Seiten)` and `_pages_from_extent` reads the same number out of both.
        Deleting the ranking term left the assertion passing, and a mutation run
        is what said so: the fixture was named for the ranking and pinned the
        page parser.
        """
        online = self._book(
            "cr#|||||||||||",
            "Der Zauberberg",
            "1 Online-Ressource (999 Seiten) : Ill.",
            '<datafield tag="264" ind1=" " ind2="1">'
            '<subfield code="b">S. Fischer</subfield>'
            '<subfield code="c">2019</subfield></datafield>',
        )
        printed = self._book("tu", "Der Zauberberg", "992 Seiten")
        return online, printed

    def test_the_fixture_gives_the_digitisation_the_higher_completeness(self):
        """Otherwise the test below passes for the wrong reason.

        The digitisation being the fuller record is why ranking on completeness
        alone picked it, so a fixture where the printed record is fuller would
        agree with the code whether the ranking term is there or not.
        """
        online, printed = self._pair()

        assert online[2].completeness > printed[2].completeness

    def test_the_printed_edition_wins_over_the_fuller_digitisation(self):
        online, printed = self._pair()

        assert metadata._fullest_physical([online, printed]).page_count == 992
        assert metadata._fullest_physical([printed, online]).page_count == 992

    def test_an_online_record_still_answers_when_it_is_the_only_one(self):
        """A rank and not a refusal, which is the DNB lookup's documented asymmetry.

        31 of those 210 K10plus lookups are answered only by records this
        refuses, and reporting a miss for all 31 would be a different decision
        from the one this ticket took.
        """
        online = self._book("cr#|||||||||||", "Der Zauberberg", "1 Online-Ressource")

        assert metadata._fullest_physical([online]).title == "Der Zauberberg"


class TestTheDublinCoreAndModsSourcesRefuseInTheirOwnTerms:
    """The three sources with no MARC control fields to read.

    Two of them still declare something and one genuinely does not, which is the
    whole answer to the ticket's question about Dublin Core.
    """

    @staticmethod
    def _bnf(kind: str, extent: str) -> Any:
        return metadata._bnf_record(
            ElementTree.fromstring(
                '<record xmlns:dc="http://purl.org/dc/elements/1.1/">'
                "<dc:title>Un livre</dc:title>"
                f"<dc:type>{kind}</dc:type>"
                f"<dc:format>{extent}</dc:format></record>"
            )
        )

    def test_an_ordinary_printed_bnf_record_is_still_a_book(self):
        assert self._bnf("texte imprime | printed text | text", "200 p.") is not None

    def test_the_dcmi_text_on_an_electronic_resource_no_longer_passes(self):
        """`_BNF_PRINTED` matches `text` as a substring, and the BnF writes the
        DCMI type `text` on an ebook. 8 of 444 live records pass that way."""
        kind = "ressource electronique | electronic resource | text"
        assert any(printed in kind for printed in metadata._BNF_PRINTED)
        assert self._bnf(kind, "") is None

    def test_a_dematerialised_resource_is_refused_although_the_type_says_printed(self):
        """The 6 records where the type is simply wrong, which is why the type
        gate above is not the whole BnF answer and prose survives here."""
        assert (
            self._bnf("texte imprime | printed text | text", "1 ressource dematerialisee")
            is None
        )
        assert not metadata._NOT_A_BOOK.search("1 ressource dematerialisee")

    @pytest.mark.parametrize(
        "form, expected",
        [
            ('<form authority="marcform">print</form>', True),
            ('<form authority="rdamedia">unmediated</form>', True),
            ('<form authority="rdacarrier">volume</form>', True),
            ('<form authority="marcform">microfilm</form>', True),
            ('<form authority="marcform">electronic</form>', False),
            ('<form authority="marccategory">electronic resource</form>', False),
            ('<form authority="rdamedia">computer</form>', False),
            # An unqualified form names no vocabulary and decides nothing.
            ("<form>electronic</form>", True),
            # 1 of 391 live records carries no form at all.
            ("", True),
        ],
    )
    def test_the_mods_form_says_what_the_marc_codes_say(self, form, expected):
        record = ElementTree.fromstring(
            '<mods xmlns="http://www.loc.gov/mods/v3">'
            f"<physicalDescription>{form}<extent>464 p.</extent>"
            "</physicalDescription></mods>"
        )

        assert metadata._loc_carrier_is_book(record) is expected

    def test_a_cd_rom_reaches_the_member_without_the_form_test(self):
        """10 of the 30 records this refuses name a CD-ROM, 6 of them in one
        spelling, `1 CD-ROM : sd., col. ; 4 3/4 in. + 1 guide (14 p. : ill. ; 12
        cm.)`. No alternative in `_DISC_FORMS` matches any of the 10 in any
        language: `CD-ROM` is missing from it in English too.

        The extent below is a third live spelling, which occurs once.
        """
        extent = "1 CD-ROM : sd., col. ; 4 3/4 in. + 1 guide (14 p.)"
        assert metadata._is_physical_book(extent, "Clean Code")

        mods = ElementTree.fromstring(
            '<mods xmlns="http://www.loc.gov/mods/v3">'
            "<typeOfResource>text</typeOfResource>"
            "<titleInfo><title>Clean Code</title></titleInfo>"
            '<physicalDescription><form authority="marcform">electronic</form>'
            f"<extent>{extent}</extent></physicalDescription></mods>"
        )

        assert _loc_record(mods) is None


class TestEverySourceSetsTheIsbnItWasAskedFor:
    """`catalogue.Record.as_lookup()`'s guarantee, as a test rather than a docstring.

    **That docstring is a tripwire and it fired once.** It says a `Record` with
    no `isbn` makes `BookLookup(**record.as_lookup())` raise, that `lookup_isbn`
    catches no `ValidationError`, and that the response would therefore be a
    500. Nothing enforces it: the return type is `dict[str, Any]`, so mypy sees
    no requirement, and the guarantee lives in the adapters. It ended "a fifth
    lookup source that leaves `isbn` unset is the change that turns this
    paragraph into a defect", and on 2026-08-27 the ÖNB was that fifth source.

    It fired because somebody wrote the **trigger** down rather than only the
    count. It should not have to fire twice. The standing rule here is that a
    mechanically detectable finding becomes a test, and this one is: every value
    that answers a lookup reaches one door, `metadata._lookup_one`, so
    driving each of them with a body that resolves and asserting the record
    carries the ISBN asked for covers all five at once.

    **Parametrised over `metadata._lookup_one` itself, not over a list written here**, which
    is the whole point: a sixth source is covered the moment it is registered,
    and a sixth source with no response body below fails this file rather than
    being silently skipped. Without that, arming the guarantee depends on
    somebody adding a source in `metadata.py` and happening to read a docstring
    in `catalogue.py`. That is the same distance that let five copies of six
    stale figures sit in `test_fetch.py`.

    **What this asserts is the invariant, not the mechanism, and that boundary
    was measured rather than assumed.** Five mutations were tried. Making
    `_open_library` or `_google_books` stop passing the argument fails here, and
    so does registering a sixth source with no body. Making the **MARC**
    adapters pass `None` instead of the argument does **not**, and that is
    correct rather than a hole: all three MARC lookups filter their candidates
    through `_marc_claims_isbn` first, so a record that reaches the parser is
    guaranteed to carry a matching 020, and `_dnb_record`'s
    `isbn = isbn or _marc_isbn(fields)` then supplies the same canonical value
    from the record. Two independent mechanisms satisfy the invariant on those
    paths, and the invariant is what `as_lookup()` needs. A test that failed
    there would be pinning which of the two ran, which is not the guarantee and
    would break on a legitimate refactor.
    """

    ISBN = "9780743273565"

    #: One resolving response per source, keyed by its name in `metadata._lookup_one`.
    #:
    #: Each is the smallest body that reaches `Outcome.FOUND` for that adapter,
    #: because what is under test is which field the record carries rather than
    #: how richly it parses.
    #:
    #: **No body carries the canonical ISBN-13 anywhere**, which is what makes
    #: the assertion discriminating rather than circular. The JSON sources carry
    #: no identifier at all. The MARC sources cannot do that, because
    #: `_marc_claims_isbn` refuses a record whose own 020 does not name the ISBN
    #: asked for, so their 020 carries the **ISBN-10** form, `0743273567`. That
    #: satisfies the identity check, which canonicalises both sides, while
    #: leaving `9780743273565` obtainable only from the argument. A first draft
    #: of this class omitted the 020 entirely and two of the five adapters
    #: correctly reported NOT_FOUND.
    # `tuple[str, httpx.Response]`, not `object`: the values are unpacked as
    # `host, response` at three call sites, and `object` is not iterable.
    def _bodies(self) -> dict[str, tuple[str, httpx.Response]]:
        marc = _marc(
            '<record xmlns="http://www.loc.gov/MARC21/slim">'
            "<leader>01533nam a2200505 c 4500</leader>"
            '<datafield tag="020" ind1=" " ind2=" ">'
            "<subfield code=\"a\">0743273567</subfield></datafield>"
            '<datafield tag="245" ind1="1" ind2="0">'
            "<subfield code=\"a\">The Great Gatsby</subfield></datafield>"
            '<datafield tag="264" ind1=" " ind2="1">'
            "<subfield code=\"c\">1925</subfield></datafield>"
            '<datafield tag="300" ind1=" " ind2=" ">'
            "<subfield code=\"a\">218 S.</subfield></datafield>"
            "</record>"
        )
        oenb = _oenb_envelope(
            '<record xmlns="http://www.loc.gov/MARC21/slim">'
            "<leader>01533nam a2200505 c 4500</leader>"
            '<datafield tag="020" ind1=" " ind2=" ">'
            "<subfield code=\"a\">0743273567</subfield></datafield>"
            '<datafield tag="245" ind1="1" ind2="0">'
            "<subfield code=\"a\">The Great Gatsby</subfield></datafield>"
            '<datafield tag="264" ind1=" " ind2="1">'
            "<subfield code=\"c\">1925</subfield></datafield>"
            '<datafield tag="300" ind1=" " ind2=" ">'
            "<subfield code=\"a\">218 S.</subfield></datafield>"
            "</record>"
        )
        return {
            "dnb": (DNB, _xml(marc)),
            "k10plus": (K10PLUS, _xml(marc)),
            "oenb": (OENB, _xml(oenb)),
            "nlg": (NLG, _xml(marc)),
            # Dublin Core rather than MARC, and the identifier carries the
            # ISBN-10 so the assertion stays discriminating: `_nkp_claims_isbn`
            # canonicalises both sides, leaving the 13 digit form obtainable
            # only from the argument.
            "nkp": (
                NKP,
                _xml(
                    _nkp_envelope(
                        "<dc-record><type>text</type>"
                        "<identifier>0743273567</identifier>"
                        "<title>The Great Gatsby</title>"
                        "<date>1925</date>"
                        "<format>218 p.</format></dc-record>"
                    )
                ),
            ),
            "open_library": (
                OPEN_LIBRARY,
                httpx.Response(200, json={"title": "The Great Gatsby"}),
            ),
            "google_books": (
                GOOGLE_BOOKS,
                httpx.Response(
                    200,
                    json={
                        "items": [
                            {"id": "gb-1", "volumeInfo": {"title": "The Great Gatsby"}}
                        ]
                    },
                ),
            ),
        }

    def test_every_registered_source_has_a_body_here(self):
        """The arming step, and the reason this class is parametrised on `metadata._lookup_one`.

        A source that answers a lookup with no entry below would make the
        parametrised test skip it in silence. This turns that into a failure, so
        adding a source forces the question the `catalogue.py` docstring asks.
        """
        missing = sorted(set(sources.LOOKUP_SOURCES) - set(self._bodies()))
        assert not missing, (
            f"{missing} answers an ISBN lookup with no response body "
            "in this test. Add one, and check the new adapter sets `isbn` from "
            "the argument rather than from the record it parsed: see "
            "`catalogue.Record.as_lookup`."
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", sorted(sources.LOOKUP_SOURCES))
    async def test_the_record_carries_the_isbn_the_source_was_asked_for(self, name):
        host, response = self._bodies()[name]
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=host).mock(return_value=response)
            result = await metadata._lookup_one(targets.SEEDED[name], self.ISBN, "a-key")

        assert result.outcome is Outcome.FOUND, (
            f"the {name} body no longer resolves, so this asserts nothing"
        )
        assert result.record is not None
        assert result.record.isbn == self.ISBN

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", sorted(sources.LOOKUP_SOURCES))
    async def test_the_lookup_schema_accepts_what_each_source_produces(self, name):
        """The other end of the same guarantee: the dictionary must build.

        `as_lookup()` names `isbn` as required and coerces only `title`, and
        `lookup_isbn` catches no `ValidationError`, so a record reaching here
        without an ISBN is a 500 rather than a bad answer. This constructs the
        model the route constructs.
        """
        host, response = self._bodies()[name]
        with respx.mock(assert_all_called=False) as mock:
            silence_covers(mock)
            mock.get(url__startswith=host).mock(return_value=response)
            result = await metadata._lookup_one(targets.SEEDED[name], self.ISBN, "a-key")

        assert result.record is not None
        assert BookLookup(**result.record.as_lookup()).isbn == self.ISBN


#: One representative of every distinct plan the roster's permutations produce.
#:
#: **Session scoped because it is enumeration, not state.** Building it walks all
#: 362,880 permutations once at about eight seconds; the class below then runs
#: 3,600 lookups per holder instead of 362,880, which took that class from 290
#: seconds to a fraction of it without dropping a single order.
#: The registration groups the filter is checked against: the two this class
#: actually asks about, and two it does not, so the property is not established
#: only on the inputs that happen to be used.
_GROUPS_CHECKED = ("978-0", "978-960", "978-3", "978-80")


@pytest.fixture(scope="session")
def distinct_orders() -> tuple[tuple[tuple[CatalogueSource, ...], ...], dict]:
    """The representatives, and the evidence that they are all of them.

    **One walk, not two.** The deduplication and the proof that it loses nothing
    read the same 362,880 permutations, so computing them separately would be
    the same fact derived twice at twice the cost. The map is returned rather
    than asserted here because a fixture that fails is an error rather than a
    failure, and this repository separates those.
    """

    def plan(order: tuple[CatalogueSource, ...]) -> sources.Plan:
        return sources.parse(
            {"sources": [{"source": name.value, "enabled": True} for name in order]}
        )

    seen: dict[tuple, tuple[CatalogueSource, ...]] = {}
    filtered: dict[tuple, tuple] = {}
    collisions: list[tuple] = []
    for order in itertools.permutations(sources.DEFAULT_ORDER):
        built = plan(order)
        signature = (tuple(built.lookup_together), tuple(built.lookup_in_turn(None)))
        seen.setdefault(signature, order)
        chains = tuple(
            (group, tuple(built.lookup_in_turn(group))) for group in _GROUPS_CHECKED
        )
        if filtered.setdefault(signature, chains) != chains:
            collisions.append((signature, order))
    return tuple(seen.values()), {"collisions": collisions, "signatures": set(seen)}


class TestNoOrderOfTheRosterFindsMoreBooks:
    """The chain asks every enabled source until one answers, so order is a schedule.

    **`sources.DEFAULT_ORDER`'s docstring rests on this and #115 measured it**, so
    it is pinned here rather than left as a sentence: over 500 domestic ISBNs,
    five candidate orders resolved the same 300. A test is the better half of
    that claim, because the survey measured the orders that were considered and
    this measures **every permutation of the roster**.

    What it protects is a refusal. The cheap answer to "the chain misses books in
    Greece" is to reorder the list, and reordering cannot help: the only thing a
    reorder buys is latency and which records `_merge` folds. A future change
    that makes a hit depend on position, an early exit or a per tier deadline
    say, breaks this rather than quietly narrowing what the chain finds.

    **Each holder is asked about a book in its own registration group, and #122
    is why.** `sources.SERVES_GROUPS` skips a national catalogue on the lookup
    path for a group outside its remit, so a source in the tail genuinely is
    unreachable for a foreign ISBN and the invariant above is now conditional on
    the remit rather than absolute. Handing every holder one English ISBN would
    make this class fail for two sources on a change that is deliberate, and
    hiding that by dropping those two rows would leave the strongest test of the
    order silently not covering them.

    **What that condition costs is measured and is zero.** A source may carry a
    remit only if it uniquely answers nothing outside it, which
    `test_no_source_with_a_remit_uniquely_answers_outside_it` recomputes from the
    committed sample. So the books this class is about are unaffected; what moved
    is which ISBN each of two sources has to be asked about to be reached at all.
    """

    #: One ISBN per holder, in a group that holder's remit reaches. Sources with
    #: no remit take the English one, which is outside both declared remits and
    #: therefore also proves the unrestricted ones are not filtered.
    ISBN = "9780306406157"
    ISBNS = {
        CatalogueSource.NLG: GREEK_ISBN,
        CatalogueSource.OENB: GERMAN_ISBN,
    }

    def _plan(self, order: tuple[CatalogueSource, ...]) -> sources.Plan:
        return sources.parse(
            {"sources": [{"source": name.value, "enabled": True} for name in order]}
        )

    @staticmethod
    def _signature(plan: sources.Plan) -> tuple:
        """Everything about a plan that `lookup` can see.

        The first tier it gathers, and the chain it walks one at a time with no
        registration group filter applied. Two orders with the same signature
        are the same input to `lookup`, which is what makes the deduplication
        below lossless rather than a sample.
        """
        return (tuple(plan.lookup_together), tuple(plan.lookup_in_turn(None)))

    @staticmethod
    def _only(holder: CatalogueSource):
        """A `metadata._lookup_one` table where exactly one catalogue holds the book."""

        def make(name: CatalogueSource):
            async def answer(isbn: str, api_key: str) -> metadata.Lookup:
                if name is not holder:
                    return metadata.Lookup(metadata.Outcome.NOT_FOUND)
                return metadata.Lookup(
                    metadata.Outcome.FOUND,
                    record=Record(source=name.value, isbn=isbn, title="Held here"),
                    source=name.value,
                )

            return answer

        return {name: make(name) for name in sources.LOOKUP_SOURCES}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("holder", sorted(sources.LOOKUP_SOURCES))
    async def test_every_permutation_finds_a_book_any_one_source_holds(
        self,
        holder: CatalogueSource,
        distinct_orders: tuple[tuple[tuple[CatalogueSource, ...], ...], dict],
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        """Parametrised on the holder, because a table where nothing answers
        would pass this with the chain deleted.

        **`distinct_orders` is every permutation, deduplicated by what `lookup`
        can see, and that is not a sample.** The roster is nine sources and the
        lookup chain is seven, of which the first tier gathers two, so most of a
        permutation is invisible here: measured, the 362,880 orders produce
        **3,600** distinct plans. Running one representative of each covers every
        order, because the ones dropped are byte identical after `parse` rather
        than merely similar, and `test_the_deduplication_reaches_every_order`
        drives all 362,880 to prove it.

        What that bought is the reason it is worth the paragraph: this class was
        290 of the backend suite's 308 seconds.
        """
        # **Silenced for memory, not for tidiness.** `lookup` logs one line per
        # resolved ISBN, and pytest's capture handler holds every record emitted
        # inside a single test. This loop is one test, so at 9! orders it held
        # 362,880 LogRecords and their argument tuples at once: measured 15 live
        # objects per iteration, a peak of 1059 MB on the xdist worker that runs
        # this file, and an OOMKill of `test:backend` against the runner's 2Gi
        # from 2026-08-31, the day the ninth source took 8! to 9!.
        #
        # Setting the level stops the record being CREATED, so it is the loop
        # that gets cheaper rather than the handler. Nothing here reads the log.
        # Restored by caplog at teardown, so a later test still captures.
        caplog.set_level(logging.WARNING, logger="endpaper.metadata")
        patch_lookup_adapters(monkeypatch, self._only(holder))

        # The signature is mirrored rather than swallowed with **kwargs, for
        # conftest's reason: a stub that accepts anything keeps passing after
        # the real one changes shape.
        async def no_cover(
            raw_isbn: str, supplied: str | None = None, deadline: float | None = None
        ) -> str | None:
            return None

        monkeypatch.setattr(covers, "resolve", no_cover)
        isbn = self.ISBNS.get(holder, self.ISBN)
        first_asked = set()
        for order in distinct_orders[0]:
            metadata.clear_cache()
            result = await metadata.lookup(isbn, "a-key", plan=self._plan(order))
            assert result.outcome is metadata.Outcome.FOUND, order
            # **`record.sources`, not `in result.source`.** That was a substring
            # match on a joined string, and `"dnb" in "oenb"` is True, so it
            # could not tell a DNB hit from an OENB one. Nothing was masked
            # because `_only` lets exactly one source answer, which is the kind
            # of accident that stops being one after an edit.
            assert result.record is not None
            assert holder.value in result.record.sources, order
            first_asked.add(result.attempts[0][0])
        # **Anti vacuity, and it is the assertion that makes the loop mean
        # something.** Everything above passes on an implementation that ignores
        # the plan and asks all five, and passes on a `parse` that returns
        # `DEFAULT_PLAN` for every input. This says the permutations really did
        # reach `lookup` as different plans.
        assert len(first_asked) > 1

    def test_the_deduplication_reaches_every_order(
        self, distinct_orders: tuple[tuple[tuple[CatalogueSource, ...], ...], dict]
    ):
        """The half that makes the class above exhaustive rather than a sample.

        It drives all 362,880 permutations, which the class itself no longer
        does, and asserts two things about them. That the signature really is
        everything `lookup` sees: two orders sharing one produce the same chain
        **after** the registration group filter, for every group this class
        asks about and two it does not. And that the deduplicated set is the
        whole of the signature space rather than a prefix of it.

        **Without this the optimisation is a silent coverage cut.** A change to
        `parse` that made the chain depend on something outside the signature
        would leave the class above passing on a fraction of the orders it
        claims, with nothing red. Here it fails.
        """
        orders, evidence = distinct_orders

        assert not evidence["collisions"], (
            "two orders share a signature and ask a different chain once the "
            "registration group filter runs, so the signature is no longer "
            "everything `lookup` sees and the class above covers a fraction of "
            f"the orders it claims: {evidence['collisions'][:3]}"
        )
        assert evidence["signatures"] == {self._signature(self._plan(o)) for o in orders}
        assert len(orders) == len(evidence["signatures"])

    @pytest.mark.asyncio
    async def test_a_source_no_permutation_reaches_would_fail_this(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """The evasion, run rather than argued.

        A holder that is dropped from the plan is unreachable under **every**
        order, which is what the test above would look like if `parse` were
        losing a source. It has to fail, or the parametrised test is measuring
        that the chain answers rather than that the order does not matter.
        """
        patch_lookup_adapters(monkeypatch, self._only(CatalogueSource.OPEN_LIBRARY))
        metadata.clear_cache()
        without = sources.parse(
            {"sources": [{"source": "open_library", "enabled": False}]}
        )
        result = await metadata.lookup(self.ISBN, "a-key", plan=without)
        assert result.outcome is not metadata.Outcome.FOUND


class TestALibraryThatAsksNothing:
    """Every catalogue switched off is a real state, and it must not raise.

    **`asyncio.wait` refuses an empty set with `ValueError`**, so the fan out
    turned a title search into a 500 for exactly the library that had just used
    the new setting. It arrived with the fix for the sibling case: `lookup`
    learned to say "nothing was asked" and this path was left to find out.

    The routes refuse before they get here, with a 409 naming the setting. This
    is the layer under that, and it is tested separately because a caller
    passing a plan by hand is not a caller that consulted the settings table.
    """

    @staticmethod
    def _nothing_on() -> sources.Plan:
        return sources.parse(
            {
                "sources": [
                    {"source": source.value, "enabled": False}
                    for source in sources.DEFAULT_ORDER
                ]
            }
        )

    @pytest.mark.asyncio
    async def test_a_title_search_answers_nothing_rather_than_raising(self):
        assert await metadata.search("anything", plan=self._nothing_on()) == []

    @pytest.mark.asyncio
    async def test_the_edition_candidates_answer_nothing_rather_than_raising(self):
        rows = await metadata.candidates(
            "anything", isbn=ENGLISH_ISBN, plan=self._nothing_on()
        )
        assert rows == []

    @pytest.mark.asyncio
    async def test_an_isbn_lookup_says_nothing_was_asked(self):
        """Distinct from "no catalogue has this book", which is a claim."""
        metadata.clear_cache()
        result = await metadata.lookup(ENGLISH_ISBN, plan=self._nothing_on())
        assert result.outcome is metadata.Outcome.NO_SOURCES
        assert result.attempts == []

    @pytest.mark.asyncio
    async def test_the_edition_cluster_is_not_asked_with_open_library_off(self):
        """Open Library is the only source of a cluster, so off means empty."""
        without = sources.parse(
            {"sources": [{"source": "open_library", "enabled": False}]}
        )
        assert await metadata.editions(ENGLISH_ISBN, 5, plan=without) == []


def _newcombe(
    first_hits: int, first_n: int, second_hits: int, second_n: int
) -> tuple[float, float, float]:
    """The difference between two proportions and its 95% interval, as percentages.

    Newcombe's method 10, which builds the difference interval out of the two Wilson
    intervals rather than assuming normality, and is what every interval quoted in this
    docstring was computed with.
    """
    z = 1.959964

    def wilson(hits: int, total: int) -> tuple[float, float]:
        share = hits / total
        spread = 1 + z * z / total
        centre = (share + z * z / (2 * total)) / spread
        half = (
            z
            * math.sqrt(
                share * (1 - share) / total + z * z / (4 * total * total)
            )
            / spread
        )
        return max(0.0, centre - half), min(1.0, centre + half)

    first, second = first_hits / first_n, second_hits / second_n
    first_low, first_high = wilson(first_hits, first_n)
    second_low, second_high = wilson(second_hits, second_n)
    low = (first - second) - math.sqrt(
        (first - first_low) ** 2 + (second_high - second) ** 2
    )
    high = (first - second) + math.sqrt(
        (first_high - first) ** 2 + (second - second_low) ** 2
    )
    return 100 * (first - second), 100 * low, 100 * high


class TestTheLibraryOfCongressTableAgreesWithItself:
    """`metadata.title_search`'s docstring states six percentages and their fractions.

    **The measurement cannot be pinned and the arithmetic can.** Re-taking the numbers
    means asking a national library from the suite, which is a test that fails when that
    library is down. Recomputing a stated percentage from the stated fraction beside it
    needs no network at all, and it is the habit `test_serialisation`'s
    "the number in the docstring is the number it costs" already establishes here.

    **What this catches is the edit that changes one row and not the other**, which is the
    shape that made the sentence above the table wrong twice: a claim written in two places
    and corrected in one.

    **It is written to fail if its own subject is deleted**, because a docstring guard that
    goes vacuous is the recurring defect this repository has recorded twenty times. The
    table's shape is asserted before its contents are: two rows, six columns each, and the
    countries named in the order the prose then reasons about them.
    """

    #: The country columns, in the docstring's own left to right order, which the prose
    #: below the table depends on: it calls the first the only separated result and
    #: compares the fourth and sixth against the second and third.
    COUNTRIES = ("Uruguay", "Spain", "Italy", "Brazil", "Portugal", "Argentina")

    @staticmethod
    def _rows() -> tuple[list[str], list[str], list[str]]:
        """The table's three rows as cell lists: headings, fractions, percentages."""
        doc = metadata.title_search.__doc__ or ""
        lines = [
            [cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in doc.splitlines()
            if line.strip().startswith("|")
        ]
        assert len(lines) == 4, f"expected a four line table, found {len(lines)}"
        return lines[0][1:], lines[2][1:], lines[3][1:]

    def test_the_table_is_still_there_and_still_the_shape_the_prose_reads(self):
        headings, fractions, percentages = self._rows()
        assert tuple(headings) == self.COUNTRIES
        assert len(fractions) == len(percentages) == len(self.COUNTRIES)

    def test_every_percentage_is_the_fraction_beside_it(self):
        _, fractions, percentages = self._rows()
        for country, fraction, stated in zip(
            self.COUNTRIES, fractions, percentages, strict=True
        ):
            held, _, asked = fraction.partition("/")
            shown = float(stated.strip("*").rstrip("%"))
            assert round(100 * int(held) / int(asked), 1) == shown, (
                f"{country}: the docstring says {stated} and {fraction} is "
                f"{100 * int(held) / int(asked):.1f}%"
            )

    def test_uruguay_leads_the_table_it_is_named_for(self):
        """The prose calls it the only separated result, so it had better be the largest."""
        _, fractions, _ = self._rows()
        shares = [int(f.split("/")[0]) / int(f.split("/")[1]) for f in fractions]
        assert shares[0] == max(shares)

    def test_the_tier_line_is_word_for_word_what_was_measured(self):
        """The clause is pinned exactly, because it has been wrong twice and neither
        spelling names a country.

        **Matching country nouns does not see the mistake this guards against.** The
        first version of this test looked for `Spain` and `Portugal` in the line. Both
        times the line was wrong it was wrong **adjectivally**, "Spanish, Portuguese and
        Latin American printings", and `Spain` is not a substring of `Spanish`. Two
        mutations written by a second seat, adding "and Spanish printings" and "and
        Portuguese printings", walked straight past it.

        **The fix is not a longer word list**, which would leave Brazilian, Argentine,
        Argentinian, Italian, Iberian and Latin American behind it: that is the
        enumerating-guard shape this repository has paid for repeatedly. It is to pin the
        clause, so that **any** edit to it fails and whoever makes it re-derives the
        claim, which is what `test_fetch.py` does for the source count. An edit backed by
        a measurement updates one string here; an edit backed by nothing cannot.
        """
        doc = metadata.title_search.__doc__ or ""
        start = doc.index("**Tier two")
        clause = doc[start : doc.index(".", doc.index("ÖNB", start))]
        assert clause == (
            "**Tier two, free, regional:** the BnF for French, the Library of Congress\n"
            "for Uruguayan printings and for anything printed before ISBNs existed, the\n"
            "ÖNB for Austrian imprints, the NLG for Greek publishing"
        ), f"the tier two clause changed and nothing re-derived it:\n{clause!r}"

    #: Which columns each aggregate in the prose sums, by position in `COUNTRIES`.
    #:
    #: Named here rather than spelled inside a test, because the prose reasons about two
    #: groups and a subtraction and all three have to agree with the same table.
    _LATIN_AMERICA = (0, 3, 5)   # Uruguay, Brazil, Argentina
    _THE_TWO_DROPPED = (1, 2)    # Spain, Italy
    _LATIN_AMERICA_WITHOUT_URUGUAY = (3, 5)

    @staticmethod
    def _prose() -> str:
        """The docstring with every run of whitespace collapsed to one space.

        **Matched against this rather than the raw text, because a regex that knows
        where a sentence wraps breaks on any rewording that moves the wrap.** The
        aggregate sentence currently breaks between `+5.3` and `points`, and the first
        version of the test below encoded that position and failed on the unmutated
        docstring.
        """
        return " ".join((metadata.title_search.__doc__ or "").split())

    def _sum(self, fractions: list[str], columns: tuple[int, ...]) -> tuple[int, int]:
        pairs = [
            (int(fractions[i].split("/")[0]), int(fractions[i].split("/")[1]))
            for i in columns
        ]
        return sum(p[0] for p in pairs), sum(p[1] for p in pairs)

    def test_the_aggregate_figures_recompute_from_the_table_too(self):
        """The sibling test pinned three derived figures and left seven, which is the
        defect it exists to describe, one subset across.

        **Measured by a second seat**, seven mutations against the previous version:
        changing `43/142`, `24/96`, `17/95`, `17.9%`, the aggregate `+5.3` and its `-6.5`
        bound all survived, and only the control was caught. Six of seven, every one
        recomputable from the two rows the test already parses.

        **So there is no unguarded figure left in this docstring.** Sixteen in total:
        six table percentages, and **ten derived from them**, being the Uruguay triple, the
        aggregate triple, the two aggregate fractions and the without-Uruguay pair. That is
        the claim, and it is what makes this test worth the ten lines rather than a note
        saying which figures are covered.

        That sentence said "ten in total" over a list summing to sixteen, folding the six
        percentages into a total that excluded them. Ten is the count of the **derived**
        figures alone, which is the number the finding above uses. **A note about a
        miscounted enumeration, miscounting its own.**
        """
        _, fractions, _ = self._rows()
        prose = self._prose()

        region = self._sum(fractions, self._LATIN_AMERICA)
        europe = self._sum(fractions, self._THE_TWO_DROPPED)
        difference, low, high = _newcombe(*region, *europe)
        stated = re.search(
            r"Latin America is (\d+)/(\d+) against Spain and Italy's (\d+)/(\d+), "
            r"\+(\d+\.\d) points, 95% Newcombe (-\d+\.\d) to \+(\d+\.\d)",
            prose,
        )
        assert stated is not None, "the docstring no longer states the aggregate sentence"
        assert (int(stated.group(1)), int(stated.group(2))) == region
        assert (int(stated.group(3)), int(stated.group(4))) == europe
        assert [round(v, 1) for v in (difference, low, high)] == [
            float(g) for g in stated.group(5, 6, 7)
        ]

        rest = self._sum(fractions, self._LATIN_AMERICA_WITHOUT_URUGUAY)
        without = re.search(r"without Uruguay it is (\d+)/(\d+), or (\d+\.\d)%", prose)
        assert without is not None, "the docstring no longer states the without-Uruguay figure"
        assert (int(without.group(1)), int(without.group(2))) == rest
        assert round(100 * rest[0] / rest[1], 1) == float(without.group(3))

    def test_the_three_derived_figures_recompute_from_the_table(self):
        """The percentages were pinned and the numbers drawn from them were not.

        **That is exactly how they went wrong.** The prose stated +28.0 points and a
        Newcombe interval of +9.0 to +44.4, which is `26/50` against `12/50`: the flat
        sample size, from before the table was corrected to the denominators that actually
        answered. The six table percentages were guarded and these three were not, so the
        guard's own coverage had picked the case that was already right.
        """
        _, fractions, _ = self._rows()
        uruguay, spain = (
            (int(f.split("/")[0]), int(f.split("/")[1])) for f in fractions[:2]
        )
        difference, low, high = _newcombe(*uruguay, *spain)
        stated = re.search(
            r"\+(\d+\.\d) points over Spain, 95% Newcombe \+(\d+\.\d) to \+(\d+\.\d)",
            self._prose(),
        )
        assert stated is not None, "the docstring no longer states the three figures"
        assert [round(v, 1) for v in (difference, low, high)] == [
            float(g) for g in stated.groups()
        ], (
            f"the docstring says {stated.groups()} and the table gives "
            f"{difference:.1f}, {low:.1f}, {high:.1f}"
        )


class TestThePlaintextSourcesAreCounted:
    """The documented count of plaintext catalogues is derived, not written down.

    **This exists because the number went stale four times.** Each plaintext
    source that landed left the previous source's prose behind: when the Czech
    national library was added, `docs/legend.md` still said two,
    `docs/security.md` still named two, and a `metadata.py` docstring still said
    "the one catalogue here reached over plaintext HTTP". None of them failed
    anything, because a count in prose does not recount itself.

    So the set is recomputed from the module's own endpoint values and the docs
    are checked against it. A fourth plaintext source fails this test rather than
    quietly making three documents wrong.

    **Two critics broke the first version of this class independently and it is
    worth recording how**, because every hole was in the guard rather than in its
    subject. It keyed on a `_*_URL` name, so a fourth endpoint spelled anything
    else passed. Its mutation test re-spelled the matching rule inline instead of
    calling it, so blanking the real rule left all five tests green. It scanned
    two files when the class docstring names three. And it matched a line at a
    time, so the retired sentence wrapped across two lines went unseen, which is
    the likely shape in a file that wraps prose at ninety five characters.
    """

    #: Number words as the docs spell them. Deliberately not a digit parse: the
    #: docs are prose and spell these out, and a test that accepted either would
    #: pass on a sentence no reviewer would let through.
    WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}

    #: The sentence that went stale, which names no number and so cannot be
    #: caught by counting words.
    RETIRED = "the one catalogue here reached over plaintext"

    #: Every file that states the count or the claim, checked as one list so a
    #: relapse cannot land in a document the tests happen not to read.
    DOCUMENTS = (
        "backend/targets.py",
        "docs/legend.md",
        "docs/security.md",
        "docs/decisions.md",
        "backend/metadata.py",
        "README.md",
    )

    @staticmethod
    def plaintext() -> dict[str, str]:
        """Every endpoint this module reaches without TLS, by constant name.

        **Every module level string starting `http://`, with no filter on the
        name.** The first version required the name to end `_URL`, which made the
        guard agree with a convention rather than with the code: an endpoint
        added as `_NKP_MIRROR_ENDPOINT` passed it, measured. Nothing enforces that
        spelling, so nothing may depend on it.

        The XML namespace URIs are not module level values here, so dropping the
        name filter costs nothing. Should one ever be added, this test fails and
        the fix is to name the exclusion, not to guess at a prefix again.

        **Two sources of endpoints now, and keeping the old one is the point.**
        The addresses became rows, so `targets.SEEDED` is where they are and a
        scan of `metadata`'s module namespace alone would find nothing and report
        zero plaintext sources with every document still saying three. The module
        scan is kept anyway, over the three modules that talk to a catalogue,
        because what it refused is a plaintext endpoint reintroduced as a
        constant beside the rows, and dropping it to follow the data would be a
        guard that got narrower in the round its subject moved.
        """
        found = {
            f"{target.source.value}.base_url": target.base_url
            for target in targets.SEEDED.values()
            if target.base_url.startswith("http://")
        }
        for module in (metadata, targets, google_books):
            found.update(
                {
                    f"{module.__name__}.{name}": value
                    for name, value in vars(module).items()
                    if isinstance(value, str) and value.startswith("http://")
                }
            )
        return found

    @staticmethod
    def mentions_only(text: str, phrase: str) -> bool:
        """Whether every occurrence of `phrase` opens a quotation rather than a claim.

        **The one rule, called by the check and by its own mutation test.** An
        earlier version spelled the regex inline in both places, so blanking the
        real rule left the mutation test passing on its own copy: it validated the
        idiom rather than the subject.

        **It does not pair quotes, and that is the point.** The version before
        this collapsed the whole document to one line and asked whether each
        occurrence fell inside a `"[^"]*"` span. Pairing quotes across a whole
        file is unbounded: `backend/metadata.py` holds 1,901 double quotes at odd
        parity, every string literal is a pair, and the gaps between pairs are
        wide enough to swallow a bare claim. Measured by planting the unquoted
        sentence at ten evenly spaced positions in each of the five documents:
        **6 of 50 went undetected**, five of them in `metadata.py`. Collapsing per
        paragraph instead brings that to 1 of 50. Asking what precedes the phrase
        brings it to **0 of 50**, and needs no pairing at all.

        So: a mention is an occurrence immediately preceded by `"` or a backtick,
        which is what quoting the retired sentence actually looks like. Anything
        else is the document saying it.

        **Whitespace is collapsed per paragraph** so a sentence wrapped across two
        lines is still seen; `docs/decisions.md` wraps prose at about ninety five
        characters and the retired sentence is forty six, so the wrapped form is
        the likely one and a line scoped match never sees it.

        **A quotation the phrase sits in the middle of reads as a claim here.**
        That is a false positive and it is the safe direction: it forces a
        rewording rather than hiding a relapse.
        """
        for paragraph in re.split(r"\n\s*\n", text):
            flat = " ".join(paragraph.split())
            index = flat.find(phrase)
            while index != -1:
                if index == 0 or flat[index - 1] not in '"`':
                    return False
                index = flat.find(phrase, index + 1)
        return True

    def test_the_set_is_the_three_this_repository_has_accepted(self):
        """The guard's own subject, pinned.

        Without this the test passes on an empty set, which is what it would
        compute if every endpoint moved to HTTPS or was renamed.
        """
        assert set(self.plaintext()) == {
            "loc.base_url",
            "nlg.base_url",
            "nkp.base_url",
        }

    def test_the_legend_states_the_current_count(self):
        legend = (BACKEND.parent / "docs" / "legend.md").read_text(encoding="utf-8")
        expected = self.WORDS[len(self.plaintext())]

        assert f"One of the {expected} sources fetched over plaintext HTTP" in legend

    def test_the_security_note_states_the_current_count(self):
        security = (BACKEND.parent / "docs" / "security.md").read_text(encoding="utf-8")
        expected = self.WORDS[len(self.plaintext())]

        assert f"the {expected} catalogues with no TLS endpoint" in security

    def test_no_document_asserts_a_single_plaintext_catalogue(self):
        """The retired sentence may be quoted, and may not be said.

        **This failed on its first run against the entry recording that the
        sentence was wrong.** `docs/decisions.md` quotes it while explaining that
        three catalogues were configured when it still read "one". A plain
        substring check cannot tell that apart from the claim itself.

        The rule is **use against mention**: a document saying the sentence in its
        own voice is a defect, one quoting it as an error is the record of the
        defect, and quotation marks separate them.
        """
        for relative in self.DOCUMENTS:
            text = (BACKEND.parent / relative).read_text(encoding="utf-8")

            assert self.mentions_only(text, self.RETIRED), (
                f"{relative} states the retired sentence rather than quoting it"
            )

    def test_the_use_against_mention_rule_still_refuses_the_bare_claim(self):
        """Or the test above passes on a document that does assert it.

        **Calls `mentions_only` rather than re-spelling it**, which is the whole
        point: the first version matched its own inline copy of the regex, so
        blanking the real rule left this green. A critic demonstrated that by
        replacing the pattern with `.*` and watching all five tests pass.

        The mutation that matters is not deleting the sentence, it is writing it
        unquoted, and writing it unquoted **across a line break**, which is how it
        would actually appear in a wrapped document.
        """
        stated = f"It is {self.RETIRED} HTTP, and that is fine."
        wrapped = "It is the one catalogue here reached over\nplaintext HTTP, and that is fine."
        mentioned = f'It said "{self.RETIRED} HTTP" and was wrong.'
        absent = "Nothing here says anything about that at all."

        assert not self.mentions_only(stated, self.RETIRED)
        assert not self.mentions_only(wrapped, self.RETIRED)
        assert self.mentions_only(mentioned, self.RETIRED)
        assert self.mentions_only(absent, self.RETIRED)


class TestACatalogueIsNotAskedAboutAForeignIsbn:
    """`sources.SERVES_GROUPS` reaching `lookup`, from the call site rather than
    from the plan.

    **The plan level tests cannot see any of this**, which is why the class
    exists. `Plan.lookup_together` takes no registration group, so an assertion
    that the tier is unfiltered is true by construction there and pins nothing;
    the thing that could go wrong is `lookup` deciding to filter the tier too,
    and only a call site test sees that.
    """

    @staticmethod
    def _plan(*names: str) -> sources.Plan:
        """A plan holding exactly these sources, **in the order given here**.

        The named ones lead, then every other source disabled. Ordering by
        `DEFAULT_ORDER` instead was the first version and it silently ignored the
        argument order: `_plan("oenb", "nlg", "dnb")` came back as the default
        order filtered, so a test meaning to put two restricted sources in the
        leading tier got the DNB in it and passed on a different plan than the
        one it named.
        """
        plan = sources.parse(
            {
                "sources": [{"source": name, "enabled": True} for name in names]
                + [
                    {"source": source.value, "enabled": False}
                    for source in sources.DEFAULT_ORDER
                    if source.value not in names
                ]
            }
        )
        assert [source.value for source in plan.asked] == list(names)
        return plan

    @staticmethod
    def _recording(asked: list[str]):
        """A `metadata._lookup_one` table where nothing answers and everything is recorded.

        Nothing answers on purpose: the chain then runs to the end and the list
        is every source the ISBN actually reached, rather than every source
        ahead of the first hit.
        """

        def make(name: CatalogueSource):
            async def answer(isbn: str, api_key: str) -> metadata.Lookup:
                asked.append(name.value)
                return metadata.Lookup(metadata.Outcome.NOT_FOUND)

            return answer

        return {name: make(name) for name in sources.LOOKUP_SOURCES}

    @pytest.fixture
    def asked(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        seen: list[str] = []
        patch_lookup_adapters(monkeypatch, self._recording(seen))
        metadata.clear_cache()
        return seen

    @pytest.mark.asyncio
    async def test_a_national_catalogue_in_the_tail_is_skipped_for_a_foreign_isbn(
        self, asked: list[str]
    ):
        await metadata.lookup(
            ENGLISH_ISBN, plan=self._plan("dnb", "k10plus", "nlg", "oenb")
        )
        assert asked == ["dnb", "k10plus"]

    @pytest.mark.asyncio
    async def test_the_same_plan_asks_it_about_a_book_from_its_own_group(
        self, asked: list[str]
    ):
        """The other half, and without it the test above passes on a `lookup`
        that never reaches the tail at all."""
        await metadata.lookup(
            GREEK_ISBN, plan=self._plan("dnb", "k10plus", "nlg", "oenb")
        )
        assert asked == ["dnb", "k10plus", "nlg"]

    @pytest.mark.asyncio
    async def test_the_leading_tier_is_asked_whatever_the_isbn(
        self, asked: list[str]
    ):
        """**The tier is gathered, so it costs its slowest member and not their
        sum**, measured in `sources.DEFAULT_ORDER` at 0.389s for the German pair
        against 0.388s for K10plus alone. There is no round trip to save, and
        filtering it would resize per ISBN the one cost bound `ALWAYS_ASKED`
        promises a household is fixed.

        Both restricted sources lead here and the ISBN is in neither remit, so a
        `lookup` that filtered the tier would ask nobody at all. The DNB behind
        them is unrestricted and is the arm that keeps this from passing on a
        `lookup` that never reaches the tail.
        """
        plan = self._plan("oenb", "nlg", "dnb")
        assert plan.lookup_together == (CatalogueSource.OENB, CatalogueSource.NLG)
        await metadata.lookup(ENGLISH_ISBN, plan=plan)
        assert sorted(asked[: sources.ALWAYS_ASKED]) == ["nlg", "oenb"]
        assert asked[sources.ALWAYS_ASKED :] == ["dnb"]

    @pytest.mark.asyncio
    async def test_an_isbn_with_no_decodable_group_asks_everyone(
        self, asked: list[str]
    ):
        """**Fail open.** `isbn.registration_group` returns None for a group the
        published ranges do not cover, and the answer to no claim is to ask
        everyone, because the alternative is a catalogue quietly not asked about
        a book it holds.
        """
        assert registration_group("9789999912341") is None
        await metadata.lookup(
            "9789999912341", plan=self._plan("dnb", "k10plus", "nlg", "oenb")
        )
        assert asked == ["dnb", "k10plus", "nlg", "oenb"]

    @pytest.mark.asyncio
    async def test_a_book_no_enabled_catalogue_serves_is_not_found_rather_than_unasked(
        self, asked: list[str]
    ):
        """**`NO_SOURCES` is a fact about the library and this is a fact about
        the book.** Its 409 tells a household it has switched every catalogue off
        and to go and switch one back on, which is the wrong sentence entirely
        for a full list that simply does not reach Spanish publishing. The
        outcome is read off `Plan.lookup_chain` rather than off `attempts` for
        exactly this, since the group rule made an empty `attempts` mean two
        different things.
        """
        # **Checked rather than assumed, because it was wrong.** The first
        # spelling of this ISBN failed its own checksum, so `lookup` returned
        # before asking anybody, `asked` was empty for that reason, and the
        # outcome assertion below passed on a lookup that never happened.
        spanish = "9788420471839"
        assert registration_group(spanish) == "978-84"
        result = await metadata.lookup(spanish, plan=self._plan("nlg", "oenb"))
        assert asked == ["nlg", "oenb"]
        assert result.outcome is metadata.Outcome.NOT_FOUND

    @pytest.mark.asyncio
    async def test_a_library_with_every_catalogue_off_still_says_nothing_was_asked(
        self, asked: list[str]
    ):
        """The arm that keeps the test above from deleting `NO_SOURCES`."""
        result = await metadata.lookup(ENGLISH_ISBN, plan=self._plan())
        assert asked == []
        assert result.outcome is metadata.Outcome.NO_SOURCES

    @pytest.mark.asyncio
    async def test_a_metered_source_with_a_remit_is_still_not_no_sources(
        self, asked: list[str], monkeypatch: pytest.MonkeyPatch
    ):
        """**The one case where reading the chain and reading `attempts` differ,
        made reachable.**

        On today's roster they agree: the leading tier is never filtered and
        holds a non metered chain member whenever one exists, and no metered
        source has a remit, so an empty `attempts` implies an empty chain. That
        makes `lookup`'s choice between them untestable and therefore
        unenforced, which is how a defensive branch comes to be deleted by
        somebody simplifying.

        One row makes them disagree. A metered source is barred from the tier
        whatever its position, so with it alone the tier is empty; give it a
        remit and a foreign ISBN empties the tail too, and `attempts` is empty
        while the library has a catalogue switched on. That is a fact about the
        book, and a 409 saying "switch a catalogue back on" would be the mistake
        `NO_SOURCES` exists to fix, pointed the other way.
        """
        monkeypatch.setattr(
            sources,
            "SERVES_GROUPS",
            {**sources.SERVES_GROUPS, CatalogueSource.GOOGLE_BOOKS: frozenset({"978-3"})},
        )
        plan = self._plan("google_books")
        assert plan.lookup_together == ()
        assert plan.lookup_chain == (CatalogueSource.GOOGLE_BOOKS,)
        result = await metadata.lookup("9788420471839", "a-key", plan=plan)
        assert asked == []
        assert result.outcome is metadata.Outcome.NOT_FOUND


class TestSearchingHarder:
    """The second action asks the slow catalogues, under its own deadline.

    **One spy reads both halves of the pair**, because the failure worth
    catching is the mismatched combination rather than either half: the long
    roster under the short deadline asks the slow catalogues and then cancels
    every one of them, which spends the requests and returns the rows the
    default search would have returned, with nothing in the answer to say so.

    `sources.SLOW_SEARCHES` is empty on the shipped roster, so every test here
    injects one. The ÖNB is what is injected, being the source the deadline is
    likeliest to drop today.
    """

    @pytest.fixture
    def fan_out(self, monkeypatch):
        """Records which catalogues were asked and under what deadline."""
        asked: list[CatalogueSource] = []
        deadlines: list[float] = []

        def recorder(name: CatalogueSource):
            async def adapter(query: str, limit: int, *rest: str) -> list[Record]:
                asked.append(name)
                return []

            return adapter

        # One door now, so the recorder replaces it and reads the source off
        # the row rather than off a table key. Same question as before: which
        # catalogues were asked, and under which deadline.
        async def door(target, query: str, limit: int, api_key: str) -> list[Record]:
            return await recorder(target.source)(query, limit)

        monkeypatch.setattr(metadata, "_search_one", door)

        real = metadata._within_deadline

        async def spy(searches, deadline):
            deadlines.append(deadline)
            return await real(searches, deadline)

        monkeypatch.setattr(metadata, "_within_deadline", spy)
        return asked, deadlines

    @pytest.fixture
    def slow_oenb(self, monkeypatch):
        monkeypatch.setattr(
            sources, "SLOW_SEARCHES", frozenset({CatalogueSource.OENB})
        )

    @pytest.mark.asyncio
    async def test_the_default_search_asks_the_fast_roster_on_the_short_deadline(
        self, fan_out, slow_oenb
    ):
        asked, deadlines = fan_out
        await metadata.search("moby dick", "key", plan=sources.DEFAULT_PLAN)

        assert CatalogueSource.OENB not in asked
        assert set(asked) == set(sources.DEFAULT_PLAN.searched)
        assert deadlines == [metadata.SEARCH_DEADLINE_SECONDS]

    @pytest.mark.asyncio
    async def test_searching_harder_asks_the_slow_one_on_the_long_deadline(
        self, fan_out, slow_oenb
    ):
        asked, deadlines = fan_out
        await metadata.search(
            "moby dick", "key", plan=sources.DEFAULT_PLAN, harder=True
        )

        assert CatalogueSource.OENB in asked
        assert set(asked) == set(sources.DEFAULT_PLAN.searched_harder)
        assert deadlines == [metadata.SEARCH_HARDER_DEADLINE_SECONDS]

    @pytest.mark.asyncio
    async def test_the_two_deadlines_are_not_the_same_number(self):
        """Or every test above passes on a build where the feature does nothing."""
        assert (
            metadata.SEARCH_HARDER_DEADLINE_SECONDS
            > metadata.SEARCH_DEADLINE_SECONDS
        )

    @pytest.mark.asyncio
    async def test_asking_harder_with_no_slow_catalogue_keeps_the_short_deadline(
        self, fan_out
    ):
        """The rosters are equal, so the longer wait would buy nothing.

        `harder` is a query parameter and not a button: nothing obliges a caller
        to have pressed anything, and three times the wall clock for the
        identical fan out is a cost with no benefit on every install that has no
        slow catalogue, which is every install today.
        """
        asked, deadlines = fan_out
        await metadata.search(
            "moby dick", "key", plan=sources.DEFAULT_PLAN, harder=True
        )

        assert set(asked) == set(sources.DEFAULT_PLAN.searched)
        assert deadlines == [metadata.SEARCH_DEADLINE_SECONDS]

    @pytest.mark.asyncio
    async def test_a_second_harder_search_runs_the_ordinary_one_instead(
        self, fan_out, slow_oenb, monkeypatch
    ):
        """The slot is never waited for. See `metadata._HARDER_AT_ONCE`.

        A queue here would hold a database connection for the length of the
        wait, so the second caller gets a true fast answer rather than a slow
        turn in a line.
        """
        asked, deadlines = fan_out
        released = asyncio.Event()
        first_is_in = asyncio.Event()
        real = metadata._within_deadline

        async def hold(searches, deadline):
            deadlines.append(deadline)
            first_is_in.set()
            await released.wait()
            return await real(searches, deadline)

        monkeypatch.setattr(metadata, "_within_deadline", hold)
        holding = asyncio.ensure_future(
            metadata.search("moby dick", "key", plan=sources.DEFAULT_PLAN, harder=True)
        )
        await first_is_in.wait()

        monkeypatch.setattr(metadata, "_within_deadline", real)
        second = asyncio.ensure_future(
            metadata.search("moby dick", "key", plan=sources.DEFAULT_PLAN, harder=True)
        )
        await second

        assert CatalogueSource.OENB not in asked
        assert deadlines[-1] == metadata.SEARCH_DEADLINE_SECONDS

        released.set()
        await holding

    @pytest.mark.asyncio
    async def test_the_slot_is_given_back_when_the_fan_out_raises(
        self, fan_out, slow_oenb, monkeypatch
    ):
        """A slot leaked once is a slot leaked for the life of the process.

        Nothing below `_within_deadline` raises today: every adapter swallows
        its own failures. That is the reason to pin it rather than not to, since
        a `finally` nothing exercises is a `finally` a later edit can drop.
        """

        async def boom(searches, deadline):
            for coroutine in searches:
                coroutine.close()
            raise RuntimeError("the fan out fell over")

        monkeypatch.setattr(metadata, "_within_deadline", boom)
        with pytest.raises(RuntimeError):
            await metadata.search(
                "moby dick", "key", plan=sources.DEFAULT_PLAN, harder=True
            )

        assert not metadata._HARDER_AT_ONCE.locked()


class TestGoogleIdentifiersAreParsedRatherThanTrusted:
    """`industryIdentifiers` is somebody else's JSON and nothing validated it.

    **A diagonal over the shapes, not one example**, because the two failures
    this family produces are different failures and a fixture for either alone
    would have looked like the whole thing. A 40 character string builds a
    `BookLookup` and puts a 40 digit ISBN in front of a member; a non string
    identifier reaches `BookLookup.isbn`, which is `str`, and 500s a scan.

    The second is also why the obvious one line fix is wrong: `parse_isbn` calls
    string methods, so parsing the int raises `TypeError` out of an adapter
    whose caller catches `httpx.HTTPError` and `ValueError` only. Every arm here
    fails against that fix as well as against the original.
    """

    #: Everything the field can hold that is not an ISBN. The two non string
    #: entries are the ones a bare parse turns into a different 500.
    NOT_AN_ISBN = ["9" * 40, "12345", 123, 9.5, True, ["9783596294336"], {}, "", None]

    def _fields(self, identifier: object) -> dict:
        volume = {
            "id": "x",
            "volumeInfo": {
                "title": "T",
                "industryIdentifiers": [
                    {"type": "ISBN_13", "identifier": identifier}
                ],
            },
        }
        return google_books._volume_to_fields(volume)

    @pytest.mark.parametrize("identifier", NOT_AN_ISBN)
    def test_a_lookup_falls_back_to_the_isbn_that_was_asked_for(self, identifier):
        record = metadata._google_record(self._fields(identifier), "9783596294336")

        assert record.isbn == "9783596294336"

    @pytest.mark.parametrize("identifier", NOT_AN_ISBN)
    def test_the_response_schema_can_still_be_built(self, identifier):
        """The 500 this closes. `lookup_isbn` catches no `ValidationError`."""
        assert BookLookup(**metadata._google_record(
            self._fields(identifier), "9783596294336"
        ).as_lookup())

    @pytest.mark.parametrize("identifier", NOT_AN_ISBN)
    def test_a_search_row_carries_no_isbn_rather_than_a_bogus_one(self, identifier):
        """A search row has no canonical ISBN to fall back to, so it carries none.

        `_google_search` calls `_google_record` with no second argument, which
        is the path that used to publish the malformed identifier as `isbn13`.
        """
        assert metadata._google_record(self._fields(identifier)).isbn is None

    def test_a_real_identifier_is_kept_and_canonicalised(self):
        """The other end of the diagonal, or every arm above passes vacuously.

        Google prints the hyphenated form, so this also pins that the fallback
        is not silently swallowing every identifier Google sends.
        """
        record = metadata._google_record(self._fields("978-3-16-148410-0"))

        assert record.isbn == "9783161484100"
