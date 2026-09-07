"""A login at somebody else's catalogue: sealed at rest, bound to one origin.

**This is not one of the app's own secrets, and that is the whole reason this
module exists rather than a row in `settings`.** Every secret `settings_store`
holds is this deployment's: an API key it uses, a mail password for its own
mailbox, a webhook secret it signs with. Losing one costs this library an
account it owns. What is held here is **an institution's account with a third
party**, and losing one costs somebody else's login. `settings` is written in
plaintext and `backup.py` copies it wholesale, so a credential of this kind put
there would sit unmasked in every archive an admin can download.

## Three kinds of secret, and they are not interchangeable

| Kind | Owner | Lives in | Replaced by | If that person goes |
|---|---|---|---|---|
| The app's own | the deployment | `settings`, plaintext | any admin | nothing |
| **An account elsewhere** | the library | here, sealed | any admin | nothing |
| A member's own login | one member | **its own table** | that member | deleted with them |

**Distinguished by construction rather than by being named.** Every envelope is
sealed against an additional-authenticated-data string carrying its kind, its
subject and **the origin it is for** (`_purpose`). A ciphertext moved between
rows, between kinds, between subjects or beside an address somebody else wrote,
by a hand-edited archive or a stray `UPDATE`, fails authentication loudly
instead of decrypting into somebody else's request.

**The origin is in there because the address stopped being a constant.** While
every caller passed `targets.SEEDED[...].base_url` the source alone was enough:
a module constant has no writer. `opds_servers.base_url` is a row, and
`backup.restore` inserts through Core, so an archive keeping a legitimate key
and changing only the address beside it sent a household's sealed login to a
host the archive named. The attacker needed a copy of the archive and not the
key, which is the loss sealing was bought to prevent. Bound here, an envelope is
unopenable at an address it was not sealed for **whichever writer moved the
row**, rather than only through the one route that was measured.
`backup._without_household_logins` stays as the belt to this brace.

**The third kind gets its own table when it arrives, not a nullable column
here.** Ownership changes the deletion rule, the visibility rule and the read
path, all three; one table answering two access-control questions is how the
answer to one of them gets applied to the other.

## Four levels, one walk, and the shipped one is at the bottom

`_resolve` is the ladder and everything asks it: the deployment's pinned
variable, then a login an admin entered, then a login the catalogue publishes
about itself and this build carries, then nothing. **The screen and the outbound
request walk the same one**, so a source cannot authenticate as something other
than what an admin is told.

**Only the fourth level is a value in a published file, and that is the owner's
decision of 2026-09-07 rather than a hole.** `targets.ShippedCredential` carries
the argument and is where to read before removing one. What makes it safe is the
order: a default that could beat an admin's entry would be the version of the
feature that was refused.

## Where the key comes from

**A seam, not one `os.environ` read**, and the environment is the first source
rather than the only conceivable one. A desktop install has no operator and no
deploy-time environment, and a confined package may not have a writable place an
environment variable can come from either. `KEY_SOURCES` is the whole of that
seam: a keychain reader is one more entry and touches neither the scheme, the
generation tag nor the migration.

**No default key, ever, and that rule is untouched by the shipped login below.**
`key_material()` has no fallback constant, so a published artefact ships none.
The two are opposite cases and it is worth saying which is which: a shipped
login is a value its own issuer published, and a shipped key would be the thing
that opens every login this deployment sealed for itself.
`tests/test_credentials.py::TestAKeyIsNeverInvented` is what stops one arriving.

**An install with no key starts, and says what it cannot do.** Storing a
credential is refused with a message naming the variables; a stored one reports
that it needs re-entering; nothing outbound carries one. Refusing to boot was
rejected: most deployments store no credential, and refusing to start over an
unused feature breaks every existing install on upgrade.

**Two sources naming a key at once is refused.** Silently preferring one is how
a rotation destroys every stored credential while looking like it worked.

## The cost, and it is real

**A lost or rotated key makes every stored credential unreadable, and they have
to be typed again.** The generation tag is what makes that a sentence somebody
can act on rather than a silent decrypt into nonsense. The cost is stated where
a person meets it: beside the field on the settings screen, in
`docs/security.md`, and at `backup.py`'s entry for this table, which is the
sharper of the two because an archive carries the ciphertext and never the key.

## What does not happen to a credential

* **It never crosses a mirror between instances.** A mirror carries a library; a
  credential is a login at a server the receiving instance was never given. A
  decision, stated here because the code that would have to honour it is not
  written yet.
* **It never leaves the origin it was set for.** `Credential.header_for` is that
  rule, and it is a property of the secret rather than of the transport: a
  redirect that leaks a page is an information leak, a redirect that carries an
  `Authorization` header off host is account theft. `fetch.py` refuses the hop
  as well, and the two are deliberately not one guard.
* **It is never rendered.** Both halves are `repr=False` and `__str__` is
  overridden, so a `logger.exception` over a frozen dataclass cannot print one.
"""

import hmac
import logging
import os
import re
import secrets
import unicodedata
from base64 import b64encode, urlsafe_b64decode, urlsafe_b64encode
from collections.abc import Callable
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Final

import httpx
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from mnemonic import Mnemonic
from sqlalchemy.orm import Session

import config
import targets
from enums import CatalogueSource, CredentialProvenance
from models import CatalogueCredential

logger = logging.getLogger("endpaper.credentials")


class CredentialError(Exception):
    """Anything this module refuses to do. Never carries a secret in its message."""


class NoKeyConfigured(CredentialError):
    """No source named a key, so nothing can be sealed or opened."""


class KeyConfigurationError(CredentialError):
    """A key was named and cannot be used: too short, unreadable, or named twice."""


class BadRecoveryPhrase(KeyConfigurationError):
    """The words are not a phrase: wrong count, unknown word, failed checksum.

    **A subclass, so every existing handler still catches it**, and separate so
    a route can answer 422 rather than 409. They are different things: a phrase
    somebody mistyped is a bad request, and a key the deployment pinned
    elsewhere is a conflict with the deployment. One status for both told a
    client nothing it could act on differently.
    """


class WrongKeyGeneration(CredentialError):
    """This envelope was written under a different key. Re-enter the credential."""


class UnreadableCredential(CredentialError):
    """The envelope is malformed, or the current key does not authenticate it."""


class UnboundCredential(CredentialError):
    """Sealed before a credential carried the address it may be sent to.

    **A refusal of its own rather than an unreadable row, because the remedy
    differs and nothing else could say so.** A `v1` envelope fails the current
    scheme's authentication for a reason that is neither a rotated key nor a
    damaged row: it was written correctly under a scheme that bound less. Told
    apart from the key, the sentence is "type this login again"; folded into
    `UnreadableCredential` it reads as corruption, and folded into
    `WrongKeyGeneration` it sends somebody looking for a recovery phrase that
    would not help.

    **Readable without any key**, which is what lets `unreadable_sources`
    answer without an address: the version is in the clear.
    """


#: A key is exactly this many bytes, and it is always written as a phrase.
#:
#: Matches `config.MIN_SECRET_KEY_LENGTH` in number and in reasoning: a key
#: shorter than the hash output adds no security beyond its length. Here it is
#: an invariant rather than a floor, because 32 bytes is what 24 words carry.
KEY_BYTES: Final = 32

#: 24 words, and one length rather than the five BIP-39 allows.
#:
#: 256 bits of entropy plus an 8 bit checksum. Accepting 12 as well would mean a
#: person who wrote some of it down cannot tell whether they finished, and would
#: put two strengths behind one field for no gain.
PHRASE_WORDS: Final = 24

#: BIP-39 English. **The encoding is not invented here and must not be.**
#:
#: A phrase is the key's one representation: in a variable, in a keychain, in a
#: file, on a screen and on a piece of paper. One representation rather than "a
#: string in the environment, words on the screen", because two encodings of one
#: key are two things that can disagree, and the disagreement is silent.
#:
#: **The checksum is the whole reason for a standard encoding rather than
#: base64.** A mistyped or misread word fails at input instead of producing a
#: different key that opens nothing and says nothing, which is exactly the
#: failure the generation tag exists to prevent, arriving by a second route.
_WORDS: Final = Mnemonic("english")

