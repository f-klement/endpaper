"""Tests for backend/dialect.py, and for what the two arms owe each other.

`test_dialect_portability.py` holds the query side and the indexes. This file
holds the construct and the CHECK constraints, which is where the two engines'
SQL actually differs.

**What each class here can and cannot see**, because a guard that reads thorough
gets believed:

* `TestTheTwoSpellings` is the construct alone: two arms, a refusal for every
  other named dialect, and the stringifier. It says nothing about any constraint.
* `TestTheTwoWalksOverTheRevisionsAgree` is what arms the two rule walks
  below, and it is here rather than inside either of them because they share
  their readers. It says nothing about any rule: it says the two ways this
  file has of enumerating `migrations/versions/` still agree about what is in
  it, and both of its instruments are the functions the rules themselves call.
* `TestTheRevisionsPostgresArmIsTheModelsPostgresArm` is the second engine's
  copy of a comparison that already existed for the first: a revision writes its
  SQL out rather than importing it, so the two copies are a fact stored twice.
  **The revisions it covers are found by type rather than listed**, for both
  rule shapes, so one that carries a rule table is covered the moment it exists.
  For a swapped rule the comparison is a **chain**: each revision's arm is the
  next one's starting point and the last is the model. For an added rule there
  is no chain, and the arm saying so is
  `::test_every_addition_is_still_the_last_text_of_its_chain`.
* `TestEveryCheckRendersWithoutASqliteOnlyIdiom` is parametrised over
  `Base.metadata`, so a constraint added to a model is covered the moment it
  exists. **It is a token scan, and a token scan is an enumeration of an open
  set**: a SQLite only function nobody has listed renders happily and goes
  green. The instrument that does not have that hole is the pipeline's
  `test:postgres` job, which creates the schema on a real server.
* `TestEveryNulArmDroppedOnACharacterColumn` is the guard under a sentence: the
  NUL arm is dropped on Postgres because a character type there cannot hold the
  byte, and that is a property of the **column type**, not of the engine. A
  `bytea` column takes a NUL freely.
* `TestNoSqliteArmLostAClause` is the per engine arm count. **It cannot see a
  clause deleted from both arms**, which is what the two engine corpus in
  `test_backup.py` is for.
* `TestTheInstalledCheckIsTheModelsCheck` is the hole in the token scan,
  closed by asking the server instead of scanning the text: the model's own
  schema is built beside the migrated one and both are read back through the
  same reflection, so the server's rendering cancels. It runs on both engines
  and skips on neither; its own class docstring states what it sees and what
  it does not.
"""

from collections.abc import Collection, Iterator, Mapping
from contextlib import contextmanager
from itertools import pairwise
from types import ModuleType
from typing import Final

import pytest
from sqlalchemy import (
    CheckConstraint,
    MetaData,
    String,
    Text,
    create_engine,
    exc,
    inspect,
    text,
)
from sqlalchemy.dialects import mysql, postgresql, sqlite
from sqlalchemy.engine import Inspector
from sqlalchemy.schema import CreateTable

from database import Base, engine
from dialect import AddedRule, DialectSQL, SwappedRule, for_bind
from models import Book  # noqa: F401  registers every table on Base.metadata

SQLITE = sqlite.dialect()
POSTGRESQL = postgresql.dialect()

#: Spellings SQLite has and Postgres does not. **An enumeration, and it is named
#: as one**: this is the set that has actually appeared in this schema, not the
#: set that exists. Measured 2026-09-17: a count of the chain's offending
#: revisions derived from the first three of these tokens put the first failure
#: at the twelfth revision, and running the chain put it at the eighth, on a
#: boolean column assigned an integer.
SQLITE_ONLY = ("GLOB", "instr(", "char(0)", "AS BLOB", "typeof(")


def _checks(table) -> list[CheckConstraint]:
    return [one for one in table.constraints if isinstance(one, CheckConstraint)]


def _dialect_checks() -> list[tuple[str, str, DialectSQL]]:
    """Every CHECK in the schema whose body is a `DialectSQL`, as
    `(table, constraint, element)`.

    **Sorted, and that is not tidiness.** `Table.constraints` is a `set`, so its
    iteration order varies between processes, and this list is a parametrisation:
    xdist compares what each worker collected and refuses the run when two
    disagree. Measured, that is exactly what happened, and it is the same
    nondeterminism that makes a raw `sqlite_master` diff a noisy instrument.
    """
    found = []
    for name, table in Base.metadata.tables.items():
        for check in _checks(table):
            if isinstance(check.sqltext, DialectSQL):
                found.append((name, str(check.name), check.sqltext))
    return sorted(found, key=lambda row: (row[0], row[1]))


def _declared(table_name: str, constraint: str, dialect) -> str:
    """One CHECK as `models.py` declares it for one dialect, whitespace
    normalised. Safe to normalise here: no constraint in this schema holds a
    string literal with internal whitespace."""
    check = next(
        one for one in _checks(Base.metadata.tables[table_name]) if one.name == constraint
    )
    return " ".join(str(check.sqltext.compile(dialect=dialect)).split())


class TestTheTwoSpellings:
    """One construct, one spelling per engine, and a refusal for the rest."""

    ELEMENT = DialectSQL(sqlite="instr(x, char(0)) = 0", postgresql="TRUE")

    def test_sqlite_gets_the_sqlite_arm(self):
        assert str(self.ELEMENT.compile(dialect=SQLITE)) == "instr(x, char(0)) = 0"

    def test_postgres_gets_the_postgres_arm(self):
        assert str(self.ELEMENT.compile(dialect=POSTGRESQL)) == "TRUE"

    def test_a_third_dialect_is_refused_at_compile_time(self):
        """Loudly, and naming where to fix it.

        Without the raise, a third engine receives one of these two spellings
        inside a security bound and nothing anywhere says so.
        """
        with pytest.raises(exc.CompileError, match="no spelling for the mysql dialect"):
            self.ELEMENT.compile(dialect=mysql.dialect())

    def test_the_stringifier_answers_with_the_sqlite_arm(self):
        """`str()` compiles against `DefaultDialect`, which is how every reader
        of a constraint's text in this tree asks what a bound says."""
        assert str(self.ELEMENT) == "instr(x, char(0)) = 0"


