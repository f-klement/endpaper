"""Tests for backend/scripts/postgres_database.py.

**Neither function that talks to a server meets one here.** They run where a
Postgres exists: the suite's own `conftest.py` creates and checks its databases
through them when `DATABASE_URL` names Postgres, and the pipeline's Postgres
job runs the script's two commands. This suite runs on SQLite, so
`wrong_locale` is judged here against a stand in engine answering the one row
its query reads; what the server itself answers stays with those two callers.

`_safe_name` needs no server, and it is the one that guards something: it is
the only thing between a name and DDL that takes no bind parameter. `main`
needs none either once those two are stood in for, and its exit status is what
fails the pipeline's job on a database with the wrong collation.
"""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from scripts import postgres_database
from scripts.postgres_database import _safe_name, main


class TestADatabaseNameIsHeldToAShapeThatCannotLeaveItsQuotes:
    @pytest.mark.parametrize("name", ["endpaper", "endpaper_partial", "endpaper_gw0"])
    def test_letters_digits_and_underscores_are_kept_as_given(self, name):
        assert _safe_name(name) == name

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "_",
            'endpaper" OWNER postgres --',
            "endpaper\\",
            "endpaper'",
            "end paper",
            "endpaper-partial",
            # A letter, to `isalnum`, in a repertoire nobody chose.
            "endpaperé",
        ],
    )
    def test_anything_else_is_refused_before_it_reaches_a_statement(self, name):
        with pytest.raises(ValueError, match="refusing a database name"):
            _safe_name(name)


class TestTheScriptsExitStatusIsWhatThePipelineReads:
    """The pipeline runs `--assert-locale` as a job step, so the status is the verdict."""

    @pytest.fixture(autouse=True)
    def _a_database_named(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+pg8000://ci@postgres/endpaper")

    def test_a_database_with_the_wrong_collation_fails_the_step(self, monkeypatch, capsys):
        monkeypatch.setattr(
            postgres_database, "wrong_locale", lambda url: "datcollate is 'en_US.utf8', wanted 'C'"
        )
        assert main(["--assert-locale"]) == 1
        assert "REFUSED: datcollate is 'en_US.utf8'" in capsys.readouterr().err

    def test_a_database_with_the_right_collation_passes_the_step(self, monkeypatch):
        monkeypatch.setattr(postgres_database, "wrong_locale", lambda url: None)
        assert main(["--assert-locale"]) == 0

    def test_create_makes_the_database_it_names_on_the_server_named(self, monkeypatch):
        created: list[tuple[str, str]] = []
        monkeypatch.setattr(
            postgres_database, "create_if_absent", lambda url, name: created.append((url, name))
        )
        assert main(["--create", "endpaper_partial"]) == 0
        assert created == [("postgresql+pg8000://ci@postgres/endpaper", "endpaper_partial")]

    @pytest.mark.parametrize("argv", [[], ["--assert"], ["endpaper_partial"]])
    def test_a_command_it_does_not_know_is_a_usage_error(self, argv, capsys):
        assert main(argv) == 2
        assert "--assert-locale" in capsys.readouterr().err


class TestTheLocaleCheckNamesEveryDimensionThatIsWrong:
    """`wrong_locale` against a stand in engine whose one row is the database's locale."""

    @pytest.fixture
    def server_answering(self, monkeypatch):
        def answer(collate: str, encoding: str) -> None:
            row = SimpleNamespace(one=lambda: (collate, encoding))

            @contextmanager
            def connect():
                yield SimpleNamespace(execute=lambda statement: row)

            monkeypatch.setattr(
                postgres_database,
                "create_engine",
                lambda url, **kwargs: SimpleNamespace(connect=connect),
            )

        return answer

    def test_a_database_in_the_wanted_locale_has_nothing_wrong(self, server_answering):
        server_answering("C", "UTF8")
        assert postgres_database.wrong_locale("postgresql://ci@postgres/endpaper") is None

    def test_a_wrong_collation_is_named_with_what_was_wanted(self, server_answering):
        server_answering("en_US.utf8", "UTF8")
        assert postgres_database.wrong_locale("postgresql://ci@postgres/endpaper") == (
            "datcollate is 'en_US.utf8', wanted 'C'"
        )

    def test_a_wrong_encoding_is_named_under_the_right_collation(self, server_answering):
        server_answering("C", "LATIN1")
        assert postgres_database.wrong_locale("postgresql://ci@postgres/endpaper") == (
            "encoding is 'LATIN1', wanted 'UTF8'"
        )

    def test_a_wrong_encoding_and_collation_are_both_named(self, server_answering):
        server_answering("en_US.utf8", "LATIN1")
        assert postgres_database.wrong_locale("postgresql://ci@postgres/endpaper") == (
            "datcollate is 'en_US.utf8', wanted 'C'; encoding is 'LATIN1', wanted 'UTF8'"
        )
