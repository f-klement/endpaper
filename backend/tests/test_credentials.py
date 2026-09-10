"""A catalogue login is sealed, bound to one origin, and openable by one key.

**The guards worth attacking here are the three that fail silently if they are
wrong**, and each has a class of its own: an envelope that opens under a key
that did not write it, a credential that goes to a host it was not set for, and
a recovery phrase whose words reach a message. The rest of this file is
ordinary round trips.
"""

import dataclasses
from pathlib import Path
from types import MappingProxyType

import httpx
import keyring
import keyring.backend
import keyring.errors
import pytest

import credentials
import targets
from database import Base
from enums import CatalogueSource, CredentialProvenance
from models import CatalogueCredential
from tests.helpers import sealed_before_the_origin_was_bound
from tests.test_house_rules import _is_vendored

#: The address the roster holds for the source these tests use.
#:
#: **The roster's own, not an invented one**, because `view` and `for_request`
#: both compare what they are handed with the row: a made up address would test
#: the ladder against a case no caller produces. The BNE ships no default, so
#: every test below that is not about one is unaffected by which address it is.
BNE_URL = targets.SEEDED[CatalogueSource.BNE].base_url

#: A second roster address, for the tests that move a ciphertext between rows.
DNB_URL = targets.SEEDED[CatalogueSource.DNB].base_url

#: An address for the orphan source the missing foreign key permits.
#:
#: **Invented, because there is nothing to look it up in**, which is the whole
#: point of those tests: a row can name a source this build's roster no longer
#: has. The address a login was sealed for is the caller's to remember, so a
#: test that keeps one is a test in the shape a caller is in.
ORPHAN_URL = "https://catalogue.invalid/opds"


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
        envelope = credentials.seal(key, "bne", BNE_URL, "alice:hunter2")
        assert credentials.generation_of(envelope) == credentials.generation_of_key(key)

    def test_a_wrong_key_says_so_rather_than_failing_like_a_damaged_row(self, key: bytes):
        envelope = credentials.seal(key, "bne", BNE_URL, "alice:hunter2")
        other = credentials.phrase_to_key(credentials.generate_phrase())
        with pytest.raises(credentials.WrongKeyGeneration):
            credentials.unseal(other, "bne", BNE_URL, envelope)

    def test_the_tag_cannot_be_rewritten_to_a_second_key(self, key: bytes):
        """It is inside the authenticated data as well as in the text."""
        envelope = credentials.seal(key, "bne", BNE_URL, "alice:hunter2")
        other = credentials.phrase_to_key(credentials.generate_phrase())
        version, _, nonce, sealed = envelope.split(".")
        forged = ".".join((version, credentials.generation_of_key(other), nonce, sealed))
        with pytest.raises(credentials.UnreadableCredential):
            credentials.unseal(other, "bne", BNE_URL, forged)

    def test_something_that_is_not_an_envelope_reports_no_generation(self):
        assert credentials.generation_of("hunter2") == ""

    def test_and_is_refused_rather_than_parsed(self, key: bytes):
        with pytest.raises(credentials.UnreadableCredential):
            credentials.unseal(key, "bne", BNE_URL, "hunter2")


class TestAnEnvelopeIsBoundToItsSourceAndItsKind:
    """The additional authenticated data, and it is what distinguishes the kinds.

    A ciphertext lifted onto another row by a hand edited archive or a stray
    `UPDATE` fails authentication rather than being sent to a host it was never
    set for.
    """

    def test_a_credential_moved_to_another_source_does_not_open(self, key: bytes):
        envelope = credentials.seal(key, "bne", BNE_URL, "alice:hunter2")
        with pytest.raises(credentials.UnreadableCredential):
            credentials.unseal(key, "dnb", DNB_URL, envelope)

    def test_it_opens_on_the_source_it_was_written_for(self, key: bytes):
        envelope = credentials.seal(key, "bne", BNE_URL, "alice:hunter2")
        assert credentials.unseal(key, "bne", BNE_URL, envelope) == "alice:hunter2"

    def test_the_purpose_names_the_kind_and_not_only_the_subject(self):
        assert (
            credentials._purpose("bne", "https://a.invalid:443")
            == "endpaper/v2/catalogue-credential/bne/https://a.invalid:443"
        )


class TestAnEnvelopeIsBoundToTheAddressItIsFor:
    """The binding that makes a moved row a refusal rather than an exfiltration.

    The source alone was enough while every caller passed a module constant.
    `opds_servers.base_url` is a row, `backup.restore` writes it through Core,
    and an archive keeping a legitimate key beside an address of its own sent a
    household's sealed login to a host the archive named: the attacker needed
    the archive and not the key, which is what sealing was bought to prevent.
    """

    def test_a_credential_asked_for_at_another_address_does_not_open(self, key: bytes):
        envelope = credentials.seal(key, "bne", BNE_URL, "alice:hunter2")
        with pytest.raises(credentials.UnreadableCredential):
            credentials.unseal(key, "bne", "https://elsewhere.invalid/opds", envelope)

    def test_it_opens_at_the_address_it_was_sealed_for(self, key: bytes):
        envelope = credentials.seal(key, "bne", BNE_URL, "alice:hunter2")
        assert credentials.unseal(key, "bne", BNE_URL, envelope) == "alice:hunter2"

    @pytest.mark.parametrize(
        ("sealed_at", "asked_at"),
        [
            ("https://host.invalid/opds", "https://host.invalid:443/other/path"),
            ("http://host.invalid/opds", "http://host.invalid:80/"),
            ("https://HOST.invalid/opds", "https://host.invalid/opds"),
        ],
    )
    def test_the_same_machine_written_differently_is_one_address(
        self, key: bytes, sealed_at, asked_at
    ):
        """The origin is bound, not the URL, or a path edit would cost a retype.

        `origin_of` is what decides, and `PUT /api/opds/servers/{id}` keeps the
        login on exactly the edits this admits.
        """
        envelope = credentials.seal(key, "bne", sealed_at, "alice:hunter2")
        assert credentials.unseal(key, "bne", asked_at, envelope) == "alice:hunter2"

    @pytest.mark.parametrize(
        ("sealed_at", "asked_at"),
        [
            ("https://host.invalid/opds", "http://host.invalid/opds"),
            ("https://host.invalid/opds", "https://host.invalid:8443/opds"),
            ("https://host.invalid/opds", "https://other.invalid/opds"),
            ("https://host.invalid/opds", "https://user@other.invalid/opds"),
        ],
    )
    def test_scheme_host_port_and_userinfo_each_make_it_another_machine(
        self, key: bytes, sealed_at, asked_at
    ):
        envelope = credentials.seal(key, "bne", sealed_at, "alice:hunter2")
        with pytest.raises(credentials.UnreadableCredential):
            credentials.unseal(key, "bne", asked_at, envelope)

    @pytest.mark.parametrize("address", ["", "not a url", "file:///etc/passwd", "://x"])
    def test_an_address_this_build_cannot_parse_seals_nothing(self, key: bytes, address):
        """Refused rather than folded to the empty string, which is the hole.

        `origin_of` answers `""` for all of these and two of those compare
        equal, so an envelope sealed over one would open beside **any** address
        this build cannot parse.
        """
        with pytest.raises(credentials.CredentialError):
            credentials.seal(key, "bne", address, "alice:hunter2")

    def test_and_opens_nothing(self, key: bytes):
        envelope = credentials.seal(key, "bne", BNE_URL, "alice:hunter2")
        with pytest.raises(credentials.CredentialError):
            credentials.unseal(key, "bne", "not a url", envelope)

    def test_two_addresses_it_cannot_parse_are_not_one_address(self, key: bytes):
        """The arm the empty string would have made pass.

        **Written as the whole round trip rather than as the refusal
        `_associated` happens to raise first**, because which end refuses is an
        implementation choice and a test pinned to the seal alone goes green the
        day it moves. Driven by removing that refusal: sealing over `"not a
        url"` and opening over `"file:///etc/passwd"` then round trips, because
        `origin_of` answers `""` for both and two empty origins compare equal.
        """
        with pytest.raises(credentials.CredentialError):
            envelope = credentials.seal(key, "bne", "not a url", "alice:hunter2")
            credentials.unseal(key, "bne", "file:///etc/passwd", envelope)

    @pytest.mark.parametrize("source", ["bne/https:", "a b", "", "BNE", "x" * 33])
    def test_a_source_that_is_not_a_source_seals_nothing(self, key: bytes, source):
        """What keeps the purpose string one string rather than two readings.

        A source may not contain a slash and an origin always does, so the pair
        is unambiguous only while `is_safe_source` holds. `put` never checked
        it: the column's CHECK did, one layer later.
        """
        with pytest.raises(credentials.CredentialError):
            credentials.seal(key, source, BNE_URL, "alice:hunter2")

    def test_no_two_source_and_address_pairs_share_a_purpose_string(self):
        pairs = [
            ("bne", "https://a.invalid:443"),
            ("bne", "https://b.invalid:443"),
            ("dnb", "https://a.invalid:443"),
            ("dnb", "https://b.invalid:443"),
        ]
        assert len({credentials._purpose(*pair) for pair in pairs}) == len(pairs)


