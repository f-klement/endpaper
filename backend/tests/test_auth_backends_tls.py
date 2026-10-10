"""TLS to the directory: the certificate and the hostname are checked, a
StartTLS that did not happen sends no password, and a referral is not followed.

Every arm here dials a real listener on the loopback address and completes, or
fails, a real handshake against a certificate generated in the test. A fake
connection could only report what the code asked ldap3 for, and the defect this
file exists for was a correct looking call whose defaults checked nothing.

The listener speaks just enough LDAP for one bind: it answers a bind, a search
(with a referral, when given one) and the StartTLS extended operation, and
records every message it read. **What
an arm asserts is what reached the listener**, because the property is that a
password never arrives anywhere it should not.
"""

import contextlib
import ipaddress
import logging
import socket
import ssl
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from cryptography import x509
from ldap3 import Connection
from ldap3.core.exceptions import LDAPException

import auth_backends
from tests.helpers import Issued, an_authority, issue_certificate

SERVICE_DN = "cn=service,dc=example,dc=org"
#: Searched for in the raw bytes the listener read, so it has to be a string
#: that appears nowhere else in a bind request.
PASSWORD = "the-service-password-7d1c"

_BIND_REQUEST = 0x60
_BIND_RESPONSE = 0x61
_SEARCH_REQUEST = 0x63
_SEARCH_DONE = 0x65
_UNBIND_REQUEST = 0x42
_EXTENDED_REQUEST = 0x77
_EXTENDED_RESPONSE = 0x78
_START_TLS_OID = b"1.3.6.1.4.1.1466.20037"
_SUCCESS = 0
_PROTOCOL_ERROR = 2
_REFERRAL = 10


# ── Certificates ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Pki:
    #: The CA a deployment names in `LDAP_CA_FILE`.
    authority: Path
    #: A second CA, standing in for the image's trust store.
    image_authority: Path
    #: Issued by `authority` for 127.0.0.1, the address every arm dials.
    for_this_address: Issued
    #: Issued by `authority` for a name that is not the one dialled.
    for_another_host: Issued
    #: Issued by `image_authority` for 127.0.0.1.
    from_the_image_store: Issued