class TestTheseAreTheConstraintsWithTwoSpellings:
    """The whole set, named, so the figure in the ADR is re-derivable.

    **Named rather than counted, because a count was wrong by one.** The first
    write up of this work said thirteen, read off a diff by hand, and missed
    `ck_catalogue_targets_isbn_claim`: the boolean comparison, which is the one
    that carries none of the SQLite only tokens anybody had grepped for and is
    therefore the one a reader's eye slides past. A number written down stops
    being re-derived and starts being copied; this recomputes it from the
    metadata.
    """

    def test_the_named_set(self):
        assert {(table, constraint) for table, constraint, _ in _dialect_checks()} == {
            ("author_identifiers", "ck_author_identifiers_bounds"),
            ("book_identifiers", "ck_book_identifiers_bounds"),
            ("catalogue_credentials", "ck_catalogue_credentials_envelope"),
            ("catalogue_credentials", "ck_catalogue_credentials_source"),
            ("catalogue_targets", "ck_catalogue_targets_base_url"),
            ("catalogue_targets", "ck_catalogue_targets_indexes"),
            ("catalogue_targets", "ck_catalogue_targets_isbn_claim"),
            ("catalogue_targets", "ck_catalogue_targets_use_attribute"),
            ("custom_field_values", "ck_custom_field_values_bounds"),
            ("custom_fields", "ck_custom_fields_name_bounds"),
            ("digital_references", "ck_digital_references_bounds"),
            ("opds_servers", "ck_opds_servers_base_url"),
            ("opds_servers", "ck_opds_servers_credential_key"),
            ("opds_servers", "ck_opds_servers_name"),
            ("quotes", "ck_quotes_text_bounds"),
        }

    def test_nine_of_the_twenty_two_tables_carry_one(self):
        """The other half of the ADR's sentence, from the same source. A set of
        names and a count of tables are two different claims, and stating both
        here is what stopped the first one going out with the wrong number."""
        assert len({table for table, _, _ in _dialect_checks()}) == 9
        assert len(Base.metadata.tables) == 22


class TestTheStringifierIsNotAnEngine:
    """The sentence `dialect.py` rests on, as a check rather than a comment.

    The `default` arm exists so `str(constraint.sqltext)` keeps answering, and
    it is safe only while no database connection reports that name.
    """

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("sqlite://", "sqlite"),
            ("postgresql+pg8000://u:p@example.invalid/db", "postgresql"),
        ],
    )
    def test_an_engine_names_itself(self, url: str, expected: str):
        """`create_engine` resolves a concrete dialect and every concrete
        dialect names itself, so nothing this application opens can land on the
        `default` arm. Built rather than connected: this asks what the dialect
        is called, not whether a server answers."""
        name = create_engine(url).dialect.name

        assert name == expected
        assert name != "default"


def _revision_modules() -> dict[str, ModuleType]:
    """Every module under `migrations/versions/`, by the revision it declares.

    **The corpus both rule walks stand on, and therefore the one thing neither
    of them can arm.** A narrowing written here shrinks both populations at
    once and every rule over them goes on passing, over a corpus nobody chose.
    `TestTheTwoWalksOverTheRevisionsAgree` is what holds it, placed beside
    this reader rather than inside either walk, because a walk that reads this
    one inherits the hole rather than noticing it.

    **Keyed on `revision` rather than on the module name**, because that is what
    `down_revision` points at and what `_in_chain_order` reads.
    """
    import importlib
    import pkgutil

    import migrations.versions as versions

    found: dict[str, ModuleType] = {}
    for module_info in pkgutil.iter_modules(versions.__path__):
        module = importlib.import_module(f"migrations.versions.{module_info.name}")
        found[module.revision] = module
    return found


def _rules_in[RuleT: tuple](
    namespace: Mapping[str, object], shape: type[RuleT]
) -> list[RuleT]:
    """Every rule of `shape` one module's namespace declares.

    **A namespace rather than a module, so this can be driven.** What it does
    is a pure function of a mapping, and taking the mapping is the whole of
    what lets `TestTheScanOverAModulesNamespace` hand it one case instead of
    the branch resting at the rung where a comment is the only thing holding
    it.

    **Two shapes are admitted: a bare rule, and a rule carrying
    collection that is not text.** The first version took a tuple alone; a
    list, a bare rule and a `frozenset` each went green carrying deliberately
    wrong SQL on both engines, while the identical payload as a tuple reddened
    the comparisons by name, so each green was about the container rather than
    about the rule. Both a list and a mapping are live module level idioms in
    `migrations/versions/` rather than hypotheses.

    **The bare rule is the one a reader misses**, and it is checked first for
    a reason that reads as a redundancy: a `NamedTuple` instance is itself a
    tuple, so it reaches the collection branch and is measured by its own
    string fields, which match no shape.

    **A mapping is read by its values**, because a rule table keyed by name is
    the shape a dictionary takes here, and iterating a mapping yields keys.

    **What is left open is a mechanism and the extent is not claimed.**
    Membership is `all`, and it has to be, or a collection holding one rule
    beside nine unrelated values would answer for the shape. So a collection
    mixing the two rule shapes, or holding a rule beside anything else, is in
    neither population, and so is a rule reached through anything that is not
    a collection of its own.
    """
    rules: list[RuleT] = []
    for value in namespace.values():
        if isinstance(value, shape):
            rules.append(value)
            continue
        if isinstance(value, str | bytes) or not isinstance(value, Collection):
            continue
        members = [
            one
            for one in (value.values() if isinstance(value, Mapping) else value)
            if isinstance(one, shape)
        ]
        if len(members) == len(value):
            rules.extend(members)
    return rules


def _revisions_carrying[RuleT: tuple](
    shape: type[RuleT],
) -> dict[str, tuple[RuleT, ...]]:
    """Every revision declaring a table of `shape`, by revision id.

    **Found by type rather than by name, and the type is the fact.** A first
    version of this was a list of three revisions and their tables, because they
    are spelled `_CEILINGS`, `_GLOB_RULES` and `_SWAPPED` and a frozen revision
    cannot be renamed. The spelling is not what makes one of these a rule table;
    the element type is. So a revision carrying one is covered the moment it
    exists, where a list was a line somebody had to remember, and the standing
    rule says to derive rather than to add a case per spelling.

    **One walk for both shapes, rather than one per shape.** `AddedRule` had no
    walk at all and was reached through the single revision that declares one,
    so for any other revision **nothing compared an added rule's own text with
    the model's**. On SQLite a disagreement would still surface once that
    revision ran, as a disagreement between the migrated schema and the model
    in `test_schema.py::TestTheMigrationsAndTheModelsAgree`; on Postgres
    nothing in this suite can, because there is no Postgres in it. The two
    shapes differ in what a revision does with them, not in how a reader finds
    them, and a second copy of this function is the second place a narrowing
    has to be noticed.

    The scan itself is `_rules_in`, which takes a namespace rather than a
    module so it can be driven directly.
    """
    carrying: dict[str, tuple[RuleT, ...]] = {}
    for revision, module in _revision_modules().items():
        rules = _rules_in(vars(module), shape)
        if rules:
            carrying[revision] = tuple(rules)
    return carrying


