"""What may be written to `classifications`, in what order, and what heals.

The ceiling and the drop rule are exercised through the routes in
`tests/routers/test_books_classifications.py`, which is where a member meets
them. What is pinned here is the module's own three rules: how a null kind is
read, which heading a full book loses, and the one path by which a row written
before the kind column existed is ever corrected.
"""

import ast
import pathlib
import re
from xml.etree import ElementTree

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

import decoders
import metadata
import targets
from catalogue import Heading
from classifications import KIND_ORDER, add_headings, bounded_headings, kind_of
from enums import ClassificationScheme, HeadingKind
from models import Book, Classification
from schemas import MAX_CLASSIFICATIONS_PER_BOOK
from schemas.classification import ClassificationIn


class TestReadingAKindOffARow:
    """`kind_of` is the only interpreter of the null, so it carries the fallback."""

    def test_a_row_no_record_ever_declared_for_is_a_subject(self):
        assert kind_of(None) is HeadingKind.SUBJECT

    @pytest.mark.parametrize("kind", list(HeadingKind))
    def test_every_member_reads_back_as_itself(self, kind):
        assert kind_of(kind) is kind

    def test_every_kind_has_a_rank(self):
        """`KIND_ORDER` is indexed rather than `get`, so a member added without
        a rank is a `KeyError` on the next lookup rather than a silent tie."""
        assert set(KIND_ORDER) == set(HeadingKind)


class TestASubjectIsNeverAValueTheColumnHolds:
    """A subject is the null, and the two enforcements of that.

    Why a stored `subject` would be wrong is `enums.HeadingKind`'s argument.
    What is pinned here is that neither route can store one: the client facing
    one, which normalises, and the database, which refuses.
    """

    def test_a_client_posting_subject_gets_the_null_it_means(self):
        assert (
            ClassificationIn(scheme=ClassificationScheme.GND, number="4139307-7",
                             kind=HeadingKind.SUBJECT).kind
            is None
        )

    def test_the_other_two_are_left_alone(self):
        """Anti vacuity: a validator returning None for everything would pass
        the test above and throw the feature away."""
        for kind in (HeadingKind.CONTENT, HeadingKind.CARRIER):
            assert (
                ClassificationIn(
                    scheme=ClassificationScheme.GND, number="4139307-7", kind=kind
                ).kind
                is kind
            )

    @pytest.mark.parametrize("stored", ["subject", "pwned", "SUBJECT", ""])
    def test_the_database_refuses_what_no_writer_should_send(self, db, stored):
        """`ck_classifications_kind`, against the route that has no validator.

        `backup.restore` inserts through Core, where neither a Pydantic model
        nor a `@validates` hook fires, so an archive decides this value. Without
        the constraint one such row raises inside `ClassificationOut`,
        `PublicClassificationOut` and `HeadingFacetOut` alike, which 500s the
        member listing, the facet endpoint and the unauthenticated public
        catalogue, for good. This is `b8e2f4c7a913`'s failure on a new column.
        """
        book = Book(title="Praxiswissen Docker")
        db.add(book)
        db.flush()

        with pytest.raises(IntegrityError):
            db.execute(
                insert(Classification).values(
                    book_id=book.id,
                    scheme=ClassificationScheme.GND,
                    number="4139307-7",
                    sort_key="4139307-7",
                    kind=stored,
                )
            )
        db.rollback()

    @pytest.mark.parametrize("stored", ["content", "carrier", None])
    def test_the_database_accepts_what_a_writer_does_send(self, db, stored):
        """The other side, so the constraint is not simply refusing everything."""
        book = Book(title="Praxiswissen Docker")
        db.add(book)
        db.flush()
        db.execute(
            insert(Classification).values(
                book_id=book.id,
                scheme=ClassificationScheme.GND,
                number="4139307-7",
                sort_key="4139307-7",
                kind=stored,
            )
        )

        assert db.query(Classification).count() == 1


