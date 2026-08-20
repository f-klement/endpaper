"""Tests for backend/auth.py: password hashing and JWT handling."""

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
import pytest

import settings_store
from auth import (
    ALGORITHM,
    BCRYPT_MAX_BYTES,
    create_access_token,
    hash_password,
    verify_password,
)
from config import secret_key
from tests.helpers import PNG_BYTES

# A cost-12 hash of "legacy-password", in the format passlib wrote before the
# switch to the bcrypt library. Existing accounts must keep working.
LEGACY_HASH = "$2b$12$QISVhx2YI209H11IZy5OWe2PWq4zh12h0tJZno9Uf6uHHaAGKiCg."


class TestPasswordHashing:
    def test_hash_then_verify_roundtrip(self):
        hashed = hash_password("correct horse battery staple")
        assert verify_password("correct horse battery staple", hashed) is True

    def test_wrong_password_is_rejected(self):
        hashed = hash_password("correct horse battery staple")
        assert verify_password("Correct horse battery staple", hashed) is False

    def test_hash_is_salted(self):
        """Two hashes of the same password must differ, or the salt is broken."""
        assert hash_password("same") != hash_password("same")

    def test_legacy_passlib_hash_still_verifies(self):
        assert verify_password("legacy-password", LEGACY_HASH) is True
        assert verify_password("wrong", LEGACY_HASH) is False

    def test_password_longer_than_bcrypt_limit_does_not_raise(self):
        """bcrypt only reads 72 bytes; the binding raises unless we truncate."""
        long_password = "a" * (BCRYPT_MAX_BYTES + 50)
        hashed = hash_password(long_password)
        assert verify_password(long_password, hashed) is True

    def test_passwords_differing_past_the_limit_collide(self):
        """Documents a real bcrypt property rather than asserting a wish.

        Anything past byte 72 is not hashed, so two passwords sharing a 72-byte
        prefix are the same password as far as bcrypt is concerned.
        """
        base = "a" * BCRYPT_MAX_BYTES
        hashed = hash_password(base + "tail-one")
        assert verify_password(base + "tail-two", hashed) is True

    def test_multibyte_password_truncates_on_bytes_not_characters(self):
        password = "🔒" * 30  # 4 bytes each: 120 bytes, 30 characters
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_malformed_hash_returns_false_instead_of_raising(self):
        assert verify_password("anything", "not-a-bcrypt-hash") is False

    def test_empty_hash_returns_false(self):
        assert verify_password("anything", "") is False


class TestAccessToken:
    def test_token_carries_user_id_and_username(self, db):
        token = create_access_token(db, 42, "alice")
        payload = jwt.decode(token, secret_key(), algorithms=[ALGORITHM])
        assert payload["sub"] == "42"
        assert payload["username"] == "alice"

    def test_token_carries_the_epoch_it_was_issued_under(self, db):
        """What a restore invalidates. See settings_store.bump_token_epoch."""
        token = create_access_token(db, 42, "alice")
        payload = jwt.decode(token, secret_key(), algorithms=[ALGORITHM])
        assert payload["epoch"] == settings_store.token_epoch(db)

    def test_token_has_a_future_expiry(self, db):
        token = create_access_token(db, 1, "alice")
        payload = jwt.decode(token, secret_key(), algorithms=[ALGORITHM])
        assert datetime.fromtimestamp(payload["exp"], tz=UTC) > datetime.now(UTC)

    def test_token_signed_with_another_key_is_rejected(self):
        token = jwt.encode({"sub": "1"}, "a-different-secret", algorithm=ALGORITHM)
        with pytest.raises(jwt.PyJWTError):
            jwt.decode(token, secret_key(), algorithms=[ALGORITHM])

    def test_expired_token_is_rejected(self):
        expired = jwt.encode(
            {"sub": "1", "exp": datetime.now(UTC) - timedelta(seconds=1)},
            secret_key(),
            algorithm=ALGORITHM,
        )
        with pytest.raises(jwt.ExpiredSignatureError):
            jwt.decode(expired, secret_key(), algorithms=[ALGORITHM])


class TestGetCurrentUserThroughTheApi:
    """get_current_user is a dependency, so it is exercised via a real route."""

    def test_valid_token_resolves_to_the_account(self, client, admin):
        res = client.get("/auth/me", headers=admin["headers"])
        assert res.status_code == 200
        assert res.json()["username"] == "admin"

    def test_missing_token_is_401(self, client):
        assert client.get("/auth/me").status_code == 401

    def test_garbage_token_is_401(self, client):
        res = client.get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
        assert res.status_code == 401

    def test_token_for_a_deleted_account_is_401(self, client, admin, db):
        from models import User

        db.query(User).delete()
        db.commit()
        assert client.get("/auth/me", headers=admin["headers"]).status_code == 401

    def test_token_without_a_subject_is_401(self, client):
        token = jwt.encode({"username": "ghost"}, secret_key(), algorithm=ALGORITHM)
        res = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 401


class TestRequireAdmin:
    def test_admin_may_set_the_login_image(self, client, admin, covers_dir):
        res = client.post(
            "/api/settings/login-image",
            files={"file": ("bg.png", PNG_BYTES, "image/png")},
            headers=admin["headers"],
        )
        assert res.status_code == 200

    def test_non_admin_is_403(self, client, member, covers_dir):
        res = client.post(
            "/api/settings/login-image",
            files={"file": ("bg.png", PNG_BYTES, "image/png")},
            headers=member["headers"],
        )
        assert res.status_code == 403


def test_bcrypt_cost_is_not_below_the_library_default():
    """Guards against a future 'speed up the tests' change weakening hashing."""
    cost = int(hash_password("x").split("$")[2])
    default_cost = int(bcrypt.gensalt().decode().split("$")[2])
    assert cost >= default_cost
