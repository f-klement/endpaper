# Legend

**The library science vocabulary this codebase borrows.** Endpaper talks to national
library catalogues, and their terms leak into `metadata.py`, `ddc.py`, the
`classifications` table and half of `decisions.md`. This page is what those mean here.
It defines nothing endpaper invented: for that, read [data-model.md](data-model.md).

## The catalogues

Eighteen of the twenty metadata sources are national or union library catalogues. The other two,
Open Library and Google Books, are ordinary web APIs and need no glossary.

| Term | What it is |
|---|---|
| **DNB** | Deutsche Nationalbibliothek. Germany's legal deposit library, so it holds essentially everything published there. It is the reason a 978-3 ISBN can be catalogued at all: for the two that prompted this work, Open Library answered 404 and the DNB returned a full record for each. |
| **K10plus** | The union catalogue of the GBV and SWB library networks, one shared database behind a large share of German academic libraries. Strong on European publishing and on printings older than the ISBN. |
| **BnF** | Bibliothèque nationale de France, the French national library. |
| **LoC** | Library of Congress, the de facto national library of the United States. One of the eight sources reached without TLS, which `decisions.md` records as accepted rather than fixed. |
| **ÖNB** | Österreichische Nationalbibliothek, Austria's national library. In the chain for Austrian imprints the German catalogues hold as cross references or not at all. Austria has no registration group of its own, so its remit is `978-3`, shared with Germany and Switzerland. |
| **NLG** | The National Library of Greece, Greece's legal deposit library. One of the plaintext sources: its catalogue answers on port 210 and offers no TLS. Asked only about Greek publishing, `978-960` and `978-618`. |
| **BNE** | Biblioteca Nacional de España, Spain's legal deposit library. Reached over Alma's SRU on its OPAC hostname, which is why an earlier survey recorded it as closed: its Z39.50 port authenticates and its catalogue does not. Asked about an ISBN and never about a title. It declares no registration group remit, because it alone answers for books outside `978-84`: Spanish language publishing from Latin America reaches this catalogue and no other in the chain. |
| **NKP** | Národní knihovna České republiky, the Czech national library. Asked about an ISBN and never about a title: its server renders one populated record per response whatever page size is asked for, so a search for ten candidates would be ten requests. Plaintext on port 9991. |
| **BNA** | Biblioteca Nacional Argentina, Argentina's national library. The Czech catalogue's profile at a different address, down to answering one populated record per response, so it is asked about an ISBN and never about a title. One of the two sources whose request carries a login: the library publishes a username and password on its own page for librarians, this build ships that pair, and a library with an account of its own enters it under Settings and is sent that instead. Plaintext on port 9991, which is what makes that login the sharpest case of the row above. |
| **BNU** | Biblioteca Nacional de Uruguay, Uruguay's national library. The BNA's profile at a different address, login included: the library publishes one and this build ships it. Asked about an ISBN and never about a title, and only about Uruguayan publishing, `978-9974`, which is all it answered when the whole sample was put to it. Plaintext on port 9992. |
| **BN_PL** | Biblioteka Narodowa, Poland's national library. Reached over Alma's SRU, the BNE's profile at another tenant. Asked about an ISBN and never about a title, and only about Polish publishing, `978-83`: every book it answered outside that group when the whole sample was put to it is held by another catalogue in the chain. |
| **LIBRIS** | The Swedish union catalogue, run by the National Library of Sweden: one shared database behind Swedish research and public libraries, so it holds foreign editions as well as Swedish publishing. Reached over SRU on its own server. Asked about an ISBN and never about a title, and about every ISBN: it is the only catalogue in the chain holding one of the sample's Italian books. |
| **KB_DK** | Det Kgl. Bibliotek, the Royal Danish Library. Reached over Alma's SRU, the BNE's profile at another tenant. Asked about an ISBN and never about a title, and only about Danish publishing, `978-87`: every book it answered outside that group when the whole sample was put to it is held by a catalogue still asked about it, BIBSYS for the one nothing older holds. |
| **BIBSYS** | The Norwegian union catalogue, the shared Alma network zone behind Norway's research and public libraries, which the National Library of Norway's records join. Reached over Alma's SRU. Asked about an ISBN and never about a title, and about every ISBN: with the Royal Danish Library asked only about Danish books, it is the one catalogue in the chain still asked about a Brazilian book of the sample that the two of them alone hold. |
| **Melinda** | The Finnish union catalogue, run by the National Library of Finland: one shared database behind Finnish research and public libraries, the national bibliography's records among them. Reached over SRU on its own server. Asked about an ISBN and never about a title, and about every ISBN: it is the only catalogue in the chain holding one of the sample's Greek books. |
| **SBN** | Servizio Bibliotecario Nazionale, Italy's national union catalogue, run by the ICCU. Reached over Z39.50, which keeps its records in UNIMARC and renders a MARC21 view when asked, the view this build asks for. Asked about an ISBN and never about a title, and only about Italian publishing, `978-88`. It answers more of the sample than the DNB does and is still not asked on every lookup: most of what it adds to the leading pair is Italian. |
| **PORBASE** | The Portuguese national union catalogue, run by the Biblioteca Nacional de Portugal. Reached over Z39.50 and answers only in UNIMARC, which is why this build reads that format. Asked about an ISBN and never about a title, and only about Portuguese publishing, `978-972` and `978-989`. The slowest catalogue in the chain, about a second and a half a lookup. |
| **OSZK** | Országos Széchényi Könyvtár, the National Széchényi Library, Hungary's national library. Reached over Z39.50. Asked about an ISBN and never about a title, and only about Hungarian publishing, `978-963` and `978-615`. It has refused about one lookup in eight with a temporary error; such a search is asked again, at most twice, and only a third refusal reads as the catalogue being unavailable for that book rather than as not holding it. |

