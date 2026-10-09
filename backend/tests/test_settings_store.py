"""Tests for backend/settings_store.py."""

import dataclasses

import pytest

import credentials
import settings_store
import sources
import targets
from enums import CatalogueSource, Locale, SettingKey


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


class TestACredentialMakesASourceReady:
    """The generalisation, not the Google Books special case beside it.

    `sources.NEEDS_A_KEY` is Google Books alone on this date, so the roster
    cannot exercise this: the rule is written for the set rather than for the
    member, because the next source to declare that capability is the reason
    #180 exists. The roster is widened here rather than the rule being spelled
    per source.
    """

    @pytest.fixture
    def needs_a_credential(self, monkeypatch):
        """Pretend the BNE declares that it needs a credential."""
        widened = sources.NEEDS_A_KEY | {CatalogueSource.BNE}
        monkeypatch.setattr(sources, "NEEDS_A_KEY", frozenset(widened))
        return CatalogueSource.BNE

    def test_it_is_neither_held_nor_ready_without_one(self, db, needs_a_credential):
        assert needs_a_credential not in settings_store.source_credentials(db)
        assert needs_a_credential not in settings_store.ready_sources(db)

    def test_storing_one_makes_it_both(self, db, needs_a_credential):
        credentials.generate_key(db)
        credentials.put(
            db,
            needs_a_credential.value,
            targets.SEEDED[needs_a_credential].base_url,
            "alice",
            "hunter2",
        )
        assert needs_a_credential in settings_store.source_credentials(db)
        assert needs_a_credential in settings_store.ready_sources(db)

    def test_a_credential_under_a_lost_key_makes_it_neither(self, db, needs_a_credential):
        """Reporting it as ready leaves a member's search to discover otherwise."""
        credentials.generate_key(db)
        credentials.put(
            db,
            needs_a_credential.value,
            targets.SEEDED[needs_a_credential].base_url,
            "alice",
            "hunter2",
        )
        credentials.store_key(credentials.generate_phrase())
        assert needs_a_credential not in settings_store.source_credentials(db)
        assert needs_a_credential not in settings_store.ready_sources(db)

    def test_a_pinned_one_counts(self, db, needs_a_credential, monkeypatch):
        monkeypatch.setenv("CATALOGUE_CREDENTIAL_BNE", "bob:correcthorse")
        assert needs_a_credential in settings_store.source_credentials(db)

    def test_google_books_is_still_decided_by_its_own_key(self, db):
        """Its credential is an API key in a query string, not a login."""
        credentials.generate_key(db)
        credentials.put(
            db,
            CatalogueSource.GOOGLE_BOOKS.value,
            targets.SEEDED[CatalogueSource.GOOGLE_BOOKS].base_url,
            "alice",
            "hunter2",
        )
        assert CatalogueSource.GOOGLE_BOOKS not in settings_store.source_credentials(db)


