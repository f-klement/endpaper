"""A catalogue login is sealed, bound to one origin, and openable by one key.

**The guards worth attacking here are the three that fail silently if they are
wrong**, and each has a class of its own: an envelope that opens under a key
that did not write it, a credential that goes to a host it was not set for, and
a recovery phrase whose words reach a message. The rest of this file is
ordinary round trips.
"""

import dataclasses

import httpx
import keyring
import keyring.backend
import keyring.errors
import pytest

import credentials
from enums import CatalogueSource
from models import CatalogueCredential


class _InMemoryKeyring(keyring.backend.KeyringBackend):
    """A keychain that exists and forgets everything at the end of the test.

    **Installed with `keyring.set_keyring` rather than by patching
    `credentials`**, because the thing under test is that this application asks
    the keychain properly: a double in front of our own function would test the
    double. `conftest.py` points the library at its failing backend for every
    other test, so nothing here can reach a real one.
    """

    priority = 1

    def __init__(self) -> None:
        self._held: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._held.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._held[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self._held:
            raise keyring.errors.PasswordDeleteError("nothing stored")
        del self._held[(service, username)]


@pytest.fixture
def keychain():
    """A working keychain for the length of one test, then the failing one back."""
    previous = keyring.get_keyring()
    fake = _InMemoryKeyring()
    keyring.set_keyring(fake)
    yield fake
    keyring.set_keyring(previous)


@pytest.fixture
def key() -> bytes:
    """32 bytes of key material, without configuring anything."""
    return credentials.phrase_to_key(credentials.generate_phrase())


class TestAKeyIsNeverInvented:
    """No default, in any artefact. A published image ships no key."""

    def test_a_clean_deployment_has_no_key(self):
        assert credentials.key_material() is None

    def test_no_source_answers_on_a_clean_deployment(self):
        assert [source.name for source in credentials.KEY_SOURCES if source.read()] == []

    def test_and_nothing_reports_a_location(self):
        assert credentials.key_location() == ""

    def test_requiring_one_says_what_to_do_rather_than_inventing_one(self):
        with pytest.raises(credentials.NoKeyConfigured) as refusal:
            credentials.require_key()
        assert "CREDENTIAL_ENCRYPTION_KEY" in str(refusal.value)


class TestARecoveryPhraseIsTheOnlyFormOfAKey:
    def test_a_generated_phrase_is_twenty_four_words(self):
        assert len(credentials.generate_phrase().split()) == credentials.PHRASE_WORDS

    def test_a_phrase_carries_a_whole_key(self, key: bytes):
        assert len(key) == credentials.KEY_BYTES

    def test_the_round_trip_is_exact(self):
        phrase = credentials.generate_phrase()
        assert credentials.key_to_phrase(credentials.phrase_to_key(phrase)) == phrase

    def test_typing_it_back_reproduces_the_same_key_generation(self):
        phrase = credentials.generate_phrase()
        first = credentials.generation_of_key(credentials.phrase_to_key(phrase))
        typed = credentials.phrase_to_key("  " + phrase.upper().replace(" ", "   ") + "\n")
        assert credentials.generation_of_key(typed) == first

    def test_capitals_and_repeated_spaces_are_absorbed(self):
        phrase = credentials.generate_phrase()
        assert credentials.normalise_phrase(f"  {phrase.title()}   ") == phrase

    def test_only_a_whole_key_can_be_written_as_a_phrase(self):
        with pytest.raises(credentials.KeyConfigurationError):
            credentials.key_to_phrase(b"too short")


class TestAMistypedPhraseFailsAtInput:
    """The checksum, and it is the reason the encoding is a standard one.

    Without it a wrong word is a **different key**, which opens nothing and says
    nothing. That is the same silent wrongness the generation tag exists to
    prevent, arriving by a second route.
    """

    def test_a_short_phrase_is_reported_as_short_rather_than_as_a_checksum_failure(self):
        half = " ".join(credentials.generate_phrase().split()[:12])
        with pytest.raises(credentials.BadRecoveryPhrase) as refusal:
            credentials.phrase_to_key(half)
        assert "24 words" in str(refusal.value)
        assert "12" in str(refusal.value)

    def test_a_word_that_is_not_in_the_list_is_refused(self):
        words = credentials.generate_phrase().split()
        with pytest.raises(credentials.BadRecoveryPhrase) as refusal:
            credentials.phrase_to_key(" ".join([*words[:-1], "endpaper"]))
        assert "Word 24" in str(refusal.value)

    def test_and_the_refusal_does_not_repeat_the_word(self):
        """The phrase **is** the key, so a message quoting a word of it is a leak."""
        words = credentials.generate_phrase().split()
        with pytest.raises(credentials.BadRecoveryPhrase) as refusal:
            credentials.phrase_to_key(" ".join([*words[:-1], "endpaper"]))
        assert "endpaper" not in str(refusal.value)

    def test_two_swapped_words_fail_the_checksum(self):
        words = credentials.generate_phrase().split()
        swapped = [*words[:22], words[23], words[22]]
        with pytest.raises(credentials.BadRecoveryPhrase) as refusal:
            credentials.phrase_to_key(" ".join(swapped))
        # The whole message, not a substring: a fixed string cannot carry any
        # part of the input, which is a stronger guarantee than any assertion
        # about which words are absent from it.
        assert str(refusal.value) == (
            "The recovery phrase failed its checksum, so at least one word is "
            "wrong or two are swapped. Check it against what you wrote down."
        )


class TestOneKeyInTwoStoresIsFineAndTwoKeysIsNot:
    def test_the_environment_alone_is_read(self, monkeypatch):
        phrase = credentials.generate_phrase()
        monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", phrase)
        assert credentials.key_material() == credentials.phrase_to_key(phrase)
        assert credentials.key_location() == "env"

    def test_the_same_key_in_two_stores_is_accepted(self, db, monkeypatch):
        phrase, _ = credentials.generate_key(db)
        monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", phrase)
        assert credentials.key_material() == credentials.phrase_to_key(phrase)

    def test_two_different_keys_are_refused_naming_both_stores(self, db, monkeypatch):
        credentials.generate_key(db)
        monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", credentials.generate_phrase())
        with pytest.raises(credentials.KeyConfigurationError) as refusal:
            credentials.key_material()
        assert "CREDENTIAL_ENCRYPTION_KEY" in str(refusal.value)
        assert "the key file" in str(refusal.value)

    def test_a_mangled_phrase_in_any_store_is_reported_against_that_store(self, monkeypatch):
        monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "not a recovery phrase")
        with pytest.raises(credentials.KeyConfigurationError) as refusal:
            credentials.key_material()
        assert str(refusal.value).startswith("CREDENTIAL_ENCRYPTION_KEY:")