class TestAnEnvelopeSealedBeforeTheBindingIsOpenedAndCarriedForward:
    """The upgrade path, and it is a product decision rather than a detail.

    **Owner's decision, 2026-09-07: a household upgrading may not lose its
    stored logins.** An earlier version of this work deleted every envelope
    written before the origin binding, which is what these tests used to pin.

    What makes carrying them forward safe is a split the deletion took the wrong
    half of. A `v1` envelope is bound to its source and not to its address, so
    being opened beside an address somebody else wrote needs somebody able to
    write one. For a roster catalogue nobody is: the address is
    `targets.SEEDED[...].base_url`, a module constant. For a household OPDS
    server somebody is, which is why the binding was made, and none of those has
    ever been released.
    """

    def test_it_opens_at_its_own_version(self, key: bytes):
        envelope = sealed_before_the_origin_was_bound(key, "bne", "alice:hunter2")
        assert credentials.unseal(key, "bne", BNE_URL, envelope) == "alice:hunter2"

    def test_and_still_refuses_the_wrong_key(self, key: bytes):
        envelope = sealed_before_the_origin_was_bound(key, "bne", "alice:hunter2")
        other = credentials.phrase_to_key(credentials.generate_phrase())
        with pytest.raises(credentials.WrongKeyGeneration):
            credentials.unseal(other, "bne", BNE_URL, envelope)

    def test_and_still_refuses_a_damaged_row(self, key: bytes):
        envelope = sealed_before_the_origin_was_bound(key, "bne", "alice:hunter2")
        version, generation, nonce, sealed = envelope.split(".")
        damaged = ".".join([version, generation, nonce, sealed[:-4] + "AAAA"])
        with pytest.raises(credentials.UnreadableCredential):
            credentials.unseal(key, "bne", BNE_URL, damaged)

    def test_it_is_still_recognised_as_an_envelope(self, key: bytes):
        """Or `backup._parse_row` refuses an archive taken before the upgrade.

        The whole restore would fail over logins that now open perfectly well,
        which is the failure the missing foreign key exists to avoid.
        """
        envelope = sealed_before_the_origin_was_bound(key, "bne", "alice:hunter2")
        assert credentials.generation_of(envelope) == credentials.generation_of_key(key)

    def test_the_key_section_does_not_list_it_as_unreadable(self, db, key: bytes):
        """It used to, and that was right while no key opened it."""
        credentials.store_key(credentials.key_to_phrase(key))
        db.add(
            CatalogueCredential(
                source="bne", envelope=sealed_before_the_origin_was_bound(key, "bne", "a:b")
            )
        )
        db.commit()
        assert credentials.unreadable_sources(db) == []

    def test_and_the_row_reports_itself_held_and_readable(self, db, key: bytes):
        credentials.store_key(credentials.key_to_phrase(key))
        db.add(
            CatalogueCredential(
                source="bne", envelope=sealed_before_the_origin_was_bound(key, "bne", "a:b")
            )
        )
        db.commit()
        seen = credentials.view(db, "bne", BNE_URL)
        assert (seen.provenance, seen.has_credential, seen.unreadable) == (
            CredentialProvenance.STORED,
            True,
            False,
        )

    def test_and_an_outbound_request_carries_it(self, db, key: bytes):
        credentials.store_key(credentials.key_to_phrase(key))
        db.add(
            CatalogueCredential(
                source="bne", envelope=sealed_before_the_origin_was_bound(key, "bne", "a:b")
            )
        )
        db.commit()
        assert credentials.for_request(db, "bne", BNE_URL) is not None

    def test_reading_it_carries_it_forward_to_the_current_scheme(self, db, key: bytes):
        """The old scheme empties itself, which is why no migration deletes.

        The key is proven by the open that just succeeded, and the address is
        the one the caller is about to use, so the re-seal binds it to that
        rather than to anything a lookup might have disagreed about.
        """
        credentials.store_key(credentials.key_to_phrase(key))
        db.add(
            CatalogueCredential(
                source="bne", envelope=sealed_before_the_origin_was_bound(key, "bne", "a:b")
            )
        )
        db.commit()

        assert credentials.stored(db, "bne", BNE_URL) == ("a", "b")
        after = credentials.stored_envelope(db, "bne")
        assert after.split(".")[0] == credentials.VERSION
        assert credentials.stored(db, "bne", BNE_URL) == ("a", "b")

    def test_and_the_carried_forward_envelope_is_bound_to_the_address(self, db, key: bytes):
        """Which is the whole point of carrying it forward rather than keeping it."""
        credentials.store_key(credentials.key_to_phrase(key))
        db.add(
            CatalogueCredential(
                source="bne", envelope=sealed_before_the_origin_was_bound(key, "bne", "a:b")
            )
        )
        db.commit()
        credentials.stored(db, "bne", BNE_URL)

        after = credentials.stored_envelope(db, "bne")
        with pytest.raises(credentials.UnreadableCredential):
            credentials.unseal(key, "bne", "https://elsewhere.invalid", after)


class TestTheSupersededSchemeIsRefusedWhereTheAddressIsARow:
    """The half the acceptance was missing, found by the design seat.

    **`unseal` accepted the older scheme for every source, including a household
    OPDS server, whose address is `opds_servers.base_url` and is a row.** So the
    acceptance was wider than the argument for it: measured, a `v1` envelope for
    an `opds-` source opened at an address of the reader's choosing exactly as at
    its own. That is the case the origin binding was made for.
    """

    def test_a_household_server_envelope_from_the_old_scheme_is_refused(
        self, key: bytes
    ):
        source = "opds-9685983b245e650e"
        envelope = sealed_before_the_origin_was_bound(key, source, "house:pw")
        with pytest.raises(credentials.UnboundCredential):
            credentials.unseal(key, source, "https://calibre.lan:8080/opds", envelope)

    def test_and_refused_at_an_address_somebody_else_chose(self, key: bytes):
        """The arm that was open: it used to return the password here."""
        source = "opds-9685983b245e650e"
        envelope = sealed_before_the_origin_was_bound(key, source, "house:pw")
        with pytest.raises(credentials.UnboundCredential):
            credentials.unseal(key, source, "https://evil.invalid/opds", envelope)

    def test_while_a_roster_envelope_from_the_old_scheme_still_opens(self, key: bytes):
        """The control: the refusal is about the address being a row, not about
        the version, or the upgrade path this was all built for would be gone."""
        envelope = sealed_before_the_origin_was_bound(key, "bne", "alice:hunter2")
        assert credentials.unseal(key, "bne", BNE_URL, envelope) == "alice:hunter2"


