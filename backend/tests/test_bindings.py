"""`tests/bindings.py` says what a name means, and no new alias read is written beside it.

Two classes: what the resolver answers, on planted sources and on a real
module through both adapters, and the ratchet that holds every other function
to the reads of an import alias it still makes.
"""

import ast
import os
from collections import Counter
from types import ModuleType
from typing import Final

import pytest

from tests import corpus
from tests.bindings import ModuleNames, SourceNames, source_of, stated
from tests.corpus import BACKEND, suite_modules


def _means(source: str, expression: str, package: str | None = None) -> set[str]:
    return set(SourceNames(source, package=package).means(ast.parse(expression, mode="eval").body))


class TestWhatANameMeans:
    """One answer per spelling a guard's author writes by accident."""

    @pytest.mark.parametrize(
        ("source", "expression", "meaning"),
        [
            ("import httpx", "httpx.get", {"httpx.get"}),
            ("import httpx as h", "h.get", {"httpx.get"}),
            ("import os.path", "os.path.join", {"os.path.join"}),
            ("import os.path as p", "p.join", {"os.path.join"}),
            ("from models import Book as B", "B", {"models.Book"}),
            ("import metadata\nm = metadata", "m.lookup", {"metadata.lookup"}),
            ("x: object = models.Book\nimport models", "x", {"models.Book"}),
            ("a = b\nb = c\nimport httpx as c", "a", {"httpx"}),
            ("def walk(node):\n    pass", "walk", set()),
            ("corpus = load()", "corpus", set()),
        ],
        ids=[
            "a module",
            "an aliased module",
            "a dotted module",
            "an aliased dotted module",
            "an aliased name",
            "a module bound to a local",
            "an annotated rebinding above its import",
            "a chain written backwards",
            "a function this module defines",
            "a call's result",
        ],
    )
    def test_a_name_means_what_it_was_bound_to(
        self, source: str, expression: str, meaning: set[str]
    ) -> None:
        assert _means(source, expression) == meaning

    @pytest.mark.parametrize(
        ("source", "expression", "meaning"),
        [
            ("import os\nos = os.path", "os", {"os", "os.path"}),
            ("import os\nos = os.path\nx = y\nz = w", "os", {"os", "os.path"}),
            ("import os\na = os\nos = a.path\nx = y\nz = w", "os", {"os", "os.path"}),
            ("import os as a\nimport httpx as b\na = b\nb = a", "a", {"os", "httpx"}),
            ("import mod\nx = mod\nx = x.sub", "x", {"mod", "mod.sub"}),
            ("import mod\nx = mod.sub\nx = x.Thing", "x", {"mod.sub", "mod.sub.Thing"}),
            ("import os\nw = os\nw = w.path", "w", {"os", "os.path"}),
        ],
        ids=[
            "rebound through itself",
            "rebound through itself beside unrelated assignments",
            "rebound through another local",
            "two names bound to each other",
            "a module bound to a local, then refined through it",
            "a name bound to a local, then refined through it",
            "a module bound to a local, then refined to a submodule",
        ],
    )
    def test_a_name_bound_twice_means_both(
        self, source: str, expression: str, meaning: set[str]
    ) -> None:
        """Flow insensitive, so a guard over-reports rather than missing one, and
        a rebinding through the name itself adds one meaning however long the module."""
        assert _means(source, expression) == meaning

    def test_a_relative_import_resolves_only_against_a_package(self) -> None:
        assert _means("from . import corpus", "corpus", package="tests") == {"tests.corpus"}
        assert _means("from .. import corpus", "corpus", package="tests.routers") == {
            "tests.corpus"
        }
        assert _means("from . import corpus", "corpus") == {".corpus"}

    def test_an_import_answers_both_its_names(self) -> None:
        names = SourceNames("from models import UserBook as UB\nalias = UB\n")

        assert names.imported() == {"UB", "UserBook"}
        assert names.bound_to("models.UserBook") == {"UB", "alias"}

    def test_a_star_binds_only_where_the_module_is_handed_over(self) -> None:
        source = "from tests.corpus import *"

        assert SourceNames(source).bound_to("tests.corpus.suite_modules") == set()
        expanded = SourceNames(source, star=lambda _: corpus)
        assert "suite_modules" in expanded.bound_to("tests.corpus.suite_modules")
        assert expanded.bound_to("tests.corpus._walk") == set()
        relative = SourceNames("from . import *", star=lambda _: corpus)
        assert "suite_modules" in relative.bound_to(".suite_modules")

    def test_both_adapters_agree_on_a_name_imported_from_where_it_is_defined(self) -> None:
        """Compared on three names `corpus.py` imports from their defining module."""
        source = SourceNames((BACKEND / "tests" / "corpus.py").read_text(encoding="utf-8"))
        module = ModuleNames(corpus)
        for spelled in ("ignore_patterns", "is_ignored", "os.walk"):
            expression = ast.parse(spelled, mode="eval").body

            assert source.means(expression) == module.means(expression), spelled

    def test_the_adapters_part_on_a_re_export_and_on_a_definition(self) -> None:
        """The source answers the import path; the module answers the defining home."""
        planted = ModuleType("planted")
        planted.join = os.path.join  # type: ignore[attr-defined]
        join = ast.parse("join", mode="eval").body
        defined = ast.parse("suite_modules", mode="eval").body
        source = SourceNames((BACKEND / "tests" / "corpus.py").read_text(encoding="utf-8"))

        assert SourceNames("from os.path import join").means(join) == {"os.path.join"}
        assert ModuleNames(planted).means(join) == {f"{os.path.join.__module__}.join"}
        assert source.means(defined) == set()
        assert ModuleNames(corpus).means(defined) == {"tests.corpus.suite_modules"}

    def test_the_module_adapter_reads_the_value_itself(self) -> None:
        assert ModuleNames(corpus).value(ast.parse("REPO.name", mode="eval").body) == (
            corpus.REPO.name
        )