class TestAKeyIsKeptWhereTheMachineCanKeepIt:
    def test_a_container_with_no_keychain_gets_a_file(self, db):
        _, where = credentials.generate_key(db)
        assert where == "file"
        assert credentials.key_file().exists()

    def test_the_file_is_readable_only_by_its_owner(self, db):
        credentials.generate_key(db)
        assert credentials.key_file().stat().st_mode & 0o777 == 0o600

    def test_a_machine_with_a_keychain_uses_it_instead(self, db, keychain):
        _, where = credentials.generate_key(db)
        assert where == "keychain"
        assert not credentials.key_file().exists()

    def test_typing_a_phrase_back_in_leaves_exactly_one_copy(self, keychain):
        """Otherwise the old key sits beside the new one and every read is refused."""
        credentials.store_key(credentials.generate_phrase())  # into the keychain
        keyring.set_keyring(keyring.backends.fail.Keyring())
        credentials.store_key(credentials.generate_phrase())  # now into the file
        keyring.set_keyring(keychain)
        replacement = credentials.generate_phrase()
        credentials.store_key(replacement)
        assert credentials.key_material() == credentials.phrase_to_key(replacement)
        assert not credentials.key_file().exists()

    def test_a_pinned_environment_key_refuses_to_be_worked_around(self, monkeypatch):
        monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", credentials.generate_phrase())
        with pytest.raises(credentials.KeyConfigurationError) as refusal:
            credentials.store_key(credentials.generate_phrase())
        assert "CREDENTIAL_ENCRYPTION_KEY" in str(refusal.value)

    def test_a_named_key_file_is_read_where_one_is_named(self, monkeypatch, tmp_path):
        phrase = credentials.generate_phrase()
        named = tmp_path / "somewhere" / "key"
        named.parent.mkdir()
        named.write_text(phrase)
        monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY_FILE", str(named))
        assert credentials.key_material() == credentials.phrase_to_key(phrase)


class TestAKeyIsShownOnceAndNeverAgain:
    """Enforced by the server rather than promised by the browser."""

    def test_the_first_call_hands_the_phrase_over(self, db):
        phrase, _ = credentials.generate_key(db)
        assert len(phrase.split()) == credentials.PHRASE_WORDS

    def test_a_second_call_refuses_rather_than_re_displaying_it(self, db):
        credentials.generate_key(db)
        with pytest.raises(credentials.KeyConfigurationError) as refusal:
            credentials.generate_key(db)
        assert "cannot be shown again" in str(refusal.value)


class TestAnEnvelopeRecordsWhichKeyWroteIt:
    def test_the_generation_can_be_read_without_any_key(self, key: bytes):
        envelope = credentials.seal(key, "bne", "alice:hunter2")
        assert credentials.generation_of(envelope) == credentials.generation_of_key(key)

    def test_a_wrong_key_says_so_rather_than_failing_like_a_damaged_row(self, key: bytes):
        envelope = credentials.seal(key, "bne", "alice:hunter2")
        other = credentials.phrase_to_key(credentials.generate_phrase())
        with pytest.raises(credentials.WrongKeyGeneration):
            credentials.unseal(other, "bne", envelope)

    def test_the_tag_cannot_be_rewritten_to_a_second_key(self, key: bytes):
        """It is inside the authenticated data as well as in the text."""
        envelope = credentials.seal(key, "bne", "alice:hunter2")
        other = credentials.phrase_to_key(credentials.generate_phrase())
        version, _, nonce, sealed = envelope.split(".")
        forged = ".".join((version, credentials.generation_of_key(other), nonce, sealed))
        with pytest.raises(credentials.UnreadableCredential):
            credentials.unseal(other, "bne", forged)

    def test_something_that_is_not_an_envelope_reports_no_generation(self):
        assert credentials.generation_of("hunter2") == ""

    def test_and_is_refused_rather_than_parsed(self, key: bytes):
        with pytest.raises(credentials.UnreadableCredential):
            credentials.unseal(key, "bne", "hunter2")


class TestAnEnvelopeIsBoundToItsSourceAndItsKind:
    """The additional authenticated data, and it is what distinguishes the kinds.

    A ciphertext lifted onto another row by a hand edited archive or a stray
    `UPDATE` fails authentication rather than being sent to a host it was never
    set for.
    """

    def test_a_credential_moved_to_another_source_does_not_open(self, key: bytes):
        envelope = credentials.seal(key, "bne", "alice:hunter2")
        with pytest.raises(credentials.UnreadableCredential):
            credentials.unseal(key, "dnb", envelope)

    def test_it_opens_on_the_source_it_was_written_for(self, key: bytes):
        envelope = credentials.seal(key, "bne", "alice:hunter2")
        assert credentials.unseal(key, "bne", envelope) == "alice:hunter2"

    def test_the_purpose_names_the_kind_and_not_only_the_subject(self):
        assert credentials._purpose("bne") == "endpaper/v1/catalogue-credential/bne"


