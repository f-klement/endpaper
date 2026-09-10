"""What a decoder is told, and what it is deliberately not told.

`decoders.py` is a contract rather than an implementation, so these are guards
over shape, plus one that runs the contract's own stated test: a decoder written
for a catalogue reading a file.

**What these cannot see, stated so it is not rediscovered.**

A decoder that takes a `decoders.Decoding` and then reaches a module level
client is invisible here inside `metadata.py`;
`test_the_contract_names_no_other_module_of_this_application` stops it only for
`decoders.py` itself. The two bespoke entries in `metadata._BESPOKE_LOOKUPS` do
fetch, which is why that table is named a table of adapters and is not in the
registries these guards read.

**`_OF_FAMILY`'s import side is invented, and that bounds what the two family
arm measures.** There is no import registry yet, so the identifier is a string
drawn from no roster, and what the arm actually measures today is that
`sources.parse` drops a name `CatalogueSource` does not hold. That is the
refusal, so the arm is not empty, but it will keep passing on the day a real
import registry exists whose identifiers reach the lookup path by some other
door. **`_OF_FAMILY` must be derived from that registry the day it lands**, and
this paragraph is the note that says so.
"""

import ast
import inspect
import pathlib
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable

import pytest

import decoders
import metadata
import sources
import targets
from enums import Capability, CatalogueSource, SourceFamily
from tests.test_house_rules import _is_vendored

BACKEND = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = BACKEND / "tests" / "fixtures" / "marc21_one_record.xml"

#: The ISBN the fixture record names in its own 020.
FIXTURE_ISBN = "9780743273565"


def _off_disk() -> ElementTree.Element:
    return ElementTree.fromstring(FIXTURE.read_text(encoding="utf-8"))


def _named(decoder: Callable[..., object]) -> str:
    """A decoder's name for a failure message, without asserting it has one.

    A registry may one day hold something that is callable and not a function,
    and a guard that crashes on the object it is reporting reports nothing.
    """
    return getattr(decoder, "__name__", repr(decoder))


def _registered() -> list[Callable[..., object]]:
    """Every decoder in a registry, which is what a guard here reads.

    The registries rather than a list of function names: a sixth decoder is
    covered by adding its row, which is the only way it becomes reachable.
    """
    return [*metadata._LOOKUP_READERS.values(), *metadata._SEARCH_READERS.values()]


class TestADecoderWorksOnAFile:
    """The contract's own test, run rather than asserted.

    A catalogue decoder, a record read off disk, no `targets.Target` anywhere
    and nothing that could open a socket. This is the demand OPF makes: the same
    decoder for a zip entry inside an EPUB and a loose file beside a book in a
    Calibre library.
    """

    def test_a_catalogue_decoder_reads_a_record_off_disk(self):
        decoding = decoders.Decoding(
            source="a folder of files", reader=decoders.Reader.MARC_GND
        )

        found = metadata._marc_lookup(_off_disk(), FIXTURE_ISBN, decoding)

        assert found.outcome is metadata.Outcome.FOUND
        assert found.record is not None
        assert found.record.title == "The Great Gatsby"

    def test_the_label_it_carries_is_not_a_catalogue(self):
        """`Decoding.source` is a `str` and this is why.

        A file has no member of `CatalogueSource` to name, so typing that field
        on the catalogue registry's key space would put a catalogue's identity
        into the one contract both families share.
        """
        decoding = decoders.Decoding(
            source="a folder of files", reader=decoders.Reader.MARC_GND
        )

        found = metadata._marc_lookup(_off_disk(), FIXTURE_ISBN, decoding)

        assert found.record is not None
        assert found.record.source == "a folder of files"
        assert "a folder of files" not in {source.value for source in CatalogueSource}

    def test_a_decoding_built_by_hand_can_be_a_rows_exactly(self):
        """The control, without which the two above could pass on a decoder no
        catalogue uses.

        **The equality of the two decodings is asserted and not inferred from
        the record**, which was a correction a critic measured. The earlier
        version differed from the NLG's row on `refuses_component_parts` and the
        records agreed anyway, because the fixture's leader/07 is `m` and that
        filter had nothing to do. Two decodings agreeing about one record is not
        two decodings agreeing.
        """
        from_a_row = targets.SEEDED[CatalogueSource.NLG].decoding
        by_hand = decoders.Decoding(
            source="nlg",
            reader=decoders.Reader.MARC_GND,
            refuses_component_parts=True,
        )

        assert by_hand == from_a_row
        assert (
            metadata._marc_lookup(_off_disk(), FIXTURE_ISBN, by_hand).record
            == metadata._marc_lookup(_off_disk(), FIXTURE_ISBN, from_a_row).record
        )


