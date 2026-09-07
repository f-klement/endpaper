"""What an import reader is, and it is never told how the file arrived.

An **import reader** turns one service's export into this application's rows.
`ImportReader` is the closed set of them and `Extraction` is the whole of what
one is told. The implementations are in `csv_import.py`; this module is the
contract they are held to.

`decoders.py` is the same idea one level down and was the worked example this
was written against: there a **decoder** turns one catalogue record into one
`catalogue.Record` and `Decoding` never names the transport. Here a **reader**
turns one whole file into a `csv_import.ParsedFile` and `Extraction` never names
the upload. They are parallel rather than shared because the units differ: a
decoder answers per record and may refuse one, a reader answers per file and
decides how many records there are at all.

## Why a reader per service, rather than a pre-pass in front of one path

The generic reader's premise is that a new service is a list of candidate header
names, and two export shapes end it: a compound cell packing publisher, year and
format into one value, and a library export that is nested JSON rather than a
table.

**A row exclusion was the third and is not one any more.** Marking what the
member deleted at the source cannot be a candidate header name either, but it
needs no reader: `csv_import.py` honours such a column wherever it appears, so
nothing has to be right about which service wrote the file. Owner's decision,
2026-09-07, in `docs/decisions.md`. It is the half that changes what a member
sees, which is the half that must not rest on a guess.

A per service pre-pass in front of the one generic path was refused, and it was
the smaller change. It keeps one path and pays with a detection step that has to
be right about which service wrote a file, and it does not reach the JSON case
at all, so this seam would have been built afterwards with a pre-pass left in
front of it. Owner's decision, 2026-09-06, in `docs/decisions.md`.

## The contract

**One input type, and it is text.** A reader is handed the decoded file and an
`Extraction`. Decoding is shared and happens once, before dispatch: every reader
wants the same answer to "what encoding is this", and a reader that decoded for
itself would be a second answer to a question this application has already
measured and settled.

**One output type.** A reader answers with a `csv_import.ParsedFile`, or raises
`csv_import.ImportError_` for a file it cannot read as a book list. Nothing else.

**One bad row fails alone and never the file.** A row a reader cannot act on is
counted and dropped, because the alternative is one malformed line costing a
member their whole library. `ParsedFile.skipped` and `ParsedFile.excluded` are
what make the counts still add up to the lines in the file.

## What a reader may not mention

**A reader names what it reads and never how it got there.** No `UploadFile`, no
filename, no content type, no HTTP status, no `Session` and no member id. It is
handed text and an `Extraction`.

**This is enforced by the registry's type rather than by prose.**
`csv_import.READERS` is a `dict[ImportReader, ReaderFn]`, and `ReaderFn` is
`Callable[[str, Extraction], ParsedFile]`, so a reader that took bytes, a
filename or a session would fail the type check rather than a review.

**The demand is near term rather than hypothetical.** Google Play Books' book
list is nested JSON filtered on a document type, so it is a reader whose input
is not a table at all. Building it is adding a member here, a function to the
registry, and a row to `csv_import.CLAIMS`, whose element is a predicate over
the decoded text rather than a set of header names for exactly that reason: no
caller changes, and nothing in the generic path is touched.

**The detector is where the refused pre-pass's price is paid, and this is where
they differ.** A pre-pass detects and then runs one path, so a wrong detection
mangles a file on the only path there is, and a file that is not a table has no
path at all. Here the detector chooses between whole readers, is replaceable
without touching one, and a reader may be asked for by name instead. A JSON
reader cannot be a pre-pass under any arrangement.

## Selection, which is the part a pre-pass would have got wrong

A file arrives as an upload with no label saying where it came from, so
something has to choose. Two things do, in this order:

1. **The member, if they name one.** This is the escape hatch, and it is the
   same escape hatch a wrong column guess already has.
2. **A claim over the decoded file**, in `csv_import.CLAIMS`.

**Generic is the fallback, and both directions are bounded now.** A claim that
fails to fire leaves the file with the reader that reads it today, so a miss is
never a regression to nothing. A claim that fires wrongly hands the file to a
reader that reads everything the generic one reads and additionally reaches
inside one named cell, so it costs that cell misread rather than a file read
short. The reader that read a file short was the one whose whole job was a row
exclusion, and that job is the generic mapping's now.

**Which reader ran is reported**, on `ParsedFile.reader` and through to the
preview, for the reason the column mapping is reported: a wrong guess about
somebody's file is invisible until after the import, and after the import the
fix is deleting a few hundred books.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType


class ImportReader(StrEnum):
    """The reader an uploaded export is read with.

    Closed, and adding a member is the only part of adding a service that is
    still code. A service that fits the candidate header names is not a member
    here: it is names added to `csv_import.COLUMN_GUESSES` and no code at all,
    which is what `GENERIC` is for and what keeps this set from growing one
    member per service anybody has heard of.

    **A member exists only where a name cannot express what the file does and
    a reader is the only way to express it.** A row exclusion is not a name
    either and is not here, because it needs no reader: `csv_import.py` honours
    that column in the generic mapping, wherever it appears.
    """

    #: Candidate header names, guessed against whatever the file has and
    #: correctable by hand. Every service that fits, which is most of them.
    GENERIC = "generic"
    #: Generic reading plus LibraryThing's `Publication`, one cell holding the
    #: publisher, the year and the format.
    LIBRARYTHING = "librarything"
    #: Generic reading plus Openreads' `readings`, one cell holding a start and
    #: a finish per reading session.
    OPENREADS = "openreads"


@dataclass(frozen=True)
class Extraction:
    """Everything an import reader is told, and the point is what is not here.

    **No upload, no filename, no content type, no session, no member.** A reader
    is handed the decoded text and this. `routers/imports.py` holds all five and
    is therefore not what a reader takes: a signature naming any of them would
    weld every service's format to the one way a file currently reaches this
    application, and the near term second way is already named in the module
    docstring.

    `csv_import.parse` is the only place in the application that builds one of
    these from an upload. A test, or a reader for a file that arrived some other
    way, builds one directly, which is the whole point.
    """

    reader: ImportReader
    #: Field name to the header it should be read from, correcting a guess.
    #:
    #: **Every reader there is guesses columns, so every reader honours these.**
    #: A reader that did not would take a correction and silently discard it,
    #: which is the failure the whole preview step exists to prevent one level
    #: up, so it would have to refuse instead. Nothing refuses today because
    #: there is nothing to refuse:
    #: `tests/test_import_readers.py::TestEveryReaderHonoursAColumnCorrection`
    #: is what goes red on the day a reader arrives that cannot.
    overrides: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """The corrections are copied behind a `MappingProxyType` on the way in.

        `frozen=True` stops the attribute being rebound and does nothing about
        the dict it points at, so without this a caller keeps a live handle on
        the settings a reader is about to read.
        """
        object.__setattr__(self, "overrides", MappingProxyType(dict(self.overrides)))