@pytest.fixture(scope="module")
def pki(tmp_path_factory: pytest.TempPathFactory) -> Pki:
    into = tmp_path_factory.mktemp("ldap-pki")
    ours = an_authority("endpaper directory CA", into)
    image = an_authority("endpaper image CA", into)
    loopback = [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    return Pki(
        authority=ours.pem,
        image_authority=image.pem,
        for_this_address=issue_certificate(ours, loopback, into, "loopback"),
        for_another_host=issue_certificate(ours, [x509.DNSName("directory.example.org")], into, "elsewhere"),
        from_the_image_store=issue_certificate(image, loopback, into, "image-loopback"),
    )


# ── The listener ──────────────────────────────────────────────────────────────


def _read_exactly(stream: socket.socket, count: int) -> bytes:
    data = b""
    while len(data) < count:
        chunk = stream.recv(count - len(data))
        if not chunk:
            raise ConnectionError("the client closed the connection")
        data += chunk
    return data


def _read_message(stream: socket.socket) -> bytes:
    """One BER encoded LDAP message, header included."""
    header = _read_exactly(stream, 2)
    length = header[1]
    extra = b""
    if length & 0x80:
        extra = _read_exactly(stream, length & 0x7F)
        length = int.from_bytes(extra)
    return header + extra + _read_exactly(stream, length)


def _parts(message: bytes) -> tuple[bytes, int]:
    """The message id, as its whole INTEGER encoding, and the operation's tag."""
    offset = 2 + (message[1] & 0x7F if message[1] & 0x80 else 0)
    id_length = message[offset + 1]
    message_id = message[offset : offset + 2 + id_length]
    return message_id, message[offset + 2 + id_length]


def _search_base(message: bytes) -> bytes:
    """A search request's base DN, the first field inside the operation."""
    message_id, _ = _parts(message)
    operation = 2 + (message[1] & 0x7F if message[1] & 0x80 else 0) + len(message_id)
    length = message[operation + 1]
    base = operation + 2 + (length & 0x7F if length & 0x80 else 0)
    return message[base + 2 : base + 2 + message[base + 1]]


def _response(message_id: bytes, operation: int, result: int, extra: bytes = b"") -> bytes:
    # resultCode, an empty matchedDN, an empty diagnosticMessage.
    body = bytes([0x0A, 1, result, 0x04, 0, 0x04, 0]) + extra
    content = message_id + bytes([operation, len(body)]) + body
    return bytes([0x30, len(content)]) + content


@dataclass(frozen=True)
class Received:
    operation: int
    message: bytes
    over_tls: bool


class Directory:
    """A directory on 127.0.0.1 that serves one connection.

    `ldaps` wraps the connection before reading anything. Otherwise it reads in
    the clear and answers StartTLS with `start_tls_result`, upgrading only on
    success, so a client that carries on after a refusal is seen doing it.
    `referral`, when given, answers a search below the root with a referral to
    that URL. The root DSE and schema reads ldap3 makes on opening are answered
    plainly: referring those too has ldap3 follow them before any bind, which
    is not the path a member search takes.
    """

    def __init__(
        self,
        issued: Issued,
        *,
        ldaps: bool,
        start_tls_result: int = _SUCCESS,
        referral: str | None = None,
    ):
        self._context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        self._context.load_cert_chain(issued.certificate, issued.key)
        self._ldaps = ldaps
        self._start_tls_result = start_tls_result
        self._referral = referral
        self._listener = socket.create_server(("127.0.0.1", 0))
        self._accepted: socket.socket | None = None
        self.received: list[Received] = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        port = self._listener.getsockname()[1]
        return f"{'ldaps' if self._ldaps else 'ldap'}://127.0.0.1:{port}"

    def password_reached_it(self) -> bool:
        return any(PASSWORD.encode() in seen.message for seen in self.received)

    def operations(self) -> list[int]:
        return [seen.operation for seen in self.received]

    def _upgrade(self, stream: socket.socket) -> socket.socket | None:
        try:
            return self._context.wrap_socket(stream, server_side=True)
        except OSError:
            return None  # The client refused the certificate, which is the point.

    def _serve(self) -> None:
        try:
            accepted, _ = self._listener.accept()
        except OSError:
            return  # Closed with nobody dialling, which some arms require.
        self._accepted = accepted
        accepted.settimeout(10)
        stream: socket.socket | None = self._upgrade(accepted) if self._ldaps else accepted
        over_tls = self._ldaps
        try:
            while stream is not None:
                message = _read_message(stream)
                message_id, operation = _parts(message)
                self.received.append(Received(operation, message, over_tls))
                if operation == _BIND_REQUEST:
                    stream.sendall(_response(message_id, _BIND_RESPONSE, _SUCCESS))
                elif (
                    operation == _SEARCH_REQUEST
                    and self._referral is not None
                    and _search_base(message) != b""
                ):
                    # LDAPResult's `referral` is [3], a sequence of URLs.
                    url = self._referral.encode()
                    urls = bytes([0x04, len(url)]) + url
                    referral = bytes([0xA3, len(urls)]) + urls
                    stream.sendall(_response(message_id, _SEARCH_DONE, _REFERRAL, referral))
                elif operation == _SEARCH_REQUEST:
                    stream.sendall(_response(message_id, _SEARCH_DONE, _SUCCESS))
                elif operation == _EXTENDED_REQUEST:
                    name = bytes([0x8A, len(_START_TLS_OID)]) + _START_TLS_OID
                    stream.sendall(
                        _response(message_id, _EXTENDED_RESPONSE, self._start_tls_result, name)
                    )
                    if self._start_tls_result == _SUCCESS:
                        stream = self._upgrade(stream)
                        over_tls = True
                elif operation == _UNBIND_REQUEST:
                    return
        except (ConnectionError, OSError):
            return

    def close(self) -> None:
        self._listener.close()
        if self._accepted is not None:
            with contextlib.suppress(OSError):
                self._accepted.shutdown(socket.SHUT_RDWR)
            self._accepted.close()
        self._thread.join(timeout=10)


@pytest.fixture
def directory(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Directory]]:
    """Directories an arm starts, each closed when it ends.

    The environment is the shape every arm shares: LDAP mode, a URL the arm
    fills in, and no CA file unless the arm names one.
    """
    monkeypatch.setenv("AUTH_MODE", "ldap")
    monkeypatch.setenv("LDAP_USER_BASE_DN", "ou=people,dc=example,dc=org")
    monkeypatch.delenv("LDAP_CA_FILE", raising=False)
    monkeypatch.delenv("LDAP_START_TLS", raising=False)
    started: list[Directory] = []
    yield started
    for each in started:
        each.close()