class TestACredentialNeverLeavesTheOriginItWasSetFor:
    """A property of the secret, so it holds even where the transport does not.

    `fetch.py` refuses a hop that leaves the host as well, and the two are not
    one guard: a redirect leaking a page is an information leak, and a redirect
    carrying an `Authorization` header off host is account theft.
    """

    @pytest.fixture
    def credential(self) -> credentials.Credential:
        origin = credentials.origin_of("https://catalogue.example/sru")
        return credentials.Credential(origin, "alice", "hunter2")

    def test_it_goes_to_its_own_origin(self, credential):
        assert "Authorization" in credential.header_for("https://catalogue.example/sru?q=1")

    def test_an_implicit_and_an_explicit_default_port_are_one_origin(self, credential):
        assert credential.header_for("https://catalogue.example:443/sru")

    def test_the_host_is_compared_without_case(self, credential):
        assert credential.header_for("https://CATALOGUE.EXAMPLE/sru")

    def test_it_does_not_go_to_another_host(self, credential):
        assert credential.header_for("https://evil.test/sru") == {}

    def test_a_host_hidden_in_the_userinfo_does_not_fool_it(self, credential):
        """`https://catalogue.example@evil.test/` reaches evil.test."""
        assert credential.header_for("https://catalogue.example@evil.test/sru") == {}

    def test_it_does_not_survive_a_downgrade_to_plaintext(self, credential):
        assert credential.header_for("http://catalogue.example/sru") == {}

    def test_it_does_not_go_to_another_port(self, credential):
        assert credential.header_for("https://catalogue.example:8443/sru") == {}

    @pytest.mark.parametrize("port", ["8_080", "99999", "65536", "-1"])
    def test_nor_to_a_port_only_one_url_parser_understands(self, credential, port):
        """The arm this guard's own first test picked around.

        `:8443` is a port every parser reads the same way, so it proved nothing
        about the case that mattered. `urlsplit` **raises** on `8_080` because
        `"8_080".isdigit()` is False, and `httpx.URL`, which is what actually
        makes the request, reads it as 8080. The first version of `origin_of`
        caught that `ValueError` and filled in the scheme default, so a
        credential bound to `:443` went to port 8080.
        """
        assert credential.header_for(f"https://catalogue.example:{port}/sru") == {}

    def test_the_parser_here_is_the_parser_that_makes_the_request(self):
        """Stated as a test, because a second parser is a hole by construction."""
        assert credentials.origin_of("https://a.test:8_080/x") == "https://a.test:8080"
        assert httpx.URL("https://a.test:8_080/x").port == 8080

    def test_an_address_that_cannot_be_parsed_binds_nothing(self):
        assert credentials.origin_of("https://") == ""
        assert credentials.origin_of("not a url") == ""

    def test_and_an_unbindable_credential_sends_nothing(self):
        assert credentials.Credential("", "alice", "hunter2").header_for(
            "https://catalogue.example/sru"
        ) == {}

    def test_a_url_with_no_host_gets_nothing(self, credential):
        assert credential.header_for("file:///etc/passwd") == {}

    def test_the_header_is_basic_and_carries_both_halves(self, credential):
        header = credential.header_for("https://catalogue.example/sru")
        assert header["Authorization"] == "Basic YWxpY2U6aHVudGVyMg=="


class TestACredentialIsNeverRendered:
    """One `logger.exception` over a frozen dataclass prints every field."""

    def test_the_repr_carries_the_origin_and_neither_half(self):
        credential = credentials.Credential("https://catalogue.example:443", "alice", "hunter2")
        assert "alice" not in repr(credential)
        assert "hunter2" not in repr(credential)
        assert "catalogue.example" in repr(credential)

    def test_and_neither_does_the_string(self):
        credential = credentials.Credential("https://catalogue.example:443", "alice", "hunter2")
        assert "hunter2" not in str(credential)

    def test_nor_does_the_key_state_carrying_the_key_itself(self, key):
        """The stronger of the two, because these bytes open every credential.

        `key_to_phrase` turns them straight back into the words, so a rendering
        discloses the key rather than one login, and a `KeyState` is bound in a
        frame on the member request path.
        """
        state = credentials.KeyState(key)
        # **The rendering does not depend on the key, which is the claim, and
        # naming an encoding is not.** Both critic seats measured an arm that
        # named one, in opposite directions and each blind to the other's
        # mutation: against a field renamed with its flag dropped, so the key
        # prints in full, an arm naming the field passes; against a repr
        # rendering the key as hex, an arm naming the bytes passes.
        #
        # **Three arms over a closed set rather than an enumeration of an open
        # one.** `repr`, `str` and `format` are every rendering protocol Python
        # has, and each falls back to the one before, so on a class overriding
        # none of them the third alone would answer. **That is a property of
        # this class today and not of the protocols**, which is why all three
        # are here: an override of one is invisible to the other two, so a
        # `__str__` that leaks under a `__format__` that does not is caught by
        # the second arm alone. An f-string is how a log line is written.
        assert repr(state) == repr(credentials.KeyState(None))
        assert str(state) == str(credentials.KeyState(None))
        assert f"{state}" == f"{credentials.KeyState(None)}"
        # The direct statement of what must not appear, beside the arm that
        # does the guarding rather than in place of it.
        assert repr(key) not in repr(state)
        assert credentials.key_to_phrase(key) not in repr(state)
        # The other field still prints, or the refusal a screen reports would
        # have gone with it.
        assert "stores disagree" in repr(credentials.KeyState(None, "stores disagree"))