def _alembics_chain() -> list[str]:
    """Every revision Alembic chains, oldest first.

    **One reader, because this file had two copies of this walk and an arm over
    one of them.** `_revisions_carrying`'s docstring states the rule and the
    first version of this arming broke it one function away: the agreement arm
    read a copy of its own and `_in_chain_order` kept another, so narrowing the
    chain reader's copy to the revisions that carry a rule left the run byte
    for byte identical to the baseline. **No count beside that**, deliberately:
    it would be a total over a corpus holding the file it is written in, so
    the next test added here falsifies it in silence, and the zero difference
    is the whole of what the sentence argues from anyway. Both callers read
    this now, so a narrowing has one place to be written and the arm is over
    the walk that is used rather than beside it.

    It is the second instrument in `TestTheTwoWalksOverTheRevisionsAgree`, and
    it degrades differently from the first on purpose: this globs the directory
    and chains what it finds on `down_revision`, where `_revision_modules`
    imports a package and reads `revision`.
    """
    from alembic.script import ScriptDirectory

    import schema

    return [
        revision.revision
        for revision in reversed(
            list(
                ScriptDirectory.from_config(schema._alembic_config()).walk_revisions()
            )
        )
    ]


def _in_chain_order(revisions: list[str]) -> list[str]:
    """Those revisions, oldest first, according to Alembic's own chain.

    **Derived rather than declared, because the comparison below is a chain.** A
    constraint two revisions have rewritten has three texts to keep in step on
    Postgres and only the last of them is the model's, so the order decides which
    text is compared with which. A hand written order is a fact that can be wrong
    silently; `down_revision` is the fact the migration runner itself uses, and
    `pkgutil` hands the modules over in filename order, which is no order at all.
    """
    oldest_first = _alembics_chain()
    return sorted(revisions, key=oldest_first.index)


def _swap_chain() -> dict[str, list[tuple[str, SwappedRule]]]:
    """Each constraint's swaps, oldest first, with the revision that made each."""
    tables = _revisions_carrying(SwappedRule)
    chain: dict[str, list[tuple[str, SwappedRule]]] = {}
    for name in _in_chain_order(list(tables)):
        for rule in tables[name]:
            chain.setdefault(rule.constraint, []).append((name, rule))
    return chain


def _added_rules() -> list[tuple[str, AddedRule]]:
    """Every `AddedRule` any revision declares, with the revision that made it,
    oldest revision first.

    **Sorted, and not for determinism.** `pkgutil.iter_modules` sorts the
    filenames itself, so the order is already the same on every worker and the
    xdist collection check this file's other sort was written for does not
    arise here. The reason is the reader: `vars()` hands a module's tables over
    in definition order, which is an order but not one somebody reading a
    failure would recognise, and chain order is the order the rest of this
    file argues in.

    **Read by `test_schema.py` as well**, which holds the SQLite half of the
    comparison this file holds the Postgres half of. One walk, so a narrowing
    is one place rather than two that drift.
    """
    carrying = _revisions_carrying(AddedRule)
    return [
        (revision, rule)
        for revision in _in_chain_order(list(carrying))
        for rule in sorted(
            carrying[revision], key=lambda one: (one.table, one.constraint)
        )
    ]


#: Bound once rather than called per parametrisation, and **the cost is
#: Alembic's chain rather than the imports**. The package walk goes through
#: `sys.modules`, so a second call re-executes nothing; `ScriptDirectory` does
#: not, so every chain build re-executes every revision file. Driven, with a
#: module level side effect in three revisions and each walk called twice in
#: one process: the package walk re-executed 0 of 3, the chain walk 3 of 3. A
#: decorator calling this for its arguments and again for its ids would pay
#: that per parametrisation. `test_schema.py` imports both of these rather
#: than calling either again, which is a second reason beside the one stated
#: there.
ADDED_RULES: Final = _added_rules()

#: The same, for the chain, which both files read at import.
SWAP_CHAIN: Final = _swap_chain()


def _swap_rows() -> list[tuple[str, str, str]]:
    """Every swap any revision makes, as `(revision, table, constraint)`, in
    chain order. Held against `THE_SWAPS` from both files that read the
    chain."""
    return [
        (revision, rule.table, rule.constraint)
        for constraint in sorted(SWAP_CHAIN)
        for revision, rule in SWAP_CHAIN[constraint]
    ]


#: Every swap the revisions make today, written down.
#:
#: **One literal, asserted from two files.** `test_schema.py` reads the chain
#: too, and a targeted run of one file is what this repository recommends
#: while implementing, so an exact list in one of them is green on exactly the
#: narrowing it exists to catch whenever the other is the file being run. The
#: fact has one home and two arms rather than two copies.
THE_SWAPS: Final = [
    ("f4a1c62d0b97", "author_identifiers", "ck_author_identifiers_bounds"),
    ("b8f4c1a7e309", "book_identifiers", "ck_book_identifiers_bounds"),
    ("b8f4c1a7e309", "catalogue_credentials", "ck_catalogue_credentials_envelope"),
    ("a6d3f92c7b14", "catalogue_targets", "ck_catalogue_targets_indexes"),
    ("b8f4c1a7e309", "catalogue_targets", "ck_catalogue_targets_indexes"),
    ("f4a1c62d0b97", "custom_field_values", "ck_custom_field_values_bounds"),
    ("f4a1c62d0b97", "custom_fields", "ck_custom_fields_name_bounds"),
    ("a6d3f92c7b14", "opds_servers", "ck_opds_servers_base_url"),
    ("f4a1c62d0b97", "opds_servers", "ck_opds_servers_name"),
    ("f4a1c62d0b97", "quotes", "ck_quotes_text_bounds"),
]


