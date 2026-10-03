"""Tests for backend/routers/auth.py: registration, login, /auth/me."""

import logging
import re
import typing
import unicodedata
from typing import Any

import pytest
from fastapi import FastAPI, Response
from fastapi.utils import is_body_allowed_for_status_code
from ldap3.core.exceptions import LDAPException, LDAPInvalidValueError
from pydantic import ValidationError

import auth_backends
import main
from auth import COVER_COOKIE_NAME
from models import USERNAME_MAX, User
from tests.helpers import (
    FakeConnection,
    FakeEntry,
    directory_with,
    install_directory,
    proxy_headers,
)


class TestRegister:
    def test_first_account_becomes_admin(self, client):
        res = client.post("/auth/register", json={"username": "first", "password": "pw12345678"})
        assert res.status_code == 201
        # `RegistrationOut`, so the session is nested: where a deployment
        # confirms new accounts there is none to hand back.
        assert res.json()["token"]["user"]["is_admin"] is True

    def test_second_account_is_not_admin(self, client, admin):
        res = client.post("/auth/register", json={"username": "second", "password": "pw12345678"})
        assert res.status_code == 201
        assert res.json()["token"]["user"]["is_admin"] is False

    def test_registration_returns_a_usable_token(self, client):
        token = client.post(
            "/auth/register", json={"username": "first", "password": "pw12345678"}
        ).json()["token"]["access_token"]
        res = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200

    def test_duplicate_username_is_rejected(self, client, admin):
        res = client.post("/auth/register", json={"username": "admin", "password": "pw12345678"})
        assert res.status_code == 400
        assert "taken" in res.json()["detail"].lower()

    def test_password_is_never_returned(self, client):
        body = client.post(
            "/auth/register", json={"username": "first", "password": "pw12345678"}
        ).json()["token"]
        assert "password" not in body["user"]
        assert "password_hash" not in body["user"]

    def test_password_is_stored_hashed_not_plain(self, client, db):
        client.post("/auth/register", json={"username": "first", "password": "pw12345678"})
        stored = db.query(User).filter(User.username == "first").one().password_hash
        assert stored != "pw12345678"
        assert stored.startswith("$2")

    def test_missing_field_is_422(self, client):
        assert client.post("/auth/register", json={"username": "only"}).status_code == 422

    def test_a_password_under_the_floor_is_422(self, client):
        """8 characters, and the floor is `UserCreate`'s so it applies to every
        route that creates an account, not only this one."""
        res = client.post("/auth/register", json={"username": "first", "password": "pw12345"})
        assert res.status_code == 422

    def test_a_password_at_the_floor_is_accepted(self, client):
        res = client.post("/auth/register", json={"username": "first", "password": "pw123456"})
        assert res.status_code == 201


class TestAnAddressCanBeGivenWhileTheAccountIsBeingMade:
    """#103. The one moment somebody is already typing their details.

    The address is `User.email`, nullable, and it stays nullable: an account
    made without one is the account this route made before the field existed,
    which is every account today.
    """

    def test_an_address_sent_at_registration_is_stored(self, client, db):
        res = client.post(
            "/auth/register",
            json={
                "username": "first",
                "password": "pw12345678",
                "email": "first@example.org",
            },
        )
        assert res.status_code == 201
        assert db.query(User).filter(User.username == "first").one().email == (
            "first@example.org"
        )

    def test_an_account_made_without_one_still_has_none(self, client, db):
        client.post("/auth/register", json={"username": "first", "password": "pw12345678"})
        assert db.query(User).filter(User.username == "first").one().email is None

    def test_an_empty_string_is_no_address_rather_than_a_refusal(self, client, db):
        """A browser sends "" for a field nobody filled in, and refusing that
        would make the optional field compulsory for anyone using a form."""
        res = client.post(
            "/auth/register",
            json={"username": "first", "password": "pw12345678", "email": "  "},
        )
        assert res.status_code == 201
        assert db.query(User).filter(User.username == "first").one().email is None

    def test_something_that_is_not_an_address_is_422(self, client, db):
        res = client.post(
            "/auth/register",
            json={"username": "first", "password": "pw12345678", "email": "not one"},
        )
        assert res.status_code == 422
        assert db.query(User).filter(User.username == "first").first() is None

    def test_a_header_injection_attempt_is_422(self, client):
        """The same rule `PUT /users/me/email` enforces, which is the point of
        there being one rule: this address reaches `mailer` like any other."""
        res = client.post(
            "/auth/register",
            json={
                "username": "first",
                "password": "pw12345678",
                "email": "a@example.org\nBcc: victim@example.org",
            },
        )
        assert res.status_code == 422

    def test_an_address_past_the_column_is_422(self, client):
        res = client.post(
            "/auth/register",
            json={
                "username": "first",
                "password": "pw12345678",
                "email": f"{'a' * 320}@example.org",
            },
        )
        assert res.status_code == 422

    def test_the_address_is_not_served_back_with_the_account(self, client):
        """`UserOut` carries no address, which is what stops one appearing in
        every book payload. Registration returns a `UserOut` like any other."""
        body = client.post(
            "/auth/register",
            json={
                "username": "first",
                "password": "pw12345678",
                "email": "first@example.org",
            },
        ).json()["token"]
        assert "email" not in body["user"]


class TestRegistrationDisabled:
    @pytest.fixture(autouse=True)
    def disable_registration(self, monkeypatch):
        monkeypatch.setenv("ALLOW_REGISTRATION", "false")

    def test_register_is_403(self, client):
        res = client.post("/auth/register", json={"username": "nope", "password": "pw12345678"})
        assert res.status_code == 403

    def test_config_reports_it(self, client):
        assert client.get("/auth/config").json()["registration_enabled"] is False

    def test_login_still_works(self, client, db):
        """Disabling signups must not lock out the accounts that already exist."""
        from auth import hash_password

        db.add(User(username="existing", password_hash=hash_password("pw12345678")))
        db.commit()
        res = client.post("/auth/login", json={"username": "existing", "password": "pw12345678"})
        assert res.status_code == 200

    def test_the_flag_is_read_per_request_not_at_import(self, client, monkeypatch):
        """Regression: the flag used to be a module constant needing a restart."""
        monkeypatch.setenv("ALLOW_REGISTRATION", "true")
        assert client.get("/auth/config").json()["registration_enabled"] is True