class TestTheKeyIsResolvedOncePerRequest:
    """`_catalogue_logins` resolves the encryption key for the loop, not per source.

    **The cost is counted, not reasoned about.** Resolving reads every entry in
    `credentials.KEY_SOURCES` and runs a BIP-39 decode per phrase held, so on a
    machine with a keychain it is a round trip; this is the member request path,
    so it is paid per lookup rather than per admin visit.

    **Two instruments, because one careful reading is one reading.**
    `_supplied` is counted here, and `KeySource.read` is counted by
    `test_the_key_sources_are_read_once_over` below, which observes the effect
    rather than the function: a resolution that stopped going through
    `_supplied` would leave the first count at zero and say nothing.

    **The arm that is a cost rather than a saving has a test of its own.** A
    roster whose credential doors are all pinned in the environment opens no
    envelope, so it needs no key, and it now pays one resolution where it paid
    none. That is stated at `_catalogue_logins` and pinned by
    `test_a_pinned_only_roster_pays_one_resolution`, because a fix measured only
    where it saves is a fix nobody has asked the other question of.

    **The whole request is counted by
    `tests/routers/test_books.py::TestTheLookupRouteDoesNotPayPerSourceEither`**,
    which is a route and stays with the route. The resolver being right is not
    the route using it.
    """

    @staticmethod
    def _counted(monkeypatch) -> list[int]:
        """A one element tally of `credentials._supplied` invocations."""
        tally = [0]
        real = credentials._supplied

        def counting():
            tally[0] += 1
            return real()

        monkeypatch.setattr(credentials, "_supplied", counting)
        return tally

    @staticmethod
    def _seal(db, key_phrase, monkeypatch, *names: str) -> None:
        monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", key_phrase)
        for name in names:
            address = targets.SEEDED[CatalogueSource(name)].base_url
            credentials.put(db, name, address, "alice", "hunter2")

    @pytest.fixture
    def key_phrase(self) -> str:
        return credentials.generate_phrase()

    def test_the_shipping_roster_resolves_the_key_once_and_opens_no_envelope(
        self, db, monkeypatch
    ):
        """Nothing is patched, so this is the roster as it ships.

        **The arm that matters has survived two changes to what the roster
        answers**, and it is the tally rather than the mapping: an install
        storing no credential pays one resolution and not one per source. A
        tally above one here is the defect this class exists for, arriving from
        the other side.

        What the mapping holds did change, twice. It was empty while no door
        carried a login at all; it was still empty once one did, because nobody
        had entered one; and it now carries the shipped default, which costs no
        resolution because it opens no envelope. So the roster as it ships pays
        exactly what it paid before and sends a login it did not send.
        """
        tally = self._counted(monkeypatch)

        resolved = settings_store._catalogue_logins(db)

        assert set(resolved) == sources.SHIPS_A_CREDENTIAL
        assert tally[0] == 1

    def test_two_sealed_logins_cost_what_one_costs(
        self, db, key_phrase, monkeypatch
    ):
        """The count is flat in the number of sources, which is the whole fix."""
        self._seal(db, key_phrase, monkeypatch, "dnb")
        monkeypatch.setattr(
            sources, "NEEDS_A_KEY", frozenset({CatalogueSource.DNB})
        )
        tally = self._counted(monkeypatch)
        assert len(settings_store._catalogue_logins(db)) == 1
        one = tally[0]

        credentials.put(
            db,
            "k10plus",
            targets.SEEDED[CatalogueSource.K10PLUS].base_url,
            "alice",
            "hunter2",
        )
        monkeypatch.setattr(
            sources,
            "NEEDS_A_KEY",
            frozenset({CatalogueSource.DNB, CatalogueSource.K10PLUS}),
        )
        tally[0] = 0
        assert len(settings_store._catalogue_logins(db)) == 2
        two = tally[0]

        assert (one, two) == (1, 1), (
            f"{one} resolution for one sealed login and {two} for two: the cost "
            "moves with the roster, which is the defect this exists to catch"
        )

    def test_a_lost_key_is_resolved_once_as_well(
        self, db, key_phrase, monkeypatch
    ):
        """The deployment whose key is gone, which is the arm that was 1 + N.

        Both critic seats found it independently: `_material` fell through to
        `require_key` on a state that already said there was no key, so the one
        state where every other reader answers from the value it was handed was
        the one state this re-read every store, per source.

        Nothing is readable here, so the loop resolves no login at all. That is
        the point: the cost was being paid to learn nothing.
        """
        self._seal(db, key_phrase, monkeypatch, "dnb", "k10plus")
        monkeypatch.setattr(
            sources,
            "NEEDS_A_KEY",
            frozenset({CatalogueSource.DNB, CatalogueSource.K10PLUS}),
        )
        monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY")
        assert credentials.key_material() is None, (
            "a key is still in force, so this measures the readable path"
        )
        tally = self._counted(monkeypatch)

        assert settings_store._catalogue_logins(db) == {}

        assert tally[0] == 1

    def test_a_pinned_only_roster_pays_one_resolution(self, db, monkeypatch):
        """The cost side of the change, stated rather than discovered.

        A pinned credential never opens an envelope, so before this the loop
        touched no key store at all. It now resolves once for the request.
        """
        monkeypatch.setattr(
            sources,
            "NEEDS_A_KEY",
            frozenset({CatalogueSource.DNB, CatalogueSource.K10PLUS}),
        )
        monkeypatch.setenv(credentials.env_variable_name("dnb"), "alice:hunter2")
        monkeypatch.setenv(
            credentials.env_variable_name("k10plus"), "alice:hunter2"
        )
        tally = self._counted(monkeypatch)

        assert len(settings_store._catalogue_logins(db)) == 2

        assert tally[0] == 1

    def test_the_key_sources_are_read_once_over(
        self, db, key_phrase, monkeypatch
    ):
        """The second instrument: every store is read once, not once per source.

        This counts what the machine actually does, where the test above counts
        a call to one of our own functions. The issue's measurement is in this
        unit: three key source reads per sealed source rather than three in all.
        """
        self._seal(db, key_phrase, monkeypatch, "dnb", "k10plus")
        monkeypatch.setattr(
            sources,
            "NEEDS_A_KEY",
            frozenset({CatalogueSource.DNB, CatalogueSource.K10PLUS}),
        )
        reads: list[str] = []
        one_pass = [source.token for source in credentials.KEY_SOURCES]

        def watching(source: credentials.KeySource) -> credentials.KeySource:
            def read() -> str:
                reads.append(source.token)
                return source.read()

            return dataclasses.replace(source, read=read)

        monkeypatch.setattr(
            credentials,
            "KEY_SOURCES",
            tuple(watching(source) for source in credentials.KEY_SOURCES),
        )

        assert len(settings_store._catalogue_logins(db)) == 2

        assert reads == one_pass, (
            f"{reads} store reads for two sealed logins, where one pass over "
            "the stores is one read each"
        )