class TestADecoderIsNeverToldHowTheBytesArrived:
    """The seam's rule, checked two ways that fail for different reasons.

    The strongest enforcement is not here: the registries in `metadata.py` are
    typed on `decoders.Decoding`, so mypy refuses a decoder taking a row without
    anybody remembering the rule. These catch the two things a type cannot.
    """

    def test_the_contract_names_no_other_module_of_this_application(self):
        """`decoders.py` may import from the standard library and nothing else.

        **Stated as the exclusion**: every module and every package of this
        application, derived from the tree rather than listed, so one added
        later is covered. An import of `fetch`, `targets` or `google_books`
        here is how the contract acquires an address, and it would then be one
        for both families.

        **The packages are half of it and were missing for a round**, measured
        by a critic: over top level `*.py` alone, 5 of 7 evasions passed, and
        the one that mattered was `from routers import books`, since
        `routers/books.py` pulls in `metadata` and `fetch`. A directory is a
        namespace package here whether or not it carries an `__init__.py`, so
        an inventory of files is not an inventory of what can be imported.
        """
        ours = (
            {path.stem for path in BACKEND.glob("*.py")}
            | {
                path.name
                for path in BACKEND.iterdir()
                if path.is_dir() and not path.name.startswith(("_", "."))
            }
        ) - {"decoders"}
        tree = ast.parse((BACKEND / "decoders.py").read_text(encoding="utf-8"))

        imported = {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        } | {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }

        assert not imported & ours, sorted(imported & ours)

    def test_the_exclusion_would_notice_an_import_of_ours(self):
        """The control for the row above, which passes on an empty set for two
        reasons and only one of them is the one being claimed.

        **Both shapes, because the first version asserted three top level
        modules and so could not see a set that held no package at all.**
        """
        ours = (
            {path.stem for path in BACKEND.glob("*.py")}
            | {
                path.name
                for path in BACKEND.iterdir()
                if path.is_dir() and not path.name.startswith(("_", "."))
            }
        )

        assert {"targets", "fetch", "metadata"} <= ours
        assert {"routers", "schemas", "tests"} <= ours

    def test_no_registered_decoder_is_handed_the_row_it_was_reached_by(self):
        """A `targets.Target` in a signature is the weld, by name.

        It carries an address, a transport, a query language and a query
        parameter, so a decoder holding one can reach back for all four and the
        separation is over. Read off the registries, so a decoder added later is
        checked by being registered rather than by being remembered.
        """
        offenders = [
            decoder
            for decoder in _registered()
            if any(
                "Target" in str(parameter.annotation)
                for parameter in inspect.signature(decoder).parameters.values()
            )
        ]

        assert not offenders, [_named(decoder) for decoder in offenders]

    def test_and_every_one_of_them_is_handed_a_decoding(self):
        """The other half of the diagonal: the row above passes on a registry
        whose decoders take nothing at all."""
        assert _registered()
        for decoder in _registered():
            annotations = {
                str(parameter.annotation)
                for parameter in inspect.signature(decoder).parameters.values()
            }
            assert any("Decoding" in name for name in annotations), _named(decoder)


