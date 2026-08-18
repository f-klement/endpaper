"""Where "who is this?" gets answered.

Three modes, chosen with `AUTH_MODE`:

* **local** (default): accounts and bcrypt hashes in this database.
* **ldap**: credentials checked against a directory. Local signup is off, and
  a matching local row is created the first time someone signs in, because
  every foreign key in the schema points at `users.id`.
* **proxy**: an upstream (Authelia, oauth2-proxy, ...) has already
  authenticated the request and names the member in a header. No login screen.

Whatever the mode, a row in `users` is what the rest of the app works with. The
directory modes keep a *shadow* row: no password, `auth_source` recording where
it came from.
"""

import logging

from fastapi import Request
from ldap3 import ALL, Connection, Server
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars
from sqlalchemy.orm import Session

from auth import verify_password
from config import (
    auth_mode,
    ldap_admin_group,
    ldap_bind_dn,
    ldap_bind_password,
    ldap_start_tls,
    ldap_url,
    ldap_user_base_dn,
    ldap_user_filter,
    ldap_username_attribute,
    proxy_admin_group,
    proxy_groups_header,
    proxy_user_header,
)
from enums import AuthMode
from models import User

logger = logging.getLogger("endpaper.auth")

# Seconds to wait on the directory. It sits on the request path for a login,
# so an unreachable server must fail rather than hang a worker.
LDAP_TIMEOUT_SECONDS = 5


# ── Shadow accounts ───────────────────────────────────────────────────────────


def upsert_directory_user(
    db: Session, username: str, *, is_admin: bool, source: AuthMode
) -> User:
    """Find or create the local row backing a directory identity.

    Admin status is re-applied on every sign-in, so removing someone from the
    admin group in the directory takes effect the next time they log in rather
    than being frozen at whatever it was when the row was first created.
    """
    user = db.query(User).filter(User.username == username).first()

    if user is None:
        user = User(
            username=username,
            password_hash=None,
            is_admin=is_admin,
            auth_source=source.value,
        )
        db.add(user)
        logger.info("Created shadow account for %s (%s)", username, source.value)
    else:
        user.is_admin = is_admin
        # An account that predates the switch to a directory keeps its rows and
        # its history; it simply stops being authenticated locally.
        user.auth_source = source.value

    db.commit()
    db.refresh(user)
    return user


# ── Local ─────────────────────────────────────────────────────────────────────


def authenticate_local(db: Session, username: str, password: str) -> User | None:
    user = db.query(User).filter(User.username == username).first()
    if user is None or not user.password_hash:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


# ── LDAP ──────────────────────────────────────────────────────────────────────


def has_password(password: str | None) -> bool:
    """Is this something we are willing to send as a bind credential?

    Empty is the dangerous case, and whitespace-only is treated the same way:
    it cannot be a deliberate password, and some directories normalise it to
    empty before comparing, which lands back on the same anonymous bind.
    """
    return bool(password and password.strip())


def _connect(user: str | None = None, password: str | None = None) -> Connection:
    """Open a connection, refusing any binding that would be anonymous.

    LDAP has *two* ways to accidentally authenticate as nobody while looking
    like success:

      * a simple bind with an empty password (anonymous bind), and
      * a bind that supplies a DN but no password (an "unauthenticated" bind),
        which RFC 4513 requires servers to treat as anonymous.

    The second is the easy mistake to make in configuration: set LDAP_BIND_DN,
    forget LDAP_BIND_PASSWORD, and the service account silently becomes
    anonymous. Everything still appears to work, while the directory is being
    searched with whatever rights an anonymous caller has.
    """
    if user and not has_password(password):
        raise LDAPException(
            f"Refusing to bind as {user!r} without a password: the directory would "
            "treat this as an anonymous bind. Set LDAP_BIND_PASSWORD."
        )

    server = Server(ldap_url(), get_info=ALL, connect_timeout=LDAP_TIMEOUT_SECONDS)
    connection = Connection(
        server,
        user=user or None,
        password=password or None,
        auto_bind=False,
        receive_timeout=LDAP_TIMEOUT_SECONDS,
    )
    if ldap_start_tls():
        connection.start_tls()
    return connection


