"""Tests for backend/routers/settings.py: the admin-set login background."""

import ast
import inspect
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

import notifications
import settings_store
from enums import OverdueNotifyReason, OverdueSender
from routers import settings as settings_router
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


class TestOverdueWebhookSettings:
    """The four settings behind the overdue digest.

    The secret follows the Google key exactly: masked on the way out, absent
    means "leave alone" on the way in. The URL deliberately does not, because a
    destination nobody can read back is a destination nobody can proofread.
    """

    HOOK = "https://hooks.example.org/t/abc"

    def test_it_starts_switched_off(self, client, admin):
        body = client.get("/api/settings", headers=admin["headers"]).json()
        assert body["overdue_webhook_enabled"] is False
        assert body["overdue_webhook_url"] == ""
        assert body["overdue_reminder_days"] == 7

    def test_it_stores_a_url(self, client, admin):
        body = client.put(
            "/api/settings",
            json={"overdue_webhook_url": self.HOOK},
            headers=admin["headers"],
        ).json()
        assert body["overdue_webhook_url"] == self.HOOK

    def test_it_refuses_a_scheme_that_is_not_http(self, client, admin):
        res = client.put(
            "/api/settings",
            json={"overdue_webhook_url": "file:///etc/passwd"},
            headers=admin["headers"],
        )
        assert res.status_code == 422

    def test_an_empty_url_clears_it(self, client, admin):
        client.put(
            "/api/settings",
            json={"overdue_webhook_url": self.HOOK},
            headers=admin["headers"],
        )
        body = client.put(
            "/api/settings", json={"overdue_webhook_url": ""}, headers=admin["headers"]
        ).json()
        assert body["overdue_webhook_url"] == ""

    def test_the_secret_is_never_returned(self, client, admin):
        client.put(
            "/api/settings",
            json={"overdue_webhook_secret": "a-very-secret-value"},
            headers=admin["headers"],
        )
        body = client.get("/api/settings", headers=admin["headers"]).text
        assert "a-very-secret-value" not in body

    def test_the_secret_is_masked_and_flagged(self, client, admin):
        client.put(
            "/api/settings",
            json={"overdue_webhook_secret": "a-very-secret-value"},
            headers=admin["headers"],
        )
        body = client.get("/api/settings", headers=admin["headers"]).json()
        assert body["has_overdue_webhook_secret"] is True
        assert body["overdue_webhook_secret_preview"].endswith("alue")

    def test_an_absent_secret_leaves_the_stored_one_alone(self, client, admin, db):
        """A form that always submitted every field would blank it, since the
        browser never received the real value."""
        import settings_store
        from enums import SettingKey

        client.put(
            "/api/settings",
            json={"overdue_webhook_secret": "kept"},
            headers=admin["headers"],
        )
        client.put(
            "/api/settings",
            json={"overdue_webhook_enabled": True},
            headers=admin["headers"],
        )

        assert settings_store.get_raw(db, SettingKey.OVERDUE_WEBHOOK_SECRET) == "kept"

    def test_an_empty_secret_clears_it(self, client, admin):
        client.put(
            "/api/settings",
            json={"overdue_webhook_secret": "kept"},
            headers=admin["headers"],
        )
        body = client.put(
            "/api/settings", json={"overdue_webhook_secret": ""}, headers=admin["headers"]
        ).json()
        assert body["has_overdue_webhook_secret"] is False

    def test_it_stores_the_reminder_interval(self, client, admin):
        body = client.put(
            "/api/settings", json={"overdue_reminder_days": 3}, headers=admin["headers"]
        ).json()
        assert body["overdue_reminder_days"] == 3

    def test_zero_days_is_refused(self, client, admin):
        """Zero would mean resending the same list on every tick."""
        res = client.put(
            "/api/settings", json={"overdue_reminder_days": 0}, headers=admin["headers"]
        )
        assert res.status_code == 422

    def test_a_member_may_not_read_them(self, client, member):
        assert client.get("/api/settings", headers=member["headers"]).status_code == 403


