"""What an import reader is told, and what it is deliberately not told.

`import_readers.py` is a contract rather than an implementation, so these are
guards over shape, plus one that runs the contract's own stated test: a reader
reading text that no upload produced.

Modelled on `test_decoders.py`, which guards the same idea one level down, and
the two differ in one place worth naming. A decoder's strongest enforcement is
that `metadata.py`'s registries are typed on `decoders.Decoding`. A reader's is
that `csv_import.READERS` is typed on `csv_import.ReaderFn`, which pins **both**
parameters and the return, so a reader taking bytes or a filename fails the type
check as loudly as one taking an upload does.

**What these cannot see, stated so it is not rediscovered.**

A reader that takes an `Extraction` and then reaches a module level global is
invisible here, exactly as it is for a decoder. There is nothing to reach today:
`csv_import.py` imports no session, no client and no request, which
`test_the_implementations_reach_no_session_and_no_request` is what actually
checks, and it is a weaker statement than the contract's own import rule because
that module legitimately imports several of this application's modules.

**Detection is not tested here.** `detect` and `CLAIMS` are `csv_import.py`'s
and are tested against that module's fixtures, where the header rows they match
are quoted from named artefacts. This file would have to restate them to test
them, and a header row restated in two places is a header row that drifts in one.
"""

import ast
import inspect
import pathlib

import pytest

import csv_import
from csv_import import ParsedFile
from import_readers import Extraction, ImportReader

BACKEND = pathlib.Path(__file__).resolve().parent.parent

#: A file with nothing service specific in it, so any reader may be asked for it.
PLAIN = "Title,Author\nSolaris,Stanislaw Lem\n"


class TestAReaderWorksOnTextNoUploadProduced:
    """The contract's own stated test, run rather than asserted.

    A reader is handed decoded text and an `Extraction` built by hand. No
    `UploadFile`, no request, no session and no member id appear anywhere in
    this class, which is the whole claim.
    """

    def test_a_reader_reads_text_handed_to_it_directly(self):
        parsed = csv_import.READERS[ImportReader.GENERIC](
            PLAIN, Extraction(reader=ImportReader.GENERIC)
        )
        assert [row.title for row in parsed.rows] == ["Solaris"]

    def test_it_reports_which_reader_read_it(self):
        """Off the `Extraction` rather than off a default, which is what makes
        the reported reader the one that ran."""
        parsed = csv_import.READERS[ImportReader.LIBRARYTHING](
            PLAIN, Extraction(reader=ImportReader.LIBRARYTHING)
        )
        assert parsed.reader is ImportReader.LIBRARYTHING

    def test_a_correction_handed_in_directly_is_honoured(self):
        """The one setting an `Extraction` carries, arriving with no query
        string anywhere near it."""
        parsed = csv_import.READERS[ImportReader.GENERIC](
            "Title,Written By\nSolaris,Stanislaw Lem\n",
            Extraction(reader=ImportReader.GENERIC, overrides={"author": "Written By"}),
        )
        assert [row.author for row in parsed.rows] == ["Stanislaw Lem"]


class TestAReaderIsNeverToldHowTheFileArrived:
    """The seam's rule, checked three ways that fail for different reasons."""

    def test_the_contract_names_no_other_module_of_this_application(self):
        """`import_readers.py` may import from the standard library and nothing
        else.

        **Stated as the exclusion**: every module and every package of this
        application, derived from the tree rather than listed, so one added
        later is covered. An import of `routers`, `dependencies` or `models`
        here is how the contract acquires an upload, a session or a member.

        A directory is a namespace package here whether or not it carries an
        `__init__.py`, so an inventory of files is not an inventory of what can
        be imported, and both halves are read.
        """
        ours = _every_module_of_ours() - {"import_readers"}
        imported = _imports_of(BACKEND / "import_readers.py")

        assert not imported & ours, sorted(imported & ours)

    def test_the_exclusion_would_notice_an_import_of_ours(self):
        """The control for the row above, which passes on an empty set for two
        reasons and only one of them is the one being claimed."""
        ours = _every_module_of_ours()

        assert {"csv_import", "importing", "models"} <= ours
        assert {"routers", "schemas", "tests"} <= ours

    def test_every_registered_reader_takes_text_and_an_extraction_and_nothing_else(self):
        """Asserted as the whole signature rather than as a list of forbidden
        types.

        A blacklist of `UploadFile`, `Session` and `Request` is the shape that
        goes stale the day somebody threads a fourth thing through. Two
        parameters, both named, plus the return, admits nothing new by
        construction.

        Read off the registry, so a reader added later is checked by being
        registered rather than by being remembered.
        """
        for reader, function in csv_import.READERS.items():
            signature = inspect.signature(function)
            assert [
                parameter.annotation for parameter in signature.parameters.values()
            ] == [str, Extraction], (reader, signature)
            assert signature.return_annotation is ParsedFile, reader

    def test_that_check_would_notice_a_reader_handed_an_upload(self):
        """The control, on a reader shaped the way the rule forbids."""

        def welded(upload: object, extraction: Extraction) -> ParsedFile:
            return ParsedFile()

        annotations = [
            parameter.annotation
            for parameter in inspect.signature(welded).parameters.values()
        ]
        assert annotations != [str, Extraction]

    def test_the_implementations_reach_no_session_and_no_request(self):
        """Weaker than the contract's rule, and deliberately so.

        `csv_import.py` imports several modules of this application and always
        has. What it may not import is the three that would let a reader reach
        past the text it was handed. Named rather than derived, because the
        exclusion this file can state about the implementations is a short list
        of doors rather than the whole tree.
        """
        forbidden = {"dependencies", "routers", "fetch", "database", "sqlalchemy"}
        assert not _imports_of(BACKEND / "csv_import.py") & forbidden