def _serve(
    started: list[Directory],
    monkeypatch: pytest.MonkeyPatch,
    issued: Issued,
    *,
    ldaps: bool,
    start_tls_result: int = _SUCCESS,
    referral: str | None = None,
) -> Directory:
    server = Directory(issued, ldaps=ldaps, start_tls_result=start_tls_result, referral=referral)
    started.append(server)
    monkeypatch.setenv("LDAP_URL", server.url)
    if not ldaps:
        monkeypatch.setenv("LDAP_START_TLS", "true")
    return server


def _bind() -> bool:
    # Unbound by hand rather than by `with`: ldap3's `__exit__` reopens a
    # connection that was open on entry, which StartTLS leaves this one.
    connection = auth_backends._connect(SERVICE_DN, PASSWORD)
    try:
        return bool(connection.bind())
    finally:
        connection.unbind()


# ── ldaps ─────────────────────────────────────────────────────────────────────


class TestLdapsChecksTheCertificate:
    def test_a_certificate_from_an_authority_nobody_trusts_gets_no_password(
        self, directory, monkeypatch, pki
    ):
        server = _serve(directory, monkeypatch, pki.for_this_address, ldaps=True)

        with pytest.raises(LDAPException):
            _bind()

        assert server.received == []

    def test_a_certificate_for_another_host_gets_no_password(self, directory, monkeypatch, pki):
        """Signed by the CA this deployment trusts, so only the name is wrong."""
        monkeypatch.setenv("LDAP_CA_FILE", str(pki.authority))
        server = _serve(directory, monkeypatch, pki.for_another_host, ldaps=True)

        with pytest.raises(LDAPException):
            _bind()

        assert server.received == []

    def test_the_ca_file_is_trusted_and_the_bind_arrives_encrypted(
        self, directory, monkeypatch, pki
    ):
        """Dialled by IP address, which the certificate names in its SAN: the
        standard library's check matches an address, where the matcher ldap3
        falls back to on this Python refuses one."""
        monkeypatch.setenv("LDAP_CA_FILE", str(pki.authority))
        server = _serve(directory, monkeypatch, pki.for_this_address, ldaps=True)

        assert _bind() is True

        binds = [seen for seen in server.received if seen.operation == _BIND_REQUEST]
        assert [seen.over_tls for seen in binds] == [True]
        assert PASSWORD.encode() in binds[0].message


class TestTheCaFileReplacesTheImageStore:
    """`SSL_CERT_FILE` points OpenSSL's default store at a second CA, which is
    the store the image would otherwise supply."""

    def test_with_no_ca_file_the_image_store_is_what_is_trusted(
        self, directory, monkeypatch, pki
    ):
        monkeypatch.setenv("SSL_CERT_FILE", str(pki.image_authority))
        _serve(directory, monkeypatch, pki.from_the_image_store, ldaps=True)

        assert _bind() is True

    def test_with_a_ca_file_the_image_store_is_no_longer_trusted(
        self, directory, monkeypatch, pki
    ):
        monkeypatch.setenv("SSL_CERT_FILE", str(pki.image_authority))
        monkeypatch.setenv("LDAP_CA_FILE", str(pki.authority))
        server = _serve(directory, monkeypatch, pki.from_the_image_store, ldaps=True)

        with pytest.raises(LDAPException):
            _bind()

        assert server.received == []


# ── StartTLS ──────────────────────────────────────────────────────────────────


