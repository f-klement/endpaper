"""Tests for backend/routers/auth.py: registration, login, /auth/me."""

import pytest

from auth import COVER_COOKIE_NAME
from models import User
from tests.helpers import directory_with, proxy_headers


class TestRegister:
    def test_first_account_becomes_admin(self, client):
        res = client.post("/auth/register", json={"username": "first", "password": "pw12345678"})
        assert res.status_code == 201
        assert res.json()["user"]["is_admin"] is True

    def test_second_account_is_not_admin(self, client, admin):
        res = client.post("/auth/register", json={"username": "second", "password": "pw12345678"})
        assert res.status_code == 201
        assert res.json()["user"]["is_admin"] is False

    def test_registration_returns_a_usable_token(self, client):
        token = client.post(
            "/auth/register", json={"username": "first", "password": "pw12345678"}
        ).json()["access_token"]
        res = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200

    def test_duplicate_username_is_rejected(self, client, admin):
        res = client.post("/auth/register", json={"username": "admin", "password": "pw12345678"})
        assert res.status_code == 400
        assert "taken" in res.json()["detail"].lower()

    def test_password_is_never_returned(self, client):
        body = client.post(
            "/auth/register", json={"username": "first", "password": "pw12345678"}
        ).json()
        assert "password" not in body["user"]
        assert "password_hash" not in body["user"]

    def test_password_is_stored_hashed_not_plain(self, client, db):
        client.post("/auth/register", json={"username": "first", "password": "pw12345678"})
        stored = db.query(User).filter(User.username == "first").one().password_hash
        assert stored != "pw12345678"
        assert stored.startswith("$2")

    def test_missing_field_is_422(self, client):
        assert client.post("/auth/register", json={"username": "only"}).status_code == 422


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
        """Nothing here logs in, so nothing mints one. Covers work anyway,
        because the proxy sets its header on the image request too. Proved in
        tests/routers/test_covers.py rather than assumed."""
        res = client.get("/auth/me", headers=proxy_headers("kim"))
        assert COVER_COOKIE_NAME not in res.cookies