class TestWhichHeadingAFullBookKeeps:
    """The kind outranks the scheme, which is what stops a disc winning."""

    def test_a_carrier_is_dropped_before_a_subject_from_any_scheme(self):
        """The case the ordering was changed for. A GND carrier used to sort
        ahead of an LCSH subject on the strength of `SCHEME_ORDER` alone, so a
        full book kept the disc and lost the heading."""
        entries = [
            Heading(ClassificationScheme.GND, "4139307-7", "CD-ROM", HeadingKind.CARRIER),
        ] + [
            Heading(ClassificationScheme.LCSH, f"Treasure troves {index}")
            for index in range(MAX_CLASSIFICATIONS_PER_BOOK)
        ]

        kept = bounded_headings(entries)

        assert len(kept) == MAX_CLASSIFICATIONS_PER_BOOK
        assert "4139307-7" not in {heading.number for heading in kept}

    def test_a_content_type_is_kept_ahead_of_a_carrier(self):
        entries = [
            Heading(ClassificationScheme.GND, "4139307-7", "CD-ROM", HeadingKind.CARRIER),
            Heading(
                ClassificationScheme.GND,
                "1071854844",
                "Fiktionale Darstellung",
                HeadingKind.CONTENT,
            ),
        ]

        assert [heading.number for heading in bounded_headings(entries)] == [
            "1071854844",
            "4139307-7",
        ]

    def test_a_content_type_survives_a_book_full_of_subject_headings(self):
        """The heading `#162` names as the reason not to refuse the content
        vocabulary, and the case a rank of its own would have lost.

        `CONTENT` ties with `SUBJECT` rather than sitting between it and
        `CARRIER`, so a content type falls through to `SCHEME_ORDER`, where GND
        already outranked LCSH. Given its own rank it would be dropped before
        every Library of Congress subject, which is a heading the ticket
        protects being lost by the change that was meant to protect it.
        """
        entries = [
            Heading(
                ClassificationScheme.GND,
                "1071854844",
                "Fiktionale Darstellung",
                HeadingKind.CONTENT,
            )
        ] + [
            Heading(ClassificationScheme.LCSH, f"Treasure troves {index}")
            for index in range(MAX_CLASSIFICATIONS_PER_BOOK)
        ]

        kept = {heading.number for heading in bounded_headings(entries)}

        assert "1071854844" in kept

    def test_the_scheme_still_decides_within_one_kind(self):
        """The old rule is unchanged where the kind does not separate two
        entries, which is every heading a record does not mark."""
        entries = [
            Heading(ClassificationScheme.LCSH, "Treasure troves"),
            Heading(ClassificationScheme.DDC, "004"),
        ]

        assert [heading.scheme for heading in bounded_headings(entries)] == [
            ClassificationScheme.DDC,
            ClassificationScheme.LCSH,
        ]

    def test_a_declared_carrier_sorts_below_an_undeclared_heading(self):
        """Two headings under one scheme, separated by the kind alone.

        **This does not pin where a null sorts**, and an earlier version of this
        docstring claimed it did. The carrier is the only kind ranked below any
        other, so the assertion holds whatever a null reads as; what pins that
        is `kind_of(None) is HeadingKind.SUBJECT` above. What this separates is a
        declared carrier from an undeclared heading, with `SCHEME_ORDER` held
        constant so it cannot be the thing deciding.
        """
        entries = [
            Heading(ClassificationScheme.GND, "4139307-7", "CD-ROM", HeadingKind.CARRIER),
            Heading(ClassificationScheme.GND, "4026894-9", "Informatik"),
        ]

        assert [heading.number for heading in bounded_headings(entries)] == [
            "4026894-9",
            "4139307-7",
        ]


