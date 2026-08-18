"""Tests for backend/routers/settings.py: the admin-set login background."""

import pytest

from tests.helpers import JPEG_BYTES, NOT_AN_IMAGE, PNG_BYTES, WEBP_BYTES

PNG = PNG_BYTES


@pytest.fixture(autouse=True)
def clean_covers(covers_dir):
    """The login background is a file on disk, so clear it between tests."""
    for existing in covers_dir.glob("login_bg.*"):
        existing.unlink()
    yield
    for existing in covers_dir.glob("login_bg.*"):
        existing.unlink()


class TestGetLoginImage:
    def test_404_when_none_is_set(self, client):
        assert client.get("/api/settings/login-image").status_code == 404

    def test_returns_the_url_once_set(self, client, admin):
        client.post(
            "/api/settings/login-image",
            files={"file": ("bg.png", PNG, "image/png")},
            headers=admin["headers"],
        )
        assert client.get("/api/settings/login-image").json() == {"url": "/covers/login_bg.png"}

    def test_is_public(self, client, admin):
        """The login page has to read it before anyone is signed in."""
        client.post(
            "/api/settings/login-image",
            files={"file": ("bg.png", PNG, "image/png")},
            headers=admin["headers"],
        )
        assert client.get("/api/settings/login-image").status_code == 200


class TestSetLoginImage:
    def test_admin_can_upload(self, client, admin, covers_dir):
        res = client.post(
            "/api/settings/login-image",
            files={"file": ("bg.png", PNG, "image/png")},
            headers=admin["headers"],
        )
        assert res.status_code == 200
        assert (covers_dir / "login_bg.png").read_bytes() == PNG

    def test_non_admin_is_403(self, client, member):
        res = client.post(
            "/api/settings/login-image",
            files={"file": ("bg.png", PNG, "image/png")},
            headers=member["headers"],
        )
        assert res.status_code == 403

    def test_anonymous_is_401(self, client):
        res = client.post(
            "/api/settings/login-image", files={"file": ("bg.png", PNG, "image/png")}
        )
        assert res.status_code == 401

    @pytest.mark.parametrize(
        "payload", [PNG_BYTES, JPEG_BYTES, WEBP_BYTES], ids=["png", "jpeg", "webp"]
    )
    def test_accepts_every_supported_format(self, client, admin, payload):
        res = client.post(
            "/api/settings/login-image",
            files={"file": ("bg.png", payload, "image/png")},
            headers=admin["headers"],
        )
        assert res.status_code == 200

    def test_rejects_a_non_image_however_it_is_named(self, client, admin):
        """An SVG named .png used to be accepted on the strength of its name.
        It is served from our own origin and can carry script."""
        res = client.post(
            "/api/settings/login-image",
            files={"file": ("bg.png", NOT_AN_IMAGE, "image/png")},
            headers=admin["headers"],
        )
        assert res.status_code == 400

    def test_stores_by_content_not_by_filename(self, client, admin, covers_dir):
        """A JPEG uploaded as "bg.png" is stored as a .jpg."""
        client.post(
            "/api/settings/login-image",
            files={"file": ("bg.png", JPEG_BYTES, "image/png")},
            headers=admin["headers"],
        )
        assert (covers_dir / "login_bg.jpg").exists()
        assert not (covers_dir / "login_bg.png").exists()

    def test_rejects_an_empty_file(self, client, admin):
        res = client.post(
            "/api/settings/login-image",
            files={"file": ("bg.png", b"", "image/png")},
            headers=admin["headers"],
        )
        assert res.status_code == 400

    def test_uploading_a_new_format_removes_the_old_file(self, client, admin, covers_dir):
        """Otherwise login_bg.png and login_bg.jpg would both exist and race."""
        client.post(
            "/api/settings/login-image",
            files={"file": ("bg.png", PNG, "image/png")},
            headers=admin["headers"],
        )
        client.post(
            "/api/settings/login-image",
            files={"file": ("bg.jpg", JPEG_BYTES, "image/jpeg")},
            headers=admin["headers"],
        )
        assert not (covers_dir / "login_bg.png").exists()
        assert (covers_dir / "login_bg.jpg").exists()

    def test_replacing_leaves_exactly_one_background(self, client, admin, covers_dir):
        for name, payload in (
            ("bg.png", PNG_BYTES),
            ("bg.jpg", JPEG_BYTES),
            ("bg.webp", WEBP_BYTES),
        ):
            client.post(
                "/api/settings/login-image",
                files={"file": (name, payload, "image/png")},
                headers=admin["headers"],
            )
        assert len(list(covers_dir.glob("login_bg.*"))) == 1


# ── Runtime settings ──────────────────────────────────────────────────────────


