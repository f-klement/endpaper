"""Tests for backend/settings_store.py."""

import ast
import dataclasses
import functools
import re
from typing import Final

import pytest

import config
import credentials
import settings_store
import sources
import targets
from enums import CatalogueSource, Locale, SettingKey
from tests.test_house_rules import _source_modules


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


# ── The override table and the reader that has to see it ──────────────────────

#: The module whose readers this rule is about, keyed as `_source_modules` keys it.
_STORE: Final = "settings_store.py"

#: The ORM name that means "this function touched the settings table".
#:
#: **An anchor rather than a list of reader names.** A keyed function that
#: reaches this is reading or writing the row; one that does not is answering
#: something else, which is what keeps `is_from_env` out of the reader set
#: without naming it. Rename the model and the split below returns nothing,
#: which `test_the_reader_split_is_read_off_the_module` is what reports.
_THE_TABLE: Final = "Setting"

#: The `config` door that reads a variable for a settings key. Same kind of
#: anchor, for the other half of the split.
_THE_ENVIRONMENT: Final = "env_override"

_A_FUNCTION: Final = (ast.FunctionDef, ast.AsyncFunctionDef)


def _mentions(node: ast.AST, name: str) -> bool:
    """Whether `name` is written anywhere in this subtree, bare or as an attribute."""
    return any(
        (isinstance(inner, ast.Name) and inner.id == name)
        or (isinstance(inner, ast.Attribute) and inner.attr == name)
        for inner in ast.walk(node)
    )


def _calls_within(node: ast.AST) -> set[str]:
    """The names called in this subtree, both dotted and bare."""
    found: set[str] = set()
    for inner in ast.walk(node):
        if isinstance(inner, ast.Call):
            called = ast.unparse(inner.func)
            found |= {called, called.rsplit(".", 1)[-1]}
    return found