class TestAnOperatorCanWithholdTheFeatureEntirely:
    """The recipe `docs/security.md` publishes, tested rather than described.

    **It is operator guidance in a published document, which is why it is
    tested at all.** A reader acting on that paragraph is deciding whether third
    party accounts are safe on somebody else's host, and the whole recipe rests
    on one `continue` in `store_key` and on `can_generate`'s expression in the
    settings router. Untested, a refactor of either republishes a false recipe
    with a green suite.

    **This class owns the `store_key` half only.** The screen's half is
    `tests/routers/test_settings.py::TestTheScreenStopsOfferingAKeyThereIsNowhereToPut`,
    which asserts `can_generate` on the response body. It belongs there and not
    here because recomputing the router's expression is the expression testing
    itself: `can_generate=True` written into the router would leave such a test
    green while the published sentence became false.

    **The off arm turns on the directory rather than the file's mode, and that
    is not a detail.** Unwritability is what `can_generate` reads, and an absent
    directory is the mechanism that achieves it at any uid: `_file_is_writable`
    asks `parent.is_dir()` before it reaches `os.access`. A read only mode does
    not, and this suite is where that shows, because it runs as root and
    `os.access` answers True there for a 0400 file.
    """

    def test_a_key_file_in_a_directory_that_does_not_exist_turns_it_off(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)
        monkeypatch.setenv(
            "CREDENTIAL_ENCRYPTION_KEY_FILE", str(tmp_path / "absent" / "key")
        )

        assert credentials.key_material() is None
        with pytest.raises(credentials.KeyConfigurationError) as refusal:
            credentials.store_key(credentials.generate_phrase())
        assert "nowhere on this machine" in str(refusal.value)

    def test_but_a_directory_that_exists_leaves_it_on(self, tmp_path, monkeypatch):
        """The arm that makes the one above evidence rather than a tautology.

        It is also why the recipe names a directory that does not exist rather
        than an absent file: the file is absent in both, and only this one has a
        directory to make it in.
        """
        monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)
        monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY_FILE", str(tmp_path / "key"))

        assert credentials.store_key(credentials.generate_phrase()) == "file"
        assert credentials.key_material() is not None

    def test_and_a_read_only_file_holding_a_key_is_not_the_same_thing(
        self, tmp_path, monkeypatch
    ):
        """The trap the same paragraph warns about, which is a mounted secret.

        A Docker secret and a Kubernetes Secret both arrive as a read only file,
        which is what `_from_file` was written for. The key is then in force for
        every request, so an operator who reads the recipe as "make it
        unwritable" has switched nothing off.

        **What is asserted is that the key is in force, and the mode is not set
        at all**, because that is the half that is honest here: this suite runs
        as root, where `os.access` answers True for a file nobody else could
        write, so a `can_generate` assertion under a 0400 file would measure the
        uid, and one under a stubbed probe would measure the stub. The two tests
        above carry the writability arm, on the condition that is root proof.
        """
        phrase = credentials.generate_phrase()
        mounted = tmp_path / "key"
        mounted.write_text(phrase + "\n", encoding="utf-8")
        monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)
        monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY_FILE", str(mounted))

        assert credentials.key_material() == credentials.phrase_to_key(phrase)


class TestTheStoreSealsWhatItIsGiven:
    def test_a_credential_round_trips(self, db):
        credentials.generate_key(db)
        credentials.put(db, "bne", "alice", "hunter2")
        assert credentials.stored(db, "bne") == ("alice", "hunter2")

    def test_a_password_containing_colons_survives(self, db):
        credentials.generate_key(db)
        credentials.put(db, "bne", "alice", "a:b:c")
        assert credentials.stored(db, "bne") == ("alice", "a:b:c")

    def test_nothing_readable_reaches_the_row(self, db):
        credentials.generate_key(db)
        credentials.put(db, "bne", "alice", "hunter2")
        row = db.get(CatalogueCredential, "bne")
        assert "alice" not in row.envelope
        assert "hunter2" not in row.envelope
        assert row.envelope.startswith("v1.")

    def test_a_second_write_replaces_the_first(self, db):
        credentials.generate_key(db)
        credentials.put(db, "bne", "alice", "hunter2")
        credentials.put(db, "bne", "bob", "correcthorse")
        assert credentials.stored(db, "bne") == ("bob", "correcthorse")

    def test_a_username_with_a_colon_is_refused(self, db):
        credentials.generate_key(db)
        with pytest.raises(credentials.CredentialError):
            credentials.put(db, "bne", "alice:smith", "hunter2")

    def test_an_empty_half_is_refused(self, db):
        credentials.generate_key(db)
        with pytest.raises(credentials.CredentialError):
            credentials.put(db, "bne", "alice", "")

    def test_storing_one_without_a_key_is_refused(self, db):
        with pytest.raises(credentials.NoKeyConfigured):
            credentials.put(db, "bne", "alice", "hunter2")

    def test_forgetting_one_needs_no_key(self, db):
        """The credential nobody can read is the one somebody most wants gone."""
        credentials.generate_key(db)
        credentials.put(db, "bne", "alice", "hunter2")
        credentials.store_key(credentials.generate_phrase())
        assert credentials.forget(db, "bne") is True
        assert credentials.stored_envelope(db, "bne") == ""

    def test_forgetting_nothing_is_not_an_error(self, db):
        assert credentials.forget(db, "bne") is False


