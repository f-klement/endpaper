"""Tests for backend/dialect.py, and for what the two arms owe each other.

`test_dialect_portability.py` holds the query side and the indexes. This file
holds the construct and the CHECK constraints, which is where the two engines'
SQL actually differs.

**What each class here can and cannot see**, because a guard that reads thorough
gets believed:

* `TestTheTwoSpellings` is the construct alone: two arms, a refusal for every
  other named dialect, and the stringifier. It says nothing about any constraint.
* `TestTheRevisionsPostgresArmIsTheModelsPostgresArm` is the second engine's
  copy of a comparison that already existed for the first: a revision writes its
  SQL out rather than importing it, so the two copies are a fact stored twice.
  **The revisions it covers are found by type rather than listed**, so one that
  carries a rule table is covered the moment it exists, and the comparison is a
  **chain**: each revision's arm is the next one's starting point and the last is
  the model.
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
"""

from itertools import pairwise

import pytest
from sqlalchemy import CheckConstraint, String, Text, create_engine, exc
from sqlalchemy.dialects import mysql, postgresql, sqlite
from sqlalchemy.schema import CreateTable

from database import Base
from dialect import DialectSQL, SwappedRule
from migrations.versions import (
    b8f4c1a7e309_bound_the_bytes_three_columns_never_had as bound_the_bytes,
)
from migrations.versions.b8f4c1a7e309_bound_the_bytes_three_columns_never_had import (
    AddedRule,
)
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


def _revisions_carrying_swapped_rules() -> dict[str, tuple[SwappedRule, ...]]:
    """Every revision declaring a table of `SwappedRule`, by revision id.

    **Found by type rather than by name, and the type is the fact.** A first
    version of this was a list of three revisions and their tables, because they
    are spelled `_CEILINGS`, `_GLOB_RULES` and `_SWAPPED` and a frozen revision
    cannot be renamed. The spelling is not what makes one of these a rule table;
    the element type is. So a revision carrying one is covered the moment it
    exists, where a list was a line somebody had to remember, and the standing
    rule says to derive rather than to add a case per spelling. Measured over
    `migrations/versions/`: exactly the three, and nothing spurious.

    **Keyed on `revision` rather than on the module name**, because that is what
    `down_revision` points at and what the ordering below reads.
    """
    import importlib
    import pkgutil

    import migrations.versions as versions

    carrying: dict[str, tuple[SwappedRule, ...]] = {}
    for found in pkgutil.iter_modules(versions.__path__):
        module = importlib.import_module(f"migrations.versions.{found.name}")
        rules = tuple(
            rule
            for value in vars(module).values()
            if isinstance(value, tuple)
            and value
            and all(isinstance(one, SwappedRule) for one in value)
            for rule in value
        )
        if rules:
            carrying[module.revision] = rules
    return carrying


def _in_chain_order(revisions: list[str]) -> list[str]:
    """Those revisions, oldest first, according to Alembic's own chain.

    **Derived rather than declared, because the comparison below is a chain.** A
    constraint two revisions have rewritten has three texts to keep in step on
    Postgres and only the last of them is the model's, so the order decides which
    text is compared with which. A hand written order is a fact that can be wrong
    silently; `down_revision` is the fact the migration runner itself uses, and
    `pkgutil` hands the modules over in filename order, which is no order at all.
    """
    from alembic.script import ScriptDirectory

    import schema

    walked = [
        revision.revision
        for revision in ScriptDirectory.from_config(
            schema._alembic_config()
        ).walk_revisions()
    ]
    oldest_first = list(reversed(walked))
    return sorted(revisions, key=oldest_first.index)


def _pg_chain() -> dict[str, list[tuple[str, SwappedRule]]]:
    """Each constraint's swaps, oldest first, with the revision that made each."""
    tables = _revisions_carrying_swapped_rules()
    chain: dict[str, list[tuple[str, SwappedRule]]] = {}
    for name in _in_chain_order(list(tables)):
        for rule in tables[name]:
            chain.setdefault(rule.constraint, []).append((name, rule))
    return chain


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
            for constraint, swaps in _pg_chain().items()
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
        assert _revisions_carrying_swapped_rules(), (
            "no revision was found to carry a table of swapped rules, so every "
            "comparison in this class is over an empty chain"
        )
        assert [
            constraint for constraint, swaps in _pg_chain().items() if len(swaps) > 1
        ]

    @pytest.mark.parametrize(
        "constraint", sorted(_pg_chain()), ids=lambda constraint: constraint
    )
    def test_the_last_revision_to_touch_a_rule_is_the_model(self, constraint: str):
        _, rule = _pg_chain()[constraint][-1]

        assert " ".join(rule.after_pg.split()) == _declared(
            rule.table, rule.constraint, POSTGRESQL
        )

    @pytest.mark.parametrize(
        "added", bound_the_bytes._ADDED, ids=lambda added: added.constraint
    )
    def test_every_rule_a_revision_added_agrees(self, added: AddedRule):
        """A constraint added rather than swapped has no `after_pg`, because it
        has no `before` either. It is the same fact stored twice all the same."""
        assert " ".join(added.postgresql.split()) == _declared(
            added.table, added.constraint, POSTGRESQL
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