class TestFeatureFlags:
    def test_is_public(self, client):
        """The login page is localised, so the default language has to be
        readable before anyone holds a token."""
        assert client.get("/api/settings/features").status_code == 200

    def test_reports_the_defaults(self, client):
        body = client.get("/api/settings/features").json()
        assert body["google_books_enabled"] is False
        assert body["goodreads_lookup_enabled"] is True
        assert body["default_locale"] == "en"

    def test_carries_no_secrets(self, client, admin):
        client.put(
            "/api/settings",
            json={"google_books_api_key": "AIzaSy-secret-value-here"},
            headers=admin["headers"],
        )

        body = client.get("/api/settings/features").json()

        assert "api_key" not in str(body)
        assert "secret" not in str(body).lower()


class TestReadSettings:
    def test_requires_admin(self, client, member):
        assert client.get("/api/settings", headers=member["headers"]).status_code == 403

    def test_requires_authentication(self, client):
        assert client.get("/api/settings").status_code == 401

    def test_an_admin_can_read_them(self, client, admin):
        assert client.get("/api/settings", headers=admin["headers"]).status_code == 200

    def test_the_api_key_is_never_returned_in_full(self, client, admin):
        client.put(
            "/api/settings",
            json={"google_books_api_key": "AIzaSyA-VeryLongSecretKey1234"},
            headers=admin["headers"],
        )

        body = client.get("/api/settings", headers=admin["headers"]).json()

        assert "VeryLongSecret" not in body["google_books_api_key_preview"]
        assert body["google_books_api_key_preview"].endswith("1234")
        assert body["has_google_books_api_key"] is True

    def test_reports_when_no_key_is_set(self, client, admin):
        body = client.get("/api/settings", headers=admin["headers"]).json()
        assert body["has_google_books_api_key"] is False
        assert body["google_books_api_key_preview"] == ""


class TestUpdateSettings:
    def test_requires_admin(self, client, member):
        res = client.put(
            "/api/settings", json={"google_books_enabled": True}, headers=member["headers"]
        )
        assert res.status_code == 403

    def test_toggles_a_flag(self, client, admin):
        res = client.put(
            "/api/settings", json={"google_books_enabled": True}, headers=admin["headers"]
        )
        assert res.json()["google_books_enabled"] is True

    def test_a_setting_survives_a_restart(self, client, admin, db):
        import settings_store
        from enums import SettingKey

        client.put(
            "/api/settings", json={"google_books_enabled": True}, headers=admin["headers"]
        )

        # Read straight from the database, bypassing the request that wrote it.
        assert settings_store.get_bool(db, SettingKey.GOOGLE_BOOKS_ENABLED) is True

    def test_an_absent_field_is_left_alone(self, client, admin):
        """The reason the update is partial.

        The browser never received the real API key, so a form that always
        submitted every field would blank it whenever an admin toggled
        something else.
        """
        client.put(
            "/api/settings",
            json={"google_books_api_key": "AIzaSy-keep-me-1234"},
            headers=admin["headers"],
        )

        client.put(
            "/api/settings", json={"google_books_enabled": True}, headers=admin["headers"]
        )

        body = client.get("/api/settings", headers=admin["headers"]).json()
        assert body["has_google_books_api_key"] is True
        assert body["google_books_api_key_preview"].endswith("1234")

    def test_an_empty_string_clears_the_key_deliberately(self, client, admin):
        client.put(
            "/api/settings",
            json={"google_books_api_key": "AIzaSy-remove-me"},
            headers=admin["headers"],
        )

        client.put(
            "/api/settings", json={"google_books_api_key": ""}, headers=admin["headers"]
        )

        assert (
            client.get("/api/settings", headers=admin["headers"]).json()[
                "has_google_books_api_key"
            ]
            is False
        )

    def test_the_key_is_trimmed(self, client, admin):
        # Pasted keys routinely carry a trailing newline, which would be sent
        # to Google verbatim and rejected.
        client.put(
            "/api/settings",
            json={"google_books_api_key": "  AIzaSy-padded-1234  "},
            headers=admin["headers"],
        )

        import settings_store
        from database import SessionLocal
        from enums import SettingKey

        session = SessionLocal()
        try:
            stored = settings_store.get_raw(session, SettingKey.GOOGLE_BOOKS_API_KEY)
        finally:
            session.close()
        assert stored == "AIzaSy-padded-1234"

    def test_sets_the_default_locale(self, client, admin):
        res = client.put("/api/settings", json={"default_locale": "de"}, headers=admin["headers"])
        assert res.json()["default_locale"] == "de"

    def test_rejects_an_unsupported_locale(self, client, admin):
        res = client.put(
            "/api/settings", json={"default_locale": "klingon"}, headers=admin["headers"]
        )
        assert res.status_code == 422