class TestEverySecretSettingIsMasked:
    """`SECRET_KEYS` names the secrets; this is what makes it enforce anything.

    Masking is written by hand per field in `_read_settings`, so before this
    test the set was a list beside the code rather than a rule over it: a third
    secret added to it would have been masked by nothing, disclosed in full to
    every admin page load, and no test would have failed. Both members are
    correctly masked today, which is exactly why the guard is worth having now
    rather than after the next one is added.

    It walks the set instead of naming the fields, so a key added there is
    covered the moment it is added.
    """

    def test_no_secret_settings_value_is_returned_in_full(self, client, admin, db):
        import settings_store

        # Longer than eight characters, or `mask()` hides the value entirely
        # and the assertion would pass without proving anything.
        stored = {}
        for index, key in enumerate(sorted(settings_store.SECRET_KEYS)):
            value = f"secret-value-{index}-{key.value}"
            settings_store.set_value(db, key, value)
            stored[key.value] = value

        body = client.get("/api/settings", headers=admin["headers"]).text

        assert [name for name, value in stored.items() if value in body] == []
        # **And the response is talking about these values**, which absence
        # alone does not say. `_read_settings` reads through
        # `settings_store.in_force`, so a variable in the environment beats the
        # row this test just wrote: the body would then carry a mask of the
        # environment's secret, the stored one would be absent, and the
        # assertion above would hold with `mask()` deleted from the line it
        # guards. `conftest.py` pops every name in `config._ENV_OVERRIDES` for
        # that reason, and this is the assertion that notices if it stops.
        assert [
            name
            for name, value in stored.items()
            if settings_store.mask(value) not in body
        ] == []

    def test_no_pinnable_secret_is_pinned_while_the_suite_runs(self):
        """The walk above goes vacuous under an environment that supplies one.

        This deployment's own `.env` sets `MAIL_PASSWORD` and
        `TELEGRAM_BOT_TOKEN`, under exactly the names `_ENV_OVERRIDES` reads, so
        a shell that exported them would disarm the guard silently rather than
        failing. `conftest.py` pops the table; this says so out loud, and covers
        a credential added to that table later.
        """
        import os

        import config

        assert [
            variable
            for variable in config._ENV_OVERRIDES.values()
            if os.environ.get(variable)
        ] == []

    def test_the_walk_covers_the_secrets_that_exist(self):
        """A guard that inspects nothing is worse than no guard. These are the
        four the set holds; a fifth is what the walk above is for.

        It read "the two" until the mail password and the Telegram bot token
        joined them, which is the whole reason a comment claiming "there are
        exactly N" is counted rather than trusted here."""
        import settings_store
        from enums import SettingKey

        assert set(settings_store.SECRET_KEYS) == {
            SettingKey.GOOGLE_BOOKS_API_KEY,
            SettingKey.OVERDUE_WEBHOOK_SECRET,
            SettingKey.MAIL_PASSWORD,
            SettingKey.TELEGRAM_BOT_TOKEN,
        }

    def test_a_secret_long_enough_to_be_partly_shown_still_is(self):
        """The masking is a preview, not a deletion, and the test above must not
        pass merely because nothing was stored."""
        import settings_store

        assert settings_store.mask("secret-value-abcd").endswith("abcd")