class TestADecodingIsValidatedWhereverItIsBuilt:
    """The value object refuses what no row has checked.

    `targets.Target` refuses the same pairings, and that covers a decoding built
    from a catalogue row because `Target.decoding` is the only builder there.
    Neither statement covers a decoding built directly, which is the side this
    module exists for.
    """

    def test_a_marc_knob_on_a_reader_that_reads_no_marc_is_refused(self):
        with pytest.raises(ValueError):
            decoders.Decoding(
                source="a folder of files",
                reader=decoders.Reader.DUBLIN_CORE,
                refuses_component_parts=True,
            )

    def test_the_other_marc_knob_is_refused_the_same_way(self):
        """Both arms, because a version checking one passed with the other
        deleted."""
        with pytest.raises(ValueError):
            decoders.Decoding(
                source="a folder of files",
                reader=decoders.Reader.MODS,
                reads_author_identifiers=True,
            )

    def test_a_reader_that_does_read_marc_may_carry_them(self):
        """The control: it must not refuse everything."""
        carried = decoders.Decoding(
            source="a folder of files",
            reader=decoders.Reader.MARC_GND,
            refuses_component_parts=True,
            reads_author_identifiers=True,
        )

        assert carried.refuses_component_parts and carried.reads_author_identifiers

    def test_the_safe_answer_is_what_omission_gives(self):
        """`requires_isbn_claim` cannot be refused here, because the rule naming
        the one source that may waive it is keyed on `CatalogueSource` and this
        module may not import it.

        What is enforceable is the default, and it is the refusing arm: a
        decoding that says nothing gets the answer that stands between a
        mistyped index and a member's shelf.
        """
        assert decoders.Decoding(
            source="a folder of files", reader=decoders.Reader.MARC_GND
        ).requires_isbn_claim


def _production_sources() -> list[pathlib.Path]:
    """Every module of this application that is not a test.

    Stated as the exclusion, so a package added later is read rather than
    skipped.

    **What vendored means is `test_house_rules._is_vendored`.** The three names
    this held were every cache anybody had seen locally, and the pipeline sets
    `UV_CACHE_DIR` inside `backend/`, so `.uv-cache/` was read and any
    dependency spelling `Decoding(` would have been reported for skipping this
    application's projection.
    """
    found = [
        path
        for path in BACKEND.rglob("*.py")
        if "tests" not in path.relative_to(BACKEND).parts
        and not _is_vendored(path, BACKEND)
    ]
    # The packages it must cover rather than a number, so a walk that lost a
    # whole directory fails rather than passing on a smaller sweep. See
    # `test_accounts._sources` for the mutation that made a count look adequate.
    assert {"routers", "schemas"} <= {path.parent.name for path in found}, found
    return found