class TestTheScanOverAModulesNamespace:
    """`_rules_in`, driven directly rather than through a revision.

    **Here because a comment was the only thing holding the branch order.**
    The bare rule case has to run before the collection case, since a
    `NamedTuple` is a tuple; moving it after, the way a tidy up would, loses
    every bare rule, and was green on the whole file.
    A reader can correctly observe that a named tuple is a tuple and conclude
    the branch is dead, which is a strong invitation to delete it.

    What the scan does is a pure function of a mapping, so arming it costs one
    case per spelling rather than a revision per spelling.
    """

    SWAPPED = SwappedRule("t", "ck_t", "a", "a_pg", "b", "b_pg")
    ADDED = AddedRule("t", "ck_t", "sqlite", "postgresql")

    def test_a_bare_rule_is_found(self):
        """The case the branch order decides. It reds when the two branches
        are swapped, which no revision in the tree would show today."""
        assert _rules_in({"_RULE": self.ADDED}, AddedRule) == [self.ADDED]

    @pytest.mark.parametrize(
        "container",
        [
            (ADDED,),
            [ADDED],
            frozenset({ADDED}),
            {ADDED},
            {"by name": ADDED},
        ],
        ids=["tuple", "list", "frozenset", "set", "mapping"],
    )
    def test_a_rule_carrying_collection_is_found(self, container: object):
        """Every container spelling, including the two that are not sequences
        and the mapping, which is read by its values because iterating one
        yields keys."""
        assert _rules_in({"_RULES": container}, AddedRule) == [self.ADDED]

    def test_every_rule_a_container_carries_is_found(self):
        """The membership test is arithmetic and a one element container
        cannot see it: narrowing it to the first rule leaves every case above
        green, because every one of them carries exactly one."""
        second = AddedRule("u", "ck_u", "sqlite u", "postgresql u")

        assert _rules_in({"_RULES": (self.ADDED, second)}, AddedRule) == [
            self.ADDED,
            second,
        ]

    def test_the_scan_finds_the_swapped_shape_when_that_is_the_shape_asked_for(
        self,
    ):
        """Both shapes are read through this one scan, and `SwappedRule` is
        the one no other case here passes as `shape`. A narrowing written
        against the added shape alone would be invisible to all of them."""
        assert _rules_in({"_RULES": (self.SWAPPED,)}, SwappedRule) == [self.SWAPPED]

    def test_the_other_shape_is_not_this_population(self):
        """The two shapes share this scan and must not share a population."""
        assert _rules_in({"_RULES": (self.SWAPPED,)}, AddedRule) == []
        assert _rules_in({"_RULE": self.SWAPPED}, AddedRule) == []

    def test_a_rule_beside_anything_else_is_in_neither_population(self):
        """The mechanism the docstring names, as a case rather than a
        sentence: membership is `all`, so this is the open edge."""
        assert _rules_in({"_RULES": (self.ADDED, "a string")}, AddedRule) == []

    def test_text_is_not_a_collection_of_rules(self):
        """`str` and `bytes` are collections, so without the exclusion a
        module constant would be scanned character by character."""
        assert _rules_in({"_NAME": "ck_t", "_RAW": b"ck_t"}, AddedRule) == []


class TestTheTwoWalksOverTheRevisionsAgree:
    """What arms both rule walks, at the readers they share.

    **Named for the agreement, not for the extent.** A first version of this
    was called "reaches every revision", which is wider than anything here
    holds: what is asserted is that this file's two ways of enumerating
    `migrations/versions/` describe the same set, and the name is the sentence
    a reader of a failure sees first.

    `_revisions_carrying` derives its population by importing every module
    under `migrations/versions/`, and two rules read that population: the
    Postgres chain below and the added rule comparison beside it. **A narrowing
    written in `_revision_modules` moves both together**, so no comparison
    between them can see it.

    **And neither can a non emptiness assertion over either population**, which
    is what the chain already had and the obvious thing to give the added walk
    beside it. Most revisions carry no rule table at all, so a walk narrowed to
    the handful that carry one today leaves both populations exactly as they
    are. Driven with that narrowing in place: every other arm in this file is
    green, and the first one below is the only thing that reds. A floor is
    worse again: the added population is one rule, and there is no room under
    one.

    So `_revision_modules` is held against `_alembics_chain`, which degrades
    differently: it globs the directory and chains what it finds on
    `down_revision`, where the package walk imports a module and reads
    `revision`. A filter written into either one is a disagreement here rather
    than a smaller corpus nobody sees. **Both of this class's instruments are
    the functions the rules themselves call**, which is the repair of a first
    version whose second instrument was a third copy of the Alembic walk:
    narrowing the copy `_in_chain_order` was using left this class green and
    the whole file byte for byte at the baseline. Said of the instruments
    rather than of the arms, because the second arm reads one of the two.

    **What an agreement cannot report is the two sides narrowing together**, by
    a filter written into both. A revision file simply going missing is not
    that case and is loud already: Alembic raises on the dangling
    `down_revision` the gap leaves, naming it, and a file lost from the head
    end takes its schema work with it. **That raise comes out of
    `_alembics_chain`, so it surfaces in the arm below** and at collection,
    rather than somewhere a reader of this has to go and find. The second arm
    covers the far end, an empty corpus. Between the two there is a band this
    says nothing about.
    """

    def test_the_package_walk_and_alembics_chain_find_the_same_revisions(self):
        found = set(_revision_modules())
        walked = set(_alembics_chain())

        assert found == walked, (
            "the package walk and Alembic's own chain disagree about which "
            "revisions exist, so every rule derived from one of them is over a "
            f"corpus nobody chose: {sorted(found ^ walked)}"
        )

    def test_there_is_a_revision_to_walk_over(self):
        """The arm above is an agreement, and two walks agree perfectly over no
        revisions at all. That is the one shape it cannot report, so it is the
        one asserted separately."""
        assert _revision_modules(), (
            "no revision module was found at all, so every walk over them is "
            "empty and every rule derived from one passes over nothing"
        )