class TestReminderSenderSettings:
    """The mail and Telegram configuration, over the API.

    What is worth pinning is the pair of rules that are silent when they break:
    a secret never leaves in full, and a value the deployment pinned is refused
    rather than stored where nothing will read it.
    """

    def test_the_defaults_are_off_and_empty(self, client, admin):
        body = client.get("/api/settings", headers=admin["headers"]).json()

        assert body["overdue_mail_enabled"] is False
        assert body["overdue_telegram_enabled"] is False
        assert body["has_mail_password"] is False
        assert body["has_telegram_bot_token"] is False
        assert body["mail_from_env"] == []

    def test_it_stores_the_mail_fields(self, client, admin):
        body = client.put(
            "/api/settings",
            json={
                "overdue_mail_enabled": True,
                "mail_server": "smtp.example.org",
                "mail_port": "465",
                "mail_use_tls": False,
                "mail_use_ssl": True,
                "mail_default_sender": "library@example.org",
                "overdue_mail_to": "house@example.org",
            },
            headers=admin["headers"],
        ).json()

        assert body["overdue_mail_enabled"] is True
        assert body["mail_server"] == "smtp.example.org"
        assert body["mail_port"] == "465"
        assert body["mail_use_ssl"] is True
        assert body["overdue_mail_to"] == "house@example.org"

    def test_the_mail_password_comes_back_masked_and_never_in_full(self, client, admin):
        client.put(
            "/api/settings",
            json={"mail_password": "correct-horse-battery"},
            headers=admin["headers"],
        )
        response = client.get("/api/settings", headers=admin["headers"])

        assert "correct-horse-battery" not in response.text
        assert response.json()["has_mail_password"] is True
        assert response.json()["mail_password_preview"].endswith("ery")

    def test_the_bot_token_comes_back_masked_and_never_in_full(self, client, admin):
        token = "0:TEST-TOKEN-NOT-A-REAL-CREDENTIAL"
        client.put(
            "/api/settings",
            json={"telegram_bot_token": token},
            headers=admin["headers"],
        )
        response = client.get("/api/settings", headers=admin["headers"])

        assert "AAaaBBbb" not in response.text
        assert response.json()["has_telegram_bot_token"] is True
        # The preview is of **this** token. Without it, a `TELEGRAM_BOT_TOKEN`
        # in the environment would win in `in_force`, the body would carry a
        # mask of that one instead, and both assertions above would hold while
        # proving nothing. See `TestEverySecretSettingIsMasked`.
        assert response.json()["telegram_bot_token_preview"].endswith(token[-4:])

    def test_the_chat_id_comes_back_in_full(self, client, admin):
        """The same asymmetry the webhook URL has: a destination nobody can read
        back is a destination nobody can proofread."""
        body = client.put(
            "/api/settings",
            json={"telegram_chat_id": "-1001234567890"},
            headers=admin["headers"],
        ).json()

        assert body["telegram_chat_id"] == "-1001234567890"

    def test_an_absent_field_leaves_the_secret_alone(self, client, admin):
        """The browser never received the stored value, so a form saving an
        unrelated toggle would otherwise blank it."""
        client.put(
            "/api/settings", json={"mail_password": "hunter2222"}, headers=admin["headers"]
        )
        body = client.put(
            "/api/settings", json={"overdue_mail_enabled": True}, headers=admin["headers"]
        ).json()

        assert body["has_mail_password"] is True

    def test_an_empty_string_clears_it(self, client, admin):
        client.put(
            "/api/settings", json={"mail_password": "hunter2222"}, headers=admin["headers"]
        )
        body = client.put(
            "/api/settings", json={"mail_password": ""}, headers=admin["headers"]
        ).json()

        assert body["has_mail_password"] is False

    def test_it_is_admin_only(self, client, member):
        assert (
            client.put(
                "/api/settings",
                json={"overdue_mail_enabled": True},
                headers=member["headers"],
            ).status_code
            == 403
        )

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("mail_server", "s" * 256),
            ("mail_port", "123456"),
            ("mail_default_sender", "a" * 321),
            ("overdue_mail_to", "a" * 1001),
            ("mail_password", "p" * 201),
            ("telegram_bot_token", "t" * 301),
            ("telegram_chat_id", "c" * 65),
        ],
    )
    def test_every_field_is_bounded(self, client, admin, field, value):
        """A settings row a restore writes through Core is a row the hourly
        ticker reads on every tick."""
        response = client.put(
            "/api/settings", json={field: value}, headers=admin["headers"]
        )
        assert response.status_code == 422


#: Every `SettingsUpdate` field that predates the reminder senders. Named rather
#: than pattern matched, so the guard below is the complement of a fixed list and
#: a field added tomorrow lands inside the rule rather than outside it.
_BEFORE_THE_SENDERS = frozenset(
    {
        "google_books_enabled",
        "google_books_api_key",
        "goodreads_lookup_enabled",
        "default_locale",
        "overdue_webhook_enabled",
        "overdue_webhook_url",
        "overdue_webhook_secret",
        "overdue_reminder_days",
    }
)