class TestASupersededEnvelopeOpensAtOneAddressAndNoOther:
    """The pair rule, over both axes at once.

    **Two predicates preceded this and each covered one axis.** One asked only
    whether the source was a household server, so a roster envelope opened at
    any address at all; the other asked only whether the address was some roster
    origin, so a household server's envelope opened as soon as an archive
    pointed its row at one. The security seat measured five hostile cases
    between them.
    """

    def _hostile(self):
        dnb = targets.SEEDED[CatalogueSource.DNB].base_url
        bne = targets.SEEDED[CatalogueSource.BNE].base_url
        return [
            ("a roster source at another roster's address", "dnb", bne),
            ("a roster source at an address a row could supply", "dnb", "https://evil.invalid/sru"),
            ("a household server at its own address", "opds-9685983b245e650e", "https://calibre.lan:8080/opds"),
            ("a household server pointed at a roster origin", "opds-9685983b245e650e", dnb),
            ("an orphan source an archive restored", "notasource", dnb),
        ]

    def test_it_opens_at_the_address_this_build_published_for_its_source(self, key: bytes):
        dnb = targets.SEEDED[CatalogueSource.DNB].base_url
        envelope = sealed_before_the_origin_was_bound(key, "dnb", "alice:hunter2")
        assert credentials.unseal(key, "dnb", dnb, envelope) == "alice:hunter2"

    def test_and_nowhere_else(self, key: bytes):
        for name, source, address in self._hostile():
            envelope = sealed_before_the_origin_was_bound(key, source, "a:b")
            with pytest.raises(credentials.UnboundCredential, match="cannot be opened"):
                credentials.unseal(key, source, address, envelope)
            # Named in the failure, because five cases in one loop otherwise
            # report as one line that does not say which admitted the envelope.
            assert not credentials._may_open_unbound(source, address), name

    def test_and_every_roster_source_still_opens_at_its_own(self):
        """The control. A rule that refused everything would pass the arm above
        and lose the upgrade path this whole change exists for."""
        opening = [
            source.value
            for source, target in targets.SEEDED.items()
            if credentials._may_open_unbound(source.value, target.base_url)
        ]
        assert len(opening) == len(targets.SEEDED)

    def test_the_address_free_question_is_the_rule_asked_at_its_own_address(self):
        """The diagonal, recomputed from the roster rather than stated.

        `_is_a_roster_source` is what `_openable_by` applies, having no address.
        It has to be the rule and not a restatement of half of it: a restatement
        agreed on every seeded row by accident of the data, and split the moment
        one seeded address stopped parsing.
        """
        for source, target in targets.SEEDED.items():
            assert credentials._is_a_roster_source(source.value) is (
                credentials._may_open_unbound(source.value, target.base_url)
            ), source.value
        for absent in ("opds-9685983b245e650e", "notasource", ""):
            assert credentials._is_a_roster_source(absent) is False, absent

    def test_a_refused_source_is_still_reported_as_unreadable(self, db, key: bytes):
        """Or the household gets a login that is dead and invisible at once.

        `_openable_by` answers without an address, so it applies the half of the
        rule that needs none. It briefly did not, and then `unreadable_sources`
        listed nothing while `unseal` refused the row for every key and address.
        """
        credentials.store_key(credentials.key_to_phrase(key))
        db.add(
            CatalogueCredential(
                source="opds-9685983b245e650e",
                envelope=sealed_before_the_origin_was_bound(key, "opds-9685983b245e650e", "a:b"),
            )
        )
        db.commit()
        assert credentials.unreadable_sources(db) == ["opds-9685983b245e650e"]


class TestAVersionWithNoPurposeShapeIsRefusedRatherThanInvented:
    """`_purpose` was two arms over an open set with a silent default.

    Anything that was not the superseded version got the current shape, so a
    third version would have been sealed over a string carrying its own number
    and nothing would have failed.
    """

    def test_every_openable_version_has_a_shape(self):
        for version in credentials._OPENABLE_VERSIONS:
            assert credentials._purpose("bne", "https://h.invalid", version)

    def test_and_a_version_with_none_raises(self):
        with pytest.raises(credentials.CredentialError):
            credentials._purpose("bne", "https://h.invalid", "v3")

    def test_recognising_and_opening_are_asked_separately(self):
        """They coincide today. The names exist for the day they do not, and
        pointing `unseal` at the wrong one is the defect this pins."""
        assert set(credentials._OPENABLE_VERSIONS) <= set(credentials.KNOWN_VERSIONS)