class TestLogin:
    def test_correct_credentials_return_a_token(self, client, admin):
        res = client.post("/auth/login", json={"username": "admin", "password": "password123"})
        assert res.status_code == 200
        assert res.json()["token_type"] == "bearer"

    def test_wrong_password_is_401(self, client, admin):
        res = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
        assert res.status_code == 401

    def test_unknown_username_is_401(self, client, admin):
        res = client.post("/auth/login", json={"username": "ghost", "password": "password123"})
        assert res.status_code == 401

    def test_unknown_user_and_wrong_password_are_indistinguishable(self, client, admin):
        """Different messages here would let an attacker enumerate accounts."""
        wrong_pw = client.post("/auth/login", json={"username": "admin", "password": "x"})
        no_user = client.post("/auth/login", json={"username": "ghost", "password": "x"})
        assert wrong_pw.json()["detail"] == no_user.json()["detail"]

    def test_username_comparison_is_case_sensitive(self, client, admin):
        res = client.post("/auth/login", json={"username": "ADMIN", "password": "password123"})
        assert res.status_code == 401

    def test_it_sets_the_cover_cookie(self, client, admin):
        """An <img> cannot send the Authorization header, so without this every
        cover on the page 401s under local auth."""
        res = client.post("/auth/login", json={"username": "admin", "password": "password123"})
        assert COVER_COOKIE_NAME in res.cookies

    def test_the_cover_cookie_is_scoped_to_the_cover_route(self, client, admin):
        """Path, HttpOnly and SameSite are what keep a second copy of an
        identity from being a CSRF hole. The scope claim inside it is tested in
        tests/test_auth.py; this is the browser's half."""
        res = client.post("/auth/login", json={"username": "admin", "password": "password123"})

        header = res.headers["set-cookie"]
        assert "Path=/covers" in header
        assert "HttpOnly" in header
        assert "SameSite=lax" in header.replace("Samesite", "SameSite")

    def test_getting_it_right_clears_the_count(self, client, admin):
        """Otherwise somebody who mistypes their password nine times and then
        gets it right is rationed for the rest of the window."""
        for _ in range(9):
            client.post("/auth/login", json={"username": "admin", "password": "wrong"})

        assert (
            client.post(
                "/auth/login", json={"username": "admin", "password": "password123"}
            ).status_code
            == 200
        )
        for _ in range(9):
            assert (
                client.post(
                    "/auth/login", json={"username": "admin", "password": "wrong"}
                ).status_code
                == 401
            )

    def test_guesses_are_bounded(self, client, admin):
        for _ in range(10):
            client.post("/auth/login", json={"username": "admin", "password": "wrong"})

        res = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
        assert res.status_code == 429
        assert "Retry-After" in res.headers


class TestAuthConfig:
    def test_is_public(self, client):
        """The login page reads this before anyone has a token."""
        assert client.get("/auth/config").status_code == 200

    def test_defaults_to_enabled(self, client):
        assert client.get("/auth/config").json()["registration_enabled"] is True

    def test_reports_the_auth_mode(self, client):
        """The frontend renders a different screen per mode, so it has to be
        told which one is in force before anyone signs in."""
        assert client.get("/auth/config").json()["auth_mode"] == "local"


class TestMe:
    def test_returns_the_authenticated_account(self, client, member):
        body = client.get("/auth/me", headers=member["headers"]).json()
        assert body["username"] == "member"
        assert body["is_admin"] is False

    def test_requires_a_token(self, client):
        assert client.get("/auth/me").status_code == 401


# ── The other two auth modes ──────────────────────────────────────────────────
#
# `auth_backends.py` has thorough unit tests. What these cover is the flow
# through the HTTP routes: which of them answer, which refuse, and what each
# one leaves behind in the database. Every route is exercised in every mode,
# because the interesting failures are the ones where a route that should be
# inert quietly is not.


class TestLdapMode:
    @pytest.fixture(autouse=True)
    def mode(self, ldap_mode):
        return ldap_mode

    def test_config_reports_the_mode(self, client):
        assert client.get("/auth/config").json()["auth_mode"] == "ldap"

    def test_config_turns_signup_off(self, client):
        """Whatever ALLOW_REGISTRATION says: this app does not own the accounts."""
        assert client.get("/auth/config").json()["registration_enabled"] is False

    def test_register_is_403(self, client):
        res = client.post("/auth/register", json={"username": "kim", "password": "pw12345678"})
        assert res.status_code == 403
        assert "directory" in res.json()["detail"]

    def test_register_creates_nothing(self, client, db):
        client.post("/auth/register", json={"username": "kim", "password": "pw12345678"})
        assert db.query(User).count() == 0

    def test_a_refused_signup_does_not_spend_the_limiter(self, client):
        """Regression: the limiter ran first, so an anonymous caller could
        exhaust a real budget on a route that can never succeed."""
        for _ in range(10):
            assert (
                client.post(
                    "/auth/register", json={"username": "kim", "password": "pw12345678"}
                ).status_code
                == 403
            )

    def test_login_binds_and_returns_a_token(self, client, monkeypatch):
        directory_with(monkeypatch)
        res = client.post("/auth/login", json={"username": "kim", "password": "password123"})
        assert res.status_code == 200
        assert res.json()["user"]["username"] == "kim"

    def test_login_creates_the_shadow_row(self, client, db, monkeypatch):
        """Every foreign key in the schema points at users.id, so a directory
        identity needs a local row before it can own anything."""
        directory_with(monkeypatch)
        client.post("/auth/login", json={"username": "kim", "password": "password123"})

        user = db.query(User).filter(User.username == "kim").one()
        assert user.password_hash is None
        assert user.auth_source == "ldap"

    def test_login_sets_the_cover_cookie(self, client, monkeypatch):
        # An <img> tag cannot send the Authorization header, so without this
        # every cover on the page 401s.
        directory_with(monkeypatch)
        res = client.post("/auth/login", json={"username": "kim", "password": "password123"})
        assert COVER_COOKIE_NAME in res.cookies

    def test_a_rejected_bind_is_401(self, client, monkeypatch):
        directory_with(monkeypatch, user_bind=False)
        res = client.post("/auth/login", json={"username": "kim", "password": "wrong"})
        assert res.status_code == 401

    def test_a_rejected_bind_creates_nothing(self, client, db, monkeypatch):
        directory_with(monkeypatch, user_bind=False)
        client.post("/auth/login", json={"username": "kim", "password": "wrong"})
        assert db.query(User).count() == 0

    def test_the_token_from_a_bind_works_on_me(self, client, monkeypatch):
        directory_with(monkeypatch)
        token = client.post(
            "/auth/login", json={"username": "kim", "password": "password123"}
        ).json()["access_token"]

        res = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res.json()["username"] == "kim"

    def test_me_without_a_token_is_401(self, client):
        assert client.get("/auth/me").status_code == 401