def _write_tables() -> dict[str, dict[str, object]]:
    """The write tables in `routers/settings.py`, by the name they are bound to.

    **Derived from the module rather than named**, and that was a correction.
    The guard below read `_SENDER_TEXT | _SENDER_BOOL` by name, so a **third**
    table was invisible to it: the library mode switches arrived in
    `_LIBRARY_MODE_BOOL`, are written on every `PUT`, and the guard reported all
    three fields as accepted and dropped. A rule that enumerates the tables it
    knows about fails on the table added after it, which is the one case it
    exists for.

    A table here is a module level `dict[str, SettingKey]`, which is what all
    three are and what a fourth would be, **and which `update_settings` actually
    reads**. That last clause is the second correction: without it a table
    somebody declared and never wired up would count as writing its fields, and
    would forgive exactly the "accepted and dropped" defect this exists to
    catch.

    One definition, returned whole, because two tests wanted this set and were
    computing it with two different predicates, which is one fact with two
    answers.
    """
    from enums import SettingKey
    from routers import settings as settings_router

    written = inspect.getsource(settings_router.update_settings)
    return {
        name: value
        for name, value in vars(settings_router).items()
        if isinstance(value, dict)
        and value
        and all(
            isinstance(field, str) and isinstance(key, SettingKey)
            for field, key in value.items()
        )
        # On a word boundary, not `name in written`: a table called `_SENDER`
        # would otherwise be counted as read because `_SENDER_TEXT` appears.
        and re.search(rf"\b{re.escape(name)}\b", written)
    }


def _written_fields() -> set[str]:
    """Every payload field one of those tables writes."""
    return {field for table in _write_tables().values() for field in table}


class TestEverySenderFieldIsActuallyWritten:
    """The write tables are tables, and a table can be short.

    A field added to `SettingsUpdate` and not to one of them is accepted by the
    schema, answered **200**, and dropped: no error, no log line, and a settings
    screen that reports the old value back as though the save had worked. Twelve
    fields against twelve rows today, which is exactly when the guard is worth
    adding rather than after the thirteenth.

    Only this direction needs a test. A row naming a field that no longer exists
    raises `AttributeError` on the first `PUT`, which is loud.
    """

    def test_the_derivation_finds_the_tables(self):
        """A guard that inspects nothing reads as coverage, and this one has
        already been blind to a whole table once."""
        assert set(_write_tables()) == {
            "_SENDER_TEXT",
            "_SENDER_BOOL",
            "_LIBRARY_MODE_BOOL",
        }, (
            "The write tables in routers/settings.py are pinned here, so a "
            "fourth fails this until somebody says it is one. That is the "
            "point: the rule below counts on finding them all, and it was blind "
            "to the third for a round."
        )
        written = _written_fields()
        assert "mail_server" in written, "the text table is not being found"
        assert "overdue_in_app_enabled" in written, "the bool table is not"
        assert "library_mode" in written, "a table added later is not"

    def test_a_table_nothing_reads_does_not_count_as_written(self, monkeypatch):
        """A declared but unwired table would otherwise forgive its own fields,
        which is the exact defect this guard exists to catch."""
        from enums import SettingKey
        from routers import settings as settings_router

        monkeypatch.setattr(
            settings_router,
            "_NEVER_WIRED_UP",
            {"a_field_nothing_writes": SettingKey.LIBRARY_MODE},
            raising=False,
        )
        assert "a_field_nothing_writes" not in _written_fields()

    def test_no_sender_field_is_accepted_and_dropped(self):
        from schemas import SettingsUpdate

        written = _written_fields()
        # The complement, not a prefix match. A prefix list fails **open** on
        # the field it most wants to catch: `smtp_relay_host` or `ntfy_topic`
        # starts with none of them, so it falls outside `declared`, the guard
        # passes, and the field is accepted, 200'd and dropped. Deriving the set
        # by subtraction makes a new field default to **inside** the rule, which
        # is the only direction that fails safe.
        declared = set(SettingsUpdate.model_fields) - _BEFORE_THE_SENDERS

        assert declared - written == set()

    def test_no_two_tables_overlap(self):
        """A field in two tables is written twice, the second write deciding,
        which is a bug that only shows up as the wrong stored type.

        Through `_write_tables`, not a second derivation of its own. It had one,
        with a slightly different predicate, which is one fact with two
        definitions and two chances to disagree about what a table is."""
        total = sum(len(table) for table in _write_tables().values())
        assert len(_written_fields()) == total, "a field is written by two tables"