class TestStartTlsChecksTheCertificate:
    def test_a_certificate_from_an_authority_nobody_trusts_gets_no_password(
        self, directory, monkeypatch, pki
    ):
        server = _serve(directory, monkeypatch, pki.for_this_address, ldaps=False)

        with pytest.raises(LDAPException):
            _bind()

        assert not server.password_reached_it()
        assert _BIND_REQUEST not in server.operations()

    def test_a_certificate_for_another_host_gets_no_password(self, directory, monkeypatch, pki):
        """Signed by the CA this deployment trusts, so only the name is wrong."""
        monkeypatch.setenv("LDAP_CA_FILE", str(pki.authority))
        server = _serve(directory, monkeypatch, pki.for_another_host, ldaps=False)

        with pytest.raises(LDAPException):
            _bind()

        assert not server.password_reached_it()
        assert _BIND_REQUEST not in server.operations()

    def test_the_ca_file_is_trusted_and_the_bind_arrives_encrypted(
        self, directory, monkeypatch, pki
    ):
        monkeypatch.setenv("LDAP_CA_FILE", str(pki.authority))
        server = _serve(directory, monkeypatch, pki.for_this_address, ldaps=False)

        assert _bind() is True

        binds = [seen for seen in server.received if seen.operation == _BIND_REQUEST]
        assert [seen.over_tls for seen in binds] == [True]
        assert PASSWORD.encode() in binds[0].message


class TestStartTlsFailsClosed:
    def test_a_directory_that_declines_start_tls_gets_no_password(
        self, directory, monkeypatch, pki
    ):
        """ldap3 2.9.1's synchronous strategy raises on a declined StartTLS,
        so this is the path a real refusal takes."""
        server = _serve(
            directory,
            monkeypatch,
            pki.for_this_address,
            ldaps=False,
            start_tls_result=_PROTOCOL_ERROR,
        )

        with pytest.raises(LDAPException):
            _bind()

        assert _EXTENDED_REQUEST in server.operations()
        assert not server.password_reached_it()

    def test_a_start_tls_that_reports_no_upgrade_sends_nothing(self, directory, monkeypatch, pki):
        """`start_tls()` answering `False` is ldap3's other way to say it did
        not upgrade, and the code reads the answer rather than the exception.

        The real listener is there to see what a connection that carried on
        would have sent: before the answer was read, this bind reached it in
        the clear, password included.
        """
        def reports_no_upgrade(*args: object, **kwargs: object) -> object:
            connection = Connection(*args, **kwargs)
            connection.start_tls = lambda *_, **__: False
            return connection

        monkeypatch.setattr(auth_backends, "Connection", reports_no_upgrade)
        server = _serve(directory, monkeypatch, pki.for_this_address, ldaps=False)

        with pytest.raises(LDAPException, match="LDAP_START_TLS"):
            _bind()

        server.close()
        assert server.received == []


# ── Referrals ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Referred:
    origin: Directory
    elsewhere: Directory


class TestAReferralIsNotFollowed:
    """The verified directory answers the member search with a referral to a
    second, plain listener. ldap3 would follow it and bind there as the service
    account, in the clear, because the origin is `ldaps://` and the referral is
    `ldap://`."""

    @pytest.fixture
    def referred(self, directory, monkeypatch, pki) -> Referred:
        monkeypatch.setenv("LDAP_CA_FILE", str(pki.authority))
        monkeypatch.setenv("LDAP_BIND_DN", SERVICE_DN)
        monkeypatch.setenv("LDAP_BIND_PASSWORD", PASSWORD)
        elsewhere = Directory(pki.for_this_address, ldaps=False)
        directory.append(elsewhere)
        origin = _serve(
            directory,
            monkeypatch,
            pki.for_this_address,
            ldaps=True,
            referral=f"{elsewhere.url}/",
        )
        return Referred(origin, elsewhere)

    def test_the_host_it_names_receives_no_bind(self, referred, db):
        assert auth_backends.authenticate_ldap(db, "kim", "the-member-password") is None

        referred.origin.close()
        referred.elsewhere.close()
        # Without these, the arm is green when nothing connected at all: the
        # origin must have taken the service bind and answered a member search,
        # below the root, with the referral, or there was nothing to follow.
        assert _BIND_REQUEST in referred.origin.operations()
        assert any(
            seen.operation == _SEARCH_REQUEST and _search_base(seen.message) != b""
            for seen in referred.origin.received
        )
        assert not referred.elsewhere.password_reached_it()
        assert _BIND_REQUEST not in referred.elsewhere.operations()

    def test_it_is_logged_naming_where_it_pointed(self, referred, db, caplog):
        with caplog.at_level(logging.WARNING, logger="endpaper.auth"):
            auth_backends.authenticate_ldap(db, "kim", "the-member-password")

        warnings = [
            record.getMessage() for record in caplog.records if record.levelno == logging.WARNING
        ]
        assert any(referred.elsewhere.url in line for line in warnings)