class TestCorrectingAHeadingWrittenBeforeTheKindExisted:
    """The only route by which anything already stored is ever put right.

    No migration can do it: a stored row does not record the `$2` it came from,
    and the two vocabularies do not enumerate, which the revision
    `a1e7c93b60df` measures. So the record that declares is the only source of
    the answer, and this is what reads it.
    """

    def _book(self, db):
        book = Book(title="Praxiswissen Docker")
        db.add(book)
        db.flush()
        return book

    def test_a_declared_kind_fills_in_the_null_a_stored_row_carries(self, db):
        book = self._book(db)
        db.add(
            Classification(
                book=book,
                scheme=ClassificationScheme.GND,
                number="4139307-7",
                label="CD-ROM",
            )
        )
        db.flush()

        changed = add_headings(
            book,
            bounded_headings(
                [
                    Heading(
                        ClassificationScheme.GND,
                        "4139307-7",
                        "CD-ROM",
                        HeadingKind.CARRIER,
                    )
                ]
            ),
            db,
        )
        db.flush()

        assert changed == ["4139307-7"]
        assert book.classifications[0].kind == HeadingKind.CARRIER
        assert len(book.classifications) == 1

    def test_the_correction_counts_as_a_change_so_the_session_is_committed(
        self, db
    ):
        """`apply_enrichment` commits only `if updated:` and `get_db` closes
        without committing, so a fill-in this did not report would be rolled
        back and the row would stay wrong with nothing to see. The same reason
        a filled in caption is reported."""
        book = self._book(db)
        db.add(
            Classification(
                book=book,
                scheme=ClassificationScheme.GND,
                number="1071854844",
                label="Fiktionale Darstellung",
            )
        )
        db.flush()

        assert add_headings(
            book,
            bounded_headings(
                [
                    Heading(
                        ClassificationScheme.GND,
                        "1071854844",
                        "Fiktionale Darstellung",
                        HeadingKind.CONTENT,
                    )
                ]
            ),
            db,
        ) == ["1071854844"]

    def test_a_stored_kind_is_never_overwritten(self, db):
        """A heading already stored came from a catalogue too, and the last
        writer is not the better one. The same rule the caption obeys."""
        book = self._book(db)
        db.add(
            Classification(
                book=book,
                scheme=ClassificationScheme.GND,
                number="4139307-7",
                label="CD-ROM",
                kind=HeadingKind.CARRIER,
            )
        )
        db.flush()

        changed = add_headings(
            book,
            bounded_headings(
                [
                    Heading(
                        ClassificationScheme.GND,
                        "4139307-7",
                        "CD-ROM",
                        HeadingKind.CONTENT,
                    )
                ]
            ),
            db,
        )
        db.flush()

        assert changed == []
        assert book.classifications[0].kind == HeadingKind.CARRIER

    def test_the_correction_deposits_no_second_row(self, db):
        """The whole reason the kind is a column and not two more
        `ClassificationScheme` members. Under new members the pair
        `uq_classifications_book_scheme_number` is on would have changed, so
        this book would carry the concept twice, once right and once wrong."""
        book = self._book(db)
        db.add(
            Classification(
                book=book,
                scheme=ClassificationScheme.GND,
                number="4139307-7",
                label="CD-ROM",
            )
        )
        db.flush()

        add_headings(
            book,
            bounded_headings(
                [
                    Heading(
                        ClassificationScheme.GND,
                        "4139307-7",
                        "CD-ROM",
                        HeadingKind.CARRIER,
                    )
                ]
            ),
            db,
        )
        db.flush()

        assert (
            db.query(Classification).filter(Classification.book_id == book.id).count()
            == 1
        )


#: `backend/`, whose modules the derivation below walks.
BACKEND = pathlib.Path(__file__).resolve().parent.parent

#: Directories under `backend/` the walk does not read, because they are this
#: application's own and are still not source a catalogue reaches.
#:
#: `tests` holds fixtures that construct a `Heading` to arrange a case, which is
#: not a source building one. `migrations` is a historical record: a revision
#: describes the data as it was on the day it ran and is not a code path any
#: catalogue reaches.
_NOT_THIS_APP = frozenset({"tests", "migrations"})

#: English for the small numbers this repository's prose spells out.
_NUMERALS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}


def _is_this_app(parts: tuple[str, ...]) -> bool:
    """Whether a path under `backend/` is this application's own source.

    **A dotted directory is tooling, and the rule is the dot rather than a list
    of names.** Naming them one at a time is exactly what failed: this set said
    `.venv`, and CI sets `UV_CACHE_DIR` to `.uv-cache` **inside `backend/`**, so
    the walk read every vendored wheel it had unpacked. Every name then had a
    caller somewhere, every reader looked reachable, and the derivation reported
    **every catalogue in the roster** as feeding a heading, against a docstring
    that says seven.

    **It passed locally and failed only in CI**, because uv caches outside the
    tree here, which is the worst shape a guard can have: green where it is
    written, red where it is trusted. A rule that depends on knowing every
    tool's directory name goes stale the day somebody sets an environment
    variable, and no one edits this file when they do.
    """
    if _NOT_THIS_APP & set(parts):
        return False
    return not any(part.startswith(".") for part in parts)


def _modules() -> list[pathlib.Path]:
    return [
        path
        for path in BACKEND.rglob("*.py")
        if _is_this_app(path.relative_to(BACKEND).parts)
    ]


def _call_graph() -> tuple[dict[str, set[str]], set[str]]:
    """Every function this application defines, what it calls, and which build a Heading."""
    calls: dict[str, set[str]] = {}
    builds: set[str] = set()
    for path in _modules():
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for inner in ast.walk(node):
                if not isinstance(inner, ast.Call):
                    continue
                called = inner.func
                if isinstance(called, ast.Name):
                    name = called.id
                elif isinstance(called, ast.Attribute):
                    name = called.attr
                else:
                    continue
                if name == Heading.__name__:
                    builds.add(node.name)
                else:
                    calls.setdefault(node.name, set()).add(name)
    return calls, builds