class TestTheEnvironmentWinsOverTheStoredValue:
    """`settings_store.google_books_api_key` set this rule; nine more follow it.

    A lookup that fails for a reason the settings screen denies is the defect,
    so the screen reports the value in force and refuses an edit that would not
    be read.
    """

    def test_the_screen_shows_the_environment_value(self, client, admin, monkeypatch):
        monkeypatch.setenv("MAIL_SERVER", "smtp.deployment.test")
        client.put(
            "/api/settings", json={}, headers=admin["headers"]
        )
        body = client.get("/api/settings", headers=admin["headers"]).json()

        assert body["mail_server"] == "smtp.deployment.test"
        assert "mail_server" in body["mail_from_env"]

    def test_a_pinned_setting_refuses_an_edit_and_names_the_variable(
        self, client, admin, monkeypatch
    ):
        monkeypatch.setenv("MAIL_SERVER", "smtp.deployment.test")
        response = client.put(
            "/api/settings", json={"mail_server": "smtp.typed.test"}, headers=admin["headers"]
        )

        assert response.status_code == 409
        assert "MAIL_SERVER" in response.json()["detail"]

    def test_a_pinned_secret_is_reported_as_pinned_and_never_shown(
        self, client, admin, monkeypatch
    ):
        monkeypatch.setenv("MAIL_PASSWORD", "from-the-deployment")
        body = client.get("/api/settings", headers=admin["headers"])

        assert "from-the-deployment" not in body.text
        assert body.json()["has_mail_password"] is True
        assert "mail_password" in body.json()["mail_from_env"]

    def test_a_pinned_bot_token_refuses_an_edit(self, client, admin, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "0:TEST-TOKEN-NOT-A-REAL-CREDENTIAL")
        response = client.put(
            "/api/settings",
            json={"telegram_bot_token": "999:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"},
            headers=admin["headers"],
        )

        assert response.status_code == 409
        assert body_has_no_token(response.text)

    def test_an_unpinned_setting_is_still_editable(self, client, admin, monkeypatch):
        monkeypatch.setenv("MAIL_SERVER", "smtp.deployment.test")
        body = client.put(
            "/api/settings", json={"mail_username": "library"}, headers=admin["headers"]
        ).json()

        assert body["mail_username"] == "library"


def body_has_no_token(text: str) -> bool:
    """A 409 must not quote the value back. It is a credential either way."""
    return "AAaaBBbb" not in text and "BBBBBBBB" not in text


class TestSenderHealthEndpoint:
    """`GET /api/settings/sender-health` (#82).

    When a channel counts as broken is pinned in `tests/test_notifications.py`.
    What is here is the route: who may read it, and that it reports the channels
    that are on rather than every one that exists.
    """

    def test_a_member_may_not_read_it(self, client, member):
        res = client.get("/api/settings/sender-health", headers=member["headers"])
        assert res.status_code == 403

    def test_it_needs_a_token(self, client):
        assert client.get("/api/settings/sender-health").status_code == 401

    def test_a_fresh_install_reports_nothing(self, client, admin):
        """Empty, though the in app channel is on: it is the one channel that
        hands the digest to nobody, so it has no delivery to have health about
        and reporting one would assert a send that never happened."""
        body = client.get("/api/settings/sender-health", headers=admin["headers"]).json()

        assert body == []

    def test_switching_a_channel_on_adds_it(self, client, admin):
        client.put(
            "/api/settings",
            json={"overdue_webhook_enabled": True},
            headers=admin["headers"],
        )

        body = client.get("/api/settings/sender-health", headers=admin["headers"]).json()

        assert [entry["sender"] for entry in body] == ["webhook"]
        assert body[0]["last_run_at"] is None
        assert body[0]["broken"] is False

    def test_switching_one_off_drops_it(self, client, admin):
        client.put(
            "/api/settings",
            json={"overdue_webhook_enabled": True},
            headers=admin["headers"],
        )
        client.put(
            "/api/settings",
            json={"overdue_webhook_enabled": False},
            headers=admin["headers"],
        )

        body = client.get("/api/settings/sender-health", headers=admin["headers"]).json()

        assert body == []


