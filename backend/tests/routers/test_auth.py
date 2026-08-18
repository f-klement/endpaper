"""Tests for backend/routers/auth.py: registration, login, /auth/me."""

import pytest

from models import User


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