class TestTheRevisionsPostgresArmIsTheModelsPostgresArm:
    """The second engine's half of a comparison that already existed.

    A revision spells its SQL out rather than importing a constant, for the
    reason every revision here gives, so each rule is a fact stored twice and
    `test_schema.py` stands between the SQLite copies. This stands between the
    Postgres ones, which nothing else reads at all: there is no Postgres in this
    suite, so a database cannot be asked.

    **Two rules rather than one per revision, because the copies form a chain.**
    What the model declares is the **last** revision's `after_pg`; what an
    earlier revision owes is that its `after_pg` is the next one's `before_pg`.
    Together those cover every text in every table with no gap, and neither can
    be satisfied by a revision quietly agreeing with itself.
    """

    def test_each_revisions_arm_is_the_next_ones_starting_point(self):
        """The links, which is what a per revision comparison against the model
        could not express.

        `before_pg` is otherwise read by nothing at all on this engine: a
        `downgrade()` installs it and no test here runs one, so a wrong value
        would break only the way back, in the one situation nobody is watching.
        """
        broken = [
            (constraint, earlier_name, later_name)
            for constraint, swaps in SWAP_CHAIN.items()
            for (earlier_name, earlier), (later_name, later) in pairwise(swaps)
            if " ".join(earlier.after_pg.split())
            != " ".join(later.before_pg.split())
        ]

        assert not broken, (
            "a revision's Postgres arm is not what the next one says it found, "
            f"so one of the two describes a schema nobody ran: {broken}"
        )

    def test_the_chain_has_a_link_to_check(self):
        """Anti vacuity, and deliberately not a count. The rule above is empty
        both when every link holds and when no constraint has been rewritten
        twice, and a number here would go stale the first time one is.

        **The walk's own emptiness is the other way this could go quiet**, since
        a reader that stopped recognising a rule table would hand back nothing
        and every rule here would pass over it. So the revisions are asserted
        before the links are.
        """
        assert _revisions_carrying(SwappedRule), (
            "no revision was found to carry a table of swapped rules, so every "
            "comparison in this class is over an empty chain"
        )
        assert [
            constraint for constraint, swaps in SWAP_CHAIN.items() if len(swaps) > 1
        ]

    def test_these_are_the_swaps_the_revisions_make(self):
        """The exact list for the swapped side, which is where the room to
        decay actually is.

        **Non emptiness was the arming here and it was the wrong instrument on
        this population.** It was refused for the added side because one rule
        makes it vacuous, and then left standing over ten rules across three
        revisions, which is the side with somewhere to shrink to. Driven: one
        line inside `_revisions_carrying` dropping a single rule carrying
        revision takes five Postgres comparisons out of the run with nothing
        red, because the parametrisation below is derived and a missing case
        is a case that does not exist rather than a case that fails.

        **Derived through `_swap_chain` rather than through
        `_revisions_carrying`**, so the same arm covers a narrowing written in
        the shared reader and one written in the chain reader. Reaching for
        the walk directly would arm the walk and leave the function between it
        and the parametrisation unguarded, which is the shape this branch has
        now been caught by twice.
        """
        assert _swap_rows() == THE_SWAPS

    @pytest.mark.parametrize(
        "constraint", sorted(SWAP_CHAIN), ids=lambda constraint: constraint
    )
    def test_the_last_revision_to_touch_a_rule_is_the_model(self, constraint: str):
        _, rule = SWAP_CHAIN[constraint][-1]

        assert " ".join(rule.after_pg.split()) == _declared(
            rule.table, rule.constraint, POSTGRESQL
        )

    @pytest.mark.parametrize(
        "added",
        [rule for _, rule in ADDED_RULES],
        ids=[f"{revision}-{rule.constraint}" for revision, rule in ADDED_RULES],
    )
    def test_every_rule_a_revision_added_agrees(self, added: AddedRule):
        """A constraint added rather than swapped has no `after_pg`, because it
        has no `before` either. It is the same fact stored twice all the same.

        **Found by walking every revision for the shape**, as the chain above
        is, and not by reaching into the revision that declares one today.
        Reaching by name is how a second revision's addition would have been
        compared against nothing: the rule nobody adds a line for is always the
        new one.
        """
        assert " ".join(added.postgresql.split()) == _declared(
            added.table, added.constraint, POSTGRESQL
        )

    def test_these_are_the_rules_the_revisions_add(self):
        """Anti vacuity for that walk, and **non emptiness would not be it.**

        A parametrisation over a derived population takes its cases with it
        when the population empties. Measured, by emptying it: pytest puts a
        **skip** where the cases were, nothing fails, and the rule above has
        stopped existing rather than started failing. So something has to
        assert the population from outside the parametrisation.

        **A bare `assert _revisions_carrying(AddedRule)` is the wrong
        something, because the population is one.** It witnesses that the one
        module declaring a rule is reachable and nothing else, so it is green
        on a walk narrowed to that module alone, which is the narrowing
        `TestTheTwoWalksOverTheRevisionsAgree` exists for. What it cannot be
        made to do is notice the corpus; that arm is there and this is not it.

        **What this adds is the other direction**: a rule going invisible to
        the walk, and a rule arriving unexamined. Naming the set means a second
        revision's addition has to be written down here by somebody who checked
        it against the model, which is the shape
        `TestTheseAreTheConstraintsWithTwoSpellings` already has in this file.
        """
        assert [
            (revision, rule.table, rule.constraint) for revision, rule in ADDED_RULES
        ] == [("b8f4c1a7e309", "catalogue_targets", "ck_catalogue_targets_base_url")]

    def test_every_addition_is_still_the_last_text_of_its_chain(self):
        """The condition under which comparing an addition with the model is
        the right comparison, asserted rather than assumed.

        An addition is the **first** text of a constraint's chain and
        `test_every_rule_a_revision_added_agrees` compares it against the
        **last**, which is what the model declares. **Two things would have to
        stay true for those to be one text**, and this asserts one of them:
        that nothing swaps a constraint some revision added. The other is that
        no constraint is added twice, which needs no arm of its own, because a
        second addition of one constraint reds the exact list beside this and
        reds whichever of the two texts is not the model's.

        **This is where the widened walk refuses something legitimate.** It
        reds **as well as** the comparisons, not instead of them: a legitimate
        swap moves the model, so driven, the two text comparisons red naming
        the addition and this reds naming the constraint. That is one extra
        named failure, and it is the one that says which of the two is the
        fault. When it fires, the fix is to fold the additions into the chain
        `_swap_chain` builds, so an addition is a link rather than an endpoint,
        and not to delete any of the three.

        **Why that fold is not already here.** It would make the comparison
        right in general, and it is a design change rather than a widening: an
        addition has no `before`, so a chain that holds one needs a convention
        for where an addition starts, and **nothing in this tree could
        exercise that convention**, because no addition has ever been swapped.
        A rule invented over an empty population is a rule nobody has run.

        **The choice between the two is failure direction, not effort.** This
        arm is wrong **loudly**: it refuses a correct revision at the line
        somebody is writing it on, and they find out the same day. A
        convention nothing exercises is wrong **quietly**, because being wrong
        about it means a chain that agrees with itself. That is the reason
        that survives the day somebody decides the fold is cheap after all,
        where an argument about effort is overturned by exactly that reader.
        """
        added = {(rule.table, rule.constraint): rule for _, rule in ADDED_RULES}
        last_swap = {
            (swaps[-1][1].table, constraint): swaps[-1][1]
            for constraint, swaps in SWAP_CHAIN.items()
        }
        # **Both engines, and the engine is in the message.** A first version
        # compared the Postgres sides alone, so an addition overtaken on the
        # SQLite arm only left this green while the addition's own comparison
        # reddened: the refusal still happened and the arm that exists to
        # explain it said nothing. SQLite is the engine every deployment runs,
        # so that is the half this cannot be blind to.
        overtaken = sorted(
            (table, constraint, engine)
            for (table, constraint), addition in added.items()
            if (table, constraint) in last_swap
            for engine, ended_on, added_as in (
                ("sqlite", last_swap[table, constraint].after, addition.sqlite),
                (
                    "postgresql",
                    last_swap[table, constraint].after_pg,
                    addition.postgresql,
                ),
            )
            if " ".join(ended_on.split()) != " ".join(added_as.split())
        )

        assert added, "no revision adds a constraint, so this asserted nothing"
        assert not overtaken, (
            f"{overtaken} was added with one text and its chain now ends on "
            "another, on the engine named beside it, so the addition is no "
            "longer the last text of its constraint and comparing it against "
            "the model refuses a correct revision"
        )


