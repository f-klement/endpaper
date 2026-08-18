"""Tests for backend/settings_store.py."""

import pytest

import settings_store
from enums import Locale, SettingKey


class TestDefaults:
    def test_every_key_has_one(self):
        # A key with no default returns a KeyError on first read, which would
        # be a 500 on a fresh install.
        for key in SettingKey:
            assert key in settings_store.DEFAULTS

    def test_google_books_starts_off(self):
        # Enrichment calls a third party. That should be a deliberate choice,
        # not something a new install begins doing on its own.
        assert settings_store.DEFAULTS[SettingKey.GOOGLE_BOOKS_ENABLED] == "false"

    def test_goodreads_lookup_starts_on(self):
        # Only an outbound link: it discloses nothing and costs nothing.
        assert settings_store.DEFAULTS[SettingKey.GOODREADS_LOOKUP_ENABLED] == "true"


class TestReadAndWrite:
    def test_an_unwritten_key_returns_its_default(self, db):
        assert settings_store.get_bool(db, SettingKey.GOOGLE_BOOKS_ENABLED) is False

    def test_a_written_value_comes_back(self, db):
        settings_store.set_value(db, SettingKey.GOOGLE_BOOKS_API_KEY, "abc123")
        assert settings_store.get_raw(db, SettingKey.GOOGLE_BOOKS_API_KEY) == "abc123"

    def test_writing_twice_updates_rather_than_duplicating(self, db):
        settings_store.set_value(db, SettingKey.GOOGLE_BOOKS_API_KEY, "first")
        settings_store.set_value(db, SettingKey.GOOGLE_BOOKS_API_KEY, "second")
        assert settings_store.get_raw(db, SettingKey.GOOGLE_BOOKS_API_KEY) == "second"

    @pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on"])
    def test_truthy_spellings(self, db, value):
        settings_store.set_value(db, SettingKey.GOOGLE_BOOKS_ENABLED, value)
        assert settings_store.get_bool(db, SettingKey.GOOGLE_BOOKS_ENABLED) is True

    @pytest.mark.parametrize("value", ["false", "0", "no", "off", ""])
    def test_everything_else_is_false(self, db, value):
        settings_store.set_value(db, SettingKey.GOOGLE_BOOKS_ENABLED, value)
        assert settings_store.get_bool(db, SettingKey.GOOGLE_BOOKS_ENABLED) is False


class TestLocale:
    def test_reads_a_supported_locale(self, db):
        settings_store.set_value(db, SettingKey.DEFAULT_LOCALE, "de")
        assert settings_store.get_locale(db, SettingKey.DEFAULT_LOCALE) is Locale.DE

    def test_an_unsupported_value_falls_back_rather_than_raising(self, db):
        # A locale dropped in a later release must degrade to the default, not
        # break every page load.
        settings_store.set_value(db, SettingKey.DEFAULT_LOCALE, "klingon")
        assert settings_store.get_locale(db, SettingKey.DEFAULT_LOCALE) is Locale.EN


class TestMasking:
    def test_a_key_is_never_returned_in_full(self):
        masked = settings_store.mask("AIzaSyA-VeryLongSecretKeyValue")
        assert "VeryLongSecret" not in masked

    def test_the_last_few_characters_survive(self):
        # Enough to tell one key from another when rotating them.
        assert settings_store.mask("AIzaSyA-VeryLongSecretKey1234").endswith("1234")

    def test_a_short_secret_is_hidden_entirely(self):
        # A fragment of something short would give away too much of it.
        masked = settings_store.mask("abc123")
        assert masked == "••••••"
        assert "abc" not in masked

    def test_an_unset_key_masks_to_nothing(self):
        assert settings_store.mask("") == ""

    def test_the_api_key_is_marked_secret(self):
        assert SettingKey.GOOGLE_BOOKS_API_KEY in settings_store.SECRET_KEYS