#: Where the keychain entry lives, for the deployments that have one.
_KEYCHAIN_SERVICE: Final = "endpaper"
_KEYCHAIN_ENTRY: Final = "credential-encryption-key"

#: The key file's name under `DATA_DIR`, when no path was named.
_KEY_FILE_NAME: Final = "credential-key"


#: Every environment variable this module reads for a **key**.
#:
#: **A tuple rather than three string literals spread over the module**, because
#: `tests/conftest.py` has to unset all of them before the app is imported: a
#: value in the shell that happens to run the suite would otherwise win over
#: whatever a test set up, and the test would pass without asserting anything.
#: That is not hypothetical here; the conftest comment beside the pop records
#: the same trap catching `GOOGLE_BOOKS_API_KEY` and then the mail settings.
#: Reading this rather than restating it means a fourth variable is disarmed the
#: moment it is added.
#:
#: The per-source pins are not here because they are generated from a prefix:
#: `env_variable_name` is their single definition.
ENV_VARIABLES: Final[tuple[str, ...]] = (
    "CREDENTIAL_ENCRYPTION_KEY",
    "CREDENTIAL_ENCRYPTION_KEY_FILE",
)


def _from_value() -> str:
    """The phrase straight from the environment. Read only, by nature."""
    return os.getenv("CREDENTIAL_ENCRYPTION_KEY", "").strip()


def _keyring() -> Any | None:
    """The keyring module, or None where this build does not carry it.

    **An optional dependency, and the container deliberately does not install
    it.** The published image is Alpine with no session bus and no keychain, so
    `keyring` there would be four packages that can only ever answer "no backend
    available". The desktop and mobile builds install the `desktop` extra, and
    the test suite carries it in the dev group so this path is exercised rather
    than asserted.
    """
    try:
        import keyring
        import keyring.errors  # noqa: F401  bound for `module.errors` below
    except ImportError:
        return None
    return keyring


def _from_keychain() -> str:
    """The phrase out of the OS keychain, or empty where there is no keychain.

    **A missing backend and a locked one are not the same answer, and treating
    them alike is the dangerous shape.** No backend means this platform has no
    keychain, which is ordinary and answers empty. A keychain that exists and
    refused (locked, or failed to initialise) must raise: answering empty there
    would report the deployment as having no key, and the sentence a person then
    reads is "generate one", which replaces the key that opens their
    credentials.
    """
    module = _keyring()
    if module is None:
        return ""
    try:
        return (module.get_password(_KEYCHAIN_SERVICE, _KEYCHAIN_ENTRY) or "").strip()
    except module.errors.NoKeyringError:
        return ""
    except module.errors.KeyringError as error:
        raise KeyConfigurationError(
            "This machine's keychain could not be read. Unlock it and try again."
        ) from error


def _to_keychain(phrase: str) -> None:
    module = _keyring()
    if module is None:
        raise KeyConfigurationError("This build has no keychain support.")
    try:
        module.set_password(_KEYCHAIN_SERVICE, _KEYCHAIN_ENTRY, phrase)
    except module.errors.KeyringError as error:
        raise KeyConfigurationError("This machine's keychain refused to store the key.") from error


def _clear_keychain() -> None:
    module = _keyring()
    if module is None:
        return
    try:
        module.delete_password(_KEYCHAIN_SERVICE, _KEYCHAIN_ENTRY)
    except module.errors.KeyringError:
        # Already absent is the common case and is not a failure. A keychain
        # that refused is reported by the write that follows, which is the call
        # whose failure actually matters.
        return


def _keychain_available() -> bool:
    """Whether this machine has a keychain that answers at all."""
    module = _keyring()
    if module is None:
        return False
    try:
        module.get_password(_KEYCHAIN_SERVICE, _KEYCHAIN_ENTRY)
    except module.errors.NoKeyringError:
        return False
    except module.errors.KeyringError:
        # It exists and is unhappy. Reporting it as available is right: the
        # refusal belongs to the read or the write, which say what is wrong.
        return True
    return True


def key_file() -> Path:
    """Where a key file lives: where an operator said, else beside the database.

    **`DATA_DIR` rather than a second volume, and the consequence is stated
    rather than implied.** On a machine nobody administers there is one place
    the application may write, so the key sits on the same disk as the database
    it protects. What that buys is still real and is exactly what the ticket
    claims: the **archive** carries ciphertext and never the key, because
    `backup.py` writes a manifest of tables and the covers directory rather than
    a copy of `DATA_DIR`. What it does not buy is protection from somebody
    holding the disk, and this docstring is where that stops being implied.
    """
    named = os.getenv("CREDENTIAL_ENCRYPTION_KEY_FILE", "").strip()
    return Path(named) if named else config.DATA_DIR / _KEY_FILE_NAME


def _from_file() -> str:
    """The phrase out of a file, for the deployments whose key arrives as one.

    A Docker secret and a Kubernetes Secret both arrive as a file, and a
    confined package may be allowed one under its own data directory where it is
    not allowed an environment. Absent is empty; unreadable raises, for the
    reason a locked keychain does.
    """
    path = key_file()
    try:
        return path.read_text("utf-8").strip()
    except FileNotFoundError:
        return ""
    except OSError as error:
        raise KeyConfigurationError(f"The key file at {path} exists and could not be read.") from error