class TestOnlyTheProjectionTurnsARowIntoADecoding:
    """`Target.decoding` says it is the only place a catalogue row becomes a
    decoding, and a docstring saying so is enforced by nothing.

    **There is no exception, which took a round to get right.** A module that
    cannot reach a `targets.Target` is free to build a `Decoding` directly, and
    that is exactly what an importer will do. A module that **can** reach one and
    hand rolls a decoding is skipping the projection, and the fields it forgets
    are the refusals, `requires_isbn_claim` at the head of them.

    `targets.py` falls out of the population by construction rather than by
    being named: it **defines** `Target`, so it does not import `targets`, so it
    is never in the set this sweeps. The first version exempted it by basename
    anyway, which a critic measured as dead today and as an exemption over an
    `rglob` sweep the day it fired: a second file called `targets.py` anywhere
    under `backend/` would have been forgiven, and this tree already carries the
    basename collision trap in its mypy and pytest configuration. Deleting the
    clause is the structural fix; making it compare paths would have kept a
    clause that cannot fire.

    **Whichever module defines `Target` is exempt wherever it lives**, for the
    one reason above and not because of its name. Measured, since the sentence
    that stood here said the opposite: with `Target` and its projection moved to
    a `rows.py` and `SEEDED` left behind, `rows.py` reads `(False, True)` and
    `targets.py` reads `(False, False)`, so neither is an offender and nothing
    fails.

    **What this cannot see, and a further arm is not the fix.**
    `dataclasses.replace(a_row.decoding, requires_isbn_claim=False)` imports
    `targets`, never spells `Decoding(`, and produces a waived decoding.
    `__post_init__` re-runs on a replace, so the MARC knob rule still holds, but
    `requires_isbn_claim` is precisely the field that cannot be checked in that
    module: the rule naming the one source that may waive it is keyed on
    `CatalogueSource`, which the contract may not import. Measured by a critic on
    this tree.

    It also matches `Decoding(` by spelling, so `from decoders import Decoding as
    D` evades it. Stated rather than answered with a further arm: the spellings
    are open and following the name to its binding is the machinery this
    repository's guards were rewritten to get rid of.
    """

    @staticmethod
    def _reads(path: pathlib.Path) -> tuple[bool, bool]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        holds_a_row = any(
            (isinstance(node, ast.Import) and any(alias.name == "targets" for alias in node.names))
            or (isinstance(node, ast.ImportFrom) and node.module == "targets")
            for node in ast.walk(tree)
        )
        builds = any(
            isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == "Decoding")
                or (isinstance(node.func, ast.Attribute) and node.func.attr == "Decoding")
            )
            for node in ast.walk(tree)
        )
        return holds_a_row, builds

    def test_no_module_that_can_reach_a_row_builds_one_itself(self):
        offenders = [
            path.relative_to(BACKEND).as_posix()
            for path in _production_sources()
            if all(self._reads(path))
        ]

        assert not offenders, offenders

    def test_the_projection_itself_is_what_this_reads(self):
        """The control, and it is also what makes the absent exception safe.

        Three claims, because the row above passes on a sweep that finds no
        builder at all, on one that reads no module holding a row, and on one
        that reads nothing.
        """
        assert self._reads(BACKEND / "targets.py") == (False, True)
        assert any(self._reads(path)[0] for path in _production_sources())
        assert len(_production_sources()) > 50


#: One source identifier of each family, shaped alike, so the only thing that
#: can separate them is which family they belong to.
_OF_FAMILY = {
    SourceFamily.CATALOGUE: CatalogueSource.K10PLUS.value,
    SourceFamily.IMPORT: "calibre_library",
}


class TestTwoFamiliesMeanTwoRegistries:
    """Every source family, asked whether it may answer a member's ISBN lookup.

    **The exclusion is derived from `SourceFamily` rather than listed**, so a
    family added later is covered without anybody remembering an arm, and it
    fails loudly if that family acquires the power the catalogue registry has.

    What it guards is a privacy refusal rather than a tidiness one, and the
    consequence is on `enums.SourceFamily`.
    """

    @staticmethod
    def _lookup_chain(identifier: str) -> list[str]:
        plan = sources.parse({"sources": [{"source": identifier, "enabled": True}]})
        return [name.value for name in plan.lookup_chain]

    @pytest.mark.parametrize("family", list(SourceFamily))
    def test_exactly_one_family_answers_a_lookup_and_it_is_the_catalogue(self, family):
        identifier = _OF_FAMILY[family]

        asked = self._lookup_chain(identifier)

        assert (identifier in asked) is (family is targets.FAMILY), family

    def test_a_plan_built_that_way_asks_anything_at_all(self):
        """The control the row above needs, or every arm of it could be passing
        because that plan asks nobody."""
        for identifier in _OF_FAMILY.values():
            assert self._lookup_chain(identifier)

    def test_what_refuses_the_other_family_is_the_registry_and_not_the_spelling(self):
        """The second control: the import name could be dropped for looking
        wrong rather than for being another family's.

        It is a well formed lower case identifier of the same shape as every
        catalogue value, and what it is not is a member of the catalogue
        registry's key space.
        """
        name = _OF_FAMILY[SourceFamily.IMPORT]

        assert name not in {source.value for source in CatalogueSource}
        assert name.replace("_", "").isalnum() and name.islower()

    def test_the_catalogue_registry_is_the_catalogue_family(self):
        """Which family `targets.SEEDED` is, in one line.

        **Not load bearing the way the identity spine's equivalent is, and that
        is measured rather than assumed.** Repointing `targets.FAMILY` at
        `IMPORT` fails this test **and** two arms of the parametrised test
        above. The spine's pin is the only failure for its own mutation because
        its parametrised test feeds the constant back in as the input it varies;
        here the identifiers are a fixed property of `CatalogueSource`, so
        repointing the constant breaks the correspondence rather than moving
        with it.

        Kept for two reasons that survive that. It fails with the sentence a
        reader needs rather than with a parametrised arm's, and the arms above
        go silent the day those identifiers are derived from the registry rather
        than named.
        """
        assert targets.FAMILY is SourceFamily.CATALOGUE