## Inside an ISBN

| Term | What it is |
|---|---|
| **Registration group** | The part of an ISBN that says which national or language agency issued it: `978-3` is German language publishing, `978-80` Czech, `978-960` and `978-618` both Greek. It is **variable length**, one to five digits, and the assignments are a published list, ISBN International's RangeMessage. `978-6` is not a group, which is the trap: Greek `978-618` and Brazilian `978-65` both begin with a digit that is not itself one. `backend/isbn.py` decodes it and `backend/sources.py` uses it to decide which catalogues are asked about a book. **`978` and `979` are separate assignment spaces**: Italy is `978-88` and `979-12`, and a catalogue's remit listing only `978` groups is silent about `979` rather than negative about it. |
| **Bookland** | The EAN prefix that marks a barcode as a book rather than a food packet: `978`, and `979` for the range added when `978` began to run out. A `979` ISBN has no ten digit form, which is the reason it exists. |

## Protocols and record formats

| Term | What it is |
|---|---|
| **SRU** | Search/Retrieve via URL. The standard HTTP query protocol for library catalogues: send a query and a `recordSchema`, receive XML. Fifteen of the eighteen catalogues above speak it, the three asked over Z39.50 being the others, though the NKP, the BNA and the BNU take their queries in PQF rather than CQL. |
| **Z39.50** | The binary library protocol SRU was designed to replace, still the only door some national catalogues open. `backend/z3950.py` speaks it through YAZ; the SBN, PORBASE and the OSZK are asked over it, a lookup that misses asking once more with the ten digit ISBN, and a search refused with a temporary error being asked again, at most twice. |
| **PQF** | Prefix Query Format, YAZ's textual form of a Z39.50 query: `@attr 1=7 "9788025712948"` is "the ISBN index equals this". The three Z39.50 catalogues are asked in it, and the NKP, the BNA and the BNU take it over SRU and refuse CQL, so their terms are quoted by `z3950.pqf_term`, which is PQF's own escaping rule and deliberately not the CQL sanitiser. |
| **CQL** | The query language SRU carries. Its index names are catalogue specific, which is why the code holds `num=` (the DNB's identifier index, which matches an identifier anywhere in a record), `WOE=` (the DNB's all words index) and `pica.all=` (K10plus's catch all, named for PICA, the cataloguing system behind those networks). |
| **MARC**, **MARC21** | MAchine Readable Cataloging, the dominant library record format since the 1960s. A record is numbered **fields**, each holding lettered **subfields**: `245 $a` is the title and `$b` the subtitle. MARC21 is the Anglo-American branch, the harmonisation of the American and Canadian formats, and it is what every catalogue this build reads sends but PORBASE. It is not the only branch: see UNIMARC below. |
| **UNIMARC** | The other MARC family, created by IFLA so national formats could be exchanged through one intermediary, and native to the Romance and Mediterranean national libraries. Same shape as MARC21, different numbers: the title is `200` rather than `245`, the author `700` rather than `100`, the publisher `210` rather than `260`, Dewey `676` rather than `082`. Two differences are not renumbering. It records a contributor's **role in the tag**, 701 for alternate and 702 for secondary responsibility, where MARC21 puts it in `$4` of a single `700`. And its relator codes are numeric, `070` for author, where MARC21's are letters. PORBASE answers only in it, so this build reads it by mapping each record onto MARC21 along the crosswalk below and handing the result to the MARC21 readers. |
| **Crosswalk** | A published field by field table for converting one record format into another. The Library of Congress issues the UNIMARC to MARC 21 one, which is why a UNIMARC reader here would be a transformation onto the MARC21 readers rather than a second parser. What a crosswalk maps is **fields**; where a subject's vocabulary is declared is an indicator question, and may not be in the table. |
| **MARCXML** | MARC serialised as XML rather than its original binary form. Requested as `MARC21-xml` from the DNB and `marcxml` from K10plus, because catalogues disagree about the spelling. |
| **Dublin Core**, **`oai_dc`** | A deliberately minimal fifteen element set: title, creator, subject, date and so on. Universally offered and easy to parse, but it carries **no identifiers**, which is the whole reason the DNB path moved to MARC. |
| **MODS** | Metadata Object Description Schema, an XML format from the Library of Congress sitting between Dublin Core and MARC in richness. The LoC path parses it. |

## Classification and authority

**The distinction that matters here.** A **classification** says where a book sits in a
scheme, which is a statement about the book. An **authority file** gives a person, place
or subject a stable identifier, which is a statement about a thing the book mentions.
Endpaper stores the first in `classifications` and the second, for authors, in
`author_identifiers`. See [data-model.md](data-model.md).

**That sentence used to end "and, as of round 2, deliberately does not store the second
for authors", and it stopped being true on 2026-08-28** when confirming a GND number began
keeping the record's cross references. It is corrected rather than deleted because the
distinction above is what makes the two tables two tables: the same GND number can be a
subject heading in one and a person in the other, and they are not the same claim.

| Term | What it is |
|---|---|
| **DDC** | Dewey Decimal Classification. Numeric and hierarchical: ten classes, one hundred divisions, one thousand sections. `004` is computing. Those hundred divisions are what `backend/ddc.py` maps to this library's own tags, and the mapping is on the **number** precisely because the caption is language dependent. |
| **LCC** | Library of Congress Classification. The alphanumeric alternative to Dewey, common in American academic libraries. |
| **LCSH** | Library of Congress Subject Headings. Not a classification: a controlled vocabulary of subject *phrases*, with subdivisions joined by two hyphens (`Computer software -- Development`). Read here out of the `<subject authority="lcsh">` elements in the MODS record the search path already fetches, not from `id.loc.gov`, which this app does not call. The record carries no identifier for a heading, so the phrase itself is the access point. |
| **GND** | Gemeinsame Normdatei, the shared authority file of the German speaking library world, covering people, organisations, subjects, places and works. Every entry carries an identifier. |
| **VIAF** | Virtual International Authority File. Clusters authority records for the *same person* across national libraries, so one author's German, American and French records share a cluster identifier. **A cluster id is a discovery route and not an identity here**: clusters split and merge, so what a cluster is read for is the national numbers it lists. |
| **ISNI** | International Standard Name Identifier, ISO 27729. Sixteen characters, language neutral, and scoped to a **public identity** rather than to a record, which is what makes it the spine: it says two spellings are one person where a cluster id only says two records were grouped. |
| **LCNAF** | Library of Congress Name Authority File. The people half of `id.loc.gov`, which also serves a subject file under the same host and a near identical URL shape. |
| **BLBNB**, **ARBABN**, **BNE**, **PTBNP**, **ICCU**, **BNCHL** | The national authority files of Brazil, Argentina, Spain, Portugal, Italy and Chile, spelled as VIAF spells them in a cluster's source list. Endpaper **stores** these and cannot look one up: two of the six refuse every request and the rest speak Z39.50, which this app asks catalogues over and no authority file. |
| **Sachgruppe** | Not an acronym. The DNB's own coarse subject group scheme, derived from Dewey, assigned to everything it receives. |

## Codes that appear inside records

| Code | Meaning |
|---|---|
| `(DE-588)` | The MARC organisation code for the GND. It labels a number as a GND number, which is why the table stores the bare number and keeps the scheme in its own column. |
| `(DE-101)` | The DNB's own organisation code. One authority record commonly carries this and `(DE-588)` for the same entity. |
| `$0` | Authority record control number: the subfield where an identifier such as a GND number lives. |
| `$2` | Names the vocabulary a heading came from. `gnd` and `gnd-content` are GND; `gatbeg` is not, which is why the value is read rather than assumed. It is also what says a heading is a content type or a carrier rather than a subject: see `classifications.kind`. |
| `$4` | A relator code, saying what a name did. `pbl` is publisher, which is how four corporate names were once read as authors. |

## The MARC fields this code reads

| Field | Carries |
|---|---|
| `082` | The Dewey number. The **only** field handed to the Dewey parser, so a subject heading beginning with three digits cannot be mistaken for one. |
| `100` | Main entry, personal name: the author, with the author's GND in `$0`. |
| `245` | Title statement: `$a` title, `$b` subtitle, already separated where Dublin Core gave one string. |
| `300` | Physical description. Its extent used to be what distinguished a printed book from an `Online-Ressource`, which only worked in German and English; the `007` and `008` codes decide that now and this is the fallback. |
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
| **Koha** | Not an acronym, a Maori word. The long established open source ILS, read here as a reference for the public library mode design. What its licence does and does not permit is settled, and the short version is that its interface may be read but its GPL code may not be copied here. |
| **OPAC** | Online Public Access Catalogue: the public facing search interface of an ILS, as opposed to the staff interface behind it. |
| **Patron** | The library word for a borrower. Not a customer: a library has no customers, and the German is Benutzer:in, registering one a Neuanmeldung. Koha's interface says patron while its schema says `borrowers`. |

## One that is not library science

**NFC** and **NFD** are Unicode normalisation forms. NFC composes an accented letter into a
single code point; NFD splits it into a base letter and a combining accent. They compare
unequal as strings. This belongs here because the DNB serves **NFD in MARC where its
Dublin Core was NFC**, measured at 83 of 85 records, so the switch changed the bytes of
almost every German title and author in the catalogue.