class TestReadinessFlag:
    """`google_books_enabled` is the toggle; `google_books_ready` is whether it
    will actually work. The UI needs the second one to decide between offering a
    control and greying it out, because a toggle with no key behind it produces
    a button that can only ever 400."""

    def features(self, client) -> dict:
        return client.get("/api/settings/features").json()

    def test_off_by_default(self, client):
        assert self.features(client)["google_books_ready"] is False

    def test_a_toggle_without_a_key_is_not_ready(self, client, admin):
        client.put(
            "/api/settings", json={"google_books_enabled": True}, headers=admin["headers"]
        )

        body = self.features(client)

        assert body["google_books_enabled"] is True
        assert body["google_books_ready"] is False

    def test_a_key_without_the_toggle_is_not_ready(self, client, admin):
        client.put(
            "/api/settings",
            json={"google_books_api_key": "secret"},
            headers=admin["headers"],
        )

        assert self.features(client)["google_books_ready"] is False

    def test_ready_with_both(self, client, admin):
        client.put(
            "/api/settings",
            json={"google_books_enabled": True, "google_books_api_key": "secret"},
            headers=admin["headers"],
        )

        assert self.features(client)["google_books_ready"] is True

    def test_clearing_the_key_takes_it_back_out_of_service(self, client, admin):
        client.put(
            "/api/settings",
            json={"google_books_enabled": True, "google_books_api_key": "secret"},
            headers=admin["headers"],
        )

        client.put(
            "/api/settings", json={"google_books_api_key": ""}, headers=admin["headers"]
        )

        assert self.features(client)["google_books_ready"] is False

    def test_the_key_itself_is_never_in_the_public_response(self, client, admin):
        """This endpoint needs no token, so it must not leak the secret it
        reports the presence of."""
        client.put(
            "/api/settings",
            json={"google_books_enabled": True, "google_books_api_key": "super-secret"},
            headers=admin["headers"],
        )

        assert "super-secret" not in client.get("/api/settings/features").text


class TestKeyFromTheEnvironment:
    """A key supplied by the deployment wins and cannot be edited here.

    That is the whole point of supplying it that way: it is managed outside the
    application, and letting an admin change it in a form would produce a value
    that silently disagrees with the deployment at the next restart.
    """

    def with_env_key(self, monkeypatch, value: str = "env-key") -> None:
        monkeypatch.setenv("GOOGLE_BOOKS_API_KEY", value)

    def test_it_is_reported_as_coming_from_the_environment(
        self, client, admin, monkeypatch
    ):
        self.with_env_key(monkeypatch)

        body = client.get("/api/settings", headers=admin["headers"]).json()

        assert body["google_books_api_key_from_env"] is True
        assert body["has_google_books_api_key"] is True

    def test_a_stored_key_alone_is_not_from_the_environment(self, client, admin):
        client.put(
            "/api/settings",
            json={"google_books_api_key": "stored"},
            headers=admin["headers"],
        )

        body = client.get("/api/settings", headers=admin["headers"]).json()

        assert body["google_books_api_key_from_env"] is False
        assert body["has_google_books_api_key"] is True

    def test_writing_one_is_refused_rather_than_ignored(
        self, client, admin, monkeypatch
    ):
        """Silently accepting a value that does nothing is worse than refusing:
        the admin would believe they had changed the key."""
        self.with_env_key(monkeypatch)

        res = client.put(
            "/api/settings",
            json={"google_books_api_key": "typed"},
            headers=admin["headers"],
        )

        assert res.status_code == 409
        assert "GOOGLE_BOOKS_API_KEY" in res.json()["detail"]

    def test_the_refusal_does_not_block_the_other_settings(
        self, client, admin, monkeypatch
    ):
        self.with_env_key(monkeypatch)

        res = client.put(
            "/api/settings",
            json={"google_books_enabled": True},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert res.json()["google_books_enabled"] is True

    def test_it_wins_over_a_stored_key(self, client, admin, monkeypatch, db):
        import settings_store
        from enums import SettingKey

        client.put(
            "/api/settings",
            json={"google_books_api_key": "stored"},
            headers=admin["headers"],
        )
        self.with_env_key(monkeypatch, "env-key")

        assert settings_store.google_books_api_key(db) == "env-key"
        # The stored one is left alone rather than deleted: unsetting the
        # environment variable should put it back, not lose it.
        assert settings_store.get_raw(db, SettingKey.GOOGLE_BOOKS_API_KEY) == "stored"

    def test_it_makes_the_feature_ready(self, client, admin, monkeypatch):
        self.with_env_key(monkeypatch)
        client.put(
            "/api/settings", json={"google_books_enabled": True}, headers=admin["headers"]
        )

        assert client.get("/api/settings/features").json()["google_books_ready"] is True

    def test_the_key_is_never_returned(self, client, admin, monkeypatch):
        """The app can use a secret without being able to show it, whichever
        side it came from."""
        self.with_env_key(monkeypatch, "super-secret-env-key")

        body = client.get("/api/settings", headers=admin["headers"]).text

        assert "super-secret-env-key" not in body

    def test_a_blank_environment_value_is_treated_as_absent(
        self, client, admin, monkeypatch
    ):
        monkeypatch.setenv("GOOGLE_BOOKS_API_KEY", "   ")

        body = client.get("/api/settings", headers=admin["headers"]).json()

        assert body["google_books_api_key_from_env"] is False
