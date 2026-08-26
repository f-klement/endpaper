# Legend

**The library science vocabulary this codebase borrows.** Endpaper talks to national
library catalogues, and their terms leak into `metadata.py`, `ddc.py`, the
`classifications` table and half of `decisions.md`. This page is what those mean here.
It defines nothing endpaper invented: for that, read [data-model.md](data-model.md).

## The catalogues

Four of the six metadata sources are national or union library catalogues. The other two,
Open Library and Google Books, are ordinary web APIs and need no glossary.

| Term | What it is |
|---|---|
| **DNB** | Deutsche Nationalbibliothek. Germany's legal deposit library, so it holds essentially everything published there. It is the reason a 978-3 ISBN can be catalogued at all: for the two that prompted this work, Open Library answered 404 and the DNB returned a full record for each. |
| **K10plus** | The union catalogue of the GBV and SWB library networks, one shared database behind a large share of German academic libraries. Strong on European publishing and on printings older than the ISBN. |
| **BnF** | Bibliothèque nationale de France, the French national library. |
| **LoC** | Library of Congress, the de facto national library of the United States. The one source still fetched over plaintext HTTP, which `decisions.md` records as accepted rather than fixed. |

## Protocols and record formats

| Term | What it is |
|---|---|
| **SRU** | Search/Retrieve via URL. The standard HTTP query protocol for library catalogues: send a query and a `recordSchema`, receive XML. All four catalogues above speak it. |
| **CQL** | The query language SRU carries. Its index names are catalogue specific, which is why the code holds `num=` (the DNB's identifier index, which matches an identifier anywhere in a record), `WOE=` (the DNB's all words index) and `pica.all=` (K10plus's catch all, named for PICA, the cataloguing system behind those networks). |
| **MARC**, **MARC21** | MAchine Readable Cataloging, the dominant library record format since the 1960s. A record is numbered **fields**, each holding lettered **subfields**: `245 $a` is the title and `$b` the subtitle. MARC21 is the international flavour. |
| **MARCXML** | MARC serialised as XML rather than its original binary form. Requested as `MARC21-xml` from the DNB and `marcxml` from K10plus, because catalogues disagree about the spelling. |
| **Dublin Core**, **`oai_dc`** | A deliberately minimal fifteen element set: title, creator, subject, date and so on. Universally offered and easy to parse, but it carries **no identifiers**, which is the whole reason the DNB path moved to MARC. |
| **MODS** | Metadata Object Description Schema, an XML format from the Library of Congress sitting between Dublin Core and MARC in richness. The LoC path parses it. |

## Classification and authority

**The distinction that matters here.** A **classification** says where a book sits in a
scheme, which is a statement about the book. An **authority file** gives a person, place
or subject a stable identifier, which is a statement about a thing the book mentions.
Endpaper stores the first in `classifications` and, as of round 2, deliberately does not
store the second for authors. See [data-model.md](data-model.md).

| Term | What it is |
|---|---|
| **DDC** | Dewey Decimal Classification. Numeric and hierarchical: ten classes, one hundred divisions, one thousand sections. `004` is computing. Those hundred divisions are what `backend/ddc.py` maps to this library's own tags, and the mapping is on the **number** precisely because the caption is language dependent. |
| **LCC** | Library of Congress Classification. The alphanumeric alternative to Dewey, common in American academic libraries. |
| **LCSH** | Library of Congress Subject Headings. Not a classification: a controlled vocabulary of subject *phrases*, with subdivisions joined by two hyphens (`Computer software -- Development`). Read here out of the `<subject authority="lcsh">` elements in the MODS record the search path already fetches, not from `id.loc.gov`, which this app does not call. The record carries no identifier for a heading, so the phrase itself is the access point. |
| **GND** | Gemeinsame Normdatei, the shared authority file of the German speaking library world, covering people, organisations, subjects, places and works. Every entry carries an identifier. |
| **VIAF** | Virtual International Authority File. Clusters authority records for the *same person* across national libraries, so one author's German, American and French records share a cluster identifier. |
| **Sachgruppe** | Not an acronym. The DNB's own coarse subject group scheme, derived from Dewey, assigned to everything it receives. |

## Codes that appear inside records

| Code | Meaning |
|---|---|
| `(DE-588)` | The MARC organisation code for the GND. It labels a number as a GND number, which is why the table stores the bare number and keeps the scheme in its own column. |
| `(DE-101)` | The DNB's own organisation code. One authority record commonly carries this and `(DE-588)` for the same entity. |
| `$0` | Authority record control number: the subfield where an identifier such as a GND number lives. |
| `$2` | Names the vocabulary a heading came from. `gnd` and `gnd-content` are GND; `gatbeg` is not, which is why the value is read rather than assumed. |
| `$4` | A relator code, saying what a name did. `pbl` is publisher, which is how four corporate names were once read as authors. |

## The MARC fields this code reads

| Field | Carries |
|---|---|
| `082` | The Dewey number. The **only** field handed to the Dewey parser, so a subject heading beginning with three digits cannot be mistaken for one. |
| `100` | Main entry, personal name: the author, with the author's GND in `$0`. |
| `245` | Title statement: `$a` title, `$b` subtitle, already separated where Dublin Core gave one string. |
| `300` | Physical description. Its extent is what distinguishes a printed book from an `Online-Ressource`. |
| `600` | A person as a subject, as opposed to `100`, a person as the author. |
| `650` | Topical subject. |
| `651` | Geographic subject. |
| `655` | Genre or form, which is what a thing *is* rather than what it is *about*. |
| `689` | The German networks' subject chain, restating headings as an ordered sequence. |
| `710` | Corporate name added entry. |
| `776` | Links a printed edition to its online counterpart. |

## Library systems

| Term | What it is |
|---|---|
| **ILS** | Integrated Library System: the software a library runs its circulation, cataloguing and catalogue on. |
| **Koha** | Not an acronym, a Maori word. The long established open source ILS, read here as a reference for the public library mode design. What its licence does and does not permit is settled in `archive/implementation_plan.md` under 30e and 30h. |
| **OPAC** | Online Public Access Catalogue: the public facing search interface of an ILS, as opposed to the staff interface behind it. |
| **Patron** | The library word for a borrower. Not a customer: a library has no customers, and the German is Benutzer:in, registering one a Neuanmeldung. Koha's interface says patron while its schema says `borrowers`. |

## One that is not library science

**NFC** and **NFD** are Unicode normalisation forms. NFC composes an accented letter into a
single code point; NFD splits it into a base letter and a combining accent. They compare
unequal as strings. This belongs here because the DNB serves **NFD in MARC where its
Dublin Core was NFC**, measured at 83 of 85 records, so the switch changed the bytes of
almost every German title and author in the catalogue.