@pytest.mark.parametrize(
    "table_name", sorted(Base.metadata.tables), ids=lambda name: name
)
class TestEveryCheckRendersWithoutASqliteOnlyIdiom:
    """Every table in the schema, rendered against the other dialect.

    Parametrised over the metadata rather than over a list of known tables, so a
    table added to a model is covered with no edit here. The token list is
    `SQLITE_ONLY`, and its own docstring says what that cannot see.
    """

    def test_the_postgres_ddl_carries_none_of_them(self, table_name: str):
        ddl = str(CreateTable(Base.metadata.tables[table_name]).compile(dialect=POSTGRESQL))

        assert not [token for token in SQLITE_ONLY if token in ddl], ddl

    def test_the_sqlite_ddl_still_compiles(self, table_name: str):
        """The other direction, so a `DialectSQL` with a broken SQLite arm is a
        failure here rather than at a deployment's next fresh install."""
        assert "CREATE TABLE" in str(
            CreateTable(Base.metadata.tables[table_name]).compile(dialect=SQLITE)
        )


class TestEveryNulArmDroppedOnACharacterColumn:
    """The guard under "Postgres cannot hold a NUL", which is about a type.

    `text` and `varchar` refuse the byte; `bytea` takes it freely. So a column
    whose SQLite arm carries `instr(x, char(0)) = 0` and whose Postgres arm does
    not is relying on its Postgres type, and this is what holds it to one.
    """

    #: Postgres types that cannot hold a NUL. Stated as the inclusion because
    #: the set of SQLAlchemy string types is closed and small, unlike the set of
    #: types a column could be given.
    CHARACTER_TYPES = (String, Text)

    @staticmethod
    def _columns_losing_a_nul_arm() -> list[tuple[str, str, str]]:
        """`(table, constraint, column)` for every NUL arm the Postgres side
        drops, read off the two arms rather than listed here."""
        losing = []
        for table_name, constraint, element in _dialect_checks():
            # `.name` per column, never the collection itself: iterating a
            # SQLAlchemy `ColumnCollection` yields `Column` objects, which
            # stringify as `table.column` and match no arm here. ruff's
            # SIM118 asks for exactly that substitution and is wrong for
            # this type; mypy is what caught it.
            for column in (one.name for one in Base.metadata.tables[table_name].columns):
                arm = f"instr({column}, char(0)) = 0"
                if arm in element.sqlite and arm not in element.postgresql:
                    losing.append((table_name, constraint, column))
        return losing

    @staticmethod
    def _constraints_losing_a_nul_arm() -> set[tuple[str, str]]:
        """The same question asked without knowing a column's name.

        **Two instruments, because the one above is a literal match.**
        `_columns_losing_a_nul_arm` looks for `instr(<column>, char(0)) = 0`
        exactly, so an arm spelled `instr(x,char(0))=0` or `instr(x, char(0)) < 1`
        is invisible to it and the frozen set below would still match: the guard
        would go on passing while covering one arm fewer. This reaches the same
        constraints through `char(0)` alone, and the case that compares the two
        is what turns that from a comment into a failure.
        """
        return {
            (table_name, constraint)
            for table_name, constraint, element in _dialect_checks()
            if "char(0)" in element.sqlite and "char(0)" not in element.postgresql
        }

    def test_the_two_instruments_reach_the_same_constraints(self):
        """The literal column matcher against a plain `char(0)` scan.

        A NUL arm the column matcher cannot see is a column this class never asks
        about, and the frozen set below cannot tell you that, because it is
        frozen. This can.
        """
        by_column = {(table, constraint) for table, constraint, _ in self._columns_losing_a_nul_arm()}

        assert by_column == self._constraints_losing_a_nul_arm()

    def test_these_are_the_columns_that_lose_one(self):
        """Named rather than counted. A count says nothing about which columns,
        and the next NUL arm should have to be written down here by somebody who
        checked what its Postgres type is."""
        assert set(self._columns_losing_a_nul_arm()) == {
            ("book_identifiers", "ck_book_identifiers_bounds", "value"),
            ("catalogue_credentials", "ck_catalogue_credentials_source", "source"),
            ("catalogue_targets", "ck_catalogue_targets_base_url", "base_url"),
            ("catalogue_targets", "ck_catalogue_targets_indexes", "isbn_index"),
            ("catalogue_targets", "ck_catalogue_targets_indexes", "title_index"),
            ("opds_servers", "ck_opds_servers_base_url", "base_url"),
            ("opds_servers", "ck_opds_servers_credential_key", "credential_key"),
        }

    def test_each_one_is_a_character_type_on_postgres(self):
        losing = self._columns_losing_a_nul_arm()
        assert losing, "the corpus of columns is empty, so this asserted nothing"

        for table_name, constraint, column in losing:
            column_type = Base.metadata.tables[table_name].columns[column].type
            assert isinstance(column_type, self.CHARACTER_TYPES), (
                f"{table_name}.{column} drops its NUL arm on Postgres in "
                f"{constraint}, and {column_type!r} is not a type that refuses "
                "the byte there"
            )

    def test_the_envelope_keeps_its_asymmetry(self):
        """One constraint deliberately has no NUL arm on **either** engine, and
        `b8f4c1a7e309` gave it a ceiling without giving it one.

        **The reason moved and the exception did not.** It was that the column
        had no ceiling for a NUL clause to make readable; it is now that no
        clause on the column is weakened by a NUL at all: the ceiling counts
        bytes, the floor reads shorter past one and is therefore harder to
        satisfy, and both `GLOB` patterns end in `*`, which truncation can only
        make fail. Regularising the three so that all carry one is the shape this
        repository names, so the exception is asserted rather than left to be
        tidied away."""
        element = next(
            one
            for _, name, one in _dialect_checks()
            if name == "ck_catalogue_credentials_envelope"
        )

        assert "char(0)" not in element.sqlite
        assert "char(0)" not in element.postgresql