class TestTheSupersededSchemeIsSafeOnlyWhileARosterAddressIsCode:
    """The condition under which a `v1` envelope may still be opened at all.

    **A `v1` envelope is bound to its source and not to its address**, so opening
    one beside an address somebody else chose needs somebody able to choose one.
    For a roster catalogue nobody is: every address comes from `targets.SEEDED`,
    which is a module constant. For a household OPDS server somebody is, which
    is the case the binding was made for, and `routers/opds.py` is where that
    lives.

    **This is the guard that ends the acceptance, and it is tied to the work
    that ends it rather than to a date.** Owner's decision, 2026-09-07. When the
    ticket that makes a catalogue row editable lands, this fails, and the fix is
    to stop opening `v1` rather than to adjust the test.

    **It watches the table rather than the call sites, and the first version of
    it watched the call sites and was worthless.** That one read a single file
    and matched a single line, so it saw 1 of the 3 resolver calls that exist and
    neither of the two written across lines; a real `#130` shaped change, taking
    the address from `db.get(CatalogueTarget, ...)`, passed it. The signal is
    upstream of every call site: a roster address stops being code the moment
    anything reads that column back.
    """

    #: Every module that may name the roster table in code.
    #:
    #: **This is an inclusion list and that is deliberate here**, which is the
    #: opposite of what this repository usually wants. The set it describes is
    #: closed by design: the model that defines the table, the seeder that
    #: reconciles it against `targets.SEEDED` on each start, and the archive that
    #: copies it. A fourth entry is the event being watched for, so the list
    #: going stale **is** the signal rather than the failure.
    #: None of the three hands a `base_url` off a row to anything.
    #:
    #: A fourth module using it is the roster becoming row decided, which is
    #: `#130`. **`#131`, a typeable host, is the other trigger and these walks
    #: cannot see it**: a typed address names no ORM class, rebinds nothing and
    #: writes no table name. `targets.py` says either one is the day. What
    #: covers that case is not here but in `unseal`, which refuses the
    #: superseded scheme at any address other than the one this build published
    #: for that very source. These three are belt to that brace, and they are
    #: early warning rather than the guard: measured by the security seat, four
    #: shapes `#130` could take survive all three, and the rule in `unseal` is
    #: what refuses every one of them. Growing this list is not the fix; dropping
    #: `_UNBOUND_VERSION` from `credentials._OPENABLE_VERSIONS` is.
    #:
    #: **The bound, measured rather than assumed**: this watches for the ORM
    #: name. Attacked 2026-09-07 with four shapes, three caught, and the one that
    #: survives is a raw `SELECT base_url FROM catalogue_targets`, which names no
    #: identifier at all. That shape exists nowhere in this backend, whose only
    #: raw statement is a liveness `SELECT 1`, so it is a gap and not a hole
    #: today. Closing it means watching the table name in string literals too,
    #: which is a second instrument rather than a further arm on this one.
    MAY_USE_THE_ROSTER_TABLE = {"models.py", "main.py", "backup.py"}

    #: What the walk does not read **of this project's own**, stated rather
    #: than as a list of what it does.
    #:
    #: The tests, which name the table in order to check it, and the migrations,
    #: which are its history and necessarily name it.
    #:
    #: **What is not ours is `test_house_rules._is_vendored` and is no longer
    #: named here.** This set held `.venv` and `__pycache__`, which is every
    #: cache anybody had seen locally, and the pipeline sets `UV_CACHE_DIR`
    #: inside `backend/`: measured 2026-09-07, without a vendored exclusion the
    #: walk read 3,148 files of which 3,068, or 97.5%, were third party, so a
    #: dependency shipping a class of this name would redden a guard about this
    #: repository, in the environment where it is trusted and nowhere else.
    #: Everything else under `backend/` is read, at every depth: the first
    #: version of this walk read the top level only, so `routers/` was invisible
    #: and the exact change it guards against passed it.
    NOT_READ = {"tests", "migrations"}

    def _modules_naming_it_in_code(self) -> set[str]:
        """Which backend modules name `CatalogueTarget` as code, not as prose.

        `ast` rather than a text search, because six modules mention it in a
        docstring or a comment and none of those is a reader.
        """
        import ast

        backend = Path(__file__).resolve().parents[1]
        found = set()
        read: set[str] = set()
        # **`rglob`, and the first version of this said `glob`.** That reads the
        # top level only, so `routers/` was not scanned at all and the mutation
        # this guard exists to catch, a resolver reading the address off a row in
        # `routers/books.py`, walked past it. Excluded: the tests, which name the
        # table to check it, and the migrations, which are the history of it.
        for path in sorted(backend.rglob("*.py")):
            parts = set(path.relative_to(backend).parts)
            if parts & self.NOT_READ or _is_vendored(path, backend):
                continue
            read.add(path.parent.name)
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                named = (
                    (isinstance(node, ast.Name) and node.id == "CatalogueTarget")
                    or (isinstance(node, ast.Attribute) and node.attr == "CatalogueTarget")
                    # The definition, which `models.py` is and which is not a
                    # `Name` node. Counted so the module holding the class is in
                    # the set rather than exempt from it: a reader added there
                    # would otherwise be the one place this cannot see.
                    or (isinstance(node, ast.ClassDef) and node.name == "CatalogueTarget")
                    or (isinstance(node, ast.alias) and node.name == "CatalogueTarget")
                )
                if named:
                    found.add(path.name)
        # **The packages it must cover, not a number.** This walk reads 81
        # files, so a floor of `> 30` did not bind: a mutation marking `routers`
        # and `schemas` vendored left this green, and `routers/` is the exact
        # directory this walk's own comment records the first version missing.
        assert {"routers", "schemas"} <= read, read
        return found

    def test_only_the_model_the_seeder_and_the_archive_use_the_roster_table(self):
        using = self._modules_naming_it_in_code()
        assert using == self.MAY_USE_THE_ROSTER_TABLE, (
            f"{sorted(using - self.MAY_USE_THE_ROSTER_TABLE)} now uses the roster "
            "table. If a catalogue address can be edited, an envelope bound to a "
            "source alone can be opened at an address somebody chose, so "
            "credentials.unseal must stop opening _UNBOUND_VERSION. Widening this "
            "set is not the fix."
        )

    def test_the_walk_finds_something(self):
        """A parse that matched nothing would make the test above pass forever."""
        assert self._modules_naming_it_in_code(), "the ast walk found no user at all"

    #: What `targets.py` may not import, stated as the exclusion.
    #:
    #: **The rule underneath is that the roster cannot be built from the table**,
    #: and this is the only arm that covers the shape the other three cannot
    #: see: changing the initialiser inside `targets.py` itself. That is not a
    #: rebinding, so `Final` permits it, and the rebind walk excludes that file
    #: by name, so nothing else would look. A helper import puts the naming in an
    #: allowlisted module and leaves all three walks green.
    #:
    #: Green today: `targets.py` imports `re`, `collections.abc`, `dataclasses`,
    #: `enum`, `types`, `typing`, `urllib.parse`, `z3950`, `decoders` and
    #: `enums`, none of which can reach a database.
    CANNOT_REACH_THE_DATABASE = ("models", "main", "backup", "sqlalchemy", "database")

    def test_the_roster_module_cannot_reach_the_table_it_is_seeded_into(self):
        """The arm that covers a roster built inside `targets.py`.

        Found by the design seat, 2026-09-07, against a claim of mine that
        `Final` and the rebind walk refuse serving the roster from the table.
        Neither does, for the one shape that change would actually take.
        """
        import ast

        source = (Path(__file__).resolve().parents[1] / "targets.py").read_text()
        imported: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert imported, "no import found, so this guard reads nothing"
        offenders = sorted(imported & set(self.CANNOT_REACH_THE_DATABASE))
        assert offenders == [], (
            f"targets.py imports {offenders}, so the roster can be built from the "
            "table inside the module that declares it. `Final` permits that and the "
            "rebind walk does not look here, so credentials._OPENABLE_VERSIONS must "
            "drop _UNBOUND_VERSION."
        )

    def test_nothing_outside_targets_rebinds_the_roster(self):
        """The second instrument, and it watches assignment rather than naming.

        **Belt to a brace that is now self enforcing.** Both seats measured that
        this misses the two shapes that can actually reach `main.py`, an item
        assignment and an `update`, while the rebinding it does catch is already
        a mypy error under `Final`. That is a guard whose own mutation test
        picked the covered case. The roster being a `MappingProxyType` is what
        closes it; this stays because a rebinding is still worth naming loudly.

        **`main.py` is allowed to name the table, so the first arm cannot see
        the seeder feeding rows back into `targets.SEEDED`.** Run in process,
        2026-09-07: rebinding it from the rows the seeder had just reconciled
        left that arm green, and "none of the three hands a `base_url` off a row
        to anything" would have been false with nothing red.

        A different question rather than a further arm on the same one, which is
        why it is its own test.
        """
        import ast

        backend = Path(__file__).resolve().parents[1]
        offenders = []
        read: set[str] = set()
        for path in sorted(backend.rglob("*.py")):
            parts = set(path.relative_to(backend).parts)
            if (
                parts & self.NOT_READ
                or _is_vendored(path, backend)
                or path.name == "targets.py"
            ):
                continue
            read.add(path.parent.name)
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                written = node.targets if isinstance(node, ast.Assign) else [node.target]
                for one in written:
                    if isinstance(one, ast.Name) and one.id == "SEEDED":
                        offenders.append(f"{path.name}: SEEDED")
                    elif isinstance(one, ast.Attribute) and one.attr == "SEEDED":
                        offenders.append(f"{path.name}: .SEEDED")
        assert offenders == [], (
            f"{offenders} rebinds the roster. A roster address is then whatever "
            "was written there, so credentials._OPENABLE_VERSIONS must drop "
            "_UNBOUND_VERSION."
        )
        # **The packages it must cover, not a number.** This walk reads 81
        # files, so a floor of `> 30` did not bind: a mutation marking `routers`
        # and `schemas` vendored left this green, and `routers/` is the exact
        # directory this walk's own comment records the first version missing.
        assert {"routers", "schemas"} <= read, read

    def test_no_module_reaches_the_roster_table_by_name_in_sql(self):
        """The third instrument, closing the one shape the first two miss.

        A raw `SELECT base_url FROM catalogue_targets` names no identifier, so
        the `ast` walk over `CatalogueTarget` cannot see it.

        **The bound**: this recognises a statement by having whitespace in it,
        so a query assembled from fragments across separate constants passes,
        and so would a one word statement if SQL had one. Nothing here builds
        SQL that way. The failure direction is a loud false positive on prose
        naming the table outside a docstring, of which there are none. Attacked in process,
        2026-09-07: that shape survived both other arms.

        This backend's only raw statement is a liveness `SELECT 1`, so the check
        costs nothing today and the table name is what it watches.
        """
        import ast

        backend = Path(__file__).resolve().parents[1]
        offenders = []
        read: set[str] = set()
        for path in sorted(backend.rglob("*.py")):
            parts = set(path.relative_to(backend).parts)
            # **Not exempting the three allowed modules, unlike the walk
            # above.** They may name the ORM class, which is what they are
            # allowed for; reaching the column by raw statement is a different
            # act and none of them does it. Exempting them here was free scope
            # given away for nothing.
            if parts & self.NOT_READ or _is_vendored(path, backend):
                continue
            read.add(path.parent.name)
            tree = ast.parse(path.read_text(encoding="utf-8"))
            # Docstrings are `ast.Constant` too, and five modules discuss this
            # table in prose. Prose is not a query, so they are collected by
            # identity and skipped rather than matched around.
            prose = set()
            for holder in ast.walk(tree):
                if isinstance(holder, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    first = next(iter(getattr(holder, "body", [])), None)
                    if (
                        isinstance(first, ast.Expr)
                        and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)
                    ):
                        prose.add(id(first.value))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if id(node) in prose:
                        continue
                    text = node.value
                    if "catalogue_targets" not in text:
                        continue
                    # **A name is one token; a statement has whitespace in it.**
                    # No module is exempt from this arm: exempting the three
                    # that may name the ORM class was scope given away, since
                    # none of them queries the column. But dropping the
                    # exemption alone fires on the table's own definition, on
                    # `__tablename__` and on four constraint names, none of
                    # which reads anything.
                    #
                    # **Whitespace rather than a list of SQL verbs**, which is
                    # what this first was. Measured 2026-09-07 over the whole
                    # backend: the six non docstring constants naming this table
                    # are all bare identifiers, and every statement shape tried
                    # has a space, `REPLACE INTO` included, which the verb list
                    # missed. So this enumerates nothing and covers more.
                    if len(text.split()) > 1:
                        offenders.append(f"{path.name}: {text[:60]}")
        assert offenders == [], (
            f"{offenders} names the roster table in SQL. See the assertion above "
            "for what that means for _OPENABLE_VERSIONS."
        )
        # **The packages it must cover, not a number.** This walk reads 81
        # files, so a floor of `> 30` did not bind: a mutation marking `routers`
        # and `schemas` vendored left this green, and `routers/` is the exact
        # directory this walk's own comment records the first version missing.
        assert {"routers", "schemas"} <= read, read

    def test_the_roster_is_read_only_and_not_merely_a_constant_name(self):
        """The premise `_may_open_unbound` rests on, made self enforcing.

        **It asserted `isinstance(dict)`, which is what the roster must not
        behave like.** `Final` stops a rebinding and stops nothing else, and both
        critic seats measured the same inversion independently: one subscript
        write on the roster moves the published side of the comparison, so a
        superseded envelope opens at whatever the write said, with the projection
        moving along and nothing reporting anything.

        A `MappingProxyType` refuses every in place write at runtime, and mypy
        refuses the two shapes statically. The walks below are early warning
        again rather than the control for this.
        """
        from collections.abc import Mapping
        from types import MappingProxyType

        assert isinstance(targets.SEEDED, Mapping) and targets.SEEDED
        assert isinstance(targets.SEEDED, MappingProxyType), (
            "the roster is writable, so an edited row moves the address a "
            "superseded envelope opens at"
        )
        for target in targets.SEEDED.values():
            assert isinstance(target.base_url, str) and target.base_url

    def test_and_no_write_to_it_is_accepted(self):
        """The three shapes, two of which every ast walk here missed."""
        import dataclasses

        source, row = next(iter(targets.SEEDED.items()))
        moved = dataclasses.replace(row, base_url="https://evil.invalid/sru")
        with pytest.raises((TypeError, AttributeError)):
            targets.SEEDED[source] = moved  # type: ignore[index]
        with pytest.raises((TypeError, AttributeError)):
            targets.SEEDED.update({source: moved})  # type: ignore[attr-defined]
        with pytest.raises(dataclasses.FrozenInstanceError):
            row.base_url = "https://evil.invalid/sru"  # type: ignore[misc]