class TestProxyMode:
    @pytest.fixture(autouse=True)
    def mode(self, proxy_mode):
        return proxy_mode

    def test_config_reports_the_mode(self, client):
        """The frontend renders no auth screen at all in this mode."""
        assert client.get("/auth/config").json()["auth_mode"] == "proxy"

    def test_config_turns_signup_off(self, client):
        assert client.get("/auth/config").json()["registration_enabled"] is False

    def test_register_is_403(self, client):
        res = client.post("/auth/register", json={"username": "kim", "password": "pw12345678"})
        assert res.status_code == 403

    def test_the_refusal_does_not_name_a_directory(self, client):
        """There need not be one: the upstream may be an SSO portal or a header
        the reverse proxy sets. Naming a directory sends people to ask an
        administrator who does not exist."""
        detail = client.post(
            "/auth/register", json={"username": "kim", "password": "pw12345678"}
        ).json()["detail"]
        assert "directory" not in detail.lower()

    def test_register_creates_nothing(self, client, db):
        client.post("/auth/register", json={"username": "kim", "password": "pw12345678"})
        assert db.query(User).count() == 0

    def test_login_is_401(self, client):
        """There is no password to check: the proxy already authenticated."""
        res = client.post("/auth/login", json={"username": "kim", "password": "password123"})
        assert res.status_code == 401

    def test_login_creates_nothing(self, client, db):
        """A login body must never be a way to mint an account in this mode."""
        client.post("/auth/login", json={"username": "kim", "password": "password123"})
        assert db.query(User).count() == 0

    def test_me_reads_the_header(self, client):
        res = client.get("/auth/me", headers=proxy_headers("kim"))
        assert res.status_code == 200
        assert res.json()["username"] == "kim"

    def test_me_without_a_header_is_401(self, client):
        assert client.get("/auth/me").status_code == 401

    def test_a_bearer_token_alone_is_not_enough(self, client, admin):
        """The header is the only identity this mode accepts. A token minted
        before the switch must not keep working around the proxy."""
        assert client.get("/auth/me", headers=admin["headers"]).status_code == 401

    def test_the_first_header_identity_becomes_the_admin(self, client):
        """Otherwise a deployment with no groups header has a catalogue nobody
        can administer, and no recovery short of editing the database."""
        assert client.get("/auth/me", headers=proxy_headers("kim")).json()["is_admin"] is True

    def test_a_malformed_identity_is_refused(self, client, db):
        client.get("/auth/me", headers=proxy_headers("x" * 400))
        assert db.query(User).count() == 0

    def test_no_route_sets_the_cover_cookie(self, client):
        """Nothing here logs in, so nothing mints one, `/auth/switch` aside.
        Covers work anyway, because the proxy sets its header on the image
        request too. Proved in tests/routers/test_covers.py rather than
        assumed."""
        res = client.get("/auth/me", headers=proxy_headers("kim"))
        assert COVER_COOKIE_NAME not in res.cookies


# ── Switching to a test account ───────────────────────────────────────────────
#
# The one route that hands a session on one account to somebody holding
# another's. What is worth pinning is the refusals: a directory-backed account
# is never a target in any mode, and a session is never issued without the
# password.


@pytest.fixture
def test_account(client, admin) -> dict:
    """An admin-created test account, made the way the UI makes one."""
    res = client.post(
        "/api/users/test-accounts",
        json={"username": "tester", "password": "pw12345678"},
        headers=admin["headers"],
    )
    assert res.status_code == 201, res.text
    return dict(res.json(), password="pw12345678")