class TestNoSqliteArmLostAClause:
    """Per engine, and counting arms rather than diffing the two.

    **The two arms differ by design**, so a guard comparing them as strings sees
    nothing, and a guard asserting the chain applies sees nothing either. What
    holds is a direction: the Postgres arm is the SQLite arm **less** what that
    engine subsumes, never more. A clause deleted from the SQLite arm alone
    fails here.

    **A clause deleted from both arms does not**, and saying so is the point.
    That is what `test_backup.py::TestTheSchemaRefusesEveryRecordedHostileValue`
    is for, and it is why that corpus runs on both engines rather than one.
    """

    @staticmethod
    def _conjuncts(sql: str) -> int:
        """Top level `AND`s plus one, counted by depth so a nested `AND` inside
        parentheses is not one of this expression's own arms."""
        depth = 0
        count = 1
        words = sql.replace("(", " ( ").replace(")", " ) ").split()
        for word in words:
            if word == "(":
                depth += 1
            elif word == ")":
                depth -= 1
            elif word == "AND" and depth == 0:
                count += 1
        return count

    @pytest.mark.parametrize(
        ("table_name", "constraint", "element"),
        _dialect_checks(),
        ids=lambda value: value if isinstance(value, str) else "arms",
    )
    def test_the_sqlite_arm_is_never_the_shorter_one(
        self, table_name: str, constraint: str, element: DialectSQL
    ):
        assert self._conjuncts(element.sqlite) >= self._conjuncts(element.postgresql), (
            f"{constraint} has more top level arms on Postgres than on SQLite, "
            "which is the direction this schema never goes: SQLite is the engine "
            "with dynamic typing and the one every deployment runs"
        )

    def test_these_are_the_rules_where_sqlite_carries_more(self):
        """Named with the difference, so an arm dropped from a SQLite side has
        to be written down here by somebody who checked what it was for.

        A count on its own would pass on any redistribution; the number beside
        each name is what makes this bite.
        """
        extra = {
            constraint: self._conjuncts(element.sqlite)
            - self._conjuncts(element.postgresql)
            for _, constraint, element in _dialect_checks()
            if self._conjuncts(element.sqlite) != self._conjuncts(element.postgresql)
        }

        assert extra == {
            # Two NUL arms, one per index column.
            "ck_catalogue_targets_indexes": 2,
            # One NUL arm.
            "ck_book_identifiers_bounds": 1,
            "ck_catalogue_targets_base_url": 1,
            "ck_catalogue_credentials_source": 1,
            "ck_opds_servers_credential_key": 1,
            "ck_opds_servers_base_url": 1,
        }

    def test_the_type_test_survives_on_sqlite(self):
        """`typeof(isbn_attribute) = 'integer'` is the only bound stopping a
        string in a column declared INTEGER on an engine whose affinity is a
        preference. Postgres is allowed to omit it; SQLite is not, and "Postgres
        enforces the type" is the honest sounding reason for deleting it from
        both."""
        element = next(
            one
            for _, name, one in _dialect_checks()
            if name == "ck_catalogue_targets_use_attribute"
        )

        assert "typeof(isbn_attribute) = 'integer'" in element.sqlite
        assert "typeof" not in element.postgresql


class TestTheCatalogueTargetsBooleanIsSpelledPerEngine:
    """`= 1` on a boolean is a type error on Postgres and the idiom on SQLite.

    This is the clause the chain stopped on, and it carries none of the tokens
    `SQLITE_ONLY` lists, which is why that scan is named as an enumeration.
    """

    def test_both_arms(self):
        element = next(
            one
            for _, name, one in _dialect_checks()
            if name == "ck_catalogue_targets_isbn_claim"
        )

        assert element.sqlite == "requires_isbn_claim = 1 OR source = 'dnb'"
        assert element.postgresql == "requires_isbn_claim OR source = 'dnb'"


# ── The database's own copy of every CHECK, against the model's own ──────────


#: The namespace the model's schema is built into, beside the migrated one on
#: the same server. One name for both engines: it is an attached database on
#: SQLite and a schema on Postgres, and what makes it the right shape for both
#: is that reflection addresses either through the same `schema=` argument.
_SCRATCH: Final = "endpaper_round_trip"


def _reflected_checks(inspector: Inspector, schema: str | None) -> dict[str, tuple[str, str]]:
    """Every named CHECK one namespace carries, as `name -> (table, text)`.

    **One walk for both sides of the comparison, and that is the whole
    instrument.** Postgres does not store a CHECK's text: it stores a parsed
    expression and hands back its own rendering, with parentheses inserted by
    precedence, membership tests rewritten, ranges expanded and casts added
    that depend on the column's type. Comparing that rendering against the
    model's would be red on its first run, and the two repairs available are
    both worse than the problem. A containment has already passed a dropped
    floor in this schema once. A normaliser is a second implementation of the
    server's own deparser, needs the column type table as well as the syntax
    classes, and is wrong in the lenient direction by construction: every rule
    it is missing makes two different expressions look the same, it is green,
    and the next spelling passes silently.

    **So both sides come out of this function and neither is written by
    hand.** Whatever the server does to a rendering it does to both, and the
    normalisation cancels with nothing between them.
    """
    found: dict[str, tuple[str, str]] = {}
    for table in inspector.get_table_names(schema=schema):
        for constraint in inspector.get_check_constraints(table, schema=schema):
            name = constraint.get("name")
            assert isinstance(name, str), (
                f"{table} carries a CHECK with no name, which this comparison cannot "
                f"address: {constraint['sqltext']}"
            )
            assert name not in found, (
                f"`{name}` is installed twice in {schema!r}, so a comparison keyed on "
                "the name reads one of the two"
            )
            found[name] = (table, " ".join(str(constraint["sqltext"]).split()))
    return found