class TestTheEnvelopeRuleAndItsConstraintAgree:
    """`credentials.KNOWN_VERSIONS` in SQL, because models.py cannot import it.

    Two spellings of one set, and the pair this project expects to come apart.
    The candidates are derived from the constant rather than listed, so adding a
    version to it and not to the constraint fails here rather than at a write on
    somebody's deployment.

    **Against a table built here from `Base.metadata`, and not against the `db`
    fixture, which cannot answer this question.** `conftest._schema_once` calls
    `create_all`, but `main.py` calls `upgrade_to_head()` at startup and the app
    is imported first, so `create_all` finds every table already built and does
    nothing: the suite's database is the **migrations'**. Measured by widening
    this constraint in `models.py` alone and running this class, which passed,
    and by reading back `sqlite_master`, which returned the quoted table name a
    batch rebuild produces rather than the unquoted one `create_all` emits. A
    version added to `models.py` and forgotten in the migration is what
    `tests/test_schema.py::TestTheEnvelopeConstraintOnAMigratedDatabase` covers
    from the other side.
    """

    @staticmethod
    def _accepted(envelope: str) -> bool:
        """Whether the table **the models declare** takes this envelope."""
        import sqlalchemy as sa
        from sqlalchemy.exc import IntegrityError

        engine = sa.create_engine("sqlite://")
        # Through the metadata rather than `__table__`, which the ORM types as
        # a `FromClause`. Same object, and the name comes off the model.
        Base.metadata.tables[CatalogueCredential.__tablename__].create(engine)
        statement = sa.text(
            "INSERT INTO catalogue_credentials (source, envelope) VALUES ('bne', :e)"
        )
        with engine.connect() as connection:
            try:
                connection.execute(statement, {"e": envelope})
            except IntegrityError:
                return False
        return True

    def test_the_version_this_build_writes_is_one_it_recognises(self):
        assert credentials.VERSION in credentials.KNOWN_VERSIONS

    @pytest.mark.parametrize("version", credentials.KNOWN_VERSIONS)
    def test_every_recognised_version_is_storable(self, version):
        assert self._accepted(f"{version}." + "a" * 40 + ".b.c")

    def test_the_constraint_names_exactly_the_versions_this_build_recognises(self):
        """Read off the SQL, because a sweep only sees the shapes it enumerates.

        The arm this replaced tried `v0` to `v9`. It caught a constraint widened
        to admit `v3` and could not see one widened to `w1`, `v10` or `v2x`, and
        a list of spellings is the guard shape this project keeps replacing.
        Comparing the two sets fails in **both** directions: a version in the
        constant and not the SQL, which is a write every deployment refuses, and
        a version in the SQL and not the constant, which is a format this build
        stores and cannot open.
        """
        import re

        clause = str(
            next(
                constraint
                for constraint in CatalogueCredential.__table_args__
                if getattr(constraint, "name", "") == "ck_catalogue_credentials_envelope"
            ).sqltext
        )
        named = set(re.findall(r"GLOB '([^.']+)\.", clause))

        assert named == set(credentials.KNOWN_VERSIONS)

    def test_and_refuses_every_one_outside_that_set(self):
        """The behavioural half, and it is a sweep rather than one candidate.

        **The structural read above enumerates the SQL operator where the arm it
        replaced enumerated candidate strings**, so the two miss different
        things and neither is the other's superset. Measured against the clause
        widened with `OR envelope LIKE 'v4.%'`: the regex still harvests
        `{v1, v2}` and the structural assert passes, because it can only see a
        widening spelled `GLOB '<version>.`. A sweep of insertions sees any
        spelling and cannot see a version it did not think to try, which is why
        both are here. Candidates computed from the constant, not listed.
        """
        unknown = [f"v{n}" for n in range(10) if f"v{n}" not in credentials.KNOWN_VERSIONS]
        assert unknown, "every one-digit version is recognised; widen the sweep"

        accepted = [
            version
            for version in unknown
            if self._accepted(f"{version}." + "a" * 40 + ".b.c")
        ]

        assert accepted == []

    def test_a_plaintext_password_is_refused(self):
        assert not self._accepted("hunter2")


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

    def test_an_address_with_no_scheme_binds_nothing_either(self):
        """No scheme is not another scheme, and the difference is now sealable.

        `httpx` reads `://x` as an empty scheme with a host of `x`, so this
        answered the bindable origin `://x`. Harmless while an origin was only
        compared; an origin goes into the associated data now, so it is a value
        an envelope can be sealed over, and nothing here can send to an address
        with no scheme.
        """
        assert credentials.origin_of("://x") == ""
        assert httpx.URL("://x").host == "x"

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
        credentials.put(db, "bne", BNE_URL, "alice", "hunter2")
        assert credentials.stored(db, "bne", BNE_URL) == ("alice", "hunter2")

    def test_a_password_containing_colons_survives(self, db):
        credentials.generate_key(db)
        credentials.put(db, "bne", BNE_URL, "alice", "a:b:c")
        assert credentials.stored(db, "bne", BNE_URL) == ("alice", "a:b:c")

    def test_nothing_readable_reaches_the_row(self, db):
        credentials.generate_key(db)
        credentials.put(db, "bne", BNE_URL, "alice", "hunter2")
        row = db.get(CatalogueCredential, "bne")
        assert "alice" not in row.envelope
        assert "hunter2" not in row.envelope
        assert row.envelope.startswith(f"{credentials.VERSION}.")

    def test_a_second_write_replaces_the_first(self, db):
        credentials.generate_key(db)
        credentials.put(db, "bne", BNE_URL, "alice", "hunter2")
        credentials.put(db, "bne", BNE_URL, "bob", "correcthorse")
        assert credentials.stored(db, "bne", BNE_URL) == ("bob", "correcthorse")

    def test_a_username_with_a_colon_is_refused(self, db):
        credentials.generate_key(db)
        with pytest.raises(credentials.CredentialError):
            credentials.put(db, "bne", BNE_URL, "alice:smith", "hunter2")

    def test_an_empty_half_is_refused(self, db):
        credentials.generate_key(db)
        with pytest.raises(credentials.CredentialError):
            credentials.put(db, "bne", BNE_URL, "alice", "")

    def test_storing_one_without_a_key_is_refused(self, db):
        with pytest.raises(credentials.NoKeyConfigured):
            credentials.put(db, "bne", BNE_URL, "alice", "hunter2")

    def test_forgetting_one_needs_no_key(self, db):
        """The credential nobody can read is the one somebody most wants gone."""
        credentials.generate_key(db)
        credentials.put(db, "bne", BNE_URL, "alice", "hunter2")
        credentials.store_key(credentials.generate_phrase())
        assert credentials.forget(db, "bne") is True
        assert credentials.stored_envelope(db, "bne") == ""

    def test_forgetting_nothing_is_not_an_error(self, db):
        assert credentials.forget(db, "bne") is False