class TestInAppReminderSetting:
    def test_it_starts_switched_on(self, client, admin):
        """The one reminder channel that does, because it sends nothing outward
        and a household that configured nothing is otherwise told nothing."""
        body = client.get("/api/settings", headers=admin["headers"]).json()
        assert body["overdue_in_app_enabled"] is True

    def test_it_can_be_switched_off(self, client, admin):
        body = client.put(
            "/api/settings",
            json={"overdue_in_app_enabled": False},
            headers=admin["headers"],
        ).json()
        assert body["overdue_in_app_enabled"] is False

    def test_a_member_may_not_change_it(self, client, member):
        res = client.put(
            "/api/settings",
            json={"overdue_in_app_enabled": False},
            headers=member["headers"],
        )
        assert res.status_code == 403


class TestEverySettingsWriteClearsWhatItInvalidates:
    """`update_settings` writes through one door, so the second half of a write
    cannot be forgotten (#82)."""

    def test_no_write_bypasses_the_helper(self):
        """Structural, because the alternative is remembering.

        A settings row written without going through `_store` leaves the health
        record describing a configuration that no longer exists, which is the
        defect #82 exists to close.

        **Scoped to the module and not to `update_settings`**, and matching a
        bare `Name` as well as a dotted one. Measured against the first version
        of this rule, which did neither: of three ways to reopen the hole it
        caught **one**. An inline `settings_store.set_value(...)` in the handler
        was caught; `from settings_store import set_value` then `set_value(...)`
        was not, because the callee is a `Name`; and a sibling `_store_raw()`
        helper was not, because the write had left the function this rule was
        looking inside. The third is ordinary refactoring, which is what makes it
        the dangerous one.

        **The writers are derived from `settings_store`, not named.** The second
        version of this rule hard-coded `set_value` and so could not see
        `set_json`, which is a second ordinary public writer in the same module
        and the one `notifications.record_run` and `forget_health` already use.
        Reaching for it in this router is the same ordinary refactoring the
        paragraph above calls dangerous, and it would have reopened the hole
        silently. A `set_` prefix over `dir()` covers a third writer the day it
        is added, which is the difference between a rule and a list.

        So the question asked is "which functions in this module write a settings
        row", and the answer must be exactly one.

        **This is one of two legs and it guards the near one.** A write reaching
        `_store` still clears nothing if its `SettingKey` is absent from
        `notifications._CONFIGURED_BY`, because `sender_for` then answers `None`;
        that leg is held by
        `TestEverySenderSettingIsOwned::test_every_settings_row_the_senders_read_belongs_to_one`
        and is invisible from here. Named so a reader does not take a green run
        on this one as covering both.
        """
        source = Path(settings_router.__file__).read_text()
        tree = ast.parse(source)

        # Every public writer `settings_store` offers, plus every local name
        # bound to one, so neither a second writer nor an aliased import can
        # rename its way out.
        writers = {name for name in dir(settings_store) if name.startswith("set_")}
        assert "set_value" in writers and "set_json" in writers, (
            "The writer names are derived from `settings_store`; if that module "
            "renamed them, this rule is now guarding nothing."
        )
        bound = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
            if alias.name in writers
        } | writers

        # `found`, not `writers`: the two are a set of names and a map of call
        # sites, and reusing one name for both made mypy the only thing that
        # noticed. The suite was green on the shadowed version.
        found: dict[str, list[int]] = {}
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for node in ast.walk(function):
                if not isinstance(node, ast.Call):
                    continue
                callee = node.func
                name = (
                    callee.id
                    if isinstance(callee, ast.Name)
                    else callee.attr
                    if isinstance(callee, ast.Attribute)
                    else None
                )
                if name in bound:
                    found.setdefault(function.name, []).append(node.lineno)

        assert sorted(found) == ["_store"], (
            "A settings row is written outside `_store`, so the health record it "
            f"invalidates is left standing: {found}"
        )

    def test_replacing_an_expired_bot_token_clears_the_record(self, client, admin, db):
        """The case #82 names, and the one the old table did not cover.

        A household whose bot token expires meets the banner. Replacing the
        token is not a toggle, so with only the switches owned the record
        survived it, and a household with nothing overdue attempts no sender, so
        no later run overwrote it either.
        """
        client.put(
            "/api/settings",
            json={"overdue_telegram_enabled": True},
            headers=admin["headers"],
        )
        notifications.record_run(
            db,
            {
                "senders": [
                    {
                        "sender": OverdueSender.TELEGRAM,
                        "sent": False,
                        "reason": OverdueNotifyReason.MISCONFIGURED,
                        "detail": "The Telegram bot token is not a bot token.",
                    }
                ]
            },
            datetime.now(UTC).replace(tzinfo=None),
        )
        before = client.get("/api/settings/sender-health", headers=admin["headers"]).json()
        assert [e["broken"] for e in before if e["sender"] == "telegram"] == [True]

        client.put(
            "/api/settings",
            # The house's fake bot id, not a realistic one:
            # `TestNoFixtureLooksLikeACredential` forbids the realistic shape
            # because both test trees are published and somebody else triages
            # the scanner alert. It still satisfies `_TELEGRAM_TOKEN`.
            json={"telegram_bot_token": "0:TEST-TOKEN-NOT-A-REAL-CREDENTIAL"},
            headers=admin["headers"],
        )

        after = client.get("/api/settings/sender-health", headers=admin["headers"]).json()
        telegram = next(e for e in after if e["sender"] == "telegram")
        assert telegram["broken"] is False
        assert telegram["last_run_at"] is None

    def test_a_mail_transport_change_clears_the_mail_record(self, client, admin, db):
        """Not a credential, and exactly the fix `MISCONFIGURED` asks for:
        `mailer.checked_config` refuses a password over neither STARTTLS nor
        implicit TLS, so the encryption choice is the write that repairs it. A
        rule covering credentials alone would have left it out."""
        client.put(
            "/api/settings",
            json={"overdue_mail_enabled": True},
            headers=admin["headers"],
        )
        notifications.record_run(
            db,
            {
                "senders": [
                    {
                        "sender": OverdueSender.EMAIL,
                        "sent": False,
                        "reason": OverdueNotifyReason.MISCONFIGURED,
                        "detail": "A password would cross the wire in the clear.",
                    }
                ]
            },
            datetime.now(UTC).replace(tzinfo=None),
        )

        client.put(
            "/api/settings",
            json={"mail_use_tls": True, "mail_use_ssl": False},
            headers=admin["headers"],
        )

        after = client.get("/api/settings/sender-health", headers=admin["headers"]).json()
        assert next(e for e in after if e["sender"] == "email")["last_run_at"] is None

    def test_the_reminder_interval_is_not_a_channel_and_clears_nothing(
        self, client, admin, db
    ):
        """It says how often a loan is chased, not whether a channel works, so
        changing it is no evidence about any of them. The mirror of the tests
        above: a rule that cleared on every settings write would be a rule that
        never reported anything."""
        client.put(
            "/api/settings",
            json={"overdue_telegram_enabled": True},
            headers=admin["headers"],
        )
        notifications.record_run(
            db,
            {
                "senders": [
                    {
                        "sender": OverdueSender.TELEGRAM,
                        "sent": False,
                        "reason": OverdueNotifyReason.UNREACHABLE,
                        "detail": "The destination could not be reached.",
                    }
                ]
            },
            datetime.now(UTC).replace(tzinfo=None),
        )

        client.put(
            "/api/settings", json={"overdue_reminder_days": 3}, headers=admin["headers"]
        )

        after = client.get("/api/settings/sender-health", headers=admin["headers"]).json()
        assert next(e for e in after if e["sender"] == "telegram")["failures"] == 1