class TestTheScreenIsToldWhetherOneIsUsableRatherThanOnlyWhetherOneExists:
    def test_nothing_stored(self, db):
        held = credentials.view(db, "bne")
        assert (held.has_credential, held.unreadable) == (False, False)

    def test_one_stored_and_readable(self, db):
        credentials.generate_key(db)
        credentials.put(db, "bne", "alice", "hunter2")
        held = credentials.view(db, "bne")
        assert (held.has_credential, held.unreadable, held.username) == (
            True,
            False,
            "alice",
        )
        assert credentials.is_held(db, "bne") is True

    def test_one_stored_under_a_key_that_is_gone(self, db):
        credentials.generate_key(db)
        credentials.put(db, "bne", "alice", "hunter2")
        credentials.store_key(credentials.generate_phrase())
        held = credentials.view(db, "bne")
        assert (held.has_credential, held.unreadable, held.username) == (True, True, "")
        assert credentials.is_held(db, "bne") is False

    def test_one_stored_with_no_key_configured_at_all(self, db):
        credentials.generate_key(db)
        credentials.put(db, "bne", "alice", "hunter2")
        credentials.key_file().unlink()
        held = credentials.view(db, "bne")
        assert (held.has_credential, held.unreadable) == (True, True)


class TestADeploymentMayPinOneInstead:
    def test_a_pinned_credential_wins_over_the_stored_one(self, db, monkeypatch):
        credentials.generate_key(db)
        credentials.put(db, "bne", "alice", "hunter2")
        monkeypatch.setenv("CATALOGUE_CREDENTIAL_BNE", "bob:correcthorse")
        request = credentials.for_request(db, "bne", "https://catalogue.example/sru")
        assert request is not None
        assert (request.username, request.password) == ("bob", "correcthorse")

    def test_the_variable_is_named_after_the_source(self):
        assert credentials.env_variable_name("bne") == "CATALOGUE_CREDENTIAL_BNE"

    def test_where_it_comes_from_is_reportable_and_the_value_is_not(self, monkeypatch):
        monkeypatch.setenv("CATALOGUE_CREDENTIAL_BNE", "bob:correcthorse")
        assert credentials.is_from_env("bne") is True

    def test_a_password_containing_colons_survives_the_split(self, monkeypatch):
        monkeypatch.setenv("CATALOGUE_CREDENTIAL_BNE", "bob:a:b:c")
        assert credentials.from_env("bne") == ("bob", "a:b:c")

    def test_an_unset_variable_names_nothing(self):
        assert credentials.from_env("bne") is None


class TestAnUnreadableCredentialIsNotSentRatherThanRaising:
    """A rotated key must cost a source, never a 500 on a member's search."""

    def test_nothing_stored_answers_none(self, db):
        assert credentials.for_request(db, "bne", "https://catalogue.example") is None

    def test_a_rotated_key_answers_none(self, db):
        credentials.generate_key(db)
        credentials.put(db, "bne", "alice", "hunter2")
        credentials.store_key(credentials.generate_phrase())
        assert credentials.for_request(db, "bne", "https://catalogue.example") is None

    def test_a_readable_one_is_bound_to_the_target_address(self, db):
        credentials.generate_key(db)
        credentials.put(db, "bne", "alice", "hunter2")
        request = credentials.for_request(db, "bne", "https://catalogue.example/sru")
        assert request is not None
        assert request.origin == "https://catalogue.example:443"


class TestThePurposeStringNamesExactlyOneSource:
    """What stops an envelope opening on a row it was not written for."""

    def test_the_purpose_string_differs_per_source(self):
        purposes = {credentials._purpose(source.value) for source in CatalogueSource}
        assert len(purposes) == len(list(CatalogueSource))


class TestAKeyIsNotMintedOverLoginsItCannotOpen:
    """The restore onto a new machine, which is what the phrase exists for.

    The archive carries the sealed rows and never the key. Minting a second key
    there reports every restored login as unreadable and leaves the phrase in
    somebody's drawer looking wrong, when it is the one thing that would have
    worked.
    """

    def test_making_a_key_is_refused_while_sealed_logins_exist(self, db):
        credentials.generate_key(db)
        credentials.put(db, "bne", "alice", "hunter2")
        credentials.forget_key()
        with pytest.raises(credentials.KeyConfigurationError) as refusal:
            credentials.generate_key(db)
        assert "recovery phrase" in str(refusal.value)

    def test_the_phrase_opens_them_again(self, db):
        phrase, _ = credentials.generate_key(db)
        credentials.put(db, "bne", "alice", "hunter2")
        credentials.forget_key()
        credentials.store_key(phrase)
        assert credentials.stored(db, "bne") == ("alice", "hunter2")

    def test_removing_the_logins_clears_the_way_for_a_new_key(self, db):
        credentials.generate_key(db)
        credentials.put(db, "bne", "alice", "hunter2")
        credentials.forget_key()
        credentials.forget(db, "bne")
        assert len(credentials.generate_key(db)[0].split()) == 24


class TestThereIsAWayBackFromNotWritingTheWordsDown:
    def test_the_key_can_be_discarded(self, db):
        credentials.generate_key(db)
        assert credentials.forget_key() == 1
        assert credentials.key_material() is None

    def test_and_a_new_one_made_when_nothing_was_sealed_with_it(self, db):
        credentials.generate_key(db)
        credentials.forget_key()
        assert len(credentials.generate_key(db)[0].split()) == 24

    def test_a_pinned_key_is_refused_rather_than_pretended_away(self, monkeypatch):
        monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", credentials.generate_phrase())
        with pytest.raises(credentials.KeyConfigurationError):
            credentials.forget_key()

    def test_discarding_nothing_clears_nothing(self):
        assert credentials.forget_key() == 0