class TestTheScreenIsToldWhetherOneIsUsableRatherThanOnlyWhetherOneExists:
    def test_nothing_stored(self, db):
        held = credentials.view(db, "bne", BNE_URL)
        assert (held.has_credential, held.unreadable) == (False, False)

    def test_one_stored_and_readable(self, db):
        credentials.generate_key(db)
        credentials.put(db, "bne", BNE_URL, "alice", "hunter2")
        held = credentials.view(db, "bne", BNE_URL)
        assert (held.has_credential, held.unreadable, held.username) == (
            True,
            False,
            "alice",
        )
        assert credentials.is_held(db, "bne", BNE_URL) is True

    def test_one_stored_under_a_key_that_is_gone(self, db):
        credentials.generate_key(db)
        credentials.put(db, "bne", BNE_URL, "alice", "hunter2")
        credentials.store_key(credentials.generate_phrase())
        held = credentials.view(db, "bne", BNE_URL)
        assert (held.has_credential, held.unreadable, held.username) == (True, True, "")
        assert credentials.is_held(db, "bne", BNE_URL) is False

    def test_one_stored_with_no_key_configured_at_all(self, db):
        credentials.generate_key(db)
        credentials.put(db, "bne", BNE_URL, "alice", "hunter2")
        credentials.key_file().unlink()
        held = credentials.view(db, "bne", BNE_URL)
        assert (held.has_credential, held.unreadable) == (True, True)


class TestADeploymentMayPinOneInstead:
    def test_a_pinned_credential_wins_over_the_stored_one(self, db, monkeypatch):
        credentials.generate_key(db)
        credentials.put(db, "bne", BNE_URL, "alice", "hunter2")
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
        credentials.put(db, "bne", BNE_URL, "alice", "hunter2")
        credentials.store_key(credentials.generate_phrase())
        assert credentials.for_request(db, "bne", "https://catalogue.example") is None

    def test_a_readable_one_is_bound_to_the_address_it_was_sealed_for(self, db):
        credentials.generate_key(db)
        credentials.put(db, "bne", BNE_URL, "alice", "hunter2")
        request = credentials.for_request(db, "bne", BNE_URL)
        assert request is not None
        assert request.origin == credentials.origin_of(BNE_URL)

    def test_and_asking_about_another_address_answers_none(self, db):
        """It used to answer the login, bound to whichever address was asked.

        That is the defect this binding closes: the caller's address decided
        where a sealed login went, and one caller's address is a row.
        """
        credentials.generate_key(db)
        credentials.put(db, "bne", BNE_URL, "alice", "hunter2")
        assert credentials.for_request(db, "bne", "https://catalogue.example/sru") is None


#: The one source this build ships a login for, and where it goes.
#:
#: **Read off the roster rather than named**, so a second shipped default is
#: covered by every test below on the day it is added, and so a default removed
#: from the row fails these rather than quietly passing them.
#: `TestThisBuildShipsExactlyTheDefaultsItSaysItDoes` is what keeps the set
#: itself honest.
SHIPPING = [
    source
    for source, target in targets.SEEDED.items()
    if target.shipped_credential is not None
]


def _url(source: CatalogueSource) -> str:
    return targets.SEEDED[source].base_url


def _a_key(db) -> None:
    """A key, without caring whether one of these tests already made it.

    The loops below run once per shipped default and `generate_key` refuses when
    a key exists, so a bare call would pass today and fail on the day a second
    catalogue publishes its login, which is exactly the day these tests are for.
    """
    if credentials.key_material() is None:
        credentials.generate_key(db)


class TestThisBuildShipsExactlyTheDefaultsItSaysItDoes:
    """The set of shipped logins, and what a row carrying one has to be.

    **The census, not a spot check.** A default arriving on a row nobody
    intended is the failure that has no symptom: the source simply starts
    working, and nothing on any screen says which account it is working as.
    """

    def test_exactly_one_row_ships_a_login_today(self):
        assert SHIPPING == [CatalogueSource.BNA]

    def test_a_row_that_ships_one_is_a_row_that_needs_one(self):
        for source in SHIPPING:
            assert targets.SEEDED[source].needs_key is True

    def test_and_the_construction_refuses_the_other_way_round(self):
        """The rule is enforced at construction, not only true of the roster."""
        row = targets.SEEDED[CatalogueSource.BNE]
        with pytest.raises(ValueError, match="needs no credential"):
            dataclasses.replace(
                row, shipped_credential=targets.ShippedCredential("u", "p")
            )

    @pytest.mark.parametrize(
        "username, password", [("", "p"), ("u", ""), ("a:b", "p")]
    )
    def test_a_shipped_pair_follows_the_rule_every_other_pair_follows(
        self, username, password
    ):
        """One representation for the shipped, sealed and pinned spellings."""
        with pytest.raises(ValueError):
            targets.ShippedCredential(username, password)

    def test_every_shipped_pair_would_be_accepted_by_the_store(self, db):
        """What ships has to be enterable, or an admin cannot reproduce it."""
        _a_key(db)
        for source in SHIPPING:
            pair = targets.SEEDED[source].shipped_credential
            assert pair is not None
            credentials.put(db, source.value, targets.SEEDED[source].base_url, pair.username, pair.password)


class TestAShippedLoginLosesToEverythingElse:
    """The ladder, level by level and transition by transition.

    **This is the property the owner's decision of 2026-09-07 states as a
    requirement**, so it is tested as a chain rather than as three independent
    facts: an institution with its own arrangement with the library has to be
    able to use it, and each step of getting there has to land where a person
    would expect.
    """

    def test_a_stock_install_sends_the_shipped_pair(self, db):
        for source in SHIPPING:
            shipped = targets.SEEDED[source].shipped_credential
            assert shipped is not None
            request = credentials.for_request(db, source.value, _url(source))
            assert request is not None
            assert (request.username, request.password) == (
                shipped.username,
                shipped.password,
            )

    def test_a_login_an_admin_enters_wins_over_it(self, db):
        for source in SHIPPING:
            _a_key(db)
            credentials.put(db, source.value, targets.SEEDED[source].base_url, "alice", "hunter2")
            request = credentials.for_request(db, source.value, _url(source))
            assert request is not None
            assert (request.username, request.password) == ("alice", "hunter2")

    def test_a_login_the_deployment_pins_wins_over_both(self, db, monkeypatch):
        for source in SHIPPING:
            _a_key(db)
            credentials.put(db, source.value, targets.SEEDED[source].base_url, "alice", "hunter2")
            monkeypatch.setenv(
                credentials.env_variable_name(source.value), "bob:correcthorse"
            )
            request = credentials.for_request(db, source.value, _url(source))
            assert request is not None
            assert (request.username, request.password) == ("bob", "correcthorse")

    def test_removing_the_pin_falls_back_to_what_the_admin_entered(
        self, db, monkeypatch
    ):
        for source in SHIPPING:
            _a_key(db)
            credentials.put(db, source.value, targets.SEEDED[source].base_url, "alice", "hunter2")
            variable = credentials.env_variable_name(source.value)
            monkeypatch.setenv(variable, "bob:correcthorse")
            monkeypatch.delenv(variable)
            request = credentials.for_request(db, source.value, _url(source))
            assert request is not None
            assert (request.username, request.password) == ("alice", "hunter2")

    def test_removing_the_admins_login_finds_the_shipped_one_underneath(self, db):
        """**Not nothing**, which is the transition a screen most easily lies about."""
        for source in SHIPPING:
            shipped = targets.SEEDED[source].shipped_credential
            assert shipped is not None
            _a_key(db)
            credentials.put(db, source.value, targets.SEEDED[source].base_url, "alice", "hunter2")
            credentials.forget(db, source.value)
            request = credentials.for_request(db, source.value, _url(source))
            assert request is not None
            assert (request.username, request.password) == (
                shipped.username,
                shipped.password,
            )

    def test_a_stored_login_that_cannot_be_opened_does_not_fall_through(self, db):
        """**The arm that would send a request as the wrong account.**

        A sealed login under a key that is gone is what the admin configured, so
        the source stops answering and the screen says the key is the problem.
        Falling back to the shipped pair would authenticate as somebody else
        while the screen reported a login this library entered.
        """
        for source in SHIPPING:
            _a_key(db)
            credentials.put(db, source.value, targets.SEEDED[source].base_url, "alice", "hunter2")
            credentials.store_key(credentials.generate_phrase())
            assert credentials.for_request(db, source.value, _url(source)) is None
            held = credentials.view(db, source.value, _url(source))
            assert (held.provenance, held.unreadable) == (
                CredentialProvenance.STORED,
                True,
            )

    @pytest.mark.parametrize("value", ["", " ", "bob", "bob:", ":hunter2"])
    def test_a_pinned_variable_set_to_nonsense_does_not_fall_through_either(
        self, db, monkeypatch, value
    ):
        """**Parametrised, and the empty string is why.**

        This arm asserted one spelling, `bob:`, and the spelling it did not
        carry was the one that fell through: a variable set to nothing read as
        unset, so the shipped account went out under a deployment that had said
        something about this source. A battery enumerating the ways a value can
        be wrong is only as good as its emptiest member.
        """
        for source in SHIPPING:
            monkeypatch.setenv(credentials.env_variable_name(source.value), value)
            assert credentials.for_request(db, source.value, _url(source)) is None
            held = credentials.view(db, source.value, _url(source))
            assert (held.provenance, held.unreadable) == (
                CredentialProvenance.ENV,
                True,
            )


