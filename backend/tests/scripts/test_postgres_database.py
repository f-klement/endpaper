"""Tests for backend/scripts/postgres_database.py.

**Only the name rule is reached here, and the split is deliberate.** The other
three functions talk to a Postgres server, and they run where one exists: the
suite's own `conftest.py` creates and checks its databases through them when
`DATABASE_URL` names Postgres, and the pipeline's Postgres job runs the script's
two commands. A SQLite run therefore leaves them unreached by design, which is
what a coverage figure taken on SQLite shows.

`_safe_name` needs no server, and it is the one that guards something: it is
the only thing between a name and DDL that takes no bind parameter.
"""

import pytest

from scripts.postgres_database import _safe_name


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
