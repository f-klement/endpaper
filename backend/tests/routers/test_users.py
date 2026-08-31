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


class TestListTestAccounts:
    """The switch-target list. Admin only, and it holds nothing else."""

    def test_it_lists_only_test_accounts(self, client, admin, member):
        client.post(
            "/api/users/test-accounts",
            json={"username": "tester", "password": "pw12345678"},
            headers=admin["headers"],
        )

        res = client.get("/api/users/test-accounts", headers=admin["headers"])

        assert res.status_code == 200
        assert [row["username"] for row in res.json()] == ["tester"]

    def test_a_non_admin_is_403(self, client, admin, member):
        assert (
            client.get("/api/users/test-accounts", headers=member["headers"]).status_code
            == 403
        )

    def test_it_needs_a_session(self, client, admin):
        assert client.get("/api/users/test-accounts").status_code == 401

    def test_it_is_empty_until_one_is_made(self, client, admin, member):
        assert client.get("/api/users/test-accounts", headers=admin["headers"]).json() == []


class TestCreateTestAccount:
    def test_an_admin_can_create_one(self, client, admin):
        res = client.post(
            "/api/users/test-accounts",
            json={"username": "tester", "password": "pw12345678"},
            headers=admin["headers"],
        )

        assert res.status_code == 201
        assert res.json()["username"] == "tester"

    def test_it_is_local_flagged_and_never_an_admin(self, client, admin, db):
        client.post(
            "/api/users/test-accounts",
            json={"username": "tester", "password": "pw12345678"},
            headers=admin["headers"],
        )

        account = db.query(User).filter(User.username == "tester").one()
        assert account.is_test_account is True
        assert account.auth_source == "local"
        assert account.is_admin is False

    def test_the_password_is_hashed(self, client, admin, db):
        client.post(
            "/api/users/test-accounts",
            json={"username": "tester", "password": "pw12345678"},
            headers=admin["headers"],
        )

        stored = db.query(User).filter(User.username == "tester").one().password_hash
        assert stored != "pw12345678"
        assert stored.startswith("$2")

    def test_an_address_can_be_set_while_the_account_is_being_made(
        self, client, admin, db
    ):
        """#103's second row: an admin creating an account for somebody else.

        `UserCreate` again, so the rule and the bound are registration's and
        there is no second answer to what an address is.
        """
        res = client.post(
            "/api/users/test-accounts",
            json={
                "username": "tester",
                "password": "pw12345678",
                "email": "tester@example.org",
            },
            headers=admin["headers"],
        )

        assert res.status_code == 201
        assert db.query(User).filter(User.username == "tester").one().email == (
            "tester@example.org"
        )

    def test_one_made_without_an_address_has_none(self, client, admin, db):
        client.post(
            "/api/users/test-accounts",
            json={"username": "tester", "password": "pw12345678"},
            headers=admin["headers"],
        )

        assert db.query(User).filter(User.username == "tester").one().email is None

    def test_something_that_is_not_an_address_is_422(self, client, admin, db):
        res = client.post(
            "/api/users/test-accounts",
            json={
                "username": "tester",
                "password": "pw12345678",
                "email": "not one",
            },
            headers=admin["headers"],
        )

        assert res.status_code == 422
        assert db.query(User).filter(User.username == "tester").first() is None

    def test_the_response_carries_no_password(self, client, admin):
        body = client.post(
            "/api/users/test-accounts",
            json={"username": "tester", "password": "pw12345678"},
            headers=admin["headers"],
        ).json()

        assert "password" not in body
        assert "password_hash" not in body

    def test_a_short_password_is_refused(self, client, admin):
        """`UserCreate`, so registration's 8 character floor applies here too."""
        res = client.post(
            "/api/users/test-accounts",
            json={"username": "tester", "password": "short"},
            headers=admin["headers"],
        )
        assert res.status_code == 422

    def test_a_taken_username_is_refused(self, client, admin):
        res = client.post(
            "/api/users/test-accounts",
            json={"username": "admin", "password": "pw12345678"},
            headers=admin["headers"],
        )
        assert res.status_code == 400
        assert "taken" in res.json()["detail"].lower()

    def test_a_non_admin_is_403(self, client, admin, member, db):
        res = client.post(
            "/api/users/test-accounts",
            json={"username": "tester", "password": "pw12345678"},
            headers=member["headers"],
        )

        assert res.status_code == 403
        assert db.query(User).filter(User.username == "tester").first() is None

    def test_it_needs_a_session(self, client, admin, db):
        res = client.post(
            "/api/users/test-accounts",
            json={"username": "tester", "password": "pw12345678"},
        )

        assert res.status_code == 401
        assert db.query(User).filter(User.username == "tester").first() is None

    def test_creating_one_is_logged_with_both_names(self, client, admin, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            client.post(
                "/api/users/test-accounts",
                json={"username": "tester", "password": "pw12345678"},
                headers=admin["headers"],
            )

        created = [r for r in caplog.records if "created the test account" in r.message]
        assert created and created[0].levelno == logging.WARNING
        assert "'admin'" in created[0].getMessage()
        assert "'tester'" in created[0].getMessage()

    def test_a_test_account_appears_in_the_member_list(self, client, admin):
        """It is a real account, and the loan picker is the reason that list
        shows every one of them."""
        client.post(
            "/api/users/test-accounts",
            json={"username": "tester", "password": "pw12345678"},
            headers=admin["headers"],
        )

        names = [row["username"] for row in client.get("/api/users", headers=admin["headers"]).json()]
        assert names == ["admin", "tester"]


class TestCreateTestAccountInDirectoryModes:
    """The whole point of the feature: it works where registration does not."""

    def test_ldap_mode_still_creates_one(self, client, admin, ldap_mode):
        res = client.post(
            "/api/users/test-accounts",
            json={"username": "tester", "password": "pw12345678"},
            headers=admin["headers"],
        )
        assert res.status_code == 201

    def test_proxy_mode_still_creates_one(self, client, proxy_mode, db):
        # The first header identity becomes the admin, which is how an admin
        # exists at all in this mode.
        client.get("/auth/me", headers=proxy_headers("boss"))

        res = client.post(
            "/api/users/test-accounts",
            json={"username": "tester", "password": "pw12345678"},
            headers=proxy_headers("boss"),
        )

        assert res.status_code == 201
        assert db.query(User).filter(User.username == "tester").one().is_test_account is True

    def test_a_non_admin_proxy_identity_is_still_403(self, client, proxy_mode, db):
        client.get("/auth/me", headers=proxy_headers("boss"))

        res = client.post(
            "/api/users/test-accounts",
            json={"username": "tester", "password": "pw12345678"},
            headers=proxy_headers("nobody"),
        )

        assert res.status_code == 403


# ── Addresses ─────────────────────────────────────────────────────────────────


def _directory_member(db, username: str, source: str, email: str | None = None) -> User:
    """A shadow account, the shape a directory sign in leaves behind."""
    user = User(username=username, password_hash=None, auth_source=source, email=email)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TestReadingYourOwnAddress:
    def test_a_new_account_has_none(self, client, admin):
        res = client.get("/api/users/me/email", headers=admin["headers"])
        assert res.status_code == 200
        assert res.json()["email"] is None

    def test_it_says_the_field_is_the_members_to_change(self, client, admin):
        res = client.get("/api/users/me/email", headers=admin["headers"])
        assert res.json()["editable"] is True

    def test_it_needs_a_session(self, client, admin):
        assert client.get("/api/users/me/email").status_code == 401

    def test_it_answers_with_the_caller_own_address(self, client, admin, member):
        client.put(
            "/api/users/me/email",
            json={"email": "admin@example.org"},
            headers=admin["headers"],
        )

        res = client.get("/api/users/me/email", headers=member["headers"])

        assert res.json()["email"] is None
        assert res.json()["username"] == "member"


class TestWritingYourOwnAddress:
    def test_it_stores_one(self, client, admin, db):
        res = client.put(
            "/api/users/me/email",
            json={"email": "kim@example.org"},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert res.json()["email"] == "kim@example.org"
        assert db.query(User).filter(User.username == "admin").one().email == "kim@example.org"

    def test_surrounding_space_is_trimmed(self, client, admin, db):
        client.put(
            "/api/users/me/email",
            json={"email": "  kim@example.org  "},
            headers=admin["headers"],
        )

        assert db.query(User).filter(User.username == "admin").one().email == "kim@example.org"

    def test_null_clears_it(self, client, admin, db):
        client.put(
            "/api/users/me/email",
            json={"email": "kim@example.org"},
            headers=admin["headers"],
        )

        res = client.put("/api/users/me/email", json={"email": None}, headers=admin["headers"])

        assert res.json()["email"] is None
        assert db.query(User).filter(User.username == "admin").one().email is None

    def test_an_empty_string_clears_it_too(self, client, admin, db):
        """A member removing their address types nothing into the field, and a
        422 there would make "remove it" the one edit the form cannot express."""
        client.put(
            "/api/users/me/email",
            json={"email": "kim@example.org"},
            headers=admin["headers"],
        )

        client.put("/api/users/me/email", json={"email": "   "}, headers=admin["headers"])

        assert db.query(User).filter(User.username == "admin").one().email is None

    @pytest.mark.parametrize(
        "value",
        [
            "not an address",
            "kim@example.org, someone@elsewhere.example",
            "kim@example.org\nBcc: someone@elsewhere.example",
            "kim@example.org;someone@elsewhere.example",
            "<kim@example.org>",
            "kim@localhost",
        ],
    )
    def test_something_that_is_not_an_address_is_refused(self, client, admin, value):
        res = client.put("/api/users/me/email", json={"email": value}, headers=admin["headers"])
        assert res.status_code == 422

    def test_an_absurdly_long_one_is_refused(self, client, admin):
        res = client.put(
            "/api/users/me/email",
            json={"email": "k" * 4000 + "@example.org"},
            headers=admin["headers"],
        )
        assert res.status_code == 422

    def test_it_needs_a_session(self, client, admin):
        res = client.put("/api/users/me/email", json={"email": "kim@example.org"})
        assert res.status_code == 401

    def test_a_member_writes_only_their_own(self, client, admin, member, db):
        client.put(
            "/api/users/me/email",
            json={"email": "member@example.org"},
            headers=member["headers"],
        )

        assert db.query(User).filter(User.username == "admin").one().email is None
        assert (
            db.query(User).filter(User.username == "member").one().email
            == "member@example.org"
        )


class TestAnAdminReadsAndWritesAnybodys:
    def test_the_list_carries_every_member(self, client, admin, member):
        res = client.get("/api/users/emails", headers=admin["headers"])

        assert res.status_code == 200
        assert [row["username"] for row in res.json()] == ["admin", "member"]

    def test_the_list_is_admin_only(self, client, admin, member):
        assert client.get("/api/users/emails", headers=member["headers"]).status_code == 403

    def test_the_list_needs_a_session(self, client, admin):
        assert client.get("/api/users/emails").status_code == 401

    def test_an_admin_writes_somebody_elses(self, client, admin, member, db):
        res = client.put(
            f"/api/users/{member['user']['id']}/email",
            json={"email": "member@example.org"},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert (
            db.query(User).filter(User.username == "member").one().email
            == "member@example.org"
        )

    def test_a_member_cannot_write_somebody_elses(self, client, admin, member, db):
        res = client.put(
            f"/api/users/{admin['user']['id']}/email",
            json={"email": "stolen@example.org"},
            headers=member["headers"],
        )

        assert res.status_code == 403
        assert db.query(User).filter(User.username == "admin").one().email is None

    def test_no_such_member_is_a_404(self, client, admin):
        res = client.put(
            "/api/users/9999/email",
            json={"email": "nobody@example.org"},
            headers=admin["headers"],
        )
        assert res.status_code == 404

    def test_a_path_id_past_the_databases_range_is_refused_not_a_500(self, client, admin):
        res = client.put(
            "/api/users/99999999999999999999/email",
            json={"email": "nobody@example.org"},
            headers=admin["headers"],
        )
        assert res.status_code == 422

    def test_the_same_address_rule_applies(self, client, admin, member):
        res = client.put(
            f"/api/users/{member['user']['id']}/email",
            json={"email": "not an address"},
            headers=admin["headers"],
        )
        assert res.status_code == 422


class TestWhetherAnAccountCameFromADirectory:
    """#103's third row, which `editable` alone could not express.

    A directory account whose directory carries no address attribute is
    **editable and empty**, exactly like a local account that has not set one.
    The screen has to tell those two apart to say why the box is empty, and
    `editable` reads the same on both.
    """

    def test_a_local_account_did_not_come_from_a_directory(self, client, admin):
        body = client.get("/api/users/me/email", headers=admin["headers"]).json()

        assert body["from_directory"] is False
        assert body["editable"] is True

    def test_a_directory_account_with_no_attribute_is_editable_and_flagged(
        self, client, admin, db
    ):
        """The case nobody could be told about: the account appeared at a first
        sign in with nobody filling in a form, the directory carries no address,
        and its owner is the only person who can give it one."""
        _directory_member(db, "kim", "ldap")

        rows = client.get("/api/users/emails", headers=admin["headers"]).json()

        kim = next(row for row in rows if row["username"] == "kim")
        assert kim["from_directory"] is True
        assert kim["editable"] is True
        assert kim["email"] is None

    def test_a_directory_that_carries_an_address_owns_it(
        self, client, admin, db, monkeypatch
    ):
        monkeypatch.setenv("PROXY_EMAIL_HEADER", "Remote-Email")
        _directory_member(db, "kim", "proxy", "kim@example.org")

        rows = client.get("/api/users/emails", headers=admin["headers"]).json()

        kim = next(row for row in rows if row["username"] == "kim")
        assert kim["from_directory"] is True
        assert kim["editable"] is False

    def test_no_row_is_owned_by_a_directory_it_did_not_come_from(
        self, client, admin, db
    ):
        """The fourth combination the wire model can express and the server never
        produces, which is the one direction the three tests above do not pin.

        **Not "the flags are not each other's negation"**, which was this test's
        first version and was strictly weaker than the one three lines above it:
        that already asserts a row which is both. `editable` is
        `not directory_owns_email(auth_source)` and that answers False for a
        local row, so `from_directory=False, editable=False` is unreachable, and
        a screen reading it would have no sentence to draw.
        """
        _directory_member(db, "kim", "ldap")
        _directory_member(db, "sam", "proxy", "sam@example.org")

        rows = client.get("/api/users/emails", headers=admin["headers"]).json()

        assert len(rows) >= 3
        assert not [
            row
            for row in rows
            if not row["from_directory"] and not row["editable"]
        ]

    def test_a_row_no_directory_wrote_is_not_a_directory_row(
        self, client, admin, db
    ):
        """`users.auth_source` has no `CheckConstraint`, so a restored or hand
        edited row can spell it anything. Such a row belongs to no directory,
        and telling its owner that a directory supplies no address names one
        they do not have. Measured under the previous `!= LOCAL` rule: `''`,
        `'LOCAL'` and arbitrary text all came back true."""
        _directory_member(db, "kim", "sqlite-restored-junk")

        rows = client.get("/api/users/emails", headers=admin["headers"]).json()

        kim = next(row for row in rows if row["username"] == "kim")
        assert kim["from_directory"] is False
        assert kim["editable"] is True


class TestWhereTheDirectoryOwnsIt:
    """The one case a write is refused rather than accepted and reverted."""

    def test_the_field_reports_itself_read_only(self, client, admin, db, monkeypatch):
        monkeypatch.setenv("PROXY_EMAIL_HEADER", "Remote-Email")
        _directory_member(db, "kim", "proxy", "kim@example.org")

        rows = client.get("/api/users/emails", headers=admin["headers"]).json()

        kim = next(row for row in rows if row["username"] == "kim")
        assert kim["editable"] is False
        assert kim["email"] == "kim@example.org"

    def test_an_admin_write_is_refused(self, client, admin, db, monkeypatch):
        monkeypatch.setenv("PROXY_EMAIL_HEADER", "Remote-Email")
        kim = _directory_member(db, "kim", "proxy", "kim@example.org")

        res = client.put(
            f"/api/users/{kim.id}/email",
            json={"email": "typo@example.org"},
            headers=admin["headers"],
        )

        assert res.status_code == 409
        assert "PROXY_EMAIL_HEADER" in res.json()["detail"]
        db.expire_all()
        assert db.query(User).filter(User.username == "kim").one().email == "kim@example.org"

    def test_a_local_account_in_a_directory_deployment_is_still_editable(
        self, client, admin, db, monkeypatch
    ):
        """`editable` is per row. An admin created test account is local, so it
        stays the admin's to set even where the directory owns everybody else's."""
        monkeypatch.setenv("PROXY_EMAIL_HEADER", "Remote-Email")

        res = client.put(
            f"/api/users/{admin['user']['id']}/email",
            json={"email": "admin@example.org"},
            headers=admin["headers"],
        )

        assert res.status_code == 200

    def test_an_unconfigured_directory_leaves_the_field_editable(self, client, admin, db):
        """`PROXY_EMAIL_HEADER` unset, which is the shipped default: a shadow
        account's address is nobody's to assert, so it stays the app's to set."""
        kim = _directory_member(db, "kim", "proxy")

        res = client.put(
            f"/api/users/{kim.id}/email",
            json={"email": "kim@example.org"},
            headers=admin["headers"],
        )

        assert res.status_code == 200


class TestAnAddressIsNotOnTheMemberList:
    """The rule the whole design turns on, checked on the wire rather than in a
    schema: `UserOut` is served inside every book payload and by this list."""

    def test_the_member_list_carries_no_address(self, client, admin, member):
        client.put(
            "/api/users/me/email",
            json={"email": "kim@example.org"},
            headers=admin["headers"],
        )

        body = client.get("/api/users", headers=member["headers"]).text

        assert "kim@example.org" not in body
        assert all("email" not in row for row in client.get(
            "/api/users", headers=member["headers"]).json())

    def test_a_book_payload_carries_no_address(self, client, admin, member, make_book):
        client.put(
            "/api/users/me/email",
            json={"email": "kim@example.org"},
            headers=admin["headers"],
        )
        make_book(admin["headers"], title="Dune")

        body = client.get("/api/books", headers=member["headers"]).text

        assert "kim@example.org" not in body