class TestTheScreenIsToldWhichOfTheFourIsInForce:
    """An admin who cannot tell a shipped login from one they entered is the
    confusion this feature exists not to create."""

    def test_a_source_with_no_login_anywhere_says_so(self, db):
        held = credentials.view(db, "bne", BNE_URL)
        assert held.provenance is CredentialProvenance.NONE
        assert held.has_credential is False

    def test_a_shipped_one_is_named_as_shipped_rather_than_as_stored(self, db):
        for source in SHIPPING:
            held = credentials.view(db, source.value, _url(source))
            assert held.provenance is CredentialProvenance.SHIPPED
            assert (held.has_credential, held.unreadable) == (True, False)

    def test_and_it_reports_no_stored_envelope_behind_it(self, db):
        """The row is what a Remove control acts on, and there is none."""
        for source in SHIPPING:
            assert credentials.stored_envelope(db, source.value) == ""

    def test_one_an_admin_entered_is_named_as_stored(self, db):
        for source in SHIPPING:
            _a_key(db)
            credentials.put(db, source.value, targets.SEEDED[source].base_url, "alice", "hunter2")
            held = credentials.view(db, source.value, _url(source))
            assert held.provenance is CredentialProvenance.STORED
            assert held.username == "alice"

    def test_a_pinned_one_is_named_as_pinned(self, db, monkeypatch):
        for source in SHIPPING:
            monkeypatch.setenv(
                credentials.env_variable_name(source.value), "bob:correcthorse"
            )
            held = credentials.view(db, source.value, _url(source))
            assert held.provenance is CredentialProvenance.ENV
            assert held.username == "bob"

    def test_a_shipped_source_counts_as_ready_on_an_install_that_typed_nothing(
        self, db
    ):
        for source in SHIPPING:
            assert credentials.is_held(db, source.value, _url(source)) is True


class TestAShippedLoginGoesOnlyWhereItsLibraryPublishedIt:
    """The origin binding, which is the shipped level's own rule.

    **Separate from `Credential.header_for`**, which binds whatever pair it was
    built with to whatever origin it was built for. This decides whether the
    pair is handed over at all, and it answers off the roster row rather than
    off the caller, so an address that is not the published one loses the
    default rather than carrying it there.
    """

    def test_it_is_handed_over_at_the_address_the_roster_holds(self):
        for source in SHIPPING:
            assert credentials.shipped(source.value, _url(source)) is not None

    def test_a_different_path_at_the_same_origin_is_still_the_same_origin(self):
        """The binding is the origin, not the address: the library publishes one
        server and this app builds more than one path against it."""
        assert credentials.shipped("bna", "http://200.123.191.9:9991/other") is not None

    @pytest.mark.parametrize(
        "url",
        [
            "http://evil.test:9991/BNA01",
            "https://200.123.191.9:9991/BNA01",
            "http://200.123.191.9:9992/BNA01",
            "http://200.123.191.9@evil.test:9991/BNA01",
            "",
            "not a url",
        ],
    )
    def test_and_nowhere_else(self, url):
        assert credentials.shipped("bna", url) is None

    def test_and_the_request_path_withholds_it_there_too(self, db):
        assert credentials.for_request(db, "bna", "http://evil.test:9991/x") is None

    def test_two_addresses_the_parser_refuses_do_not_compare_equal(
        self, monkeypatch
    ):
        """**Empty never matches**, which is `origin_of`'s own rule.

        Unreachable from today's roster, whose addresses all parse, so it is
        driven rather than left stated: a row whose `base_url` the parser
        refuses would otherwise hand the pair to any other address the parser
        also refuses, both sides comparing equal at the empty string.
        """
        row = targets.SEEDED[CatalogueSource.BNA]
        broken = dataclasses.replace(row, base_url="http://[::1")
        # **Replace the mapping rather than write through it**, which is the
        # code change the register names as the trigger rather than a way
        # around it. The literal is never bound to a name at all, so there
        # is nothing any module could write through, tests included.
        #
        # `targets.SEEDED_ORIGINS` is computed at import and still describes
        # the shipped roster, so a test substituting a row is measuring a world
        # where the two disagree. Nothing reads that constant today, and this
        # is the reason to replace the object rather than reach past it when
        # something does.
        monkeypatch.setattr(
            targets,
            "SEEDED",
            MappingProxyType({**targets.SEEDED, CatalogueSource.BNA: broken}),
        )
        assert credentials.origin_of(broken.base_url) == ""
        assert credentials.shipped("bna", "http://[::1") is None
        assert credentials.shipped("bna", "not a url either") is None

    def test_the_screen_and_the_sender_part_company_at_an_address_nothing_parses(
        self, db, monkeypatch
    ):
        """**`is_held` answers the sender; `view` answers the screen.**

        The whole of what `is_held` gained by asking `for_request` rather than
        `view` is this one state, and nothing on the shipping roster reaches it:
        all eleven addresses parse, so reverting `is_held` to the `view` form
        left the suite green. Driven here with the same instrument the arm above
        uses, and it pins both halves of the claim at once.

        Its consumer, `settings_store._sources_with_a_credential`, decides
        whether an ISBN is sent to a third party. Reporting a source ready when
        nothing can be sent to it is what that function's own docstring says it
        exists to stop.

        A pinned variable rather than a sealed login, so this needs no key.
        """
        row = targets.SEEDED[CatalogueSource.BNA]
        broken = dataclasses.replace(row, base_url="http://[::1")
        # **Replace the mapping rather than write through it**, which is the
        # code change the register names as the trigger rather than a way
        # around it. The literal is never bound to a name at all, so there
        # is nothing any module could write through, tests included.
        #
        # `targets.SEEDED_ORIGINS` is computed at import and still describes
        # the shipped roster, so a test substituting a row is measuring a world
        # where the two disagree. Nothing reads that constant today, and this
        # is the reason to replace the object rather than reach past it when
        # something does.
        monkeypatch.setattr(
            targets,
            "SEEDED",
            MappingProxyType({**targets.SEEDED, CatalogueSource.BNA: broken}),
        )
        monkeypatch.setenv("CATALOGUE_CREDENTIAL_BNA", "bob:correcthorse")
        assert credentials.origin_of(broken.base_url) == ""

        # The screen keeps the login the deployment pinned, and with it the
        # sentence naming the variable. Answering "none" here would take that
        # off a screen for a source that really is configured.
        seen = credentials.view(db, "bna", broken.base_url)
        assert (seen.provenance, seen.has_credential, seen.unreadable) == (
            CredentialProvenance.ENV,
            True,
            False,
        )
        # The sender answers no, because nothing can be sent to that address.
        assert credentials.for_request(db, "bna", broken.base_url) is None
        assert credentials.is_held(db, "bna", broken.base_url) is False

    def test_a_source_this_build_does_not_know_ships_nothing(self):
        assert credentials.shipped("../../books/5?", _url(CatalogueSource.BNA)) is None

    def test_and_neither_does_one_that_ships_no_default(self):
        assert credentials.shipped("bne", BNE_URL) is None