def _reaching(calls: dict[str, set[str]], builds: set[str]) -> set[str]:
    """The functions that build a Heading, plus everything that can call one."""
    reaching = set(builds)
    moved = True
    while moved:
        moved = False
        for function, callees in calls.items():
            if function not in reaching and callees & reaching:
                reaching.add(function)
                moved = True
    return reaching


def _registered_entries() -> dict[decoders.Reader, set[str]]:
    """Which function each reader is answered by, read off the tables themselves."""
    entries: dict[decoders.Reader, set[str]] = {}
    for table in (
        metadata._LOOKUP_READERS,
        metadata._SEARCH_READERS,
        metadata._BESPOKE_LOOKUPS,
        metadata._FREE_SEARCHES,
        metadata._METERED_SEARCHES,
    ):
        for reader, decoder in table.items():
            entries.setdefault(reader, set()).add(decoder.__name__)
    return entries


def _marc_probe(reader: decoders.Reader, extra: str) -> bool:
    """Whether one MARC reader builds a heading out of a record, by asking it."""
    record = ElementTree.fromstring(
        '<record xmlns="http://www.loc.gov/MARC21/slim">'
        '<datafield tag="245" ind1="1" ind2="0">'
        "<subfield code=\"a\">Praxiswissen Docker</subfield></datafield>"
        f"{extra}</record>"
    )
    built = metadata._marc_build(
        decoders.Decoding(source="probe", reader=reader),
        metadata._marc_fields(record),
        "9783960092353",
    )
    return built is not None and bool(built.headings)


#: A MARC record carrying both of the things a MARC reader can make a heading
#: from: an `082` Dewey number and a `650` with a GND identifier on it.
_CLASSIFIED = (
    '<datafield tag="082" ind1="0" ind2="4">'
    "<subfield code=\"a\">004</subfield></datafield>"
    '<datafield tag="650" ind1=" " ind2="7">'
    "<subfield code=\"a\">Informatik</subfield>"
    '<subfield code="0">(DE-588)4026894-9</subfield>'
    "<subfield code=\"2\">gnd</subfield></datafield>"
)