@contextmanager
def _the_servers_copy_of_the_model() -> Iterator[tuple[Inspector, str]]:
    """The model's schema, built by this engine's own server into `_SCRATCH`.

    **Built from `Base.metadata` and never from a table declared here.** The
    casts the server inserts depend on a column's type, so a scratch column one
    step off the model's renders differently and the comparison fails for a
    reason that is not its subject. Copying the model's own `Table` objects
    makes the types right by construction.

    **The statements that make and unmake the namespace are the only per
    engine text, and they go through `dialect.for_bind`** like every other
    rule spelled twice here, so a third engine is refused where it arrives
    rather than silently receiving one of the two.

    **The namespace is cleared before it is made, and that is not
    belt and braces on one of the two engines.** On Postgres a schema outlives
    the connection and the worker database is reused between runs, so a kill
    between the create and the cleanup leaves the namespace behind and every
    later run of the job that owns this errors on the create until somebody
    drops it by hand. That job is the release gate, so the cost of the leak is
    a release that cannot be cut. On SQLite there is nothing to clear: the
    attach makes a temporary database that no other connection can see and
    that the detach or the disconnect destroys, so the arm there is a
    statement with no effect rather than a second mechanism.
    """
    opened = False
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        try:
            connection.execute(
                text(
                    for_bind(
                        connection,
                        sqlite="SELECT 1",
                        postgresql=f"DROP SCHEMA IF EXISTS {_SCRATCH} CASCADE",
                    )
                )
            )
            connection.execute(
                text(
                    for_bind(
                        connection,
                        sqlite=f"ATTACH DATABASE '' AS {_SCRATCH}",
                        postgresql=f"CREATE SCHEMA {_SCRATCH}",
                    )
                )
            )
            opened = True
            target = MetaData(schema=_SCRATCH)
            for table in Base.metadata.tables.values():
                table.to_metadata(target, schema=_SCRATCH)
            target.create_all(connection)
            yield inspect(connection), _SCRATCH
        finally:
            if opened:
                connection.execute(
                    text(
                        for_bind(
                            connection,
                            sqlite=f"DETACH DATABASE {_SCRATCH}",
                            postgresql=f"DROP SCHEMA {_SCRATCH} CASCADE",
                        )
                    )
                )


class TestTheInstalledCheckIsTheModelsCheck:
    """What the database in front of us holds, against what the model says.

    **The instrument the file's own header calls for.** The token scan two
    classes up is an enumeration of an open set, and the thing named there as
    not having that hole is the pipeline's `test:postgres` job, which creates
    a schema on a real server. That job creates the **revisions'** schema; the
    model's arm reaches the server only as source compared against source. This
    is the missing hop, and it is one comparison rather than two because both
    copies are rendered by the server.

    **It runs on both engines and skips on neither**, which is not an accident
    of where it was put. On SQLite the round trip is the identity, because
    SQLite stores a CHECK's source text, so here the comparison degenerates to
    the equality the schema tests already make. Outside the files that exist to
    run against a live server, nothing in this test tree skips on a dialect,
    and a skip is how a test stops running without anybody being told; another
    should not arrive as a side effect of this.

    **The cheap engine's half is already owned elsewhere, and this does not
    claim it.** `test_schema.py::TestTheMigrationsAndTheModelsAgree` compares
    the model's declarations against the installed schema as two dicts and
    catches, on SQLite, everything this catches there. **The delta is the
    other engine**, because that class is not in the job's selection, and the
    delta is exactly the deparser cancellation: there the model's text and the
    server's rendering are different strings for the same rule, and only
    putting both through the server makes them comparable.

    **What it sees.** A constraint the chain installs on one engine and not on
    the other. A constraint whose text in the migrated schema differs from the
    model's, as this server renders each. A constraint the model declares that
    no revision installed.

    **Not a rewrite.** A rewrite the server applies to a rendering it applies
    to both copies, so it cancels by construction; that is the instrument
    rather than a hole in it, and naming it here as something seen would
    promise the one thing the design gave up to get the comparison.

    **What it cannot see.** A declared arm wrong in the same way in both
    copies, which is textual comparison's standing blind spot on either engine;
    the instrument for that is behavioural, and the hostile value corpus in
    `test_backup.py` runs on both engines. And the two arms disagreeing in
    **meaning**: `sqlite` and `postgresql` are different languages and only a
    corpus can compare them, which is the same limit the token scan states.

    **What the round trip itself does not reach.** Anything the copy is not
    asked about: a server default, a trigger, a privilege. The namespace is
    built for the CHECK comparison and reflected for that alone.
    """

    @staticmethod
    def _declared_names() -> set[str]:
        """Every named CHECK the model declares.

        **An unnamed one is refused here rather than dropped.** Dropping it
        leaves the reflection walk to hit it first and report a CHECK with no
        name on a table, which is true and names the wrong end: the fix is at
        the model's own site. This says so where the site can be found.
        """
        names = set()
        for table in Base.metadata.tables.values():
            for check in _checks(table):
                assert check.name is not None, (
                    f"{table.name} declares a CHECK with no name, which neither side of "
                    f"this comparison can address: {check.sqltext}"
                )
                names.add(str(check.name))
        return names

    def test_the_servers_copy_carries_every_constraint_the_model_declares(self):
        """The anti vacuity arm, and it is the one that keeps the next one
        honest: a comparison over two empty walks agrees perfectly.
        """
        declared = self._declared_names()
        assert declared, "no model in this schema declares a named CHECK"
        with _the_servers_copy_of_the_model() as (inspector, schema):
            copied = _reflected_checks(inspector, schema)
        assert set(copied) == declared, (
            f"the server's copy of the model holds {sorted(set(copied) ^ declared)} "
            "differently from the model, so the comparison below is over a schema that "
            "is not the one being asserted about"
        )

    def test_every_installed_check_is_what_the_model_renders(self):
        # Through the name walk first, so an unnamed model constraint is
        # reported at the site that declares it rather than at the reflection
        # that reaches it. This arm never called it, so half the fix for that
        # was in the other arm only.
        self._declared_names()
        with _the_servers_copy_of_the_model() as (inspector, schema):
            model = _reflected_checks(inspector, schema)
            installed = _reflected_checks(inspector, inspector.default_schema_name)
        disagreeing = sorted(
            name for name in set(model) | set(installed) if model.get(name) != installed.get(name)
        )
        shown = [(name, installed.get(name), model.get(name)) for name in disagreeing[:3]]
        assert not disagreeing, (
            f"{disagreeing} differ between the schema the revisions built and the schema "
            "the model declares, as this server renders each of them. Installed against "
            f"model: {shown}"
        )