class TestTheClosedSetHasNoMemberWithoutAReader:
    """A member added and not wired up is selectable over the API and a
    `KeyError` on dispatch, which reaches a member as a 500."""

    def test_every_member_of_the_set_is_registered(self):
        assert set(csv_import.READERS) == set(ImportReader)

    def test_a_member_left_out_of_the_registry_is_refused(self):
        """The check the module runs at import, asked directly.

        Every member in turn, so the refusal is not resting on whichever one
        somebody happened to drop.
        """
        for missing in ImportReader:
            partial = {
                reader: function
                for reader, function in csv_import.READERS.items()
                if reader is not missing
            }
            with pytest.raises(RuntimeError) as error:
                csv_import._complete(partial)
            assert missing.value in str(error.value)

    def test_the_registry_the_application_uses_passes_that_check(self):
        """The other half of the diagonal: the row above passes on a check that
        refuses everything."""
        assert csv_import._complete(dict(csv_import.READERS)) == csv_import.READERS


class TestEveryReaderHonoursAColumnCorrection:
    """What replaced a refusal whose only subject the owner's decision removed.

    `Extraction` used to refuse a correction handed to a reader that guesses no
    columns, because such a reader would take one and silently discard it, which
    is the failure the preview step exists to prevent one level up. The only
    reader that guessed nothing was the one whose whole job was a row exclusion,
    and the exclusion belongs to the generic mapping now. A refusal with no
    subject passes whatever it is handed, and the guard written against exactly
    that, an assertion that the split still had a member on each side, is what
    said so rather than a reader noticing.

    **So the rule is asserted the other way round and off the registry.** Every
    reader registered honours a correction, each asked in turn. A reader that
    cannot fails here, and that is the day a refusal has a subject again.
    """

    #: One file per reader, because a reader may refuse text it cannot read at
    #: all. `author` is corrected to a header no candidate name covers, so the
    #: correction is what fills the field or nothing does.
    SAMPLES = {
        ImportReader.GENERIC: "Title,Written By\nSolaris,Stanislaw Lem\n",
        ImportReader.LIBRARYTHING: (
            "Title\tWritten By\tPublication\nSolaris\tStanislaw Lem\tFaber (1970)\n"
        ),
        ImportReader.OPENREADS: (
            "title,Written By,readings\nSolaris,Stanislaw Lem,2021-01-02|2021-02-03|\n"
        ),
    }

    def test_every_registered_reader_has_a_sample_here(self):
        """Keyed on the registry rather than listed beside it: a reader with no
        sample fails rather than being quietly skipped, which is how a loop
        over a table goes vacuous while every assertion in it passes."""
        assert set(csv_import.READERS) == set(self.SAMPLES)

    def test_every_reader_reads_the_column_it_was_told_to(self):
        for reader, text in self.SAMPLES.items():
            parsed = csv_import.READERS[reader](
                text, Extraction(reader=reader, overrides={"author": "Written By"})
            )
            assert [row.author for row in parsed.rows] == ["Stanislaw Lem"], reader

    def test_without_the_correction_that_column_is_unread(self):
        """The other half of the diagonal. Without it the row above would pass
        on a reader that ignored the correction and guessed the column anyway,
        which is the same green for the opposite reason."""
        for reader, text in self.SAMPLES.items():
            parsed = csv_import.READERS[reader](text, Extraction(reader=reader))
            assert [row.author for row in parsed.rows] == [None], reader

    def test_a_reader_may_be_asked_for_with_no_correction_at_all(self):
        for reader in ImportReader:
            assert Extraction(reader=reader).overrides == {}

    def test_the_corrections_cannot_be_written_through_afterwards(self):
        """`frozen=True` stops the attribute being rebound and does nothing
        about the dict it points at."""
        given = {"author": "By"}
        extraction = Extraction(reader=ImportReader.GENERIC, overrides=given)

        given["title"] = "Name"

        assert extraction.overrides == {"author": "By"}
        with pytest.raises(TypeError):
            extraction.overrides["title"] = "Name"  # type: ignore[index]


def _every_module_of_ours() -> set[str]:
    """Every top level module and package of this application, off the tree."""
    return {path.stem for path in BACKEND.glob("*.py")} | {
        path.name
        for path in BACKEND.iterdir()
        if path.is_dir() and not path.name.startswith(("_", "."))
    }


def _imports_of(path: pathlib.Path) -> set[str]:
    """The top level names one module imports, both spellings of import."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