def _to_file(phrase: str) -> None:
    """Write the key file, never readable by anyone but its owner.

    **`fchmod` on the descriptor before the write, not `chmod` on the path
    after it.** `O_CREAT`'s mode applies only when it creates, so a file that
    already existed at 0644 stayed 0644 for the length of the write with the
    phrase in it, and the `chmod` that followed narrowed it afterwards. That is
    the exact case the mode argument was supposed to cover, and it did not.
    Measured 2026-09-06 against a pre-existing 0644 file.

    **`O_NOFOLLOW`**, because `DATA_DIR` is a directory the application does not
    own on every deployment, and writing through a symlink planted at this path
    writes the key wherever it points.

    An `OSError` becomes a refusal this module's callers already handle: a read
    only data directory is a deployment fact to report on a screen, not a 500 on
    a button.
    """
    path = key_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600
        )
        os.fchmod(handle, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as opened:
            opened.write(phrase + "\n")
    except OSError as error:
        raise KeyConfigurationError(
            f"The key file at {path} could not be written."
        ) from error


def _file_is_writable() -> bool:
    """Whether a key file could actually be created where one would go.

    **Not a constant True, which is what it was.** `can_generate` is what a
    screen keys off to offer "create a key", and answering yes on a read only
    data directory turned a refusal that names the problem into an unhandled
    `OSError` and a 500. The directory is probed rather than the file, because
    the file is what does not exist yet.
    """
    path = key_file()
    if path.exists():
        return os.access(path, os.W_OK)
    parent = path.parent
    return parent.is_dir() and os.access(parent, os.W_OK)


def _clear_file() -> None:
    key_file().unlink(missing_ok=True)


@dataclass(frozen=True)
class KeySource:
    """One place a key may live, and what may be done to it there.

    `name` is what an operator has to change, so a refusal can name it rather
    than saying "the environment" and sending somebody through a compose file.
    `read` answers the empty string when this source holds nothing, which is how
    "unset" is told apart from "set to something unusable": the second raises.

    `write` is None for a source this application cannot put a key into. The
    environment is the only one: a process cannot set a variable for its own
    next start.
    """

    #: What a screen shows, translated. **Not `name`**, which is English server
    #: prose: interpolated into a translated sentence it produced "Ein Schlüssel
    #: liegt vor, verwahrt in this machine's keychain." A token is the half a
    #: catalogue can carry three phrases for.
    token: str
    name: str
    read: Callable[[], str]
    write: Callable[[str], None] | None = None
    clear: Callable[[], None] | None = None
    available: Callable[[], bool] = lambda: True

    @property
    def writable(self) -> bool:
        return self.write is not None and self.available()


#: Every place a key may come from, in the order they are preferred.
#:
#: **Three, and the order is a decision.** The environment first, because an
#: operator who pinned one meant it and nothing this application does should
#: quietly beat it. The keychain next, because on a machine that has one it is
#: the only store that is not simply a file on the same disk. The file last,
#: because it is the fallback that always exists.
#:
#: **The same order is the write order**, so a key generated on a desktop lands
#: in the keychain and a key generated in a container lands in a file, without
#: either being a special case anywhere else.
KEY_SOURCES: Final[tuple[KeySource, ...]] = (
    KeySource("env", "CREDENTIAL_ENCRYPTION_KEY", _from_value),
    KeySource(
        "keychain",
        "this machine's keychain",
        _from_keychain,
        _to_keychain,
        _clear_keychain,
        _keychain_available,
    ),
    KeySource(
        "file", "the key file", _from_file, _to_file, _clear_file, _file_is_writable
    ),
)


def _supplied() -> list[tuple[KeySource, bytes]]:
    """Every source holding a key, decoded, in preference order.

    Decoded here rather than at the point of use so that a mangled phrase in a
    source nobody is looking at is still reported: a key that fails its checksum
    is not a key, whichever store it came from.
    """
    held: list[tuple[KeySource, bytes]] = []
    for source in KEY_SOURCES:
        phrase = source.read()
        if not phrase:
            continue
        try:
            held.append((source, phrase_to_key(phrase)))
        except KeyConfigurationError as error:
            raise KeyConfigurationError(f"{source.name}: {error}") from None
    return held


def key_material() -> bytes | None:
    """The configured key, or None when no source holds one.

    **Two sources holding the *same* key is ordinary; two holding different keys
    is refused.** The first happens the moment somebody types a recovery phrase
    back in on a machine that also has a file, and refusing it would be hostile
    for no gain. The second is the dangerous one: whichever this preferred, the
    other store's owner would watch their credentials stop opening and be told
    nothing about why. The comparison is on the decoded keys, so it never has to
    put a phrase anywhere near a message.

    **No default, ever.** There is no fallback constant here, so a published
    artefact ships no key.
    `tests/test_credentials.py::TestAKeyIsNeverInvented` is what stops one
    arriving.
    """
    held = _supplied()
    if not held:
        return None
    if len({material for _, material in held}) > 1:
        raise KeyConfigurationError(
            "Different encryption keys are configured in "
            + " and ".join(source.name for source, _ in held)
            + ". Leave exactly one of them in place."
        )
    return held[0][1]


def key_location() -> str:
    """Which source the key in force came from, as a token, or empty.

    A token rather than a sentence, because the screen puts this inside a
    translated line. Never the key itself: reporting *where* a value comes from
    is not reporting the value, which is the rule `settings_store.is_from_env`
    already runs on.
    """
    held = _supplied()
    return held[0][0].token if held else ""


def store_key(phrase: str) -> str:
    """Put a key where this machine can keep it, and leave exactly one copy.

    **Every other writable source is cleared**, which is what keeps
    `key_material`'s agreement rule from being tripped by this function itself.
    Typing a recovery phrase back in on a machine that already has a key file
    would otherwise leave the old key beside the new one and refuse every read.

    **The environment is refused rather than worked around.** A process cannot
    set a variable for its own next start, so a key pinned there and a different
    one stored here is a disagreement this function would be creating on
    purpose.
    """
    material = phrase_to_key(phrase)
    pinned = _from_value()
    if pinned and phrase_to_key(pinned) != material:
        raise KeyConfigurationError(
            "CREDENTIAL_ENCRYPTION_KEY pins a different key for this deployment. "
            "Change it where the app is configured, or clear it."
        )
    written = ""
    for source in KEY_SOURCES:
        write = source.write
        if write is None or not source.available():
            continue
        if not written:
            write(normalise_phrase(phrase))
            written = source.token
        elif source.clear is not None:
            source.clear()
    if not written:
        raise KeyConfigurationError(
            "There is nowhere on this machine to keep an encryption key. Set "
            "CREDENTIAL_ENCRYPTION_KEY where the app is configured."
        )
    return written


def generate_key(db: Session) -> tuple[str, str]:
    """Make a key, store it, and hand back the phrase **once**.

    **The only function in this application that returns a key to a caller**, and
    the only one that may. It refuses when a key already exists, which is what
    makes "shown once" a property of the server rather than a promise the
    browser makes: there is no call that renders an existing key, so no amount
    of replaying this one re-displays it.

    **It also refuses when a sealed credential exists and no key does**, and
    that arm is the one that matters on a machine nobody administers. A restore
    onto a new laptop brings the rows and not the key, so this button would mint
    a second key, report every restored login as unreadable, and leave the
    phrase in somebody's drawer looking wrong. Ciphertext in the table is proof
    that a key existed, so the answer there is to type the phrase in, not to
    make a new one. Somebody who genuinely lost the phrase removes the logins
    first, which `forget` does without a key for exactly this reason.
    """
    if key_material() is not None:
        raise KeyConfigurationError(
            "This deployment already has an encryption key, and it cannot be "
            "shown again. To replace it, discard the key first."
        )
    stranded = unreadable_sources(db)
    if stranded:
        raise KeyConfigurationError(_stranded_refusal(db, stranded))
    phrase = generate_phrase()
    return phrase, store_key(phrase)


def _stranded_refusal(db: Session, stranded: list[str]) -> str:
    """Why a new key is refused, and it is two causes with two remedies.

    **The version is in the clear, which is what lets this tell them apart with
    no key in hand**, and telling them apart is the whole reason the tag and the
    version sit outside the ciphertext. An envelope sealed before a credential
    carried its address is opened by no key at all, so naming the recovery
    phrase for one sends somebody to find the phrase, watch it be accepted, and
    discover the login still shut. That is the sentence `UnboundCredential`
    exists to prevent, and it reaches a person here rather than at `unseal`,
    because this message is written before anything is opened.

    Only a restore of an archive taken before the binding produces the second
    kind: revision `d9c1f47b2a06` removed the rows it found. That is the
    ordinary move-to-a-new-machine case `backup._TABLES` describes, which is
    exactly the one this refusal exists for.
    """
    superseded = [
        source
        for source in stranded
        if stored_envelope(db, source).split(".")[0] != VERSION
    ]
    said: list[str] = []
    if keyed := [source for source in stranded if source not in superseded]:
        said.append(
            f"Catalogue logins are stored for {', '.join(keyed)} and were sealed "
            "with a key this machine no longer has. Enter the recovery phrase to "
            "open them. If it is lost, remove those logins and then make a new key."
        )
    if superseded:
        said.append(
            f"Catalogue logins are stored for {', '.join(superseded)} and were "
            "sealed before a credential carried the address it may be sent to, so "
            "no key opens them. Remove those logins and enter them again."
        )
    return " ".join(said)


def forget_key() -> int:
    """Drop the key this machine holds. Returns how many stores were cleared.

    **The way back from "I closed the tab without writing the words down".**
    Without it `generate_key` refuses forever and `store_key` wants a phrase
    nobody has, which is a deployment stuck over a key protecting nothing. It
    strands whatever the key was opening, so the caller reports that count
    rather than this function hiding it.

    The environment is not cleared, because a process cannot unset a variable
    for its own next start; a pinned key is refused instead.
    """
    if _from_value():
        raise KeyConfigurationError(
            "CREDENTIAL_ENCRYPTION_KEY pins this deployment's key. Clear it where "
            "the app is configured."
        )
    cleared = 0
    for source in KEY_SOURCES:
        if not source.read():
            continue
        clear = source.clear
        if clear is None or not source.available():
            # **Reads but cannot be cleared**, which is a real deployment rather
            # than a corner: `CREDENTIAL_ENCRYPTION_KEY_FILE` on a read only
            # mount is the shape a Kubernetes Secret and a Docker secret both
            # take, and `_from_file` reads it while `_file_is_writable` refuses
            # it. Skipping it left the key in force and answered as though the
            # key had been discarded, which is the silent success this project
            # keeps writing rules against.
            raise KeyConfigurationError(
                f"The key in {source.name} cannot be removed from here. Remove it "
                "where the app is configured."
            )
        clear()
        cleared += 1
    return cleared


#: What a deployment with no key is told, wherever that is met.
#:
#: **A constant because two callers raise it and only one of them may resolve.**
#: `require_key` reads the stores to find out; `_material` is handed a
#: `KeyState` that already says there is none, and calling `require_key` there
#: would read every store again, per source, which is the whole cost a
#: `KeyState` exists to pay once.
#:
#: Names the action rather than the three stores, because only one of the three
#: is something a person types: an admin with no key needs to be told to make
#: one, not to be handed a list of places it could have come from.
_NO_KEY: Final = (
    "This deployment has no encryption key, so a catalogue credential "
    "cannot be stored. Create one on the Catalogue settings screen, or "
    "set CREDENTIAL_ENCRYPTION_KEY where the app is configured."
)


def require_key() -> bytes:
    """The configured key, or a refusal naming what to do about it."""
    material = key_material()
    if material is None:
        raise NoKeyConfigured(_NO_KEY)
    return material


def normalise_phrase(text: str) -> str:
    """A phrase as it is compared, whatever a person's keyboard did to it.

    NFKD because BIP-39 specifies it, then lowercased and re-joined on single
    spaces. **Not cosmetic**: `Mnemonic.check` rejects an uppercase phrase and a
    phrase with a double space outright, so a person who pasted from a document
    that capitalised the first word would be told their key was wrong.
    """
    return " ".join(unicodedata.normalize("NFKD", text).lower().split())


def phrase_to_key(text: str) -> bytes:
    """The 32 bytes a recovery phrase carries.

    **No message here ever names a word.** The phrase is the key: a refusal that
    quoted the word it did not recognise would put a twenty-fourth of the secret
    in a log, and an operator debugging a paste would put the rest there over
    the next three attempts. A position is enough to act on and discloses
    nothing.

    The word count is checked first because the library does not distinguish it:
    a 12 word phrase raises "Failed checksum", which sends somebody looking for
    a typo in a phrase whose only fault is that half of it is missing.
    """
    words = normalise_phrase(text).split()
    if len(words) != PHRASE_WORDS:
        raise BadRecoveryPhrase(
            f"A recovery phrase is {PHRASE_WORDS} words; this one has {len(words)}."
        )
    for position, word in enumerate(words, start=1):
        if word not in _WORDS.wordlist:
            raise BadRecoveryPhrase(
                f"Word {position} of the recovery phrase is not one of the "
                f"{len(_WORDS.wordlist)} words in the list."
            )
    try:
        material = bytes(_WORDS.to_entropy(words))
    except ValueError as error:
        raise BadRecoveryPhrase(
            "The recovery phrase failed its checksum, so at least one word is "
            "wrong or two are swapped. Check it against what you wrote down."
        ) from error
    if len(material) != KEY_BYTES:
        raise BadRecoveryPhrase("The recovery phrase does not carry a whole key.")
    return material


def key_to_phrase(material: bytes) -> str:
    """The phrase that reproduces this key, for somebody to write down.

    **Shown once and never logged**, exactly like the credentials it protects:
    it is not a hint about the key, it is the key. Nothing in this module calls
    it on a path that reaches a log line or a response body.
    """
    if len(material) != KEY_BYTES:
        raise KeyConfigurationError("Only a whole key can be written as a phrase.")
    return _WORDS.to_mnemonic(material)


def generate_phrase() -> str:
    """A new key, as the phrase that is its only form.

    `Mnemonic.generate` draws from `secrets` under the hood; the entropy is 256
    bits and the checksum is the standard's.
    """
    return _WORDS.generate(strength=KEY_BYTES * 8)


#: The version this build writes and the only one it can open.
#:
#: Written into the additional authenticated data as well as into the text, so
#: it cannot be rewritten on a stored row. **`v2` is `v1` plus the origin in the
#: associated data**, and the bump is what makes a pre-binding envelope
#: legible without a key: the alternative, changing the associated data under
#: `v1`, leaves an envelope that fails authentication for a reason nothing can
#: distinguish from a damaged row.
VERSION: Final = "v2"

#: Every version this build recognises **as an envelope**, newest last.
#:
#: **Recognising is not opening, and the two are deliberately different sets.**
#: `unseal` opens `VERSION` alone; this is the shape question, asked by
#: `generation_of` and therefore by `backup._parse_row`, which is what stands
#: between a hand edited archive and a plaintext password in this column. An
#: archive taken before the bump carries `v1` rows, and refusing them at the
#: insert would fail an entire restore over logins that are merely to be typed
#: again. `ck_catalogue_credentials_envelope` carries the same set in SQL and
#: `tests/test_credentials.py::TestTheEnvelopeRuleAndItsConstraintAgree` walks
#: the two together, because models.py cannot import this module.
KNOWN_VERSIONS: Final[tuple[str, ...]] = ("v1", "v2")

#: Info strings for the two derivations. **Different on purpose**: the tag is
#: written where anyone holding the database can read it, and it must not be a
#: function of the key that encrypts beside it.
_ENCRYPTION_INFO: Final = b"endpaper/v1/credential-encryption"
_GENERATION_INFO: Final = b"endpaper/v1/credential-key-generation"

#: Bytes of the generation tag. Four is enough to tell one key from another and
#: is not a key check anybody needs to be precise about: the authoritative
#: answer to "does this key open this envelope" is AES-GCM's own tag.
_GENERATION_BYTES: Final = 4

#: AES-GCM wants 96 bits, and a random nonce per envelope is safe at this volume:
#: one is drawn per credential written, and the birthday bound on 96 bits is
#: nowhere near a roster of catalogue sources typed by hand.
_NONCE_BYTES: Final = 12


def _expand(material: bytes, info: bytes, length: int) -> bytes:
    """HKDF-Expand, one block, per RFC 5869.

    Extract is skipped deliberately and the RFC allows it: the input is already
    a uniformly random key of at least the hash length, which `key_material`
    enforces. Expanding rather than using the configured bytes directly is what
    keeps the value an operator typed from being the AES key itself, and what
    lets the generation tag be published beside the ciphertext without being a
    function of the key that encrypts it.
    """
    return hmac.new(material, info + b"\x01", sha256).digest()[:length]


def generation_of_key(material: bytes) -> str:
    """Which key this is, as eight hex characters.

    **Derived rather than declared, so nobody has to remember to bump it.** An
    operator who rotates the key gets a new tag by construction; one who does
    not, does not.
    """
    return _expand(material, _GENERATION_INFO, _GENERATION_BYTES).hex()


def _b64(raw: bytes) -> str:
    return urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _purpose(source: str, origin: str) -> str:
    """What this envelope is for, whose it is, and where it may be sent.

    **The kind, the subject and the origin, sealed over rather than stored
    beside.** A credential lifted onto another source's row, into a table for a
    different kind of secret, or beside an address somebody else wrote, fails
    authentication rather than being sent to a host it was never set for.

    **Unambiguous because an origin carries exactly two slashes and a source
    carries none**, so the first slash after `catalogue-credential/` splits the
    pair whatever either side holds. `origin_of` is what fixes the origin's
    shape: it emits `scheme://host` or `scheme://host:port` and nothing else,
    measured over every Unicode codepoint as a host character with **0** outputs
    at any other slash count. `is_safe_source`, refused in `_associated`, is
    what fixes the source's, and it is the half that has a writer: the column is
    written by `backup.restore` through Core and `put` never checked it.
    """
    return f"endpaper/{VERSION}/catalogue-credential/{source}/{origin}"


def _associated(material: bytes, source: str, base_url: str) -> bytes:
    """The additional authenticated data, and the two refusals that make it one string.

    **Built in one place because `seal` and `unseal` must not be able to
    disagree**, and both of the refusals below are what an envelope openable at
    an address nobody chose would need.

    **An address this build cannot parse binds nothing, so it is refused rather
    than folded to the empty string.** `origin_of` answers `""` for an
    unparseable address, and two of those compare equal: sealing over one would
    write an envelope that opens beside **any** address this build cannot
    parse. The same rule is spelled at `shipped`, which met it first.

    **The origin is computed here from the address rather than taken as one**,
    so no caller can hand over a half parsed value. `origin_of` says why it is
    `httpx.URL` and not `urllib`, and it is the parser that makes the request.
    """
    if not is_safe_source(source):
        raise CredentialError("That is not a catalogue source.")
    origin = origin_of(base_url)
    if not origin:
        raise CredentialError(
            "A credential cannot be bound to an address this server cannot parse."
        )
    return f"{VERSION}.{generation_of_key(material)}.{_purpose(source, origin)}".encode()


def seal(material: bytes, source: str, base_url: str, secret: str) -> str:
    """`v2.<generation>.<nonce>.<ciphertext>`, base64url without padding.

    **The generation tag is outside the ciphertext and inside the additional
    authenticated data.** Outside, because the whole point is reading it without
    the key; inside, because a tag that could be rewritten on a stored row would
    turn "re-enter this" into "silently try the wrong key".

    **`base_url` is the address this credential may be sent to**, and it is
    sealed over rather than stored beside: see `_associated`. The origin is not
    written into the envelope in the clear, because it is not something a reader
    without the key needs and every field that is readable is a field an archive
    can rewrite.
    """
    nonce = secrets.token_bytes(_NONCE_BYTES)
    generation = generation_of_key(material)
    associated = _associated(material, source, base_url)
    box = AESGCM(_expand(material, _ENCRYPTION_INFO, 32))
    sealed = box.encrypt(nonce, secret.encode("utf-8"), associated)
    return ".".join((VERSION, generation, _b64(nonce), _b64(sealed)))


def generation_of(envelope: str) -> str:
    """Which key wrote this envelope, read without holding any key.

    Empty for anything that is not an envelope of a version this build knows,
    which is `KNOWN_VERSIONS` and not `VERSION`: the question here is the shape,
    and `backup._parse_row` asks it of an archive that may predate the bump.
    That is what lets a settings screen say "written under a different key" on a
    deployment that has no key configured at all.
    """
    parts = envelope.split(".")
    if len(parts) != 4 or parts[0] not in KNOWN_VERSIONS:
        return ""
    return parts[1]


def _openable_by(material: bytes, envelope: str) -> bool:
    """Whether this key could open this envelope at all, address aside.

    **Everything `unseal` decides before it needs an address**: the version is
    one this build opens and the generation tag is this key's. It deliberately
    does not answer whether the ciphertext is intact or whether the origin
    matches, both of which need the key applied to a particular address.
    `unreadable_sources` is the caller and says what that costs.
    """
    parts = envelope.split(".")
    return (
        len(parts) == 4
        and parts[0] == VERSION
        and parts[1] == generation_of_key(material)
    )


def unseal(material: bytes, source: str, base_url: str, envelope: str) -> str:
    """The secret back, or a refusal that says which kind of wrong this is.

    **Four outcomes, not two, and the two middle ones are why the version and
    the tag are in the clear.** AES-GCM refuses a wrong key, an envelope from an
    older scheme and a corrupted row identically, so without them an admin
    looking at an unreadable credential cannot tell "the key changed, type it
    again" from "this predates the binding, type it again" from "this row is
    damaged". Both are reported before any decryption is attempted.

    **`base_url` is the address this credential is being asked for, and it is
    the one it must have been sealed for.** Not the address on some row looked
    up here: this is what the caller is about to send to, so an envelope opens
    only where `Credential.header_for` would then let it go. A lookup would be a
    second route to the same fact and could disagree with the request.
    """
    parts = envelope.split(".")
    if len(parts) != 4 or parts[0] not in KNOWN_VERSIONS:
        raise UnreadableCredential("The stored credential is not in a known format.")
    version, generation, nonce, sealed = parts
    if version != VERSION:
        raise UnboundCredential(
            "This login was stored before a credential carried the address it may "
            "be sent to, and cannot be opened. Enter it again."
        )
    if generation != generation_of_key(material):
        raise WrongKeyGeneration(
            "This credential was stored under a different encryption key and cannot be read. Enter it again."
        )
    associated = _associated(material, source, base_url)
    box = AESGCM(_expand(material, _ENCRYPTION_INFO, 32))
    try:
        return box.decrypt(_unb64(nonce), _unb64(sealed), associated).decode("utf-8")
    except (InvalidTag, ValueError, UnicodeDecodeError) as error:
        raise UnreadableCredential("The stored credential could not be read. Enter it again.") from error


def origin_of(url: str) -> str:
    """Scheme, host and port, as the one string a credential is bound to.

    **Parsed with `httpx.URL`, which is the parser that makes the request**, and
    that is the whole of why this is not `urllib`. The two disagree, measured
    2026-09-06: `urlsplit` raises on the port in `https://host:8_080/` because
    `"8_080".isdigit()` is False, and httpx reads it as 8080. An earlier version
    caught that `ValueError` and filled in the scheme default, so a credential
    bound to `:443` was attached to a request that went to port 8080. A parser
    that is not the requester's is a hole by construction, and the same
    reasoning covers IDN and punycode, where the two also differ.

    The port is filled in for `http` and `https` only, matching `fetch._port`,
    so `https://host` and `https://host:443` are one origin. For any other
    scheme it is compared as written, because nothing here knows what that
    scheme's default is and guessing would make two addresses look like one.

    **No scheme at all is not another scheme, and it answers empty.** `httpx`
    reads `://x` as an empty scheme with a host of `x`, which produced the
    bindable origin `://x`. That was only ever a comparison string before the
    origin went into the associated data; now it is a value an envelope can be
    **sealed** over, and an address with no scheme is one nothing here can send
    to. Measured 2026-09-07 against `httpx.URL("://x")`.

    **Empty on anything that cannot be parsed, and empty never matches**, which
    is what `Credential.header_for` and `for_request` both check. Userinfo is
    dropped by `.host`, which is the point: a base URL written
    `https://user@host/` and a redirect to `https://host@elsewhere/` must not
    compare equal.
    """
    try:
        parsed = httpx.URL(url)
        host = (parsed.host or "").lower()
        scheme = parsed.scheme.lower()
        port = parsed.port
    except Exception:
        # `httpx.URL` raises `InvalidURL`, and an unusable IDN host surfaces as
        # a `UnicodeError` from idna, which is neither. `fetch._walk_hops`
        # carries the measurement for that second one. Both mean the same thing
        # here and both must fail closed rather than produce a comparable
        # origin.
        return ""
    if not host or not scheme:
        return ""
    if port is None and scheme in ("http", "https"):
        port = 443 if scheme == "https" else 80
    return f"{scheme}://{host}:{port}" if port is not None else f"{scheme}://{host}"


@dataclass(frozen=True)
class Credential:
    """A username, a password, and the one origin they may be sent to.

    **Both halves are `repr=False` and `__str__` is overridden.** A frozen
    dataclass prints every field, so one `logger.exception` over a request that
    carried one of these would put an institution's password in the container
    log. `MailConfig.password` carries the same rule for the same reason.
    """

    origin: str
    username: str = field(repr=False)
    password: str = field(repr=False)

    def __str__(self) -> str:
        return f"<credential for {self.origin}>"

    def header_for(self, url: str) -> dict[str, str]:
        """The `Authorization` header, and only where this credential belongs.

        **The rule is the secret's, not the transport's**, and that is what makes
        it hold when the transport is wrong. `fetch.py` already refuses a hop
        that leaves the host, and it should: a redirect leaking a page is an
        information leak. But the consequence differs by kind. If that guard
        were removed, or bypassed, a page would leak; this header would still
        not go anywhere it was not set for, because it is computed per hop from
        the origin the credential carries rather than pinned to the client.

        Basic, per RFC 7617, and nothing else: no surveyed target asks for a
        flow that is not a username and a password.
        """
        reached = origin_of(url)
        if not reached or not self.origin or reached != self.origin:
            # Names two origins and no secret. The only way here is a caller
            # holding a credential for one target and asking another, which is
            # a defect worth a line rather than a silent unauthenticated GET.
            logger.warning(
                "Withheld a catalogue credential set for %s from a request to %s",
                self.origin,
                reached,
            )
            return {}
        raw = f"{self.username}:{self.password}".encode()
        return {"Authorization": "Basic " + b64encode(raw).decode("ascii")}


#: How a deployment pins one source's credential instead of storing it.
#:
#: **`config._ENV_OVERRIDES` could not carry this**, and the reason is the
#: ticket's own: that table is keyed by `SettingKey`, and a credential is keyed
#: by a catalogue target row rather than by a settings row. A second,
#: differently keyed table inside `config.py` would be two schemes in one
#: module, so this one lives beside what reads it.
_ENV_PREFIX: Final = "CATALOGUE_CREDENTIAL_"


#: What a source may be, and it is narrower than the column's type.
#:
#: **The value travels, which is why this exists.** A source is not only a
#: primary key: `unreadable_sources` returns it to a browser, and a generated
#: client interpolates it into a URL path. `catalogue_credentials` has no
#: foreign key on purpose and `backup.restore` inserts through Core, so an
#: archive decides this column, and an archive is a file an admin was handed.
#: A source of `../../books/5?` sent that admin's own authenticated DELETE to
#: `/api/books/5`, with the trailing path swallowed into the query string.
#:
#: Lowercase, digits, underscore and hyphen, at most 32. Every roster member
#: passes, which is checked rather than assumed. Nothing in the set needs
#: escaping in a path segment, in a shell, or in an environment variable name,
#: so the value is safe wherever it has learned to go.
#:
#: **`ck_catalogue_credentials_source` is the same rule in SQL and is the last
#: line**, for a write that never comes through here. It carries an explicit NUL
#: check because it would otherwise not be: `length` and `GLOB` are C string
#: operations and stop at the first NUL, so the SQL read `bne\0../../books/5?`
#: as `bne` and admitted what this refuses.
#: `tests/test_credentials.py::TestTheSourceRuleAndItsConstraintAgree` walks
#: both over one battery, and **the battery has to carry control characters**,
#: because that is the only input class where the two languages part.
_SAFE_SOURCE: Final = re.compile(r"[a-z0-9_-]{1,32}")


def is_safe_source(value: str) -> bool:
    """Whether this is a source string, rather than something shaped like a path."""
    return _SAFE_SOURCE.fullmatch(value) is not None


def env_variable_name(source: str) -> str:
    """Which variable pins this source's credential, for a message that names it."""
    return f"{_ENV_PREFIX}{source.upper()}"


def from_env(source: str) -> tuple[str, str] | None:
    """A credential this deployment pinned, as `username:password`.

    **Split on the first colon, and that is Basic's own rule rather than a
    convenience.** RFC 7617 forbids a colon in the user-id, so everything after
    the first one is the password and a password containing colons survives.

    **Set and unusable raises; unset answers None, and the two are not the same
    thing.** `CATALOGUE_CREDENTIAL_BNE=bob:` used to answer None, which made
    `is_from_env` False, offered an edit on a screen, and quietly used the
    stored credential while the operator believed the environment was in force.
    An empty password is refused everywhere else in this application, and
    reading a typo as one would authenticate as somebody with nothing.

    **Set to the empty string is set, and that arm cost a round.** The rule
    above stopped one value short of the value an operator is most likely to
    produce: `CATALOGUE_CREDENTIAL_BNA=` in a compose file, an `.env` line with
    nothing after the `=`, or a Kubernetes `value: ""` all arrive here as `""`,
    and reading that as unset walked past the level the deployment set. It
    reached the stored login before a default shipped and it reaches the shipped
    account now, which is the level nobody in the deployment chose. So the test
    is `is None`, not truthiness. The consequence is deliberate and is what the
    screen already says: such an install reports the variable as in force and
    not a credential, by name.
    """
    raw = os.getenv(env_variable_name(source))
    if raw is None:
        return None
    username, separator, password = raw.partition(":")
    if not separator or not username or not password:
        raise CredentialError(
            f"{env_variable_name(source)} is set and is not a credential. It has "
            "to be a username and a password separated by a colon."
        )
    return username, password


def shipped(source: str, base_url: str) -> tuple[str, str] | None:
    """The login this build ships for a source, at the address it ships it for.

    **The bottom of the ladder, and the only level whose value is in a published
    file.** `targets.ShippedCredential` is where that is argued; the rule here is
    the address. A shipped default is the one credential nobody chose, so
    nothing else records what it was meant for, and this compares the caller's
    address with the roster row's own before handing the pair over.

    **`origin_of` on both sides, not a string comparison, and not
    `targets.origin`.** The two parsers disagree, which `origin_of` records
    against a measurement, and a bound computed by a parser that is not the
    requester's is a bound on a different string than the one sent.

    None for a source outside this build's roster, which is a row an archive can
    write: `catalogue_credentials` carries no foreign key on purpose.
    """
    try:
        known = CatalogueSource(source)
    except ValueError:
        return None
    target = targets.SEEDED.get(known)
    if target is None or target.shipped_credential is None:
        return None
    published = origin_of(target.base_url)
    # **Empty never matches**, which is `origin_of`'s own rule and is spelled
    # here rather than relied on: two unparseable addresses compare equal, so a
    # bare inequality hands the pair over on the one input the parser refused.
    if not published or published != origin_of(base_url):
        # Names neither address and no secret: the only way here is a caller
        # asking one row's default about another row's address, which #130 makes
        # reachable the day a `base_url` is editable. Withholding is the safe
        # direction; the source then answers nothing rather than authenticating
        # somewhere the library never published this pair for.
        return None
    return target.shipped_credential.username, target.shipped_credential.password


def is_from_env(source: str) -> bool:
    """Whether the deployment pinned this one, so the app must not offer an edit.

    **True for a pinned value that is unusable**, which is the whole reason this
    is not `from_env(...) is not None`. A variable somebody set wrongly is still
    a variable somebody set: offering an edit there hides the mistake behind a
    field that appears to work.

    **True for a variable set to the empty string**, for the reason `from_env`
    gives at length: that is the commonest way of setting one wrongly, and it is
    still a variable somebody set. `bool(...)` here read it as unset and let
    `_resolve` walk to the level below.

    Reporting *where* a credential comes from is not reporting the credential,
    which is what lets this be true for a secret.

    **`settings_store.is_from_env` still reads emptiness the other way, and the
    reason is the sentinel rather than the subject.** `config.env_override`
    returns a string and `settings_store.in_force` is `env_override(key) or
    get_raw(db, key)`, so over there the empty string **is** "the environment
    said nothing", for the ten keys in `config._ENV_OVERRIDES`, two of them
    parsed as booleans, `MAIL_USE_TLS` and `MAIL_USE_SSL`, and one as an int,
    `MAIL_PORT`. Aligning that one function alone would refuse the edit on a screen
    while `in_force` went on using the stored row, which is the screen saying
    pinned while the send uses the row: strictly worse than today and the exact
    disagreement both modules exist to prevent. Underneath it there is a real
    asymmetry: a credential may never be empty, refused here, by `put` and by
    `targets.ShippedCredential`, so `""` can only be a mistake, where
    `MAIL_USERNAME` against a server with no auth is legitimately empty.
    """
    return os.getenv(env_variable_name(source)) is not None


# ── The store ─────────────────────────────────────────────────────────────────


def stored_envelope(db: Session, source: str) -> str:
    """The sealed text on this source's row, or empty. No key needed."""
    row = db.get(CatalogueCredential, source)
    return row.envelope if row is not None else ""


def put(db: Session, source: str, base_url: str, username: str, password: str) -> None:
    """Seal a credential onto a source's row, replacing whatever was there.

    The username is sealed with the password rather than stored beside it. It is
    half of a login at somebody else's server, the archive carries this table,
    and a masked username on a screen costs one decryption on a page an admin
    opens by hand.

    **`base_url` is the address this login is for, and it is required rather
    than looked up.** Both callers already hold it: the roster screen hands over
    `targets.SEEDED[source].base_url` and the OPDS route hands over the row's
    own, which is the same value each will later ask `for_request` about. A
    lookup here would be a second route to that fact, and the two could
    disagree in exactly the direction that matters: sealing for the address a
    row names while the request goes to the address a caller was handed.

    **A release that moves a roster row's address invalidates every deployment's
    stored login for that source**, because the envelope was sealed over the old
    origin and nothing re-seals it. That is the binding working: a login entered
    for one machine is not a login for another. It is worth knowing before the
    literal in `targets.SEEDED` is edited, because the symptom lands on a
    deployment rather than in a test.
    """
    if not username or not password:
        raise CredentialError("A credential needs both a username and a password.")
    if ":" in username:
        # One representation for the sealed pair and for the pinned variable, so
        # there is one rule to state. RFC 7617 forbids a colon in the user-id,
        # which is why splitting on the first one loses nothing a target could
        # have accepted over Basic anyway.
        raise CredentialError("A username may not contain a colon; HTTP Basic forbids one (RFC 7617).")
    envelope = seal(require_key(), source, base_url, f"{username}:{password}")
    row = db.get(CatalogueCredential, source)
    if row is None:
        db.add(CatalogueCredential(source=source, envelope=envelope))
    else:
        row.envelope = envelope
    db.commit()


def forget(db: Session, source: str) -> bool:
    """Drop this source's stored credential. True if there was one."""
    row = db.get(CatalogueCredential, source)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def stored(
    db: Session, source: str, base_url: str, state: KeyState | None = None
) -> tuple[str, str]:
    """The stored username and password, opened. Raises rather than returning blanks.

    **`base_url` is the address the caller is about to use**, and an envelope
    sealed for another one does not open: see `unseal`. So this cannot answer
    with a login for a machine other than the one being asked about, which is
    what a row deciding an address made possible.

    Pass `state` when asking about more than one source; see `KeyState`.
    """
    envelope = stored_envelope(db, source)
    if not envelope:
        raise UnreadableCredential("No credential is stored for this source.")
    opened = unseal(_material(state), source, base_url, envelope)
    username, _, password = opened.partition(":")
    return username, password


@dataclass(frozen=True)
class KeyState:
    """The key, resolved once for a caller that asks about many sources.

    **Resolved once rather than per source**, which is what this type is for.
    `_supplied` reads the keychain and runs a BIP-39 decode, so a settings page
    asking ten roster rows was ten keychain round trips on a desktop. A frozen
    value passed down, not a cache: nothing here survives the request, so there
    is no second source of truth to invalidate.

    `problem` carries a configuration refusal as a sentence rather than raising,
    because two stores holding different keys is a **state to report on a
    screen**, not a 500 on the settings page.

    **`material` is `repr=False`, for the reason `Credential`'s two halves are.**
    A frozen dataclass prints every field, and these bytes are the recovery
    phrase: `key_to_phrase` turns them straight back into the words, so one
    rendering discloses the key that opens every stored credential rather than
    one login. It is bound in a frame on the member request path now, which is
    where a `logger.exception` lives.
    """

    material: bytes | None = field(repr=False)
    problem: str = ""


def key_state() -> KeyState:
    """Resolve the key once, turning a configuration refusal into a sentence."""
    try:
        return KeyState(key_material())
    except KeyConfigurationError as refusal:
        return KeyState(None, str(refusal))


def _material(state: KeyState | None) -> bytes:
    """The key to open an envelope with, from a resolved state or from scratch.

    **A state carrying no key raises what resolving it would have raised**, and
    that is the whole of this function. `key_state` turns a configuration
    refusal into a sentence so a settings screen can report it; a caller that
    opens an envelope has to meet the refusal instead. Answering "no key" for a
    deployment whose two stores hold different keys would tell an admin to type
    a credential in again, when the thing to fix is the second store, and it
    would do it on a path where nothing else says so.

    **A state saying there is no key binds, and nothing here reads a store
    again.** Both critic seats found the arm that did: `require_key` at the end
    of this function costs one full resolution per source on the deployment
    whose key is gone, which is 1 + N against the N it replaced, in the one
    state every other reader of a `KeyState` already answers from the value it
    was handed. Given `material is None`, `key_state` has exactly two ways of
    getting there: `problem` set, where `key_material` refused, and `problem`
    empty, where no source held a key at all.
    `tests/routers/test_books.py::test_a_lost_key_is_resolved_once_as_well` is
    the arm that stops it coming back.
    """
    if state is None:
        return require_key()
    if state.material is not None:
        return state.material
    if state.problem:
        raise KeyConfigurationError(state.problem)
    raise NoKeyConfigured(_NO_KEY)


def _resolve(
    db: Session, source: str, base_url: str, state: KeyState | None
) -> tuple[CredentialProvenance, tuple[str, str] | None]:
    """Which level supplies this source's login, and the pair it carries.

    **One walk of the ladder, and both the screen and the request ask it.** The
    two used to be separate chains that happened to agree, which is the shape
    that produces a source silently authenticating as something other than what
    the screen says. `view` reports which level this picked and `for_request`
    sends what it carried, so the two cannot disagree about **which login**.

    **An address `origin_of` cannot parse now reaches the stored level rather
    than only `for_request`**, and that is the binding rather than a second
    guard. `unseal` refuses to build associated data over an unparseable
    address, so such a row answers `None` for the pair here and `view` reports
    it as held and unreadable. That is the honest answer once the origin is
    sealed over: the login genuinely cannot be opened. The Remove control stays,
    because the provenance is still `STORED` and `has_credential` reads that
    rather than the pair. `for_request` still refuses the address itself, which
    is a fact about the address rather than about the ladder and is what keeps
    a `Credential` from ever being built with no origin.

    **The order is pinned, stored, shipped, and it is the whole of what makes a
    shipped default safe.** The owner's decision of 2026-09-07 states
    replaceability as a requirement rather than a consequence: a default that
    could win over an admin's entry is the version of the feature that should
    have been refused.

    **The first level with anything to say wins whether or not it works**, and
    that arm is the one worth stating. A pinned variable set to nonsense, and a
    stored login sealed under a key that is gone, both keep the levels below
    them: falling through would send a request as a different account while the
    screen reports the one the admin configured, which is exactly the confusion
    a shipped default is otherwise most likely to create. So an unusable level
    answers `None` for the pair rather than deferring, and `view` turns that into
    `unreadable`, whose remedy is on the key.

    `None` for the pair therefore means "this level is in force and cannot be
    used"; `CredentialProvenance.NONE` means no level is in force at all.
    """
    if is_from_env(source):
        try:
            return CredentialProvenance.ENV, from_env(source)
        except CredentialError:
            return CredentialProvenance.ENV, None
    if stored_envelope(db, source):
        try:
            return CredentialProvenance.STORED, stored(db, source, base_url, state)
        except CredentialError:
            return CredentialProvenance.STORED, None
    default = shipped(source, base_url)
    if default is not None:
        return CredentialProvenance.SHIPPED, default
    return CredentialProvenance.NONE, None


@dataclass(frozen=True)
class CredentialView:
    """What a settings screen may be told, and it is never the secret.

    **`username` leaves this module unmasked and is masked by the caller.**
    Masking is presentation and lives with the other previews in
    `settings_store.mask`; importing it here would be a cycle, and copying the
    rule would be the same rule in two places. `field(repr=False)` for the
    reason `Credential`'s halves carry it.

    **`provenance` is what tells an admin which login is in force**, and it is
    one field rather than a flag per level for the reason `CredentialProvenance`
    gives. `has_credential` is derived from it rather than sent beside it: two
    fields answering "is there one" is two chances to disagree, and the flag was
    the one a screen believed.

    **`unreadable` says a login is held and cannot be opened, and deliberately
    does not say why.** It used to be called `needs_reentry` and it caught every
    `CredentialError`, so a locked keychain and a deployment with no key at all
    both produced "enter this login again" when the thing to do was to unlock
    the keychain or type the recovery phrase, either of which recovers all of
    them at once. The remedy for every one of those lives on the key, so the key
    is where it is reported: `KeyState.problem` and `CredentialKeyOut`.

    **There is a fifth cause now and its remedy is the row's, not the key's.**
    An envelope sealed before a credential carried its address, which reaches a
    deployment only by restoring an archive taken before that change, since the
    migration removed the rows it found. The key is intact and the recovery
    phrase opens nothing; the only way out is entering the login again.

    A shipped default is never `unreadable`: it is a constant in this build, so
    there is no key to lose and nothing to type again.
    """

    provenance: CredentialProvenance
    unreadable: bool
    username: str = field(default="", repr=False)

    @property
    def has_credential(self) -> bool:
        """Whether any level supplies one, usable or not."""
        return self.provenance is not CredentialProvenance.NONE


def view(
    db: Session, source: str, base_url: str, state: KeyState | None = None
) -> CredentialView:
    """What a settings screen may say about one source's login.

    **`base_url` for the reason `for_request` takes one**: the shipped level is
    bound to the address the library published it for, so a screen answering
    without one would report a default the next request withholds. Both callers
    hand over the roster row's own address.

    Pass `state` when asking about more than one source; see `KeyState`.

    A pinned credential reports `unreadable` False whatever is on the row:
    nothing about it is broken from the screen's point of view, and the row is
    not what the next request will carry. Same rule the mail fields follow. A
    pinned credential that is **set and unusable** reports both, because a
    variable somebody set wrongly is still in force as far as the screen is
    concerned and the edit must stay refused.
    """
    resolved = key_state() if state is None else state
    provenance, pair = _resolve(db, source, base_url, resolved)
    return CredentialView(
        provenance,
        provenance is not CredentialProvenance.NONE and pair is None,
        pair[0] if pair is not None else "",
    )


def unreadable_sources(db: Session, state: KeyState | None = None) -> list[str]:
    """Every stored envelope this deployment cannot open, by source, sorted.

    **Read off the table, never off the roster.** `catalogue_credentials`
    carries no foreign key on purpose, so a row can name a source this build's
    roster no longer has: an archive from a release that shipped one more
    catalogue restores exactly that. A caller iterating `CatalogueSource` counts
    ten and misses it, which is how `generate_key` came to refuse with a number
    the settings screen denied and name logins the screen showed nothing to
    remove.

    **The question here is the envelope's and not the screen's, and that
    difference is a regression this function already caused once.** `view` answers the screen's
    question, "is this source's login usable", and short-circuits on a pinned
    credential before it ever reads the row, because a pinned source is not
    broken from the screen's point of view. Built on `view`, this function
    answered `[]` for a sealed row whose source was also pinned, and
    `generate_key` then minted a key straight over it: measured in process, seal
    a login, discard the key, set `CATALOGUE_CREDENTIAL_<SOURCE>`, and the
    refusal that exists to stop exactly that did not fire. **The rule this
    replaced, a plain row count, refused it.** So the question here is the
    envelope's and not the screen's: what would a new key strand.

    **Asked of the key and the version, not by opening the envelope, and that
    is forced rather than chosen.** An envelope is now sealed over the address
    it may be sent to, and this function has none: the only ways to get one
    would be to look the source up in `catalogue_targets` or in `opds_servers`,
    which would make this module enumerate the kinds of row that may own a
    credential. `CatalogueCredential.source` is deliberately not keyed to the
    enum so that a curated registry or a typed host gets a credential with no
    migration, and an arm per kind here is exactly what that reversed.

    **What that stops reporting, and it is a loss rather than a wash.** An
    envelope of this version and this key's generation whose ciphertext an
    archive damaged, or whose address has moved under it, answers True here and
    is no longer listed. `view` catches it wherever a screen asks `view`, which
    today is the catalogue logins section and nothing else. Three kinds of
    source are therefore left, and they are what this loses:

    * a **pinned** source, where `_resolve` returns at `is_from_env` before it
      reads the row, so `view` reports the row as fine and this list was the one
      place its sealed row could be removed from;
    * an **orphan**, a source neither the roster nor `opds_servers` names, which
      nothing asks `view` about at all;
    * a **household's OPDS server**, which `routers/opds._out` does ask about,
      on `GET /api/opds/servers`, a route no screen calls today. The report
      exists in the API and reaches nobody.

    All three are inert, and for three reasons: a pinned source resolves to the
    variable, an orphan is asked by nothing, and a household's server no longer
    opens its envelope at all, so `for_request` answers None and a sync sends no
    header. `TestAnEnvelopeDoesNotOpenBesideAnAddressAnotherWriterChose`, in
    `tests/routers/test_opds.py`, measures that last one end to end. What is lost
    is the affordance for removing a row an archive damaged, not a login going
    anywhere.
    `TestWhatCannotBeOpenedIsCountedOffTheTableAndNotTheRoster` pins that so it
    stays a decision rather than a surprise.

    **`generate_key`'s refusal is untouched.** It is reachable only with no key
    configured, where `material is None` strands every stored envelope before
    this predicate is consulted.

    Sources rather than a count, so a screen can say which. A count beside a
    list is the same fact twice.
    """
    resolved = key_state() if state is None else state
    stranded: list[str] = []
    for (source,) in db.query(CatalogueCredential.source).all():
        envelope = stored_envelope(db, source)
        if not envelope:
            continue
        if resolved.material is None or not _openable_by(resolved.material, envelope):
            stranded.append(source)
    return sorted(stranded)


def is_held(
    db: Session, source: str, base_url: str, state: KeyState | None = None
) -> bool:
    """Whether the next request to this source would actually carry a login.

    **Asked through `for_request` and not through `view`, and the two are not
    the same question.** This one's consumer is
    `settings_store._sources_with_a_credential`, which decides whether a source
    is ready to be asked, so it wants the sender's answer: a stored credential
    under a rotated key is not a credential this deployment has, and reporting
    it as held would tell a screen the source is ready and leave a member's
    search to discover otherwise. `view`'s answer is the screen's, which keeps a
    Remove control on a row that holds a sealed login even at an address nothing
    can send to. They agree on every state but that one, which is exactly why
    this must not be built on it.

    True on a shipped default, which is what makes a stock install ask the one
    source that has one.
    """
    return for_request(db, source, base_url, state) is not None


def for_request(
    db: Session, source: str, base_url: str, state: KeyState | None = None
) -> Credential | None:
    """The credential a request to this target would actually carry, bound to its origin.

    **Every outbound caller goes through here rather than reading the row**, the
    same rule `settings_store.in_force` states for a settable value: this answers
    "what will the next request send", and `stored_envelope` answers "what is on
    the row". The ladder is `_resolve`, walked once here and once by the screen,
    so the two cannot answer differently.

    Pass `state` when asking about more than one source; see `KeyState`. Without
    it this resolves the key again per call, which on the member request path is
    one keychain round trip and one BIP-39 decode per source asked.

    None on anything that cannot be read, deliberately. A request that cannot be
    authenticated is one the target refuses, which every caller already handles
    as a source being unavailable; raising here would turn a rotated key into a
    500 on a member's search.
    """
    origin = origin_of(base_url)
    if not origin:
        # An address this build cannot parse is one no credential may be bound
        # to. `origin_of` says why it fails closed rather than guessing.
        return None
    _, pair = _resolve(db, source, base_url, state)
    if pair is None:
        return None
    return Credential(origin, pair[0], pair[1])
