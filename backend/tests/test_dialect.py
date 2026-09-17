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
  It covers the two revisions that carry a table of rules and no others.
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

import pytest
from sqlalchemy import CheckConstraint, String, Text, create_engine, exc
from sqlalchemy.dialects import mysql, postgresql, sqlite
from sqlalchemy.schema import CreateTable

from database import Base
from dialect import DialectSQL, SwappedRule
from migrations.versions import (
    a6d3f92c7b14_a_nul_clause_on_two_glob_rules as a_nul_clause_on_two_glob_rules,
)
from migrations.versions import (
    f4a1c62d0b97_bind_every_text_ceiling_on_bytes_too as bind_every_text_ceiling,
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


class TestTheRevisionsPostgresArmIsTheModelsPostgresArm:
    """The second engine's half of a comparison that already existed.

    A revision spells its SQL out rather than importing a constant, for the
    reason every revision here gives, so each rule is a fact stored twice and
    `test_schema.py` stands between the SQLite copies. This stands between the
    Postgres ones, which nothing else reads at all.
    """

    @pytest.mark.parametrize(
        "rule", bind_every_text_ceiling._CEILINGS, ids=lambda rule: rule.constraint
    )
    def test_every_byte_ceiling_agrees(self, rule: SwappedRule):
        assert " ".join(rule.after_pg.split()) == _declared(
            rule.table, rule.constraint, POSTGRESQL
        )

    @pytest.mark.parametrize(
        "rule",
        a_nul_clause_on_two_glob_rules._GLOB_RULES,
        ids=lambda rule: rule.constraint,
    )
    def test_every_glob_rule_agrees(self, rule: SwappedRule):
        assert " ".join(rule.after_pg.split()) == _declared(
            rule.table, rule.constraint, POSTGRESQL
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
        """One constraint deliberately has no NUL arm on **either** engine,
        because its column has no ceiling for one to make exact. Regularising
        the three so that all carry one is the shape this repository names, so
        the exception is asserted rather than left to be tidied away."""
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
