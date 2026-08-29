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


class TestJsonSettings:
    """One settings row holds the reminder senders' health record (#82), so the
    parser has to survive whatever a restore or a hand edit put in it: it is
    read on the hourly ticker, where a raise stops the task for the life of the
    container."""

    def test_a_written_object_reads_back(self, db):
        settings_store.set_json(db, SettingKey.SENDER_HEALTH, {"email": {"failures": 3}})
        assert settings_store.get_json(db, SettingKey.SENDER_HEALTH) == {
            "email": {"failures": 3}
        }

    def test_an_unwritten_key_is_an_empty_object(self, db):
        assert settings_store.get_json(db, SettingKey.SENDER_HEALTH) == {}

    def test_text_that_is_not_json_degrades(self, db):
        settings_store.set_value(db, SettingKey.SENDER_HEALTH, "{oh no")
        assert settings_store.get_json(db, SettingKey.SENDER_HEALTH) == {}

    def test_json_that_is_not_an_object_degrades(self, db):
        """A list parses, and would then be indexed by a string somewhere far
        from the row that caused it."""
        for stored in ("[1, 2]", "null", '"a string"', "7"):
            settings_store.set_value(db, SettingKey.SENDER_HEALTH, stored)
            assert settings_store.get_json(db, SettingKey.SENDER_HEALTH) == {}

    def test_keys_are_written_in_a_stable_order(self, db):
        """An unchanged record writes an unchanged string, which is what makes
        a settings diff readable and a backup comparison mean anything."""
        settings_store.set_json(db, SettingKey.SENDER_HEALTH, {"telegram": 1, "email": 2})
        assert settings_store.get_raw(db, SettingKey.SENDER_HEALTH) == (
            '{"email": 2, "telegram": 1}'
        )


class TestLibraryModeAndThePublicCatalogue:
    """The two nested switches, and the rule that publishing needs both.

    The conjunction lives here rather than in the router because it is a
    question about the settings, and because a router is not the only caller:
    `robots.txt` and the feature flags both ask, and three copies of `a and b`
    is three places for one of them to be written `a or b`.
    """

    def test_both_switches_start_off(self):
        """A household that reads no setting publishes nothing. This is the
        default that matters most in the whole table."""
        assert settings_store.DEFAULTS[SettingKey.LIBRARY_MODE] == "false"
        assert settings_store.DEFAULTS[SettingKey.PUBLIC_CATALOGUE_ENABLED] == "false"

    def test_indexing_starts_off_too(self):
        """Publishing a catalogue and inviting a search engine to crawl it are
        different decisions, and the default answer to the second is no."""
        assert (
            settings_store.DEFAULTS[SettingKey.PUBLIC_CATALOGUE_INDEXING_ENABLED]
            == "false"
        )

    def test_a_fresh_database_publishes_nothing(self, db):
        """The default read through the accessor, not off the table: a default
        that is never consulted is not a default."""
        assert settings_store.library_mode(db) is False
        assert settings_store.public_catalogue_is_published(db) is False

    def test_library_mode_alone_publishes_nothing(self, db):
        settings_store.set_value(db, SettingKey.LIBRARY_MODE, "true")
        assert settings_store.library_mode(db) is True
        assert settings_store.public_catalogue_is_published(db) is False

    def test_the_publish_switch_alone_publishes_nothing(self, db):
        """**The refusal.** A publish row on while library mode is off is
        treated as off, so turning library mode back off cannot leave a
        catalogue public with nothing on screen saying so."""
        settings_store.set_value(db, SettingKey.PUBLIC_CATALOGUE_ENABLED, "true")
        assert settings_store.public_catalogue_is_published(db) is False

    def test_both_together_publish(self, db):
        """The diagonal. Without it every assertion above is satisfied by a
        function that returns False."""
        settings_store.set_value(db, SettingKey.LIBRARY_MODE, "true")
        settings_store.set_value(db, SettingKey.PUBLIC_CATALOGUE_ENABLED, "true")
        assert settings_store.public_catalogue_is_published(db) is True

    def test_indexing_needs_a_published_catalogue_as_well(self, db):
        """An indexing row left on while nothing is published cannot invite a
        crawler to a catalogue that answers 404."""
        settings_store.set_value(
            db, SettingKey.PUBLIC_CATALOGUE_INDEXING_ENABLED, "true"
        )
        assert settings_store.public_catalogue_may_be_indexed(db) is False

    def test_a_published_catalogue_is_still_not_indexed_by_default(self, db):
        settings_store.set_value(db, SettingKey.LIBRARY_MODE, "true")
        settings_store.set_value(db, SettingKey.PUBLIC_CATALOGUE_ENABLED, "true")
        assert settings_store.public_catalogue_may_be_indexed(db) is False

    def test_all_three_together_invite_a_crawler(self, db):
        settings_store.set_value(db, SettingKey.LIBRARY_MODE, "true")
        settings_store.set_value(db, SettingKey.PUBLIC_CATALOGUE_ENABLED, "true")
        settings_store.set_value(
            db, SettingKey.PUBLIC_CATALOGUE_INDEXING_ENABLED, "true"
        )
        assert settings_store.public_catalogue_may_be_indexed(db) is True

    def test_the_three_switches_are_not_pinnable_from_the_environment(self):
        """Settings rather than environment variables, and pinned as a decision
        rather than left as an accident of an unedited table.

        An environment variable takes a redeploy to correct, which is the wrong
        property for the switch most likely to be turned on by mistake. It would
        also make the catalogue publishable by a variable that never went
        through the confirmation naming what becomes public.
        """
        import config

        pinnable = [
            key.value
            for key in (
                SettingKey.LIBRARY_MODE,
                SettingKey.PUBLIC_CATALOGUE_ENABLED,
                SettingKey.PUBLIC_CATALOGUE_INDEXING_ENABLED,
            )
            if config.env_variable_name(key)
        ]
        assert pinnable == [], (
            f"These are now pinnable from the environment: {pinnable}. Publishing "
            "a catalogue has to stay a runtime decision an admin can undo without "
            "a redeploy."
        )
