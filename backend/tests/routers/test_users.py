"""Tests for backend/routers/users.py: the member list and appearance."""

import pytest

from models import User
from tests.helpers import proxy_headers


class TestListUsers:
    def test_every_member_can_read_the_list(self, client, admin, member):
        res = client.get("/api/users", headers=member["headers"])
        assert res.status_code == 200
        assert [row["username"] for row in res.json()] == ["admin", "member"]

    def test_it_needs_a_session(self, client, admin):
        assert client.get("/api/users").status_code == 401


class TestReadAppearance:
    def test_a_new_account_has_chosen_nothing(self, client, admin):
        res = client.get("/api/users/me/appearance", headers=admin["headers"])
        assert res.status_code == 200
        assert res.json() == {"palette": None, "mode": None, "wallpaper": None}

    def test_it_needs_a_session(self, client, admin):
        assert client.get("/api/users/me/appearance").status_code == 401

    def test_it_answers_with_the_caller_own_appearance(self, client, admin, member, db):
        client.put(
            "/api/users/me/appearance",
            json={"palette": "nord", "mode": "dark", "wallpaper": None},
            headers=admin["headers"],
        )

        res = client.get("/api/users/me/appearance", headers=member["headers"])
        assert res.json()["palette"] is None


class TestWriteAppearance:
    def test_it_stores_a_whole_appearance(self, client, admin, db):
        res = client.put(
            "/api/users/me/appearance",
            json={"palette": "gruvbox", "mode": "light", "wallpaper": "willow"},
            headers=admin["headers"],
        )
        assert res.status_code == 200
        assert res.json() == {
            "palette": "gruvbox",
            "mode": "light",
            "wallpaper": "willow",
        }

        stored = db.query(User).filter(User.username == "admin").one()
        assert stored.appearance_palette == "gruvbox"
        assert stored.appearance_mode == "light"
        assert stored.appearance_wallpaper == "willow"

    def test_a_null_clears_a_stored_choice(self, client, admin):
        client.put(
            "/api/users/me/appearance",
            json={"palette": "nord", "mode": "dark", "wallpaper": "lily"},
            headers=admin["headers"],
        )

        # The whole appearance is replaced, so an omitted wallpaper is a
        # cleared one. That is what makes "a different one every visit"
        # choosable rather than only ever the absence of a choice.
        res = client.put(
            "/api/users/me/appearance",
            json={"palette": "nord", "mode": "dark"},
            headers=admin["headers"],
        )
        assert res.json()["wallpaper"] is None

    def test_it_writes_only_the_caller_row(self, client, admin, member, db):
        client.put(
            "/api/users/me/appearance",
            json={"palette": "nord", "mode": "dark", "wallpaper": None},
            headers=member["headers"],
        )

        assert db.query(User).filter(User.username == "admin").one().appearance_palette is None

    def test_it_needs_a_session(self, client, admin):
        res = client.put("/api/users/me/appearance", json={"palette": "nord"})
        assert res.status_code == 401

    def test_a_mode_outside_the_three_is_refused(self, client, admin):
        res = client.put(
            "/api/users/me/appearance",
            json={"mode": "sepia"},
            headers=admin["headers"],
        )
        assert res.status_code == 422

    def test_an_id_that_is_not_an_id_is_refused(self, client, admin):
        # Which palettes exist is the frontend's business, but the shape is
        # not: an unbounded string here is stored and served straight back to
        # a browser.
        for value in ("<script>", "a" * 31, "Nord", "nord nord"):
            res = client.put(
                "/api/users/me/appearance",
                json={"palette": value},
                headers=admin["headers"],
            )
            assert res.status_code == 422, value

    def test_an_unknown_palette_is_stored(self, client, admin):
        # A palette this server has never heard of is not an error: the list
        # lives in the frontend, and a server that held it would need
        # redeploying to add one.
        #
        # It survives being *read* by an older client, which shows the default
        # instead. It does not survive that client changing anything, because
        # the PUT replaces the whole appearance, so the next mode change writes
        # the resolved default over it. That is the price of a whole-record
        # write and it is the right way round: the alternative is a client
        # sending back a value it cannot render.
        res = client.put(
            "/api/users/me/appearance",
            json={"palette": "kanagawa", "mode": "system", "wallpaper": None},
            headers=admin["headers"],
        )
        assert res.status_code == 200
        assert res.json()["palette"] == "kanagawa"


class TestAppearanceIsNotOnUserOut:
    def test_the_member_list_carries_no_appearance(self, client, admin, member):
        client.put(
            "/api/users/me/appearance",
            json={"palette": "nord", "mode": "dark", "wallpaper": None},
            headers=admin["headers"],
        )

        rows = client.get("/api/users", headers=member["headers"]).json()
        assert all("palette" not in row for row in rows)
        assert all("appearance" not in row for row in rows)

    def test_the_session_account_carries_no_appearance(self, client, admin):
        client.put(
            "/api/users/me/appearance",
            json={"palette": "nord", "mode": "dark", "wallpaper": None},
            headers=admin["headers"],
        )

        body = client.get("/auth/me", headers=admin["headers"]).json()
        assert set(body) == {"id", "username", "is_admin", "created_at"}


class TestAppearanceForADirectoryAccount:
    """A shadow account is a row like any other, which is the point of columns.

    `upsert_directory_user` creates it with three NULLs and no extra step. A
    side table would have needed one here and in the LDAP path beside it.
    """

    @pytest.fixture(autouse=True)
    def mode(self, proxy_mode):
        return proxy_mode

    def test_it_starts_with_nothing_chosen(self, client):
        res = client.get("/api/users/me/appearance", headers=proxy_headers("kim"))
        assert res.status_code == 200
        assert res.json() == {"palette": None, "mode": None, "wallpaper": None}

    def test_it_can_be_set(self, client, db):
        res = client.put(
            "/api/users/me/appearance",
            json={"palette": "nord", "mode": "dark", "wallpaper": None},
            headers=proxy_headers("kim"),
        )
        assert res.status_code == 200
        assert db.query(User).filter(User.username == "kim").one().appearance_palette == "nord"