def _is_member_of_admin_group(entry: object, groups: list[str]) -> bool:
    wanted = ldap_admin_group()
    if not wanted:
        return False
    wanted_lower = wanted.lower()
    return any(wanted_lower == group.lower() or wanted_lower in group.lower() for group in groups)


def authenticate_ldap(db: Session, username: str, password: str) -> User | None:
    """Bind against the directory, then mirror the identity locally.

    Two-step: a service account (or an anonymous bind) searches for the entry,
    then the app re-binds *as that entry* with the supplied password. Binding
    directly with a constructed DN would only work for one directory layout.
    """
    # An empty password must never reach the server. Most LDAP servers treat a
    # bind with an empty password as an ANONYMOUS bind and return success, so
    # forwarding one turns "leave the password blank" into a login as anybody.
    # This is the single most important line in this function. `_connect`
    # enforces the same rule as a backstop, so a future caller cannot bypass it.
    if not has_password(password):
        return None

    # The username is escaped before substitution, so a value containing filter
    # metacharacters cannot rewrite the query.
    search_filter = ldap_user_filter().format(username=escape_filter_chars(username))

    try:
        with _connect(ldap_bind_dn(), ldap_bind_password()) as search_connection:
            if not search_connection.bind():
                logger.error("LDAP service bind failed: %s", search_connection.result)
                return None

            search_connection.search(
                search_base=ldap_user_base_dn(),
                search_filter=search_filter,
                attributes=[ldap_username_attribute(), "memberOf"],
            )
            if not search_connection.entries:
                # No such member. Deliberately indistinguishable from a wrong
                # password to whoever is asking.
                return None
            if len(search_connection.entries) > 1:
                logger.error(
                    "LDAP filter matched %d entries for %s",
                    len(search_connection.entries),
                    username,
                )
                return None

            entry = search_connection.entries[0]
            user_dn = entry.entry_dn
            groups = [str(group) for group in (entry.memberOf.values if "memberOf" in entry else [])]
            # Trust the directory's spelling of the name, not the one typed, so
            # "Kim" and "kim" cannot become two accounts.
            resolved_username = str(entry[ldap_username_attribute()].value)

        with _connect(user_dn, password) as user_connection:
            if not user_connection.bind():
                return None

    except LDAPException:
        # Directory unreachable or misconfigured. Logged with the traceback,
        # reported to the caller as an ordinary failed login.
        logger.exception("LDAP authentication failed for %s", username)
        return None

    return upsert_directory_user(
        db,
        resolved_username,
        is_admin=_is_member_of_admin_group(entry, groups),
        source=AuthMode.LDAP,
    )


# ── Proxy ─────────────────────────────────────────────────────────────────────


def user_from_proxy_headers(db: Session, request: Request) -> User | None:
    """Trust an upstream's assertion of who this is.

    SAFE ONLY BEHIND A PROXY THAT SETS THESE HEADERS AND STRIPS INCOMING ONES.
    A header is client-supplied by default, so if this app is reachable
    directly then anyone can send `Remote-User: admin` and become an admin.
    That is a property of every proxy-auth integration, not a defect here, but
    it means AUTH_MODE=proxy must never be enabled on a container whose port is
    exposed beyond the proxy.
    """
    username = (request.headers.get(proxy_user_header()) or "").strip()
    if not username:
        return None

    raw_groups = (request.headers.get(proxy_groups_header()) or "").strip()
    groups = [group.strip() for group in raw_groups.split(",") if group.strip()]

    wanted = proxy_admin_group()
    is_admin = bool(wanted) and any(group.lower() == wanted.lower() for group in groups)

    return upsert_directory_user(db, username, is_admin=is_admin, source=AuthMode.PROXY)


# ── Dispatch ──────────────────────────────────────────────────────────────────


def authenticate(db: Session, username: str, password: str) -> User | None:
    """Check a username and password using whichever backend is configured.

    Returns None in proxy mode: there is no password to check, because the
    proxy already did the authenticating.
    """
    mode = auth_mode()
    if mode is AuthMode.LOCAL:
        return authenticate_local(db, username, password)
    if mode is AuthMode.LDAP:
        return authenticate_ldap(db, username, password)
    return None


def local_signup_allowed() -> bool:
    """Registration only means anything when this app owns the passwords."""
    return auth_mode() is AuthMode.LOCAL