#: Every published module under `backend/tests` that reads an import alias, and
#: how many reads each function makes.
#:
#: **Equality, keyed by the enclosing function**, so a new read reds by name,
#: and so does one removed without its row moving or one moved to another
#: function. A guard asking what a name means asks `tests/bindings.py`; a row
#: here is a resolver not yet moved there, or a read that resolves nothing. A
#: module the mirror strips states its own in `ASNAME_READS_OF_MY_OWN`, for the
#: reason `tests.bindings.stated` gives. Lower a row when a read goes.
ASNAME_READS: Final[dict[str, dict[str, int]]] = {
    # The home.
    "bindings.py": {"SourceNames.__init__": 3},
    "routers/test_concurrency_bounds.py": {"_concurrency_classes": 2},
    "routers/test_imports_marc.py": {"TestNoProductionModuleWritesAWholeCollection.calls_to_write": 1},
    "routers/test_settings.py": {
        "TestEverySettingsWriteClearsWhatItInvalidates.test_no_write_bypasses_the_helper": 1,
    },
    "test_book_columns.py": {"_names_read_outside_the_tests": 1},
    "test_catalogue.py": {
        "TestARecordAgreesWithTheColumnsItFeeds."
        "test_every_ceiling_comes_from_the_module_that_declares_the_columns": 1,
    },
    "test_classifications.py": {"_imported": 3},
    "test_cover_store.py": {"_names_used": 1},
    "test_coverage_register.py": {"_pytest_bindings": 2, "_written_to": 2},
    "test_database.py": {
        "TestEveryEngineHidesItsParameters.test_no_engine_builder_is_imported_under_another_name": 1,
        "_binds": 1,
    },
    "test_deadline.py": {"_what_this_module_imported": 3},
    "test_fields.py": {"_definition_bindings": 2},
    "test_folding.py": {"_read_roots": 1},
    "test_house_rules.py": {
        "_dataclasses_modules": 1,
        "_elementtree_names": 4,
        "_loan_names": 1,
        "_model_names_safe_to_resolve": 2,
        "_parse_sites": 4,
        "_replace_aliases": 1,
    },
    "test_marc.py": {"TestNoModuleReadsAnotherModulesPrivateNames._private_reads": 1},
    "test_metadata.py": {"TestTheCarrierTestIsTheOnlyWayIn._functions": 1},
    "test_models.py": {"_note_aliases": 2},
    "test_notifications.py": {
        "TestWhoTheInAppNoticeIsFor.test_the_mode_arm_is_decided_in_exactly_one_place": 2,
    },
    "test_schema.py": {
        "TestTheBoundsThisRevisionPutOnBytes."
        "test_no_router_reaches_the_module_by_a_name_this_walk_cannot_see": 2,
    },
    "test_settings_store.py": {"_imported_modules": 3, "_reader_bindings": 1, "_store_aliases": 1},
    "test_shelf.py": {
        "TestTheShelfIsTheOnlyWayIn.test_the_superseded_expression_let_the_aliases_and_the_stars_past."
        "superseded": 1,
        "_module_level_names": 1,
        "_predicate_calls": 1,
        "_sqlalchemy_names": 2,
    },
    "test_tags.py": {"_bindings": 2, "_binds_tag_to_something_else": 2},
}