class TestTheKeyFileIsWrittenSafelyOrNotAtAll:
    def test_a_symlink_at_the_path_is_refused_rather_than_followed(self, db, tmp_path):
        """`DATA_DIR` is not this application's alone on every deployment."""
        elsewhere = tmp_path / "somebody-elses-file"
        elsewhere.write_text("untouched")
        credentials.key_file().symlink_to(elsewhere)
        with pytest.raises(credentials.KeyConfigurationError):
            credentials.store_key(credentials.generate_phrase())
        assert elsewhere.read_text() == "untouched"

    def test_a_file_that_already_existed_wide_open_ends_narrow(self, db):
        """The window itself is not observable from a test; the outcome is.

        `O_CREAT` applies its mode only when it creates, so the phrase was
        written into a pre-existing 0644 file and narrowed afterwards. The fix
        is `fchmod` on the descriptor before the write, and what a test can see
        is that the mode is right at the end whichever path was taken.
        """
        path = credentials.key_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("old")
        path.chmod(0o644)
        credentials.store_key(credentials.generate_phrase())
        assert path.stat().st_mode & 0o777 == 0o600

    def test_a_place_no_file_can_go_is_reported_rather_than_raising_an_oserror(
        self, monkeypatch, tmp_path
    ):
        """A parent that is a file, rather than a directory mode 0500.

        The suite runs as root in its container, where `os.access` answers True
        for a directory nobody else could write, so a mode based case would pass
        for the wrong reason. A regular file is not a directory for any uid.
        """
        blocked = tmp_path / "not-a-directory"
        blocked.write_text("")
        monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY_FILE", str(blocked / "key"))
        assert credentials.KEY_SOURCES[2].available() is False
        with pytest.raises(credentials.KeyConfigurationError):
            credentials.store_key(credentials.generate_phrase())


class TestAPinnedCredentialThatIsSetAndUnusableIsReported:
    """Silently ignoring it offered an edit on a screen and used the stored one."""

    @pytest.mark.parametrize("value", ["bob", "bob:", ":hunter2", ":"])
    def test_a_value_that_is_not_a_credential_raises(self, monkeypatch, value):
        monkeypatch.setenv("CATALOGUE_CREDENTIAL_BNE", value)
        with pytest.raises(credentials.CredentialError):
            credentials.from_env("bne")

    @pytest.mark.parametrize("value", ["bob", "bob:", ":hunter2"])
    def test_and_the_deployment_still_counts_as_having_pinned_it(
        self, monkeypatch, value
    ):
        monkeypatch.setenv("CATALOGUE_CREDENTIAL_BNE", value)
        assert credentials.is_from_env("bne") is True

    def test_the_screen_is_told_it_is_pinned_and_unusable(self, db, monkeypatch):
        monkeypatch.setenv("CATALOGUE_CREDENTIAL_BNE", "bob:")
        held = credentials.view(db, "bne")
        assert (held.has_credential, held.from_env, held.unreadable) == (True, True, True)

    def test_and_nothing_is_sent(self, db, monkeypatch):
        monkeypatch.setenv("CATALOGUE_CREDENTIAL_BNE", "bob:")
        assert credentials.for_request(db, "bne", "https://a.test") is None


class TestTheKeyIsResolvedOncePerCaller:
    def test_a_state_carries_the_key_rather_than_the_source_being_re_read(self, db):
        """Observable rather than counted: the key is removed between the two calls.

        A call count would have needed the frozen `KeySource` instrumented. This
        asks the object what it does instead: with the state, the login still
        opens after the key file is gone, because the state holds the material;
        without it, the same call has to go back to a source that no longer
        answers.
        """
        credentials.generate_key(db)
        credentials.put(db, "bne", "alice", "hunter2")
        state = credentials.key_state()
        credentials.key_file().unlink()
        assert credentials.view(db, "bne", state).username == "alice"
        assert credentials.view(db, "bne").unreadable is True

    def test_a_configuration_problem_is_a_sentence_rather_than_a_raise(
        self, db, monkeypatch
    ):
        credentials.generate_key(db)
        monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", credentials.generate_phrase())
        state = credentials.key_state()
        assert state.material is None
        assert "Different encryption keys" in state.problem


def _carries_a_sealed_login(source: CatalogueSource) -> bool:
    """Whether a request to this source would actually carry a sealed login.

    **Asks `metadata.carries_a_credential` rather than spelling the rule again.**
    It was spelled again, and that was a defect of exactly the kind this class
    guards: `routers/books.py` skips the rows the rule rejects, so a second copy
    here means the day a transport starts carrying a login the red test below
    demands an edit to *this* copy, which greens the suite while the router goes
    on skipping the row and the request goes on unauthenticated.

    A module level function rather than a line inside the roster check, so the
    rule can be put to a row directly. That is the only way either verdict is
    ever observed while the set the check reads is empty.
    """
    import metadata
    import targets

    return metadata.carries_a_credential(targets.SEEDED[source])