def _answered_calls(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """The names called inside this function's `return` expressions."""
    found: set[str] = set()
    for inner in ast.walk(node):
        if isinstance(inner, ast.Return) and inner.value is not None:
            found |= _calls_within(inner.value)
    return found


def _answers_with(node: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    """Whether `name` is written inside one of this function's answers."""
    return any(
        isinstance(inner, ast.Return)
        and inner.value is not None
        and _mentions(inner.value, name)
        for inner in ast.walk(node)
    )


def _keyed_parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    arguments = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
    return {
        argument.arg
        for argument in arguments
        if argument.annotation is not None
        and ast.unparse(argument.annotation).rsplit(".", 1)[-1] == "SettingKey"
    }


def _answers_with_a_value(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """A reader answers with something; a writer answers `None`.

    Read off the annotation because this project annotates every return, and
    because it separates `set_value` from `get_raw` without either being named:
    both touch the table, and only one hands a value back.
    """
    return node.returns is not None and ast.unparse(node.returns).strip("\"'") != "None"


def _keyed_readers(store: str) -> tuple[frozenset[str], frozenset[str]]:
    """`settings_store`'s keyed readers, split by whether they see the environment.

    **Derived from the module, never listed.** A reader is a top level function
    taking a `SettingKey`, answering with a value, and reaching the settings
    table; it is an in force reader when it also reaches `config.env_override`.
    A `get_float` added tomorrow lands in the first set with no edit here, which
    is the whole reason this is a derivation: every version of this rule that
    named its readers would have been evaded by the next one.
    """
    tree = ast.parse(store)
    bodies = {node.name: node for node in tree.body if isinstance(node, _A_FUNCTION)}

    def reaches(name: str, anchor: str, seen: set[str]) -> bool:
        if name in seen:
            return False
        seen.add(name)
        body = bodies.get(name)
        if body is None:
            return False
        if _mentions(body, anchor):
            return True
        return any(reaches(call, anchor, seen) for call in _calls_within(body))

    def answers_from(name: str, seen: set[str]) -> bool:
        """Whether the environment decides what this function hands back.

        **The answer rather than the body, and the two anchors are deliberately
        asymmetric.** `get_raw` touches `Setting` outside its return, so the
        table anchor has to be a whole body walk. The environment anchor must
        not be: a reader that calls `config.env_override` and does nothing with
        the result reads exactly as it did before, and counting the mention
        moves it into the in force set, which is where a stored read of a pinned
        key stops being reported. Measured: `get_int` with a three line `if
        config.env_override(key): pass` in it passed every arm of this class
        while `mailer` read a pinned key off the table.
        """
        if name in seen:
            return False
        seen.add(name)
        body = bodies.get(name)
        if body is None:
            return False
        if _answers_with(body, _THE_ENVIRONMENT):
            return True
        return any(answers_from(call, seen) for call in _answered_calls(body))

    readers = {
        name
        for name, body in bodies.items()
        if _keyed_parameters(body)
        and _answers_with_a_value(body)
        and reaches(name, _THE_TABLE, set())
    }
    sees_the_environment = {name for name in readers if answers_from(name, set())}
    return frozenset(readers - sees_the_environment), frozenset(sees_the_environment)


def _key_tables(tree: ast.Module) -> dict[str, frozenset[str]]:
    """Module level names holding `SettingKey` members, and which members.

    `notifications._ENABLED_KEY` is why this exists: `get_bool(db,
    _ENABLED_KEY[sender])` names no key, and a pass that skipped what it could
    not read would have a hole exactly where a key stops being a literal. The
    whole table is the answer, which over reports rather than under reports.
    """
    tables: dict[str, frozenset[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if node.value is None:
            continue
        members = _keys_named(node.value)
        for target in targets:
            if isinstance(target, ast.Name) and members:
                tables[target.id] = members
    return tables


def _keys_named(node: ast.AST) -> frozenset[str]:
    """Every `SettingKey.X` in this subtree, however the enum was imported."""
    return frozenset(
        inner.attr
        for inner in ast.walk(node)
        if isinstance(inner, ast.Attribute)
        and ast.unparse(inner.value).rsplit(".", 1)[-1] == "SettingKey"
    )


def _named_key(expression: ast.expr, tables: dict[str, frozenset[str]]) -> frozenset[str]:
    """Which keys this argument can name, or an empty set for "cannot tell"."""
    if isinstance(expression, ast.Attribute) and _keys_named(expression):
        return _keys_named(expression)
    rooted = expression.value if isinstance(expression, ast.Subscript) else expression
    if isinstance(rooted, ast.Name):
        return tables.get(rooted.id, frozenset())
    return frozenset()


#: What a call is labelled when the pass can see it reaches a reader and cannot
#: say which. It is in neither reader set, so it can never be an offender, and
#: it carries no key, so it is reported as unreadable.
_UNNAMEABLE: Final = "<not named from the source>"


def _store_aliases(tree: ast.Module) -> set[str]:
    """Local names bound to the `settings_store` module.

    `from . import settings_store` is an `ImportFrom` and binds the module just
    as `import settings_store as ss` does, so both forms are read here.
    """
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            found |= {
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "settings_store"
            }
    return found


def _store_aliases_here(tree: ast.Module, path: str) -> set[str]:
    """`_store_aliases`, plus the module's own name when this IS the store.

    **One home for the alias half of the store special case.** It was split
    between `_reader_calls`, which added the name, and `_re_exported_readers`,
    which passed a bare `_store_aliases(tree)` and did not: the two callers of
    `_reader_bindings` differed in `aliases` as well as in `module_level_only`,
    and nothing made that visible because `settings_store.py` has no module
    scope `X = settings_store.get_bool` for the difference to act on.

    `_spells_a_reader_call` deliberately keeps the bare one. It is the second
    instrument and reads the characters rather than the syntax, and the symmetry
    it feeds names `_STORE` itself.
    """
    aliases = _store_aliases(tree)
    if path == _STORE:
        aliases.add("settings_store")
    return aliases


#: Where the descent to module scope stops: a name bound inside one of these is
#: not an attribute on the module.
#:
#: **Not a claim about which node types open a scope**, which is a larger set
#: than this and is not what the refusal turns on. Both callers read statements
#: and only statements: `ImportFrom`, `Assign` and `AnnAssign` in
#: `_reader_bindings`; `Assign`, `AnnAssign`, `FunctionDef`, `AsyncFunctionDef`
#: and `ClassDef` in `_defined_here`, which does not read `ImportFrom` because
#: an imported reader is already carried by `bound` before that clause is
#: reached. So the refusal has work to do exactly where a scope has a statement
#: body, which is a `def`, an `async def` and a `class`,
#: and `test_a_reader_bound_inside_a_scope_of_its_own_is_not_an_attribute_on_that_module`
#: has one row per one of those: drop a member and its row goes red.
#:
#: `ast.Lambda` is a fourth member that can never fire, because a lambda holds
#: an expression and no statement can sit in one. Every other expression scope,
#: the four comprehensions and a PEP 695 type parameter list, is absent for
#: exactly that reason, so the tuple is three live entries and one dead one
#: rather than a set anybody should extend by category.
_ITS_OWN_SCOPE: Final = (*_A_FUNCTION, ast.ClassDef, ast.Lambda)

#: The `typing` flag whose block a type checker reads and the interpreter never
#: runs. The test is asked whether it MENTIONS this, not what it evaluates to,
#: so `if not TYPE_CHECKING:` is read backwards; nothing in this tree writes one.
_ONLY_FOR_TYPES: Final = "TYPE_CHECKING"


def _at_module_scope(tree: ast.Module) -> list[ast.AST]:
    """Every node that runs when this module is imported, in source order.

    **`tree.body` is not module scope, and the difference is not exotic.** A
    `try:` around an import and a `with` block both bind a name on the module
    and both sit a level below the body. Reading only `tree.body` meant a
    subject that re exported a reader inside a `try:` handed out nothing, so a
    pinned key read off the table through it was reported by nothing, while the
    identical binding read by the subject's own calls was.

    The descent stops at `_ITS_OWN_SCOPE` and nowhere else, which is why it is
    written as a refusal to enter the node types that open a scope rather than
    as a list of the statements it will walk through.

    **An `if TYPE_CHECKING:` body is not entered, and that is the difference
    between "runs at import" and "is written at this indent".** It is right for
    both callers, which is why the function is defined by the first of those:
    `_reader_bindings` asks what a subject hands out, and an attribute bound
    only for a type checker raises at run time rather than reading a setting;
    `_defined_here` asks whether a module defines a name itself, and one defined
    only for a type checker does not, so a bare call to it came from a re export
    and is the unreadable this rule exists to report. **Stating it as a trade
    was wrong**: the direction reverses between the two callers, because the
    first adds bindings and the second only ever suppresses a report. All five
    of the corpus modules that bind below `tree.body` do it this way, so on this
    tree the descent reaches nothing the body does not, measured.
    """
    found: list[ast.AST] = []
    stack: list[ast.AST] = list(reversed(tree.body))
    while stack:
        node = stack.pop()
        found.append(node)
        if isinstance(node, _ITS_OWN_SCOPE):
            continue
        children = (
            list(node.orelse)
            if isinstance(node, ast.If) and _mentions(node.test, _ONLY_FOR_TYPES)
            else list(ast.iter_child_nodes(node))
        )
        stack.extend(reversed(children))
    return found


@functools.cache
def _rebound_here(source: str) -> frozenset[str]:
    """Every name this module binds by anything other than an import.

    **The caller side of the question `_re_exported_readers` asks of the
    subject**, and it was missing. `subjects` is a flat name to module map with
    no scope analysis, so a parameter or a local called `helpers` resolved as
    the module `helpers` and a call on it was reported as a read of a pinned
    key. That is a red on a clean tree against a call that cannot reach the
    module at all, which is how a guard gets argued away by whoever meets it
    next. The name clash it needs already exists twice in the corpus:
    `metadata.py` binds `sources` both as a module and otherwise, and
    `routers/books.py` does it for `catalogue` and `lending`.

    **Read off the context the parser already assigned**, rather than off a list
    of the statements that bind: every binding `Name` carries `Store` or `Del`,
    which covers assignment, tuple unpacking, `for`, `with ... as`, `except*`,
    a comprehension target and the walrus in one question. Parameters are
    `ast.arg`. Everything else that binds carries its name as a plain string on
    the node, so that is asked generically, with `ast.alias` excluded because an
    import is the one binding this must not count.

    **Cost, and it is the safe direction**: a module that imports `helpers` and
    also has a parameter called `helpers` anywhere in it loses the resolution
    for its genuine reads through that module, and goes silent rather than
    wrong. `ast.MatchMapping`'s `rest` is spelled `rest` rather than `name` and
    is not seen, which is the one binding form this misses.

    Takes the source rather than the tree so it can be cached: it is a whole
    tree walk per module, asked once per module per rule run, and the corpus is
    re read for every one of them.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
            found.add(node.id)
        elif isinstance(node, ast.arg):
            found.add(node.arg)
        elif not isinstance(node, ast.alias):
            name = getattr(node, "name", None)
            if isinstance(name, str):
                found.add(name)
    return frozenset(found)


def _module_index(corpus: dict[str, str]) -> dict[str, str]:
    """Dotted module name to corpus path, for every module the corpus holds.

    **It states its exclusion by inheriting one.** The corpus is
    `_source_modules()`, so whatever is not in it resolves to nothing: the test
    tree, the migrations, anything vendored, and everything outside `backend/`,
    the standard library and site-packages included. A reader re exported
    through a module none of those walks reach leaves the call on it silent,
    exactly as silent as it was before any of this resolution existed.
    """
    index: dict[str, str] = {}
    for path in corpus:
        parts = path.removesuffix(".py").split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            index[".".join(parts)] = path
    return index


def _imported_modules(tree: ast.Module, path: str, index: dict[str, str]) -> dict[str, str]:
    """Local names bound to another module of the corpus, and which module.

    `import mailer`, `import routers.settings as rs`, `from routers import
    settings` and `from . import settings_store` each bind a module to a name
    here; `from config import auth_mode` binds a function. **The index is what
    tells those apart**, rather than a rule about how the import is spelled, so
    a name that resolves to no module of the corpus is simply absent.

    Walked rather than read off `tree.body`, because an import inside a function
    binds the module for that function's calls just as a top level one does.

    `import a.b` with no `as` binds `a`, so the subject of `a.b.get_bool()` is an
    attribute rather than a name and no caller ever asks about it.
    """
    package = path.rsplit("/", 1)[0].replace("/", ".") if "/" in path else ""
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                dotted = alias.name if alias.asname else alias.name.split(".", 1)[0]
                if dotted in index:
                    found[alias.asname or dotted] = index[dotted]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                above = package.split(".") if package else []
                above = above[: len(above) - node.level + 1]
                base = ".".join([*above, base] if base else above)
            for alias in node.names:
                dotted = f"{base}.{alias.name}" if base else alias.name
                if dotted in index:
                    found[alias.asname or alias.name] = index[dotted]
    return found


def _readers_named(
    node: ast.expr,
    readers: frozenset[str],
    aliases: set[str],
    bound: dict[str, frozenset[str]],
) -> frozenset[str]:
    """Which readers this expression hands out, by any spelling it can be read by.

    **The expression's own shape, not a walk of it**, and the difference is a
    value that *calls* a reader rather than being one: `use_tls =
    settings_store.bool_in_force(db, key)` holds a bool, and a walk binds
    `use_tls` to the reader. Nothing calls such a name today, so the walk cost
    nothing and would have been a false offender the day something did.

    A collection literal is looked through, because a table of readers is the
    shape a module reaches for as soon as it has two.
    """
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in aliases
        and node.attr in readers
    ):
        return frozenset({node.attr})
    if isinstance(node, ast.Name):
        return bound.get(node.id, frozenset())
    if isinstance(node, ast.Dict):
        held = [value for value in node.values if value is not None]
        return frozenset().union(
            *(_readers_named(value, readers, aliases, bound) for value in held)
        ) if held else frozenset()
    if isinstance(node, ast.List | ast.Tuple | ast.Set):
        return frozenset().union(
            *(_readers_named(element, readers, aliases, bound) for element in node.elts)
        ) if node.elts else frozenset()
    return frozenset()


def _names_the_door(
    node: ast.expr,
    aliases: set[str],
    readers: frozenset[str],
    bound: dict[str, frozenset[str]],
) -> bool:
    """Whether this expression names the module, a reader, or a name holding one.

    The test for a call the pass cannot follow. It asks what the expression
    mentions rather than what it is, because that is all there is to go on once
    the door is computed: `getattr(settings_store, "get_bool")` and
    `settings_store.__dict__["get_bool"]` name it, and `Page[BookOut]` names
    nothing, which is what keeps eight instantiations in the corpus silent.

    **`bound` is the third population and it is not redundant**, which is what a
    merge of two conditions costs when nobody re-checks the half that went. A
    reader imported as `gb` is in neither of the other two, so `_pick(gb)(db,
    key)` was silent while `gb(db, key)` beside it was an offender: aliasing
    handled everywhere but through the computed door. `bound` is seeded from the
    import bindings, so one clause covers both that and `_R =
    settings_store.get_bool`.
    """
    return any(
        (isinstance(inner, ast.Name) and (inner.id in aliases | readers or inner.id in bound))
        or (isinstance(inner, ast.Attribute) and inner.attr in readers)
        for inner in ast.walk(node)
    )


def _reader_bindings(
    path: str,
    tree: ast.Module,
    readers: frozenset[str],
    aliases: set[str],
    *,
    module_level_only: bool = False,
) -> dict[str, frozenset[str]]:
    """Which readers each name this module binds can hold.

    Lifted out of `_reader_calls` because the cross module half asks the same
    question of a different module, and a second copy of these rules is a second
    place for the next spelling to go missing from one side only.

    **`module_level_only` is now the only difference between the two callers,
    and it is not a tuning knob.** A module's own calls reach a name bound
    anywhere in it, including a `read = settings_store.get_bool` inside a
    function, which is the cheapest spelling of this rule's evasion. Another
    module reaches only what is an attribute on this one, which is what module
    scope binds and a function body does not: counting a function local there
    would report a caller that cannot reach it. **Module scope is
    `_at_module_scope`, not `tree.body`**, and the two are not the same set.

    The store's own readers are seeded here for both callers, and the store's
    own name is added to `aliases` by `_store_aliases_here` before either calls
    in, so the special case is not a third difference between them.

    Either way the statements arrive in source order, so `_B = _A` resolves in
    the same pass that bound `_A`.
    """
    statements: list[ast.AST] = (
        _at_module_scope(tree) if module_level_only else list(ast.walk(tree))
    )
    bare = {
        (alias.asname or alias.name): alias.name
        for node in statements
        if isinstance(node, ast.ImportFrom) and node.module == "settings_store"
        for alias in node.names
        if alias.name in readers
    }
    if path == _STORE:
        bare |= {name: name for name in readers}

    bound: dict[str, frozenset[str]] = {
        name: frozenset({reader}) for name, reader in bare.items()
    }
    for statement in statements:
        if isinstance(statement, ast.Assign):
            targets: list[ast.expr] = list(statement.targets)
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
        else:
            continue
        if statement.value is None:
            continue
        held = _readers_named(statement.value, readers, aliases, bound)
        for target in targets:
            if isinstance(target, ast.Name) and held:
                bound[target.id] = held
    return bound


@functools.cache
def _re_exported_readers(
    path: str, source: str, readers: frozenset[str]
) -> dict[str, frozenset[str]]:
    """Which readers this module hands out as attributes on itself.

    **The cross module half, and the whole of what tells `helpers.get_bool` from
    `sources.in_force`.** Both are an attribute call whose name is a reader's on
    a subject that is not this module; the first is a reader because `helpers`
    bound that name from `settings_store`, and the second is not because
    `sources` defines an `in_force` of its own. The question is asked of what the
    subject did, never of what it is called.

    One hop. A module re exporting another module's re export is not followed,
    and is silent rather than reported, which is the same trade the direct re
    export through a bare name already makes. **No corpus module re exports a
    reader at all**, so nothing on a clean tree can tell one hop from two and
    `test_a_re_export_of_a_re_export_is_not_followed` is the whole of what pins
    the bound.

    Cached because a corpus of ninety one modules is read once per rule and only
    the handful reached by an attribute call are ever asked. **The dict is read
    and never mutated**: every caller is handed the same object.
    """
    tree = ast.parse(source)
    return _reader_bindings(
        path, tree, readers, _store_aliases_here(tree, path), module_level_only=True
    )


def _defined_here(tree: ast.Module) -> set[str]:
    """Module scope names this module binds itself, whatever they hold.

    **`_at_module_scope`, for the reason it exists.** This read `tree.body`,
    which is the same defect one function over: a `def get_bool` inside a `try:`
    was not seen, so a bare call to it read as a re export and was reported
    unreadable, which is red on a clean tree against a module that is correct.
    """
    found = set()
    for node in _at_module_scope(tree):
        if isinstance(node, (*_A_FUNCTION, ast.ClassDef)):
            found.add(node.name)
        elif isinstance(node, ast.Assign):
            found |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            found.add(node.target.id)
    return found


def _reader_calls(
    path: str, source: str, readers: frozenset[str], corpus: dict[str, str]
) -> list[tuple[int, str, frozenset[str]]]:
    """Every call of one of `readers` here, with the keys it can name.

    **Bound by what the module did, rather than matched by name.**
    `sources.in_force` is a different function with the same name and a plan for
    an argument, so a pass matching the attribute alone reports a module that
    reads no setting at all. This repository has been walked past by an aliased
    import before: see
    `test_notifications.py::test_the_mode_arm_is_decided_in_exactly_one_place`.

    **Five ways of reaching a reader, and the third and fourth are why this is
    not a list of two.** A module level name bound to one (`_read =
    settings_store.get_bool`) is `notifications._ENABLED_KEY`'s own idiom one
    step over, and a table of them is that idiom exactly; both are read here the
    way `_key_tables` reads a table of keys, by over reporting what the name can
    hold. A call the pass cannot follow at all is labelled `_UNNAMEABLE` and
    reported as unreadable rather than dropped, which covers `getattr` and every
    other computed door, **but only when its subject mentions this module or a
    reader**: `Page[BookOut](...)` is a call on a subscript too, eight of them in
    the corpus, and reporting those would leave this rule red on a tree with
    nothing wrong with it.

    A bare call to a reader's name in a module that neither imports it from
    `settings_store` nor defines it is a re export, and is unreadable for the
    same reason. Measured over the corpus: no module is flagged today, and
    `sources.py` is not because it defines an `in_force` of its own.

    **The fifth is an attribute on another module of the corpus**, and it is the
    one that needs a second module read rather than a further clause: `helpers`
    is not this module and not `settings_store`, so nothing in this file's own
    syntax says whether `helpers.get_bool(db, key)` reads a setting. The subject
    is resolved to a corpus module and asked what it hands out, which is what
    separates it from `sources.in_force` at `settings_store.py:439`, where the
    subject resolves and hands out nothing. `_module_index` states what the
    resolution does not reach.

    The one shape dropped is `settings_store` handing its own `SettingKey`
    parameter down, which is the module's plumbing rather than a call site.
    """
    tree = ast.parse(source)
    tables = _key_tables(tree)
    aliases = _store_aliases_here(tree, path)
    defined = _defined_here(tree)

    # **Every assignment in the module, not only the top level ones.** A function
    # local `read = settings_store.get_bool` is the cheapest spelling of the
    # evasion this rule exists for, and reading only `tree.body` left it silent
    # rather than reported.
    bound = _reader_bindings(path, tree, readers, aliases)

    # A name this module also binds itself is not the module it imported, so it
    # is no longer a subject: `def send(db, helpers)` reaches a parameter, and
    # resolving it as the module reports a call that cannot get there.
    rebound = _rebound_here(source)
    subjects = {
        name: target
        for name, target in _imported_modules(tree, path, _module_index(corpus)).items()
        if name not in rebound
    }

    plumbing: dict[int, set[str]] = {}
    if path == _STORE:
        for node in ast.walk(tree):
            if isinstance(node, _A_FUNCTION):
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Call):
                        plumbing.setdefault(id(inner), set()).update(
                            _keyed_parameters(node)
                        )

    found: list[tuple[int, str, frozenset[str]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        rooted: ast.expr = node.func
        while isinstance(rooted, ast.Subscript):
            rooted = rooted.value

        if isinstance(node.func, ast.Attribute):
            subject = node.func.value
            if ast.unparse(subject) in aliases:
                reached = frozenset({node.func.attr} & readers)
            elif isinstance(subject, ast.Name) and subject.id in subjects:
                reached = _re_exported_readers(
                    subjects[subject.id], corpus[subjects[subject.id]], readers
                ).get(node.func.attr, frozenset())
            else:
                continue
        elif isinstance(rooted, ast.Name):
            if rooted.id in bound:
                reached = bound[rooted.id]
            elif (
                isinstance(node.func, ast.Name)
                and node.func.id in readers
                and node.func.id not in defined
            ):
                found.append((node.lineno, _UNNAMEABLE, frozenset()))
                continue
            else:
                continue
        elif _names_the_door(node.func, aliases, readers, bound):
            found.append((node.lineno, _UNNAMEABLE, frozenset()))
            continue
        else:
            continue

        if not reached:
            continue

        arguments = list(node.args) + [keyword.value for keyword in node.keywords]
        named: frozenset[str] = frozenset().union(
            *(_named_key(argument, tables) for argument in arguments)
        )
        if not named and any(
            isinstance(argument, ast.Name)
            and argument.id in plumbing.get(id(node), set())
            for argument in arguments
        ):
            continue
        found += [(node.lineno, reader, named) for reader in sorted(reached)]
    return found


def _reads_of_a_pinned_key(
    modules: dict[str, str], only: str | None = None
) -> tuple[list[str], list[str], int]:
    """(read off the table, key unreadable, calls examined).

    `only` narrows the verdict to one module while the split is still derived
    from the whole of `settings_store`, which is what lets a planted module be
    judged by this function rather than by a second copy of the rule. It narrows
    the verdict alone: every module stays in the corpus, because a cross module
    read is resolved against modules no verdict is being asked about.
    """
    off_the_table, in_force = _keyed_readers(modules[_STORE])
    pinned = {key.name for key in config._ENV_OVERRIDES}

    offenders: list[str] = []
    unreadable: list[str] = []
    examined = 0
    for path, source in sorted(modules.items()):
        if only is not None and path != only:
            continue
        for line, reader, named in _reader_calls(
            path, source, off_the_table | in_force, modules
        ):
            examined += 1
            if not named:
                unreadable.append(f"{path}:{line} {reader}")
            elif reader in off_the_table and named & pinned:
                offenders.append(f"{path}:{line} {reader} {sorted(named & pinned)}")
    return offenders, unreadable, examined


def _spells_a_reader_call(source: str, readers: frozenset[str]) -> bool:
    """Whether this module's TEXT spells a qualified call of a reader.

    **A second instrument, deliberately not the one the rule uses.** The pass
    above reads the syntax; this reads the characters, so a resolution that
    quietly stopped covering a module shows up as a module that plainly calls a
    reader and contributes nothing.

    Qualified, so `_google_books_in_force(` in `routers/books.py` is not a
    reader call. That module imports `settings_store`, spells `in_force(` in a
    private helper's name and calls no reader at all, so a bare substring would
    make this red on a tree with nothing wrong with it.
    """
    tree = ast.parse(source)
    aliases = _store_aliases(tree)
    patterns = [rf"(?<![\w.]){alias}\.{reader}\(" for alias in aliases for reader in readers]
    if not aliases:
        return False
    return any(re.search(pattern, source) for pattern in patterns)


def _planted(
    source: str,
    store: str | None = None,
    alongside: dict[str, str] | None = None,
    path: str = "planted.py",
) -> tuple[list[str], list[str], int]:
    """The rule run over one planted module, against the real store or a planted one.

    The verdict covers the planted module alone, so a count means what the
    plant did rather than what the store already does beside it.

    `alongside` puts further modules in the corpus without putting them in the
    verdict, which is what a read through another module needs: the module being
    read through has to be resolvable, and what it does in its own right is not
    what is being judged.

    `path` is where the plant sits, and it is not decoration: a relative import
    resolves against the package the reading module is in, so at the top level
    `from . import helpers` and `helpers` are the same answer and a plant there
    cannot tell a resolution that walks the package from one that ignores it.
    """
    return _reads_of_a_pinned_key(
        {
            _STORE: store or _source_modules()[_STORE],
            path: source,
            **(alongside or {}),
        },
        only=path,
    )


#: Ways of reaching a reader that the rule must judge rather than walk past.
#:
#: **Diagonals, not the rule.** The rule names no spelling: it resolves what the
#: module bound and reports what it cannot follow. This table is what says so,
#: one row per way somebody has actually reached past a guard here, and every
#: row after the first came from a critic seat rather than from this file's
#: author, which is the arrangement rather than an accident.
_PLANTED_SPELLINGS: Final = (
    "import settings_store\nsettings_store.{reader}(db, SettingKey.MAIL_USE_TLS)\n",
    "import settings_store as ss\nss.{reader}(db, SettingKey.MAIL_USE_TLS)\n",
    "from settings_store import {reader} as _read\n_read(db, SettingKey.MAIL_USE_TLS)\n",
    "import settings_store\n"
    '_KEYS = {{"tls": SettingKey.MAIL_USE_TLS}}\n'
    "settings_store.{reader}(db, _KEYS[name])\n",
    # A module level name bound to the reader, which is `_ENABLED_KEY`'s idiom
    # one step over.
    "import settings_store\n"
    "_READ = settings_store.{reader}\n"
    "_READ(db, SettingKey.MAIL_USE_TLS)\n",
    # A table of them, which is that idiom exactly.
    "import settings_store\n"
    '_READERS = {{"flag": settings_store.{reader}}}\n'
    '_READERS["flag"](db, SettingKey.MAIL_USE_TLS)\n',
    # The module bound by a relative import rather than an absolute one.
    "from . import settings_store\n"
    "settings_store.{reader}(db, SettingKey.MAIL_USE_TLS)\n",
    # Imported to a bare name and then rebound to another.
    "from settings_store import {reader}\n"
    "_ALSO = {reader}\n"
    "_ALSO(db, SettingKey.MAIL_USE_TLS)\n",
    # The alias inside a function, which is the cheapest way to write the row
    # above and was silent while that one was reported.
    "import settings_store\n"
    "def send(db):\n"
    "    read = settings_store.{reader}\n"
    "    return read(db, SettingKey.MAIL_USE_TLS)\n",
    # Two steps, both at the top level. The second name is bound here and the
    # first is what says which reader it holds.
    "import settings_store\n"
    "_A = settings_store.{reader}\n"
    "_B = _A\n"
    "_B(db, SettingKey.MAIL_USE_TLS)\n",
)

#: Ways of reaching a reader that the pass can see and cannot follow. It has to
#: report these rather than drop them: dropping is what makes an evasion free.
_UNFOLLOWABLE_SPELLINGS: Final = (
    "import settings_store\n"
    'getattr(settings_store, "get_bool")(db, SettingKey.MAIL_USE_TLS)\n',
    "import settings_store\n"
    'settings_store.__dict__["get_bool"](db, SettingKey.MAIL_USE_TLS)\n',
    # A re export: another module imports the reader and this one imports it
    # from there, so nothing here names `settings_store` at all.
    "from helpers import get_bool\nget_bool(db, SettingKey.MAIL_USE_TLS)\n",
    # A computed door built on a reader imported under another name, which is
    # the case a merge of two conditions dropped: `gb` names neither the module
    # nor a reader, and the direct call of it beside this one is an offender.
    "from settings_store import get_bool as gb\n"
    "_pick(gb)(db, SettingKey.MAIL_USE_TLS)\n",
    # The same door built on a module level binding.
    "import settings_store\n"
    "_R = settings_store.get_bool\n"
    "_pick(_R)(db, SettingKey.MAIL_USE_TLS)\n",
    # And on a re export, where the name is a reader's and this module binds it
    # from somewhere else, so only the reader half of the door test sees it.
    "from helpers import get_bool\n_pick(get_bool)(db, SettingKey.MAIL_USE_TLS)\n",
    # A computed door built on a module **attribute** re export, which is the
    # attribute half's only witness: neither `Name` population sees anything
    # here, and the two doors that look like its cases, `getattr` and
    # `__dict__`, are carried by the alias half instead. Dropping that clause
    # leaves every other row of both tables green.
    #
    # `helpers` is outside this corpus, so the direct form beside it is silent
    # rather than reported and `_ATTRIBUTE_SPELLINGS` is where it is read. That
    # is the difference between a door and a subject: a door is judged by what
    # it mentions, and a subject by what the module it names hands out.
    "import helpers\n_pick(helpers.get_bool)(db, SettingKey.MAIL_USE_TLS)\n",
)


#: A reader reached as an attribute on another module of the corpus, paired with
#: what that module had to do for it to be one.
#:
#: **Both halves are `{reader}`**, so the diagonal below is read off
#: `settings_store` rather than listed: a reader added tomorrow is carried by
#: every row at once. The left column is how the subject bound the name and the
#: right is how this module reached the subject, because either half alone was
#: silent before the resolution existed.
_ATTRIBUTE_SPELLINGS: Final = (
    (
        "from settings_store import {reader}\n",
        "import helpers\nhelpers.{reader}(db, SettingKey.MAIL_USE_TLS)\n",
    ),
    # The subject reached through an import alias, which is the spelling a name
    # match on the subject would walk past.
    (
        "from settings_store import {reader}\n",
        "import helpers as h\nh.{reader}(db, SettingKey.MAIL_USE_TLS)\n",
    ),
    # And through a relative import, as `_store_aliases` already reads for the
    # module itself.
    (
        "from settings_store import {reader}\n",
        "from . import helpers\nhelpers.{reader}(db, SettingKey.MAIL_USE_TLS)\n",
    ),
    # The same import with an alias on it, which is a different expression from
    # the one `import helpers as h` reads and went missing from one of them.
    (
        "from settings_store import {reader}\n",
        "from . import helpers as h\nh.{reader}(db, SettingKey.MAIL_USE_TLS)\n",
    ),
    # The subject re exporting by assignment rather than by import, which is the
    # binding half of the rule asked of a module other than this one.
    (
        "import settings_store\n{reader} = settings_store.{reader}\n",
        "import helpers\nhelpers.{reader}(db, SettingKey.MAIL_USE_TLS)\n",
    ),
    # The subject imported inside the function that reads through it, which is
    # the cheapest way to write the first row and is what a top level read of
    # this module's imports would walk past.
    (
        "from settings_store import {reader}\n",
        "def send(db):\n"
        "    import helpers\n"
        "    return helpers.{reader}(db, SettingKey.MAIL_USE_TLS)\n",
    ),
    # The subject binding it a level below `tree.body` in a block that runs,
    # which was the hole a reader of `tree.body` left: the name is an attribute
    # on the module either way. Paired with
    # `test_a_subject_binding_only_for_a_type_checker_hands_out_nothing`, which
    # is the same indent and the opposite answer.
    (
        "try:\n"
        "    from settings_store import {reader}\n"
        "except ImportError:\n"
        "    {reader} = None\n",
        "import helpers\nhelpers.{reader}(db, SettingKey.MAIL_USE_TLS)\n",
    ),
    # The `else:` of an `if TYPE_CHECKING:`, which is the ordinary run time and
    # typing split and so the likeliest way this file's newest clause is met.
    # The clause refuses the body and takes this branch, and replacing that
    # branch with nothing left every other row of both tables green.
    (
        "if TYPE_CHECKING:\n"
        "    from settings_store import {reader}\n"
        "else:\n"
        "    from settings_store import {reader}\n",
        "import helpers\nhelpers.{reader}(db, SettingKey.MAIL_USE_TLS)\n",
    ),
)


class TestAnOverriddenSettingIsReadWhereItIsPinned:
    """No key the environment can pin is read off the table.

    Ten keys carry an entry in `config._ENV_OVERRIDES` and all ten were already
    read through `in_force`, so this starts green: it guards a hole rather than
    a defect. Delete it and the next key to gain an override can be read by the
    routine that uses it through a reader that never consults the environment,
    with the settings screen reporting the deployment's value and the send using
    the admin's. Nothing else relates the two.

    **No module is exempt and no key is named.** The settings screen was the
    exemption this would have needed, and it stopped needing one when
    `routers/settings.py` stopped spelling `in_force` out by hand.

    **What it does not cover**, stated rather than discovered:

    * A key with no override is read either way and is not reported, which is
      why `notifications.py` reading `SENDER_HEALTH` through `get_json` is
      clean. The rule wakes up when the override arrives.
    * A module reaching `models.Setting` itself rather than through a reader is
      invisible to it. `backup.py` is the one that does, over every table by
      name, and it archives rather than reads a value.
    * Inside `settings_store` a call in a nested function inherits the outer
      function's keyed parameters, so the plumbing skip is wider there than the
      one call it exists for.
    * A class attribute read as `R.read(db, key)` is followed no further.
      Matching it means treating every attribute call whose name collides with a
      bound one as a reader, and the cross module resolution does not arrive at
      it for free: that resolution asks what a **module** hands out, and a class
      is not in the index it asks. Naming this residue as "built at run time"
      was wrong in both directions, since a class attribute is neither built at
      run time nor followed.
    * The cross module resolution reaches the corpus and nothing else, and
      within it only a subject this module does not also bind by some other
      means. `helpers.get_bool(db, key)` is read when `helpers` is a module
      `_source_modules()` returns and nothing here rebinds that name, and is
      silent otherwise; `_module_index` and `_rebound_here` are where the two
      halves of that are written down. Falling through to `_names_the_door`
      rather than resolving was tried and refused: measured against the rule as
      it stands, 14 unreadable entries at 70 examined on a clean tree. It was 15
      at 71 before the resolution existed, and the entry that went is
      `sources.in_force` at `settings_store.py:439`, which the subject branch
      now answers before any fallthrough could reach it.
    * It follows one hop. A module re exporting another module's re export hands
      out nothing, and the call on it is silent rather than reported.
    * A computed door on a resolvable subject is silent. `getattr(helpers,
      "get_bool")(db, key)` and `helpers.__dict__["get_bool"](db, key)` are
      examined by nothing, where the same two written on `settings_store` are
      reported as unreadable: `_names_the_door` reads the store aliases and the
      bound names, not `subjects`. Widening it to `subjects` pulls directly
      against `_rebound_here`, which exists to take names out of that map, so it
      is a decision rather than a line and is not taken here.
    * `functools.partial(settings_store.get_bool, db)` is silent, and it was an
      offender until the binding started reading an expression's shape rather
      than walking it. The same walk made a name holding a reader's **result** a
      second offender for one read, `partial` is not an idiom in this tree, and a
      false offender on a clean tree is worse than a silent exotic spelling. The
      trade is here rather than nowhere, because a loss nobody wrote down is a
      loss nobody can reconsider.
    """

    def test_no_key_the_environment_can_pin_is_read_off_the_table(self):
        offenders, _, _ = _reads_of_a_pinned_key(_source_modules())
        assert not offenders, (
            "these read a key the environment can pin through a reader that "
            "cannot see it, so the settings screen and the routine that uses "
            f"the value disagree: {offenders}"
        )

    def test_every_key_a_reader_is_handed_can_be_named(self):
        """A call the pass cannot read is a hole, not a pass.

        Reported rather than skipped, because the evasion is free otherwise:
        put the key in a local and the rule above sees nothing.
        """
        _, unreadable, _ = _reads_of_a_pinned_key(_source_modules())
        assert not unreadable, (
            "the key these read cannot be named from the source, so no rule of "
            f"this shape can see them: {unreadable}"
        )

    @pytest.mark.parametrize("spelling", _UNFOLLOWABLE_SPELLINGS)
    def test_a_reader_reached_by_a_door_the_pass_cannot_follow_is_reported(
        self, spelling
    ):
        """Not dropped. Everything the loop walks past is free to be an evasion,
        and these three are the ones a critic seat reached the old rule by."""
        _, unreadable, examined = _planted(spelling)
        assert unreadable, spelling
        assert examined

    def test_a_call_on_a_subscript_that_reaches_no_reader_is_left_alone(self):
        """The other side of the arm above, and the reason it asks what the
        subject mentions. Eight calls in the corpus are a generic being
        instantiated, and reporting those would leave this class red on a tree
        with nothing wrong with it."""
        _, unreadable, examined = _planted(
            "import settings_store\nPage[BookOut](items=rows)\n"
        )
        assert not unreadable
        assert examined == 0

    def test_every_module_that_spells_a_reader_call_contributes_one(self):
        """The population, derived rather than stated.

        **This was `examined >= 40` against a live 56**, which is the shape this
        repository pays for by name: a stated bound stops guarding without ever
        failing. Breaking resolution for `mailer.py` alone left 48 examined
        calls and every arm green, and that module holds seven of the ten keys
        the environment can pin.

        So the floor is a symmetry between two instruments instead: a module
        whose text spells a qualified reader call has to contribute a call the
        syntax pass found.
        """
        modules = _source_modules()
        off_the_table, in_force = _keyed_readers(modules[_STORE])
        readers = off_the_table | in_force

        spelled = {
            path
            for path, source in modules.items()
            if _spells_a_reader_call(source, readers) or path == _STORE
        }
        contributed = {
            path
            for path, source in modules.items()
            if _reader_calls(path, source, readers, modules)
        }
        assert spelled - {_STORE}, (
            "the text instrument matched nothing but the module that defines "
            "the readers, so this symmetry is one instrument compared with "
            f"itself: {sorted(spelled)}"
        )
        assert not spelled - contributed, (
            "these spell a call this pass then found nothing in, so the rule "
            f"covers less of the tree than it reads: {sorted(spelled - contributed)}"
        )

    def test_the_reader_split_is_read_off_the_module(self):
        """The floor. A split that returned nothing would report no offender.

        It names two members and no more: one on each side, so a classifier
        that had collapsed into one set is visible. Which readers are in each
        set is the module's business and deliberately not asserted here.
        """
        off_the_table, in_force = _keyed_readers(_source_modules()[_STORE])
        assert "get_bool" in off_the_table, off_the_table
        assert "in_force" in in_force, in_force
        assert not off_the_table & in_force

    def test_a_reader_that_mentions_the_environment_without_answering_from_it_is_not_in_force(
        self,
    ):
        """The sharpest evasion of the round, and the one this split is for.

        A reader that calls `config.env_override` and throws the answer away
        reads exactly as it did before. Counting the mention moves it into the
        in force set, and a stored read of a pinned key through it then goes
        unreported: measured with `mailer` reading `MAIL_PORT` off the table,
        every arm of this class green.
        """
        store = _source_modules()[_STORE].replace(
            "    try:\n        value = int(get_raw(db, key).strip())",
            "    if config.env_override(key):\n"
            "        pass  # honoured in a later release\n"
            "    try:\n        value = int(get_raw(db, key).strip())",
            1,
        )
        # **The anchor has to have matched.** Left unmutated, `get_int` is off
        # the table and the planted read is already an offender, so both
        # assertions below pass with no mutation applied and this test retires
        # itself the day that body is refactored.
        assert store != _source_modules()[_STORE], "the mutation anchor went stale"

        off_the_table, _ = _keyed_readers(store)
        assert "get_int" in off_the_table

        offenders, _, _ = _planted(
            "import settings_store\n"
            "settings_store.get_int(db, SettingKey.MAIL_PORT, minimum=1, maximum=2)\n",
            store=store,
        )
        assert offenders, "a reader that ignores the environment is not an in force door"


    @pytest.mark.parametrize("spelling", _PLANTED_SPELLINGS)
    def test_a_read_of_a_pinnable_key_off_the_table_is_reported(self, spelling):
        """The diagonal, once per way of reaching the reader."""
        offenders, unreadable, _ = _planted(spelling.format(reader="get_bool"))
        assert offenders, f"not reported: {spelling}"
        assert not unreadable

    @pytest.mark.parametrize("spelling", _PLANTED_SPELLINGS)
    def test_the_same_read_through_the_in_force_door_is_not_reported(self, spelling):
        """The other half of the diagonal. Without it the rule is satisfied by
        a pass that reports every call it finds."""
        offenders, unreadable, examined = _planted(spelling.format(reader="bool_in_force"))
        assert not offenders, offenders
        assert not unreadable
        assert examined

    def test_a_key_the_environment_cannot_pin_is_left_alone(self):
        offenders, _, _ = _planted(
            "import settings_store\n"
            "settings_store.get_bool(db, SettingKey.LIBRARY_MODE)\n"
        )
        assert not offenders, offenders

    def test_a_key_held_in_a_local_is_reported_rather_than_skipped(self):
        _, unreadable, _ = _planted(
            "import settings_store\nsettings_store.get_bool(db, chosen)\n"
        )
        assert unreadable

    def test_a_module_that_wraps_a_read_in_a_keyed_helper_is_reported(self):
        """The plumbing skip is `settings_store`'s alone, and this is what says
        so. Widen it and any module opts out by taking a `SettingKey` and
        handing it down, which is the shape the skip exists for."""
        _, unreadable, _ = _planted(
            "import settings_store\n"
            "def read(db, key: SettingKey):\n"
            "    return settings_store.get_bool(db, key)\n"
        )
        assert unreadable

    def test_a_function_of_the_same_name_in_another_module_is_not_a_reader(self):
        """`sources.in_force` takes a plan and reads no setting. A pass matching
        the attribute name alone reports it, which is what binding the call to
        the import stops."""
        _, _, examined = _planted("import sources\nsources.in_force(plan, ready)\n")
        assert examined == 0

    @pytest.mark.parametrize("subject, spelling", _ATTRIBUTE_SPELLINGS)
    def test_a_reader_reached_as_an_attribute_on_an_importing_module_is_reported(
        self, subject, spelling
    ):
        """The spelling this resolution buys: a reader reached as an attribute
        on a module that imported it.

        **Not the last silent one.** The class docstring names every spelling
        that is still silent after it. **No count here**: one was claimed and
        was wrong, then a smaller one was claimed and was wrong the other way,
        and a number in this docstring goes stale the next time a residue opens
        or closes.

        Delete the subject clause in `_reader_calls` and this is what goes red:
        the call falls through to the same `continue` that keeps
        `sources.in_force` out, and a pinned key read off the table through a
        module that re exported the reader is reported by nothing.
        """
        offenders, unreadable, _ = _planted(
            spelling.format(reader="get_bool"),
            alongside={"helpers.py": subject.format(reader="get_bool")},
        )
        assert offenders, spelling
        assert not unreadable

    @pytest.mark.parametrize("subject, spelling", _ATTRIBUTE_SPELLINGS)
    def test_the_same_read_through_a_re_exported_in_force_door_is_not_reported(
        self, subject, spelling
    ):
        """The other half of that diagonal. Without it the resolution is
        satisfied by one that reports every attribute call it can resolve."""
        offenders, unreadable, examined = _planted(
            spelling.format(reader="bool_in_force"),
            alongside={"helpers.py": subject.format(reader="bool_in_force")},
        )
        assert not offenders, offenders
        assert not unreadable
        assert examined

    def test_a_module_that_defines_the_name_itself_is_not_a_reader(self):
        """`sources.in_force` with the subject in the corpus, which is the
        sharper half of the test above it.

        That one passes on a corpus holding no `sources.py` at all, so it says
        nothing about a resolution that resolves. This one plants the module, so
        the only thing keeping the call out is that `sources` defines `in_force`
        rather than binding it from `settings_store`.
        """
        _, _, examined = _planted(
            "import sources\nsources.in_force(plan, ready)\n",
            alongside={"sources.py": "def in_force(plan, ready):\n    return plan\n"},
        )
        assert examined == 0

    def test_a_module_that_binds_the_name_from_somewhere_else_is_not_a_reader(self):
        """The same refusal where the subject imported the name rather than
        defining it. A resolution asking only whether the subject binds the name
        reports this; one asking where it bound it from does not."""
        _, _, examined = _planted(
            "import helpers\nhelpers.get_bool(db, SettingKey.MAIL_USE_TLS)\n",
            alongside={"helpers.py": "from flags import get_bool\n"},
        )
        assert examined == 0

    @pytest.mark.parametrize(
        "opener",
        (
            "def send(db):\n    read = settings_store.get_bool\n    return read\n",
            "async def send(db):\n    read = settings_store.get_bool\n    return read\n",
            "class R:\n    read = settings_store.get_bool\n",
        ),
    )
    def test_a_reader_bound_inside_a_scope_of_its_own_is_not_an_attribute_on_that_module(
        self, opener
    ):
        """Why the cross module read stops at module scope.

        `helpers.read` does not exist: the binding is a local in `send` or an
        attribute on `R`, and the module hands out nothing by that name.
        Reading the subject the way this rule reads its own module would report
        a caller that cannot reach it.

        **One arm per member of `_ITS_OWN_SCOPE` that can hold a binding.** The
        `def` arm was the only one for a round, and dropping either of the other
        two from that tuple left every arm of this class green. `ast.Lambda` has
        no arm because it has no body a binding can sit in.
        """
        _, _, examined = _planted(
            "import helpers\nhelpers.read(db, SettingKey.MAIL_USE_TLS)\n",
            alongside={"helpers.py": "import settings_store\n" + opener},
        )
        assert examined == 0

    def test_a_subject_binding_only_for_a_type_checker_hands_out_nothing(self):
        """`if TYPE_CHECKING:` is written at module scope and does not run there.

        An attribute bound only for a type checker raises at run time, so a call
        on it reads no setting. The `try:` row of the diagonal is the same
        indent and the opposite answer, and the pair is what says the descent
        asks what runs rather than what is written.
        """
        _, unreadable, examined = _planted(
            "import helpers\nhelpers.get_bool(db, SettingKey.MAIL_USE_TLS)\n",
            alongside={
                "helpers.py": "if TYPE_CHECKING:\n"
                "    from settings_store import get_bool\n"
            },
        )
        assert not unreadable
        assert examined == 0

    def test_a_name_defined_only_for_a_type_checker_does_not_hide_a_re_export(self):
        """The same block read by the other caller, where the direction reverses.

        `defined` only ever suppresses a report, so widening it with a name that
        does not exist at run time hides exactly the case the unreadable label
        is for: a bare call that must have reached its reader from somewhere
        this module does not name.
        """
        _, unreadable, _ = _planted(
            "if TYPE_CHECKING:\n"
            "    def get_bool(db, key):\n"
            "        return False\n"
            "get_bool(db, SettingKey.MAIL_USE_TLS)\n"
        )
        assert unreadable

    @pytest.mark.parametrize(
        "shadow",
        (
            "def send(db, helpers):\n"
            "    return helpers.get_bool(db, SettingKey.MAIL_USE_TLS)\n",
            "def send(db):\n"
            "    helpers = Fake()\n"
            "    return helpers.get_bool(db, SettingKey.MAIL_USE_TLS)\n",
            "try:\n"
            "    helpers = Fake()\n"
            "except NameError:\n"
            "    pass\n"
            "helpers.get_bool(db, SettingKey.MAIL_USE_TLS)\n",
            # The generic clause rather than a `Name` or an `arg`: a `def`, a
            # `class`, an `except ... as` and a `TypeVar` all carry the name
            # they bind as a plain string, and removing that clause left every
            # other row of this table green.
            "def helpers():\n"
            "    return None\n"
            "helpers.get_bool(db, SettingKey.MAIL_USE_TLS)\n",
        ),
    )
    def test_a_name_this_module_also_binds_itself_is_not_the_module_it_imported(
        self, shadow
    ):
        """The caller side of the question the subject side already answered.

        `subjects` carries no scope analysis, so a parameter or a local called
        `helpers` resolved as the module `helpers` and its call was reported as
        a read of a pinned key. That is a red on a clean tree against a call
        that cannot reach the module, which is the shape that gets a guard
        argued away rather than fixed. The third arm is the one the module scope
        descent made reachable: a rebinding a level below `tree.body`.
        """
        _, unreadable, examined = _planted(
            "import helpers\n" + shadow,
            alongside={"helpers.py": "from settings_store import get_bool\n"},
        )
        assert not unreadable
        assert examined == 0

    def test_a_module_defining_a_readers_name_at_module_scope_is_not_a_re_export(self):
        """The same `tree.body` defect, on the half that decides a re export.

        A bare call to a reader's name is a re export only when this module
        neither imports the name from `settings_store` nor defines it. Reading
        `tree.body` for the second half missed a `def` a level below it, so a
        module holding its own `get_bool` was reported unreadable: red on a
        clean tree against code with nothing wrong with it, which is the
        direction `_rebound_here` exists for on the other side.
        """
        _, unreadable, _ = _planted(
            "try:\n"
            "    def get_bool(db, key):\n"
            "        return False\n"
            "except NameError:\n"
            "    pass\n"
            "get_bool(db, SettingKey.MAIL_USE_TLS)\n"
        )
        assert not unreadable, unreadable

    def test_the_store_naming_itself_reaches_its_own_readers(self):
        """The alias half of the store special case, which nothing else reaches.

        `settings_store.py` calls its own readers bare, so the name it binds for
        itself does no work on the tree as it stands: removing it left every arm
        of this class green. This is what stops it being free to delete, and it
        is the only arm that asks a verdict of the store rather than of a plant
        beside it.
        """
        store = _source_modules()[_STORE] + (
            "\n\ndef get_flag(db: Session, key: SettingKey) -> bool:\n"
            "    return settings_store.get_bool(db, SettingKey.MAIL_USE_TLS)\n"
        )
        offenders, _, _ = _reads_of_a_pinned_key({_STORE: store}, only=_STORE)
        assert offenders, "the store no longer reaches a reader through its own name"

    def test_a_re_export_of_a_re_export_is_not_followed(self):
        """The one hop bound, which nothing on a clean tree can see.

        No corpus module re exports a reader at all, so a two hop resolution
        and this one agree on every module in the tree: both give `([], [], 56)`.
        The nearest arm beside this one puts the second module outside the
        corpus, where one hop and two agree as well. This is the only plant
        where they differ.
        """
        _, unreadable, examined = _planted(
            "import helpers\nhelpers.get_bool(db, SettingKey.MAIL_USE_TLS)\n",
            alongside={
                "helpers.py": "from mid import get_bool\n",
                "mid.py": "from settings_store import get_bool\n",
            },
        )
        assert not unreadable
        assert examined == 0

    def test_a_subject_reached_by_a_relative_import_is_resolved_against_the_package(
        self,
    ):
        """The relative arm, which needs the reading module to be inside a
        package to say anything.

        At the top level `from . import helpers` and `import helpers` reach the
        same name, so the rows above pass whether the package is walked or
        ignored. Here the plant is in `routers/` and the subject is its sibling,
        which is the only shape where the two answers differ.
        """
        offenders, _, _ = _planted(
            "from . import helpers\nhelpers.get_bool(db, SettingKey.MAIL_USE_TLS)\n",
            alongside={"routers/helpers.py": "from settings_store import get_bool\n"},
            path="routers/planted.py",
        )
        assert offenders

    def test_a_subject_the_corpus_does_not_hold_is_left_alone(self):
        """The exclusion, asserted rather than described.

        Same source as the first row of the diagonal with the subject module
        taken out of the corpus. Nothing in the tree says what a module
        `_source_modules()` never returns hands out, so the call is silent, and
        that is the boundary this resolution stops at.
        """
        _, unreadable, examined = _planted(
            "import helpers\nhelpers.get_bool(db, SettingKey.MAIL_USE_TLS)\n"
        )
        assert not unreadable
        assert examined == 0

    def test_a_reader_added_later_is_classified_by_what_it_reaches(self):
        """The reason the split is derived. Both halves of a new type land
        where they belong with no edit to this file."""
        store = _source_modules()[_STORE] + (
            "\n\ndef get_float(db: Session, key: SettingKey) -> float:\n"
            "    return float(get_raw(db, key))\n"
            "\n\ndef float_in_force(db: Session, key: SettingKey) -> float:\n"
            "    return float(in_force(db, key))\n"
        )
        off_the_table, in_force = _keyed_readers(store)
        assert "get_float" in off_the_table
        assert "float_in_force" in in_force

        offenders, _, _ = _planted(
            "import settings_store\n"
            "settings_store.get_float(db, SettingKey.MAIL_PORT)\n",
            store=store,
        )
        assert offenders, "a reader added later is not covered by the rule"

    def test_a_writer_is_not_a_reader(self):
        """`set_value` touches the same table and hands nothing back. Counting
        it would report every write of a pinned key, which `_refuse_if_pinned`
        answers with a 409 rather than this rule."""
        off_the_table, in_force = _keyed_readers(_source_modules()[_STORE])
        assert "set_value" not in off_the_table | in_force
        assert "set_json" not in off_the_table | in_force