class TestTheCapabilityVocabularyIsSharedRatherThanCatalogueShaped:
    """`enums.Capability` is the half of the contract both families use."""

    def test_the_vocabulary_is_declared_where_both_families_can_reach_it(self):
        """In `enums.py`, not in `targets.py`.

        A capability vocabulary living in the catalogue registry's own module
        would make an importer import the catalogue roster to say it serves no
        ISBN, which is the merge two registries exist to refuse.
        """
        assert Capability.__module__ == "enums"
        assert SourceFamily.__module__ == "enums"

    @pytest.mark.parametrize("capability", list(Capability))
    def test_every_capability_is_asked_somewhere(self, capability):
        """A declared capability nothing reads is a flag, not a vocabulary.

        **The exclusion is the two modules that declare rather than ask**, and
        that was a correction: over `enums.py` alone every arm was satisfied by
        `targets.py`, which is the projection itself, so a member could be
        declared, projected and read by nothing and this stayed green.

        **`Capability.NAME` and not `NAME`**, measured: the bare name passed the
        `METERED` arm off `sources.METERED`, a frozenset of sources that is not
        this vocabulary and would still be there with the enum member deleted.
        """
        declares = {"enums", "targets"}
        asked = f"Capability.{capability.name}"
        readers = [
            path.name
            for path in BACKEND.glob("*.py")
            if path.stem not in declares and asked in path.read_text(encoding="utf-8")
        ]

        assert readers, capability


class TestEveryReaderBelongsToExactlyOneFamily:
    """`decoders.IMPORT_READERS` and `CATALOGUE_READERS` partition `Reader`.

    **Neither list is the rule on its own**, which is what this class exists to
    say. `targets.Target` refuses a reader in the first, so a member left out of
    it is admitted to the catalogue registry in silence: that is the
    `enums.SourceFamily` merge arriving with nothing red. A member left out of
    the second fails loudly at `targets.SEEDED`, which is built at module scope,
    but only if it is actually seeded.

    So the guard is the partition rather than either side, and a `Reader` added
    without being placed fails here.
    """

    def test_together_they_are_the_whole_enum(self):
        assert set(decoders.Reader) == (
            decoders.IMPORT_READERS | decoders.CATALOGUE_READERS
        )

    def test_no_reader_is_in_both(self):
        assert not decoders.IMPORT_READERS & decoders.CATALOGUE_READERS

    def test_neither_side_is_empty(self):
        """The control. Two empty sets are disjoint, and an empty import side is
        what a future edit would leave behind: the union test would then fail,
        but only because the catalogue side had to grow to cover it, which is a
        different failure than the one this class is about."""
        assert decoders.IMPORT_READERS
        assert decoders.CATALOGUE_READERS