class TestASealedLoginNeedsATransportThatCarriesIt:
    """The residual of #209, which threaded a login down the SRU door only.

    `routers/books.py` resolves a login per source and `metadata` passes it to
    `fetch.get_once`, so the gap this class was opened for is closed and
    `test_metadata.py::TestACatalogueLoginReachesTheRequestItWasStoredFor` is the
    send that proves it. What is left is the door a login does **not** go
    through: a row declaring `Capability.NEEDS_A_CREDENTIAL` whose secret is a
    sealed login and whose transport is bespoke would be resolved by the router
    and dropped by `metadata._lookup_one`, silently, exactly as before.

    **It cannot be refused in `metadata.resolve`**, which is where a row naming a
    capability nothing can serve is turned away at boot. Which store a source's
    secret lives in is `settings_store._SECRET_IS_A_SETTINGS_ROW`, and #210 is
    open to make it a capability on the row. Until it is, `resolve` cannot tell a
    sealed login from an API key and this is the tripwire instead.

    **The weakness the earlier version carried is gone.** It asserted a
    signature, which a door accepting the argument and dropping it satisfied,
    and its body never executed because the set it reads is empty. The rule is a
    function now, so it is exercised against a target the roster has not got as
    well as against the roster.
    """

    def test_a_bespoke_row_is_reported_as_carrying_nothing(self):
        """The arm that runs today, and the reason the rule is not inline.

        Google Books is the roster's bespoke credentialled row. It is fine
        because its secret is a settings row rather than a sealed login, which
        is precisely the distinction this file cannot see and #210 exists for.
        """
        assert not _carries_a_sealed_login(CatalogueSource.GOOGLE_BOOKS)

    def test_an_sru_row_is_reported_as_carrying_one(self):
        """The other end of the diagonal, or the arm above passes on everything."""
        assert _carries_a_sealed_login(CatalogueSource.DNB)

    def test_every_source_needing_a_sealed_login_is_on_such_a_transport(self):
        import settings_store
        import sources

        sealed = sources.NEEDS_A_KEY - settings_store._SECRET_IS_A_SETTINGS_ROW
        if not sealed:
            pytest.skip("no roster source needs a sealed login yet")
        stranded = sorted(
            source.value for source in sealed if not _carries_a_sealed_login(source)
        )
        assert not stranded, (
            f"{stranded} need a sealed login on a transport that sends none. "
            "See #210."
        )


class TestWhatCannotBeOpenedIsCountedOffTheTableAndNotTheRoster:
    """The orphan the missing foreign key exists to permit.

    `catalogue_credentials` has no foreign key, so an archive from a release
    that shipped one more catalogue restores a row naming a source this build's
    roster has not got. A caller iterating `CatalogueSource` counts ten and
    misses it, which is how `generate_key` came to refuse with a number the
    settings screen denied, naming logins the screen showed nothing to remove.
    """

    def test_a_row_outside_the_roster_is_still_counted(self, db):
        credentials.generate_key(db)
        credentials.put(db, "a-catalogue-that-went-away", "alice", "hunter2")
        credentials.store_key(credentials.generate_phrase())
        assert credentials.unreadable_sources(db) == ["a-catalogue-that-went-away"]

    def test_and_still_blocks_a_new_key_with_a_number_that_matches(self, db):
        credentials.generate_key(db)
        credentials.put(db, "a-catalogue-that-went-away", "alice", "hunter2")
        credentials.forget_key()
        with pytest.raises(credentials.KeyConfigurationError) as refusal:
            credentials.generate_key(db)
        assert "a-catalogue-that-went-away" in str(refusal.value)
        assert credentials.unreadable_sources(db) == ["a-catalogue-that-went-away"]

    def test_a_sealed_row_whose_source_is_pinned_still_blocks_a_new_key(
        self, db, monkeypatch
    ):
        """The arm the first four tests all walked around.

        Built on `view`, this answered `[]` here, because `view` short-circuits
        on a pinned credential before reading the envelope: a pinned source is
        not broken from the **screen's** point of view. So the button minted a
        key straight over a sealed row, and when the operator later cleared the
        pin, which is the ordinary end of pinning one source while others are
        stored, the row surfaced unreadable with the phrase gone. **The plain
        row count this replaced refused it.**

        None of the four tests beside this one sets a pin, which is why the arm
        went green on the covered case.
        """
        credentials.generate_key(db)
        credentials.put(db, "bne", "alice", "hunter2")
        credentials.forget_key()
        monkeypatch.setenv("CATALOGUE_CREDENTIAL_BNE", "bob:correcthorse")

        assert credentials.view(db, "bne").unreadable is False
        assert credentials.unreadable_sources(db) == ["bne"]
        with pytest.raises(credentials.KeyConfigurationError):
            credentials.generate_key(db)

    def test_and_the_phrase_still_opens_it_afterwards(self, db, monkeypatch):
        phrase, _ = credentials.generate_key(db)
        credentials.put(db, "bne", "alice", "hunter2")
        credentials.forget_key()
        monkeypatch.setenv("CATALOGUE_CREDENTIAL_BNE", "bob:correcthorse")
        monkeypatch.delenv("CATALOGUE_CREDENTIAL_BNE")
        credentials.store_key(phrase)
        assert credentials.stored(db, "bne") == ("alice", "hunter2")

    def test_a_readable_login_is_not_counted(self, db):
        credentials.generate_key(db)
        credentials.put(db, "bne", "alice", "hunter2")
        assert credentials.unreadable_sources(db) == []

    def test_they_are_reported_in_a_stable_order(self, db):
        credentials.generate_key(db)
        for source in ("dnb", "bne", "loc"):
            credentials.put(db, source, "alice", "hunter2")
        credentials.store_key(credentials.generate_phrase())
        assert credentials.unreadable_sources(db) == ["bne", "dnb", "loc"]