class TestHowManyCataloguescanFeedOneBooksHeadings:
    """`#206`: the count is derived from the code, not restated beside it.

    `bounded_headings` says a merge has concatenated up to *n* catalogues,
    "which is every source that builds a `Heading` at all", and that *n* was
    wrong twice in two days. Both corrections were made by a reader noticing,
    which is the weakest instrument here and the one this repository has
    repeatedly recorded as insufficient.

    **Deliberately not a census assertion.** The roster census already holds a
    row of hand maintained figures, and a seventh would put this number under
    the same class of guard it has twice demonstrated it cannot survive:
    something a person states. This walks instead, from the `Heading`
    construction sites, to the functions that can reach one, to the readers
    those functions answer for, to the rows in `targets.SEEDED` naming those
    readers. Add a catalogue on a heading building reader and the derived number
    moves with it, so the assertion is about the relationship and the literal in
    the prose is the only thing that can be stale.

    **Two instruments, because two careful readings are one instrument twice.**
    The walk is static and cannot see which branch of a dispatcher a reader
    takes, so any reader sharing an entry function with another is asked
    directly instead. Today that is the two MARC readers and no others, which is
    checked rather than assumed.

    **What neither instrument sees, stated because a blind spot left implicit is
    the one nobody looks for.** The probe enters at `metadata._marc_build`,
    which is one call below the registered entries `_marc_lookup` and
    `_marc_search`. A change that stripped headings **between** the entry and
    `_marc_build`, a `decoders.Decoding` flag say, is invisible to the walk,
    which sees the call, and to the probe, which starts underneath it. Probing
    the entries themselves is not a smaller fix: they take a whole SRU response
    and return a `Lookup`, so the fixture would be a response per reader and the
    thing under test would become the transport.
    """

    def _derived(self) -> set[decoders.Reader]:
        calls, builds = _call_graph()
        reaching = _reaching(calls, builds)
        return {
            reader
            for reader, names in _registered_entries().items()
            if names & reaching
        }

    def test_a_tooling_directory_is_not_read_however_a_tool_names_it(self):
        """The evasion that broke this guard in CI, kept as a test.

        The exclusion named `.venv` and nothing else, and CI sets `UV_CACHE_DIR`
        to `.uv-cache` under `backend/`, so the walk read every vendored wheel
        and reported **every catalogue in the roster** as feeding a heading,
        where the docstring says seven. **This passed locally throughout**, because uv caches
        outside the tree here.

        So the rule is the leading dot rather than a list, and this fails if
        anybody puts it back to a list: the third case is a name no list could
        have held, because no tool has invented it yet.
        """
        assert not _is_this_app((".venv", "lib", "site.py"))
        assert not _is_this_app((".uv-cache", "pkg", "vendored.py"))
        assert not _is_this_app((".a-cache-no-tool-has-invented-yet", "x.py"))
        assert _is_this_app(("metadata.py",))
        assert _is_this_app(("routers", "books.py"))

    def test_the_walk_reads_no_dotted_directory_on_this_machine(self):
        """The live half of the rule above, which the pure one cannot see.

        A cache present in this checkout right now would be caught here rather
        than by a pipeline an hour later.
        """
        walked = _modules()

        assert walked
        assert not [p for p in walked if any(part.startswith(".") for part in p.parts)]

    def test_the_walk_finds_the_construction_sites_at_all(self):
        """Anti vacuity, and the first thing to break if `Heading` is renamed or
        the module layout moves: with an empty set every assertion below passes
        by finding nothing."""
        _, builds = _call_graph()

        assert builds

    def test_every_reader_is_answered_by_something(self):
        """A reader missing from all five tables would be excluded silently
        rather than counted as building nothing, so the count would fall with no
        finding anywhere. `metadata._check_readable` raises on this for a live
        row; this is the same rule asked of the closed set."""
        assert set(_registered_entries()) == set(decoders.Reader)

    def test_the_walk_separates_readers_rather_than_admitting_all_of_them(self):
        """The other half of anti vacuity. A walk that answered "every reader"
        would also produce the right total, for the wrong reason."""
        assert self._derived() < set(decoders.Reader)

    def test_only_the_marc_readers_share_an_entry_the_walk_cannot_split(self):
        """The walk's blind spot, named and checked rather than commented on.

        `_marc_lookup` serves both MARC readers and dispatches inside
        `_marc_build`, so the static walk credits both with whatever either can
        build. That is the right answer today and it is not the walk that makes
        it right. If a third reader ever shares an entry function, this fails
        and the reader below has to be asked the way the MARC pair is.
        """
        entries = _registered_entries()
        shared = {
            reader
            for reader, names in entries.items()
            if any(
                names & other
                for another, other in entries.items()
                if another is not reader
            )
        }

        assert shared == {decoders.Reader.MARC_GND, decoders.Reader.MARC_PLAIN}

    @pytest.mark.parametrize(
        "reader", [decoders.Reader.MARC_GND, decoders.Reader.MARC_PLAIN]
    )
    def test_each_marc_reader_builds_a_heading_when_asked(self, reader):
        """The second instrument. Both are counted, so both have to earn it on
        their own rather than through the dispatcher they share."""
        assert _marc_probe(reader, _CLASSIFIED)

    @pytest.mark.parametrize(
        "reader", [decoders.Reader.MARC_GND, decoders.Reader.MARC_PLAIN]
    )
    def test_the_probe_can_answer_no(self, reader):
        """Sensitivity for the pair above: a probe that answered yes on a record
        with nothing to classify would prove nothing about either reader."""
        assert not _marc_probe(reader, "")

    def test_the_stated_count_is_the_derived_one(self):
        """The claim itself. Read out of `__doc__` rather than off the source
        literal, because a docstring is dedented and its literal is not, so a
        guard comparing one against the other reports a mismatch that is not
        there."""
        derived = {
            source
            for source, target in targets.SEEDED.items()
            if target.reader in self._derived()
        }
        stated = re.search(
            r"concatenated up to (\w+) catalogues", bounded_headings.__doc__ or ""
        )

        assert stated is not None, (
            "`bounded_headings` no longer says how many catalogues a merge can "
            "have concatenated"
        )
        assert _NUMERALS.get(stated.group(1)) == len(derived), (
            f"the docstring says {stated.group(1)} catalogues; the readers that "
            f"build a Heading are fed by {len(derived)}: "
            f"{sorted(source.value for source in derived)}"
        )

    def test_the_data_model_states_the_same_count(self):
        """The same sentence lives in a published document, and a figure written
        twice is a figure that stops being re-derived. Both are checked against
        the derivation rather than against each other."""
        derived = sum(
            target.reader in self._derived() for target in targets.SEEDED.values()
        )
        stated = re.search(
            r"concatenated up to (\w+) catalogues",
            (BACKEND.parent / "docs" / "data-model.md").read_text(),
        )

        assert stated is not None, (
            "`docs/data-model.md` no longer states how many catalogues a merge "
            "can have concatenated"
        )
        assert _NUMERALS.get(stated.group(1)) == derived