class TestThePurposeStringNamesExactlyOneSource:
    """What stops an envelope opening on a row it was not written for."""

    def test_the_purpose_string_differs_per_source(self):
        purposes = {
            credentials._purpose(source.value, "https://a.invalid:443")
            for source in CatalogueSource
        }
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
        credentials.put(db, "bne", BNE_URL, "alice", "hunter2")
        credentials.forget_key()
        with pytest.raises(credentials.KeyConfigurationError) as refusal:
            credentials.generate_key(db)
        assert "recovery phrase" in str(refusal.value)

    def test_a_login_from_before_the_binding_is_blamed_on_the_key_too(
        self, db, key: bytes
    ):
        """It used to get its own sentence, and that was right while no key
        opened it. The phrase now does, so sending somebody to remove it would
        be sending them to destroy a login that is about to work.

        Reached by restoring an archive taken before the binding, which is the
        ordinary move-to-a-new-machine case.
        """
        db.add(
            CatalogueCredential(
                source="bne",
                envelope=sealed_before_the_origin_was_bound(key, "bne", "a:b"),
            )
        )
        db.commit()

        with pytest.raises(credentials.KeyConfigurationError) as refusal:
            credentials.generate_key(db)

        said = str(refusal.value)
        assert "recovery phrase" in said
        assert "sealed before" not in said

    def test_and_the_phrase_then_opens_it(self, db, key: bytes):
        """The half that makes the sentence above true rather than convenient."""
        db.add(
            CatalogueCredential(
                source="bne",
                envelope=sealed_before_the_origin_was_bound(key, "bne", "alice:hunter2"),
            )
        )
        db.commit()
        credentials.store_key(credentials.key_to_phrase(key))
        assert credentials.stored(db, "bne", BNE_URL) == ("alice", "hunter2")

    def test_both_kinds_of_stranded_login_are_named_in_one_sentence(
        self, db, key: bytes
    ):
        """One cause now, so one sentence naming both sources rather than two
        sentences splitting them."""
        credentials.store_key(credentials.key_to_phrase(key))
        credentials.put(db, "bne", BNE_URL, "alice", "hunter2")
        db.add(
            CatalogueCredential(
                source="dnb",
                envelope=sealed_before_the_origin_was_bound(key, "dnb", "a:b"),
            )
        )
        db.commit()
        credentials.forget_key()

        with pytest.raises(credentials.KeyConfigurationError) as refusal:
            credentials.generate_key(db)

        said = str(refusal.value)
        assert "recovery phrase" in said
        assert "bne" in said and "dnb" in said

    def test_the_phrase_opens_them_again(self, db):
        phrase, _ = credentials.generate_key(db)
        credentials.put(db, "bne", BNE_URL, "alice", "hunter2")
        credentials.forget_key()
        credentials.store_key(phrase)
        assert credentials.stored(db, "bne", BNE_URL) == ("alice", "hunter2")

    def test_removing_the_logins_clears_the_way_for_a_new_key(self, db):
        credentials.generate_key(db)
        credentials.put(db, "bne", BNE_URL, "alice", "hunter2")
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
    """Silently ignoring it offered an edit on a screen and used the stored one.

    **The empty string is in both batteries and was in neither**, which is the
    hole a security seat measured on 2026-09-07: it is the commonest way of
    setting one of these wrongly and it was the one spelling read as unset. The
    level below was a stored login before a default shipped and is an account
    nobody in the deployment chose now.
    """

    @pytest.mark.parametrize("value", ["", " ", "bob", "bob:", ":hunter2", ":"])
    def test_a_value_that_is_not_a_credential_raises(self, monkeypatch, value):
        monkeypatch.setenv("CATALOGUE_CREDENTIAL_BNE", value)
        with pytest.raises(credentials.CredentialError):
            credentials.from_env("bne")

    @pytest.mark.parametrize("value", ["", " ", "bob", "bob:", ":hunter2"])
    def test_and_the_deployment_still_counts_as_having_pinned_it(
        self, monkeypatch, value
    ):
        monkeypatch.setenv("CATALOGUE_CREDENTIAL_BNE", value)
        assert credentials.is_from_env("bne") is True

    def test_an_unset_variable_is_still_told_apart_from_an_empty_one(self):
        assert credentials.is_from_env("bne") is False
        assert credentials.from_env("bne") is None

    def test_the_screen_is_told_it_is_pinned_and_unusable(self, db, monkeypatch):
        monkeypatch.setenv("CATALOGUE_CREDENTIAL_BNE", "bob:")
        held = credentials.view(db, "bne", BNE_URL)
        assert (held.provenance, held.unreadable) == (CredentialProvenance.ENV, True)

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
        credentials.put(db, "bne", BNE_URL, "alice", "hunter2")
        state = credentials.key_state()
        credentials.key_file().unlink()
        assert credentials.view(db, "bne", BNE_URL, state).username == "alice"
        assert credentials.view(db, "bne", BNE_URL).unreadable is True

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
        credentials.put(db, "a-catalogue-that-went-away", ORPHAN_URL, "alice", "hunter2")
        credentials.store_key(credentials.generate_phrase())
        assert credentials.unreadable_sources(db) == ["a-catalogue-that-went-away"]

    def test_and_still_blocks_a_new_key_with_a_number_that_matches(self, db):
        credentials.generate_key(db)
        credentials.put(db, "a-catalogue-that-went-away", ORPHAN_URL, "alice", "hunter2")
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
        credentials.put(db, "bne", BNE_URL, "alice", "hunter2")
        credentials.forget_key()
        monkeypatch.setenv("CATALOGUE_CREDENTIAL_BNE", "bob:correcthorse")

        assert credentials.view(db, "bne", BNE_URL).unreadable is False
        assert credentials.unreadable_sources(db) == ["bne"]
        with pytest.raises(credentials.KeyConfigurationError):
            credentials.generate_key(db)

    def test_and_the_phrase_still_opens_it_afterwards(self, db, monkeypatch):
        phrase, _ = credentials.generate_key(db)
        credentials.put(db, "bne", BNE_URL, "alice", "hunter2")
        credentials.forget_key()
        monkeypatch.setenv("CATALOGUE_CREDENTIAL_BNE", "bob:correcthorse")
        monkeypatch.delenv("CATALOGUE_CREDENTIAL_BNE")
        credentials.store_key(phrase)
        assert credentials.stored(db, "bne", BNE_URL) == ("alice", "hunter2")

    def test_a_readable_login_is_not_counted(self, db):
        credentials.generate_key(db)
        credentials.put(db, "bne", BNE_URL, "alice", "hunter2")
        assert credentials.unreadable_sources(db) == []

    def test_a_damaged_envelope_on_a_pinned_source_is_no_longer_listed(
        self, db, monkeypatch
    ):
        """The accepted loss, pinned so that it stays a decision.

        An envelope is sealed over its address now, and this function has none,
        so it answers from the version and the generation tag. A `v2` envelope
        of this key's generation whose ciphertext an archive damaged passes that
        and is not listed, where opening it used to fail and list it. `view`
        covers every row it is asked about and is not asked about a pinned
        source, so this is one of the two places the loss lands.
        `unreadable_sources`' docstring carries the reasoning and why restoring
        it would cost an arm per kind of row.
        """
        credentials.generate_key(db)
        credentials.put(db, "bne", BNE_URL, "alice", "hunter2")
        row = db.get(CatalogueCredential, "bne")
        version, generation, nonce, sealed = row.envelope.split(".")
        row.envelope = ".".join((version, generation, nonce, "AAAA" + sealed[4:]))
        db.commit()
        monkeypatch.setenv("CATALOGUE_CREDENTIAL_BNE", "bob:correcthorse")

        assert credentials.unreadable_sources(db) == []
        assert credentials.view(db, "bne", BNE_URL).unreadable is False
        with pytest.raises(credentials.UnreadableCredential):
            credentials.stored(db, "bne", BNE_URL)

    def test_but_a_key_that_cannot_open_it_still_lists_it(self, db):
        """The arm the test above must not be read as weakening.

        What `unreadable_sources` answers is still the key's question, and that
        is the one `generate_key` asks. Rotating the key lists the same row.
        """
        credentials.generate_key(db)
        credentials.put(db, "bne", BNE_URL, "alice", "hunter2")
        credentials.store_key(credentials.generate_phrase())

        assert credentials.unreadable_sources(db) == ["bne"]

    def test_they_are_reported_in_a_stable_order(self, db):
        credentials.generate_key(db)
        for source in ("dnb", "bne", "loc"):
            address = targets.SEEDED[CatalogueSource(source)].base_url
            credentials.put(db, source, address, "alice", "hunter2")
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