class TestDiscardingAKeyThatCannotBeDiscardedSaysSo:
    """Answering 200 while the key stays in force is the silent success again.

    `CREDENTIAL_ENCRYPTION_KEY_FILE` on a read only mount is the shape a
    Kubernetes Secret and a Docker secret both take, and `_from_file` reads one
    where `_file_is_writable` refuses it.
    """

    def test_a_key_file_that_cannot_be_written_is_refused_rather_than_skipped(
        self, monkeypatch, tmp_path
    ):
        readable = tmp_path / "key"
        readable.write_text(credentials.generate_phrase())
        monkeypatch.setattr(credentials, "key_file", lambda: readable)
        # **`dataclasses.replace`, not `setattr`.** `KeySource` is frozen, which
        # is the point of it, so the source is rebuilt and the tuple swapped.
        # A mode based case would not do: the suite runs as root, where
        # `os.access` answers True for a file nobody else could write.
        unwritable = dataclasses.replace(
            credentials.KEY_SOURCES[2], available=lambda: False
        )
        monkeypatch.setattr(
            credentials,
            "KEY_SOURCES",
            (*credentials.KEY_SOURCES[:2], unwritable),
        )
        with pytest.raises(credentials.KeyConfigurationError) as refusal:
            credentials.forget_key()
        assert "cannot be removed from here" in str(refusal.value)

    def test_a_key_it_can_reach_is_still_cleared(self, db):
        credentials.generate_key(db)
        assert credentials.forget_key() == 1


class TestASourceIsNotSomethingShapedLikeAPath:
    """The column travels, and that is newer than the column.

    `unreadable_sources` returns a source to the browser so somebody can remove
    a login that blocks a new key, and the generated client interpolates it
    into a URL path with no encoding: it is the only string path segment in
    that client, every other being a numeric id. With no foreign key and a
    restore inserting through Core, an archive decides the value, and an
    archive is a file an admin was handed on the strength of it carrying only
    ciphertext.
    """

    @pytest.mark.parametrize(
        "source",
        ["bne", "google_books", "open_library", "k10plus", "a-catalogue-that-went-away"],
    )
    def test_a_real_source_passes(self, source):
        assert credentials.is_safe_source(source) is True

    def test_every_roster_member_passes(self):
        """Checked rather than assumed, since the rule is narrower than the type."""
        refused = [
            source.value
            for source in CatalogueSource
            if not credentials.is_safe_source(source.value)
        ]
        assert refused == []

    @pytest.mark.parametrize(
        "source",
        [
            "../../../auth/users/1",
            "../../books/5?",
            "../../books/5#",
            "a/b",
            "a%2fb",
            "BNE",
            "a b",
            "",
            "x" * 33,
            "a.b",
            "café",
        ],
    )
    def test_anything_that_could_steer_a_request_is_refused(self, source):
        assert credentials.is_safe_source(source) is False

    def test_the_database_refuses_one_too(self, db):
        """The last line, for a write that does not come through the Python."""
        from sqlalchemy.exc import IntegrityError

        db.add(
            CatalogueCredential(
                source="../../books/5?", envelope="v1." + "a" * 40 + ".b.c"
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


class TestTheSourceRuleAndItsConstraintAgree:
    """One rule in two languages, walked over one battery so they cannot drift.

    The Python answer is what turns a hostile archive into the 400 this module
    promises; the SQL answer is what holds for a write that never reaches it.
    Two spellings of one rule is exactly the pair this project expects to come
    apart, so the test is a comparison rather than two assertions.

    **The battery has to carry control characters, and the first one did not.**
    That omission is the whole lesson here: the two agreed on every printable
    input, including all three path traversal payloads, and parted on an
    embedded NUL, because SQLite's `length` and `GLOB` are C string operations
    that stop at the first one. `bne\0../../books/5?` read as `bne` in SQL and
    was refused in Python, so the constraint the comments called "the last line"
    was not there for exactly the value that needed it. A differential test
    whose inputs are all drawn from the class where two implementations agree
    proves nothing about the class where they do not.
    """

    @pytest.mark.parametrize(
        "source",
        [
            # Real values, including the orphan the no-foreign-key design permits.
            "bne",
            "google_books",
            "open_library",
            "a-catalogue-that-went-away",
            "_",
            "-",
            "0",
            # The attack, in the three shapes a browser normalises differently.
            "../../../auth/users/1",
            "../../books/5?",
            "../../books/5#",
            "a/b",
            "a%2fb",
            # Ordinary refusals.
            "BNE",
            "a b",
            "",
            "x" * 32,
            "x" * 33,
            "a.b",
            # Non-ASCII, where a `\w` spelling would have widened silently.
            "café",
            "\u0664\u0664\u0663",
            "\u2170",
            "\u200b",
            # **Control characters, the class the first battery omitted.**
            "\n",
            "\r",
            "\t",
            "\x01",
            "bne\x00",
            "\x00bne",
            "bne\x00../../books/5?",
            "a\x01b",
        ],
    )
    def test_both_answer_the_same(self, db, source):
        from sqlalchemy.exc import IntegrityError

        expected = credentials.is_safe_source(source)
        try:
            db.add(
                CatalogueCredential(source=source, envelope="v1." + "a" * 40 + ".b.c")
            )
            db.commit()
            accepted = True
        except IntegrityError:
            db.rollback()
            accepted = False
        assert accepted == expected, f"the two rules disagree about {source!r}"

    def test_the_nul_case_is_the_one_that_disagreed(self, db):
        """Named on its own, so deleting it from the list above is visible.

        Reduced from the parametrisation because a case that once failed and is
        now one entry in a list of thirty is a case somebody trims.
        """
        from sqlalchemy.exc import IntegrityError

        assert credentials.is_safe_source("bne\x00../../books/5?") is False
        db.add(
            CatalogueCredential(
                source="bne\x00../../books/5?", envelope="v1." + "a" * 40 + ".b.c"
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