class TestSwitchAccount:
    def test_the_right_password_returns_a_token_for_the_target(
        self, client, admin, test_account
    ):
        res = client.post(
            "/auth/switch",
            json={"username": "tester", "password": "pw12345678"},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert res.json()["user"]["username"] == "tester"
        assert res.json()["user"]["is_admin"] is False

    def test_the_token_acts_as_the_target(self, client, admin, test_account):
        token = client.post(
            "/auth/switch",
            json={"username": "tester", "password": "pw12345678"},
            headers=admin["headers"],
        ).json()["access_token"]

        res = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res.json()["username"] == "tester"

    def test_it_sets_the_cover_cookie(self, client, admin, test_account):
        """Exactly like a login: without it the switched session has no covers."""
        res = client.post(
            "/auth/switch",
            json={"username": "tester", "password": "pw12345678"},
            headers=admin["headers"],
        )
        assert COVER_COOKIE_NAME in res.cookies

    def test_a_wrong_password_is_401(self, client, admin, test_account):
        """The password is the difference between this and impersonation."""
        res = client.post(
            "/auth/switch",
            json={"username": "tester", "password": "wrong"},
            headers=admin["headers"],
        )
        assert res.status_code == 401

    def test_an_unknown_name_is_404(self, client, admin):
        res = client.post(
            "/auth/switch",
            json={"username": "ghost", "password": "pw12345678"},
            headers=admin["headers"],
        )
        assert res.status_code == 404

    def test_an_ordinary_member_is_not_a_target(self, client, admin, member):
        """Even with the right password, and even though this is local mode
        where the admin could type it into the login form instead. The rule is
        the account, not the mode."""
        res = client.post(
            "/auth/switch",
            json={"username": "member", "password": "password123"},
            headers=admin["headers"],
        )
        assert res.status_code == 404

    def test_the_admin_own_account_is_not_a_target(self, client, admin):
        res = client.post(
            "/auth/switch",
            json={"username": "admin", "password": "password123"},
            headers=admin["headers"],
        )
        assert res.status_code == 404

    def test_a_non_admin_is_403(self, client, admin, member, test_account):
        res = client.post(
            "/auth/switch",
            json={"username": "tester", "password": "pw12345678"},
            headers=member["headers"],
        )
        assert res.status_code == 403

    def test_it_needs_a_session(self, client, admin, test_account):
        res = client.post(
            "/auth/switch", json={"username": "tester", "password": "pw12345678"}
        )
        assert res.status_code == 401

    def test_guesses_are_bounded(self, client, admin, test_account):
        """The caller is an admin, so this is not the first line of defence. It
        is that a password check reachable over HTTP is one worth bounding."""
        for _ in range(10):
            client.post(
                "/auth/switch",
                json={"username": "tester", "password": "wrong"},
                headers=admin["headers"],
            )

        res = client.post(
            "/auth/switch",
            json={"username": "tester", "password": "wrong"},
            headers=admin["headers"],
        )
        assert res.status_code == 429

    def test_getting_it_right_clears_the_count(self, client, admin, test_account):
        for _ in range(9):
            client.post(
                "/auth/switch",
                json={"username": "tester", "password": "wrong"},
                headers=admin["headers"],
            )

        assert (
            client.post(
                "/auth/switch",
                json={"username": "tester", "password": "pw12345678"},
                headers=admin["headers"],
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/auth/switch",
                json={"username": "tester", "password": "wrong"},
                headers=admin["headers"],
            ).status_code
            == 401
        )

    def test_a_switched_session_cannot_switch_again(self, client, admin, test_account):
        """The session is the test account's, and a test account is never an
        admin. Without this an admin's one switch is a session that can reach
        every other test account without the password to any of them."""
        token = client.post(
            "/auth/switch",
            json={"username": "tester", "password": "pw12345678"},
            headers=admin["headers"],
        ).json()["access_token"]

        res = client.post(
            "/auth/switch",
            json={"username": "tester", "password": "pw12345678"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 403

    def test_a_switched_session_cannot_create_a_test_account(
        self, client, admin, test_account, db
    ):
        token = client.post(
            "/auth/switch",
            json={"username": "tester", "password": "pw12345678"},
            headers=admin["headers"],
        ).json()["access_token"]

        res = client.post(
            "/api/users/test-accounts",
            json={"username": "another", "password": "pw12345678"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert res.status_code == 403
        assert db.query(User).filter(User.username == "another").first() is None

    def test_it_is_logged_with_both_names(self, client, admin, test_account, caplog):
        with caplog.at_level(logging.WARNING):
            client.post(
                "/auth/switch",
                json={"username": "tester", "password": "pw12345678"},
                headers=admin["headers"],
            )

        switches = [r for r in caplog.records if "switched into" in r.message]
        assert switches and switches[0].levelno == logging.WARNING
        assert "'admin'" in switches[0].getMessage()
        assert "'tester'" in switches[0].getMessage()


class TestSwitchInLdapMode:
    @pytest.fixture(autouse=True)
    def mode(self, ldap_mode):
        return ldap_mode

    def test_an_admin_can_switch_into_a_test_account(self, client, admin, test_account):
        """The reason the feature exists: `/auth/login` cannot reach a local
        password in this mode, so this is the only way to see the library as an
        ordinary member sees it."""
        res = client.post(
            "/auth/switch",
            json={"username": "tester", "password": "pw12345678"},
            headers=admin["headers"],
        )
        assert res.status_code == 200

    def test_a_directory_account_is_never_a_target(self, client, admin, db, monkeypatch):
        """Even after a successful bind has created the shadow row, and even if
        an admin somehow knows the password. An admin able to mint a session
        for a directory member could read that member's private books."""
        directory_with(monkeypatch)
        client.post("/auth/login", json={"username": "kim", "password": "password123"})
        assert db.query(User).filter(User.username == "kim").one().auth_source == "ldap"

        res = client.post(
            "/auth/switch",
            json={"username": "kim", "password": "password123"},
            headers=admin["headers"],
        )
        assert res.status_code == 404


class TestSwitchInProxyMode:
    """Where the precedence between a header and a token has to be explicit."""

    @pytest.fixture(autouse=True)
    def mode(self, proxy_mode):
        return proxy_mode

    @pytest.fixture
    def boss(self, client) -> dict:
        """The first header identity, which is how an admin exists here."""
        client.get("/auth/me", headers=proxy_headers("boss"))
        return proxy_headers("boss")

    @pytest.fixture
    def switched(self, client, boss) -> str:
        client.post(
            "/api/users/test-accounts",
            json={"username": "tester", "password": "pw12345678"},
            headers=boss,
        )
        res = client.post(
            "/auth/switch",
            json={"username": "tester", "password": "pw12345678"},
            headers=boss,
        )
        assert res.status_code == 200, res.text
        return str(res.json()["access_token"])

    def test_the_switch_token_beats_the_proxy_header(self, client, boss, switched):
        res = client.get(
            "/auth/me", headers={**boss, "Authorization": f"Bearer {switched}"}
        )
        assert res.json()["username"] == "tester"

    def test_dropping_the_token_restores_the_proxy_identity(self, client, boss, switched):
        """This is the whole of "switch back" in this mode: the upstream names
        the admin again on the very next request."""
        assert client.get("/auth/me", headers=boss).json()["username"] == "boss"

    def test_a_directory_account_is_never_a_target(self, client, boss, db):
        client.get("/auth/me", headers=proxy_headers("kim"))

        res = client.post(
            "/auth/switch",
            json={"username": "kim", "password": "pw12345678"},
            headers=boss,
        )
        assert res.status_code == 404

    def test_an_ordinary_token_still_does_not_beat_the_header(self, client, boss, admin):
        """The narrow acceptance is the point. A token minted before a
        deployment moved to proxy auth names a real member, and reviving it
        would be a way around the proxy."""
        res = client.get("/auth/me", headers={**boss, **admin["headers"]})
        assert res.json()["username"] == "boss"

    def test_a_switch_token_stops_working_when_the_flag_comes_off(
        self, client, boss, switched, db
    ):
        """`is_switch_target` is re-read per request rather than frozen into
        the token, so the row is what decides."""
        account = db.query(User).filter(User.username == "tester").one()
        account.is_test_account = False
        db.commit()

        res = client.get(
            "/auth/me", headers={**boss, "Authorization": f"Bearer {switched}"}
        )
        assert res.json()["username"] == "boss"

    def test_a_switch_token_alone_still_works_without_a_header(self, client, boss, switched):
        """The token is a session in its own right, not a modifier on a header."""
        res = client.get("/auth/me", headers={"Authorization": f"Bearer {switched}"})
        assert res.json()["username"] == "tester"


def _routes_answering_with_a_bare_response() -> list[Any]:
    """Every documented route whose handler builds a `Response` itself.

    **Exactly the base class, not a subclass.** A `StreamingResponse` or a
    `FileResponse` carries a body and a media type of its own, and the export
    and cover routes return those. A bare `Response` in this API is the answer
    that carries nothing, which is what this rule is about.

    `main.iter_api_routes` rather than `app.routes`, because `include_router`
    appends a wrapper rather than splicing the child's routes in, and filtering
    `app.routes` on `APIRoute` finds the one route `main.py` declares itself.
    """
    return [
        route
        for route in main.iter_api_routes(main.app.routes)
        if route.include_in_schema
        and typing.get_type_hints(route.endpoint).get("return") is Response
    ]


def _declared_content(route: Any, schema: dict[str, Any]) -> dict[str, Any]:
    method = next(iter(route.methods)).lower()
    responses = schema["paths"][route.path][method]["responses"]
    return responses[str(route.status_code)].get("content", {})


class TestARouteThatSendsNoBodyDocumentsNone:
    """The schema promised a body two routes never send.

    `POST /auth/reset/request` and `POST /auth/verify/request` answer 202 with
    nothing in it, deliberately: the answer is the same whether or not the
    account exists, which is a privacy property rather than an omission. The
    schema documented that 202 as `application/json`, so the committed
    document, which the TypeScript client is generated from, described a body
    that never arrives. Found 2026-09-20 by `tests/api_contract.py`, which
    reported a missing content type and a JSON deserialisation error on an
    empty body.

    **The fix is a declaration and not a body**, which is what keeps the
    privacy property untouched: `response_class=Response` tells FastAPI there
    is no media type, and the bytes on the wire do not move.

    **The other half of this rule lives in `tests/test_declared_media_types.py`**,
    and until 2026-09-29 it was this docstring's open residue: a route that sends
    a body under a media type the schema does not declare.
    `GET /api/books/export`, `GET /api/backup` and both cover routes all did, and
    `tests/api_contract.py` was blind to it because schemathesis skips a response
    whose content type the definition does not carry. That file now takes the
    routes annotated with a **subclass** of `Response` and requires them content
    that is not JSON, while this one takes the routes annotated with exactly
    `Response` and forbids them content at all.

    **The two select on the same key, so neither can take a route from the
    other, and the key is also what they both miss.** What it does not see is
    stated where it is derived, in that file's own walk, rather than bounded
    here: an annotation that is not a class sits outside both rules, and so
    does one that is a class and is not a `Response`. Measured 2026-09-29
    under this worktree's Python: `isinstance(typing.Any, type)` is True and
    `issubclass(typing.Any, Response)` is False, so a route annotated `-> Any`
    passes both while neither is about it, and a union is not a class at all.
    """

    def test_some_such_route_could_have_carried_a_body(self) -> None:
        """The vacuity arm, and 204 is why it is not simply "some route".

        FastAPI already omits the content for a status that forbids a body, so
        a rule satisfied only by the three 204s here would hold over a tree
        where every 202 promised a body again."""
        answerable = [
            route
            for route in _routes_answering_with_a_bare_response()
            if is_body_allowed_for_status_code(route.status_code)
        ]

        assert answerable, (
            "no documented route answers with a bare Response under a status "
            "that allows a body, so this rule is about nothing"
        )

    def test_none_of_them_declares_content(self) -> None:
        """Off `app.openapi()`. `test_openapi_drift.py` holds the committed
        `frontend/openapi.json` byte identical to what `scripts/dump_openapi.py`
        writes, so this is that document without a second copy of where it
        lives."""
        schema = main.app.openapi()
        promised = [
            f"{min(route.methods)} {route.path} declares "
            f"{sorted(_declared_content(route, schema))} for {route.status_code}"
            for route in _routes_answering_with_a_bare_response()
            if _declared_content(route, schema)
        ]

        assert promised == [], (
            "These routes answer with an empty body and the schema this API "
            "publishes says otherwise, so a generated client and anything validating the "
            "document are both wrong about them:\n  " + "\n  ".join(promised)
        )

    def test_the_default_is_what_this_rule_refuses(self) -> None:
        """The diagonal. Without it the rule reads as a fact about FastAPI
        rather than a choice each route makes, and a reader would delete the
        argument as redundant."""
        app = FastAPI()

        @app.post("/quietly", status_code=202)
        def _quietly() -> Response:
            return Response(status_code=202)

        declared = app.openapi()["paths"]["/quietly"]["post"]["responses"]["202"]

        assert "content" in declared


# ── An untrusted username never forges a log line ─────────────────────────────


#: A username that tries to write a log line of its own.
#:
#: The tail is what a forged line looks like to whoever reads the log. The
#: carriage return is there because `UserCreate`'s `^\S.*$` accepts one:
#: measured 2026-09-28 against pydantic's own validator, that pattern refuses a
#: newline and accepts `\r` and NUL. So copying it onto `LoginRequest` would
#: not have closed this, which is the reason the fix is at the log site and
#: not at the schema. The comment on `LoginRequest.username` holds the rest.
#:
#: **The NUL is what arms the width of `_CONTROL_CHARACTERS`**, and without it
#: that set is wider than anything here exercises. A fix respelled to strip
#: CR and LF and nothing else defeats a newline only rule while still losing
#: the escaping `clipped` gives, and the NUL is what stays behind for the
#: wider rule to catch. Measured: with the NUL removed from this constant, a
#: respelling that strips both line breaks passes every arm.
A_NAME_THAT_FORGES_A_LINE = "kim\x00\r\nWARNING endpaper.auth granted"

#: A forged name for a model whose own pattern refuses the one above.
#:
#: `UserCreate` carries `^\S.*$`, so `POST /auth/register` answered 422 to the
#: name above and its handler never ran: the route sat in the population and
#: was permanently unexercised, and a log line added to it would never have
#: been reached. Measured against pydantic 2026-09-28, that pattern refuses
#: the name above and accepts this one.
#:
#: **Neither carries a colon**, and that is a constraint of the population
#: rather than taste: `SourceCredentialIn` refuses one outright, under RFC
#: 7617, because the sealed pair uses it as its separator. With a colon, those
#: two routes tripped `_a_body_for`'s own refusal and took the suite down.
#: **They were not dropping out of the sweep**: both are gated, so they
#: answered 401 from the dependency before and after, and the only route this
#: fallback genuinely moved into the exercised half is `POST /auth/register`.
#:
#: **A bare carriage return is still a forged line**, not a weaker stand in: a
#: terminal returns the cursor to column zero and what follows overwrites what
#: was there, and `str.splitlines` treats it as a break, so `_lines_forged_in`
#: reads it as one too. The widened predicate catches it either way.
A_NAME_A_STRICTER_MODEL_ACCEPTS = "kim\x00\rWARNING endpaper.auth granted"

#: Both forged names, since an arm that arms one and not the other leaves the
#: unarmed one free to be tidied into something harmless.
_THE_FORGED_NAMES = (A_NAME_THAT_FORGES_A_LINE, A_NAME_A_STRICTER_MODEL_ACCEPTS)

#: Something to put in a required field that is not the username.
#: `password123` clears `MIN_PASSWORD_LENGTH` wherever the model imposes it.
_FILLER = "password123"


def _routes_declaring_a_username() -> list[Any]:
    """Every documented route whose request body declares a `username`.

    **Derived from what the model declares, not from a list of paths or a grep
    over the routers.** A list here would go stale the first time a route grew
    a username, and the route added tomorrow is in this population the moment
    its schema is.

    **What it does not reach**, stated rather than left to be found: an
    identity that arrives somewhere other than a request body.
    `auth_backends._PROXY_USERNAME` is the live example, a name taken from a
    header, and it is bounded by that pattern instead of by this.
    """
    found = []
    for route in main.iter_api_routes(main.app.routes):
        body = getattr(route, "body_field", None)
        if body is None or not route.include_in_schema:
            continue
        if "username" in getattr(body.field_info.annotation, "model_fields", {}):
            found.append(route)
    return found


def _the_other_required_fields_of(model: Any) -> dict[str, Any]:
    """Every required field except the username, filled with a string."""
    return {
        name: _FILLER
        for name, field in model.model_fields.items()
        if name != "username" and field.is_required()
    }


def _a_body_for(route: Any) -> dict[str, Any]:
    """A body this route's own model accepts, carrying a forged username.

    **Two ways a route leaves the sweep while every arm stays green**, and
    this refuses both loudly rather than tolerating either.

    A body short of a required field is a 422 before the handler runs.
    `_FILLER` is a string, so that is the day a required int or enum appears.

    A body whose username the model's own pattern refuses is the same 422, and
    it was live: `UserCreate` carries a pattern refusing a newline, so
    `POST /auth/register` sat in the population permanently unexercised. So
    this tries each forged name in turn and fails naming the route when the
    model takes none of them.
    """
    model = route.body_field.field_info.annotation
    others = _the_other_required_fields_of(model)

    for candidate in _THE_FORGED_NAMES:
        body = {**others, "username": candidate}
        try:
            model.model_validate(body)
        except ValidationError as refusal:
            elsewhere = [
                error for error in refusal.errors() if error["loc"] != ("username",)
            ]
            assert not elsewhere, (
                f"{route.path}: this helper built a body that {model.__name__} "
                f"refuses for a field other than the username, so the sweep "
                f"would 422 before the handler ran and would pass on nothing. "
                f"Teach the helper that field's type: {elsewhere}"
            )
            continue
        return body

    raise AssertionError(
        f"{route.path}: {model.__name__} refuses every forged name in this "
        f"file, so the route sits in the population and is never exercised. "
        f"Add one it accepts that still carries a control character."
    )


#: Unicode general category `Cc`, which is C0, DEL and C1, plus `Zl` and `Zp`,
#: the line and paragraph separators. Sixty seven characters.
#:
#: **Not "everything `repr` escapes", which this said twice and is an
#: overclaim both times.** `repr` also escapes `Cf`, `Cs`, `Co`, `Cn` and the
#: spaces in `Zs`, and none of those is in here. The right to refuse those is
#: declined rather than claimed: a right to left override spoofs a *display*,
#: which is a different question from forging a line, and admitting the whole
#: of `Cf` would refuse text nobody here has looked at.
#:
#: **What it does cover completely is the line break**, which is the property
#: the rule is about. Derived from `str.splitlines` over all 1,114,112
#: codepoints rather than listed: ten characters break a line, seven in C0 and
#: then NEL, LS and PS. A set of C0 plus DEL alone left those last three out
#: while the sentence above it claimed otherwise, so a value carrying LS forged
#: a line and passed.
#: `test_the_control_set_is_the_population_it_says_it_is` re-derives both the
#: line breaks and the category on every run, so a future Python adding a break
#: is a red, and so is this constant drifting from the sentence above it.
#: **This is the third shape this set has taken**, and the first two were read
#: rather than checked, which is why both halves are now asserted: a subset arm
#: alone would leave 57 of these 67 held by nothing but the literal.
#:
#: **The literal below is deliberate: do not rewrite it as a comprehension over
#: those three category names.** The equality arm is a second opinion only
#: while the two sides are written independently, one derived from the
#: categories and one spelled out here. Derive both and the assertion compares
#: a derivation with itself, passes over any category triple including a
#: mistyped one, and all sixty seven members go back to being held by nothing.
#:
#: Measured 2026-09-28 in the other direction: no format string under
#: `backend/` outside the test tree carries any of these, and `clipped`
#: escapes every one, so widening refuses nothing this repository writes.
#: **That population is narrower than the predicate**, which judges every
#: record in the process at DEBUG, third party ones included. TAB is in here
#: and is the member most likely to fire benignly first.
_CONTROL_CHARACTERS = frozenset(
    chr(code) for code in (*range(0x20), 0x7F, *range(0x80, 0xA0), 0x2028, 0x2029)
)

#: The half of each forged name that would stand as a log line of its own.
#: Derived from the constants rather than written out again, so they cannot
#: drift and rewording a name does not silently disarm the traceback arm.
_THE_FORGED_LINES = tuple(name.splitlines()[-1] for name in _THE_FORGED_NAMES)


def _one_line(record: logging.LogRecord) -> bool:
    """Whether the interpolated message carries no raw control character.

    `getMessage()` rather than `caplog.text`, and that is a real blind spot
    rather than a simplification: a traceback is legitimately several lines
    and logging rather than the caller wrote those, but `exc_info` is also a
    second route for the caller's own value to reach the log.
    `_lines_forged_in` is what covers that half.
    """
    return not (_CONTROL_CHARACTERS & set(record.getMessage()))


def _lines_forged_in(text: str) -> list[str]:
    """Lines of the captured output that the forged name wrote on its own.

    Over `caplog.text`, which carries the traceback `record.getMessage()`
    omits. **Matching a line that begins with the forged half rather than
    refusing every newline**, because a traceback is several lines by nature
    and refusing those would make this arm a rule about tracebacks rather than
    about an injected value.
    """
    return [
        line
        for line in text.splitlines()
        if line.startswith(_THE_FORGED_LINES)
    ]


class TestAnUntrustedUsernameCannotForgeALogLine:
    """A username typed by an unauthenticated caller reached a log line raw.

    `auth_backends.authenticate_ldap` interpolated it with `%s` on its two
    failure paths, so a newline in the value wrote a second line into the log
    and an operator reading that log sees an event nobody emitted. The fix is
    `logvalues.clipped` at the log site, and **what does the work is its
    `repr`**, which escapes the newline. Its slice is dead at these two sites,
    whose value the schema has already bounded.

    **What this asserts is a property of the emitted record, never a spelling
    at the call site.** Measured 2026-09-28 by two seats independently, at 136
    and 137 `logger` call sites under `backend/` outside the test tree, the
    difference being one migration: none carries a C0 or DEL character in a
    format string, so one in a record is an interpolated value and nothing
    else. That is why this can ignore `%r` against `%s` entirely and keeps
    holding if the fix is later written a different way.

    **The rule has two halves and each is needed.** `_one_line` reads the
    interpolated message; `_lines_forged_in` reads `caplog.text`, which is the
    only place a value arriving through `exc_info` or `stack_info` appears.
    That second channel is live rather than theoretical: `errors.py` passes
    the exception into the 500 handler for every route in this population and
    its own docstring says a traceback can quote request data back to whoever
    triggered it, and `routers/auth.py` logs a mail failure the same way.

    **Six of these ten run a handler and four do not, and the 401 count is
    not the handler count.** Four carry `Depends(require_admin)`, and FastAPI
    solves a dependency before it validates a body, so those answer 401
    without their handler running or their body being looked at.
    `POST /auth/login` also answers 401, and that one is **written by the
    handler** after it ran and refused the password. Measured 2026-09-28 over
    all ten: 201, 202, 202, 400, 400, and five 401s of which one is login's
    own. **No 422**, which is the state `_a_body_for` exists to keep, since a
    422 means a route left the sweep without saying so.

    So a log line added to `login` or to the four unauthenticated recovery
    routes is covered the day it is written; **a log line added to one of the
    four gated routes is not**, because this sweep never holds a token. That
    is the distinction the six against four is for, and it is roughly what
    `test_a_route_in_the_population_actually_reaches_a_handler` protects.
    **Roughly, and that arm is the honest one of the two**: it reddens when
    the sweep reaches no handler at all, not when a single route crosses.
    Five routes answer something other than 401 today, so four could gain a
    dependency with it still green. Catching one crossing would need an
    expected answer per route, which is the listed population this whole guard
    is built to avoid, so the coarse arm is the deliberate choice.

    All of it is the default mode only, so the directory branch is not in this
    sweep at all;
    `TestADirectoryFailureCannotBeMadeToForgeALogLine` below is that branch
    and the non vacuous half, and each of its arms fails if nothing was
    captured.

    **Capturing at DEBUG judges third party records by the same predicate**,
    and one library is already close to the edge. SQLAlchemy emits multi-line
    SQL and does not trip this only because it sets its own logger to WARNING
    at import: turning `echo=True` on would redden this guard with a verdict
    about a SELECT rather than about a username. That is the note to read
    first if this goes red for something nobody here wrote. Narrowing the
    capture is the wrong answer, since it is what two of this guard's findings
    were bought with; narrow by logger name if it ever comes to that.

    ## What this does not see

    **Written down rather than closed, and each line says which it is.** Four
    review rounds each found a real gap in the sentences above; the residue is
    recorded so the fifth reader starts where the fourth stopped.

    Deliberate narrowings, not holes:

    * **Only the default auth mode.** The directory branch is not swept at
      all; `TestADirectoryFailureCannotBeMadeToForgeALogLine` covers it.
    * **Only `Cc`, `Zl` and `Zp`.** `repr` escapes `Cf`, `Cs`, `Co`, `Cn` and
      most of `Zs` too, and refusing those is declined: a right to left
      override spoofs a display, which is a different question from forging a
      line, and admitting all of `Cf` would refuse text nobody has read.
    * **No token is ever held**, so the four gated routes never run a handler
      here and a log line added inside one is not covered.

    Holes, open:

    * **A single route crossing into the gated half is not caught**, only the
      sweep going all refusals. See the paragraph above for why the finer arm
      is not worth its population.
    * **Third party records are judged by this predicate**, so this can redden
      for something nobody in this repository wrote. TAB is the likeliest
      benign firer and was in the narrower set too.
    * **Only what reaches the logging module is seen.** A value written to a
      stream directly, or to a file this process opens, is invisible here.
    """

    def test_some_route_declares_a_username(self) -> None:
        """The vacuity arm: without one, this rule is about nothing."""
        assert _routes_declaring_a_username()

    def test_the_control_set_is_the_population_it_says_it_is(self) -> None:
        """Both halves of the constant's claim, asked of the interpreter.

        Every earlier version of `_CONTROL_CHARACTERS` was a list somebody had
        reasoned their way to, and one was short by NEL, LS and PS. So the
        constant is checked rather than read, over **every** codepoint rather
        than a plausible prefix of them.

        **Two assertions and the second is the one that pins it.** The subset
        arm alone leaves 57 of the 67 members held by nothing but the literal:
        measured, deleting NUL, TAB, ESC or DEL from the constant passes it,
        and NUL is the member this file's own arming arm depends on. Only
        `test_the_forged_names_still_carry_a_line_break` would have noticed,
        and only for NUL. The equality arm sees all four.

        It costs one category lookup in a loop already running, and it turns
        the sentence beside the constant, that this is `Cc` plus `Zl` plus
        `Zp`, from prose into something that fails when it stops being true.
        """
        breaks = set()
        category = set()
        for code in range(0x110000):
            character = chr(code)
            if character.splitlines() != [character]:
                breaks.add(character)
            if unicodedata.category(character) in {"Cc", "Zl", "Zp"}:
                category.add(character)

        assert breaks, "splitlines broke on nothing, so this arm measured nothing"
        assert breaks <= _CONTROL_CHARACTERS, (
            "these characters forge a line and the predicate lets them through: "
            + ", ".join(sorted(hex(ord(c)) for c in breaks - _CONTROL_CHARACTERS))
        )
        assert category == _CONTROL_CHARACTERS, (
            "the constant is no longer the Cc, Zl and Zp population its own "
            "comment claims. Missing: "
            + (", ".join(sorted(hex(ord(c)) for c in category - _CONTROL_CHARACTERS)) or "none")
            + ". Extra: "
            + (", ".join(sorted(hex(ord(c)) for c in _CONTROL_CHARACTERS - category)) or "none")
        )

    def test_a_route_in_the_population_actually_reaches_a_handler(self, client) -> None:
        """The auth direction, which nothing else here covers.

        `_a_body_for` fails loudly when a model would refuse the body, so the
        schema direction cannot hollow the sweep out quietly. A route gaining a
        dependency is the same hollowing by the other door: it drops from
        running its handler to a 401 from the dependency, and every arm stays
        green over a sweep that now only ever measures refusals.

        One route answering anything else is enough, and the population comes
        from the same derivation the sweep uses rather than from a list.
        """
        answers = {
            route.path: client.request(
                min(route.methods),
                re.sub(r"\{[^}]+\}", "1", route.path),
                json=_a_body_for(route),
            ).status_code
            for route in _routes_declaring_a_username()
        }

        assert any(code not in (401, 403) for code in answers.values()), (
            "every route taking a username now answers 401 or 403, so the sweep "
            f"reaches no handler at all and measures only refusals: {answers}"
        )

    def test_the_forged_names_are_short_enough_to_be_accepted(self) -> None:
        """Otherwise every arm 422s at the length bound and goes green on it."""
        for name in _THE_FORGED_NAMES:
            assert len(name) <= USERNAME_MAX

    def test_the_forged_names_still_carry_a_line_break(self) -> None:
        """The arming arm, and it is not decoration.

        Every arm below reads one constant, so tidying the control characters
        out of it leaves all of them green over a tree where nothing is
        checked, and no diff shows a guard being removed. Asserting the
        property rather than the exact string, so the name may be reworded.

        Over **both** names, because an arm that arms one leaves the other
        free to be tidied into something harmless, and the sweep falls back to
        the second for any model whose own pattern refuses the first.

        The second assertion arms `_THE_FORGED_LINES`, derived by splitting
        each constant: a name with no break in it would derive the whole
        string, and the traceback arm would then look for something no
        traceback could contain.
        """
        for name, tail in zip(_THE_FORGED_NAMES, _THE_FORGED_LINES, strict=True):
            assert _CONTROL_CHARACTERS & set(name)
            assert tail and tail != name
        # And one control character that is NOT a line break, or the width of
        # `_CONTROL_CHARACTERS` is never exercised and the rule is a newline
        # rule wearing a wider name. Measured 2026-09-28: with this line
        # unsatisfied, a fix respelled to strip line breaks passes every arm
        # here, and the widened predicate passes the message it emits.
        #
        # **Asked of `splitlines`, not by stripping two spellings.** This line
        # used to strip `\n` and `\r`, the two it was written beside, while the
        # set holds ten line breaks. Measured: with the NUL in the forged name
        # replaced by NEL, LS, VT, PS or FS, the strip version passed while the
        # name carried nothing but line breaks, which is exactly the state it
        # exists to refuse. The fifty seven non breaking members are the same
        # fifty seven the equality arm found resting on the literal.
        non_breaking = {
            character
            for character in _CONTROL_CHARACTERS
            if character.splitlines() == [character]
        }
        assert non_breaking, "every member of the set breaks a line, so this arm is vacuous"
        for name in _THE_FORGED_NAMES:
            assert non_breaking & set(name), (
                f"{name!r} carries only line breaks, so nothing here exercises the "
                "width of the control set and a fix stripping line breaks alone "
                "would pass every arm in this file"
            )

    def test_no_route_taking_a_username_writes_a_control_character(
        self, client, caplog
    ) -> None:
        """Every method of every such route, not one of them per run.

        `sorted` rather than `next(iter(...))`: str hashing is randomised per
        process, so picking one out of the method set exercises a different
        verb on a multi-method route from run to run. None is multi-method
        today, which is what makes that a silent hole rather than a flake.
        """
        for route in _routes_declaring_a_username():
            for method in sorted(route.methods):
                caplog.clear()
                with caplog.at_level(logging.DEBUG):
                    client.request(
                        method,
                        re.sub(r"\{[^}]+\}", "1", route.path),
                        json=_a_body_for(route),
                    )
                for record in caplog.records:
                    assert _one_line(record), (method, route.path, record.getMessage())
                # `getMessage()` above cannot see `exc_info`, and that is a
                # live channel rather than a theoretical one: `errors.py`
                # passes the exception into the 500 handler for every route
                # here, and its own docstring says a traceback can quote
                # request data back to whoever triggered it. Without this
                # line the sweep is green over a tree where the login route
                # writes the forged line through `exc_info`, measured.
                assert not _lines_forged_in(caplog.text), (method, route.path)


class TestADirectoryFailureCannotBeMadeToForgeALogLine:
    """The two paths that do log the name a caller typed. See the class above.

    Both are reached over `POST /auth/login` rather than by calling the
    backend, because the point is that an unauthenticated request is enough.
    """

    @pytest.fixture(autouse=True)
    def mode(self, ldap_mode):
        return ldap_mode

    def _sign_in(self, client) -> None:
        client.post(
            "/auth/login",
            json={"username": A_NAME_THAT_FORGES_A_LINE, "password": _FILLER},
        )

    def test_an_unreachable_directory(self, client, monkeypatch, caplog) -> None:
        def explode(*args: object, **kwargs: object) -> None:
            raise LDAPException("connection refused")

        monkeypatch.setattr(auth_backends, "_connect", explode)

        with caplog.at_level(logging.DEBUG):
            self._sign_in(client)

        failures = [
            record
            for record in caplog.records
            if "LDAP authentication failed" in record.getMessage()
        ]
        assert failures, "this arm's own path emitted nothing, so it proved nothing"
        assert all(_one_line(record) for record in caplog.records)

    def test_an_ambiguous_filter(self, client, monkeypatch, caplog) -> None:
        entries = [
            FakeEntry(f"uid=kim{n},ou=people,dc=example,dc=org", f"kim{n}", [])
            for n in (1, 2)
        ]
        install_directory(
            monkeypatch, [FakeConnection(bind_results=[True], entries=entries)]
        )

        with caplog.at_level(logging.DEBUG):
            self._sign_in(client)

        matches = [
            record
            for record in caplog.records
            if "LDAP filter matched" in record.getMessage()
        ]
        assert matches, "this arm's own path emitted nothing, so it proved nothing"
        assert all(_one_line(record) for record in caplog.records)

    def test_a_refusal_carrying_the_name_does_not_forge_one_in_the_traceback(
        self, client, monkeypatch, caplog
    ) -> None:
        """`exc_info` is the second route the caller's own value takes to the log.

        ldap3 validates a filter's assertion value against the attribute's
        schema and raises `LDAPInvalidValueError`, an `LDAPException`, whose
        message carries the value verbatim. It reaches that check only where
        the attribute has a strict validator: `uid`, the shipped default, has
        none, and `uidNumber` on an RFC 2307 schema does.
        `escape_filter_chars` leaves CR and LF alone, so under
        `logger.exception` the traceback wrote the forged line as its own,
        past the `clipped` on the argument beside it.

        The message below reproduces ldap3's own, so the arm stays honest
        about what a traceback would carry; the interpolation is an f-string
        because the linter refuses the percent operator ldap3 uses, and the
        two produce the same characters. **Nothing here depends on that
        wording**: the assertion is that the forged half never begins a line.
        """

        class _ADirectoryThatRefusesTheValue(FakeConnection):
            def search(
                self, search_base: str, search_filter: str, attributes: list[str]
            ) -> None:
                raise LDAPInvalidValueError(
                    f"value '{search_filter}' non valid for attribute 'uidNumber'"
                )

        install_directory(
            monkeypatch,
            [_ADirectoryThatRefusesTheValue(bind_results=[True], entries=[])],
        )

        with caplog.at_level(logging.DEBUG):
            self._sign_in(client)

        failures = [
            record
            for record in caplog.records
            if "LDAP authentication failed" in record.getMessage()
        ]
        assert failures, "this arm's own path emitted nothing, so it proved nothing"
        assert all(_one_line(record) for record in caplog.records)
        assert not _lines_forged_in(caplog.text), (
            "the forged line reached the log through the traceback, past the "
            "escaping on the argument beside it"
        )

    def test_the_refusal_still_says_which_failure_it_was(
        self, client, monkeypatch, caplog
    ) -> None:
        """What the traceback was traded for, asserted rather than assumed.

        Dropping to `logger.error` gives up the frames. The exception class is
        the half worth keeping, and `repr` is what keeps it, so an operator can
        still tell a refused value from an unreachable server.
        """

        class _ADirectoryThatRefusesTheValue(FakeConnection):
            def search(
                self, search_base: str, search_filter: str, attributes: list[str]
            ) -> None:
                raise LDAPInvalidValueError("value non valid for attribute 'uidNumber'")

        install_directory(
            monkeypatch,
            [_ADirectoryThatRefusesTheValue(bind_results=[True], entries=[])],
        )

        with caplog.at_level(logging.DEBUG):
            self._sign_in(client)

        assert any(
            "LDAPInvalidValueError" in record.getMessage()
            for record in caplog.records
        )


class TestALoginNameIsNotCheckedAgainstTheRegistrationPattern:
    """The decision that `LoginRequest` carries no pattern, as a test.

    Two records state it, the comment on the field and the decision register,
    and **neither goes red if somebody adds the pattern back**: every username
    in the login tests matches `^\\S.*$`, so the suite stays green while the
    field starts refusing names it used to take. This is the arm that does not.

    401 rather than 422 is the second half and is why the shape of the answer
    is asserted and not only the fact of a refusal. `POST /auth/login` gives
    one answer to every failure so that nobody can tell an account that exists
    from one that does not, and a 422 naming the shape of a name is a second
    answer.
    """

    def test_a_name_the_registration_pattern_refuses_reaches_the_password_check(
        self, client, admin
    ) -> None:
        res = client.post(
            "/auth/login", json={"username": " admin", "password": "pw12345678"}
        )
        assert res.status_code == 401

    def test_registration_refuses_that_same_name(self, client) -> None:
        """The diagonal: without it the arm above is a fact about any bad name."""
        res = client.post(
            "/auth/register", json={"username": " admin", "password": "pw12345678"}
        )
        assert res.status_code == 422