def _asname_reads(source: str) -> dict[str, int]:
    """How many times each function in `source` reads `asname` off a node.

    Keyed by the dotted names of the classes and functions around the read,
    `<module>` outside all of them. Past it: `getattr`, which is deliberate,
    and a class pattern, `case ast.alias(asname=a)`, which no module here writes.
    """
    counts: Counter[str] = Counter()

    def visit(node: ast.AST, around: tuple[str, ...]) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            around = (*around, node.name)
        if isinstance(node, ast.Attribute) and node.attr == "asname":
            counts[".".join(around) or "<module>"] += 1
        for child in ast.iter_child_nodes(node):
            visit(child, around)

    visit(ast.parse(source), ())
    return dict(counts)


class TestOnlyTheResolverReadsAnAlias:
    """No function reads an import alias beyond the reads stated for it.

    **A ratchet on reads rather than a policing of each resolver.** The copies
    this replaces disagreed about rebinding and about which of an import's two
    names to answer, and each was right for the spellings its author tried.
    The application and the migrations are not read: neither can import a
    test module.
    """

    def test_only_the_stated_modules_read_an_alias(self) -> None:
        tests = BACKEND / "tests"
        sources = {path.relative_to(tests).as_posix(): source_of(path) for path in suite_modules()}
        wrong = {
            relative: f"{reads} read, {allowed} stated"
            for relative, source in sources.items()
            if (reads := _asname_reads(source))
            != (allowed := stated(source, relative, ASNAME_READS, "ASNAME_READS_OF_MY_OWN", {}))
        }

        assert wrong == {}, (
            "a module reads an import alias itself, or stopped. Ask "
            "tests/bindings.py what a name means instead; lower a row here when "
            "a read goes."
        )
        assert set(ASNAME_READS) <= set(sources), sorted(set(ASNAME_READS) - set(sources))

    @pytest.mark.parametrize(
        ("source", "reads"),
        [
            ("{a.asname or a.name for a in node.names}", {"<module>": 1}),
            ("local = alias.asname\nother = node.names[0].asname", {"<module>": 2}),
            (
                "def f(alias):\n    return alias.asname\n"
                "class C:\n    def g(self, alias):\n        return [alias.asname]",
                {"f": 1, "C.g": 1},
            ),
            ('getattr(alias, "asname")', {}),
            ('"alias.asname"', {}),
        ],
    )
    def test_what_counts_as_a_read(self, source: str, reads: dict[str, int]) -> None:
        assert _asname_reads(source) == reads
