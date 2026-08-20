from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

import settings_store
from config import auth_mode, secret_key
from database import get_db
from enums import AuthMode
from models import User, is_switch_target

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 1 week

# ── The media cookie ──────────────────────────────────────────────────────────
#
# Covers are served by a route that applies `book_for_read`, because the static
# mount they used to be had no authorization at all and cover files are named by
# book id. That fix has one consequence: an `<img src>` cannot carry an
# `Authorization` header, so under `AUTH_MODE=local`, where identity lives in a
# token in localStorage, every cover request arrives anonymous and 401s. Under
# proxy auth it is fine, because identity arrives in a request header the proxy
# sets on every request. Local is the published image's default, so unfixed this
# ships a catalogue with no covers.
#
# So a token is also placed in a cookie. Not the same token: this one is minted
# with `scope: covers` and every route other than the cover route refuses it, so
# a cookie that escapes cannot be replayed as a bearer token against the API.
# Three further properties keep it from being a CSRF hole rather than a fix:
#
#   Path=/covers   The browser never sends it anywhere else. It cannot
#                  authenticate a write because it does not reach a write.
#   HttpOnly       Script cannot read it, so an XSS cannot exfiltrate the token
#                  from here (it is still in localStorage; this adds nothing).
#   SameSite=Lax   Not None. A cross-site <img> is a GET, and Lax withholds the
#                  cookie on cross-site subresource loads, so another site
#                  embedding /covers/1.jpg gets a 401 rather than a picture.
#
# The route it guards is a GET that changes nothing, which is the whole reason
# cookie auth is acceptable here and would not be acceptable on the API.
COVER_COOKIE_NAME = "endpaper_cover"
# Claimed by the cookie token and refused by every route but the cover one.
COVER_SCOPE = "covers"
COVER_COOKIE_PATH = "/covers"

# Deliberately shorter than the token's own week. This app has no revocation
# short of rotating SECRET_KEY, and the cookie is a second copy of the token
# living outside localStorage, so bounding how long that copy is useful costs
# one silent re-login a day and shortens the window a stolen cookie is worth
# anything. The token itself is unaffected: the app keeps working from
# localStorage, and only the covers go quiet until the next sign-in.
COVER_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24

# bcrypt hashes at most the first 72 bytes of a password and ignores the rest.
# The C implementation truncates silently; the Python binding raises instead, so
# truncation is done here to keep the behaviour of previously stored hashes.
BCRYPT_MAX_BYTES = 72

# auto_error=False so a missing token is not an automatic 401: in proxy mode
# there is no token at all, and the caller is identified by a header instead.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def _password_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_password_bytes(plain), hashed.encode("utf-8"))
    except ValueError:
        # Malformed hash in the database: treat as a failed login, not a 500.
        return False


def create_cover_token(db: Session, user_id: int, username: str) -> str:
    """A token that can fetch covers and do nothing else.

    Deliberately not the access token. The cookie is the one place identity
    leaves the Authorization header, and a copy of the full token there means
    anything that can read a cookie can act as the account. Scoping it means
    the worst case is somebody else seeing the cover images.
    """
    return _encode(db, user_id, username, scope=COVER_SCOPE)


def create_access_token(db: Session, user_id: int, username: str) -> str:
    """Mint a signed token for `user_id`.

    Takes the session rather than defaulting the epoch, so a new call site
    cannot quietly issue a token that survives a restore.
    """
    return _encode(db, user_id, username, scope=None)


def _encode(db: Session, user_id: int, username: str, *, scope: str | None) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload: dict[str, object] = {
        "sub": str(user_id),
        "username": username,
        "exp": expire,
        "epoch": settings_store.token_epoch(db),
    }
    if scope is not None:
        payload["scope"] = scope
    return jwt.encode(payload, secret_key(), algorithm=ALGORITHM)


def set_cover_cookie(response: Response, token: str, *, secure: bool) -> None:
    """Attach the media cookie to a successful sign-in.

    `secure` is decided by the caller from the request scheme rather than
    hardcoded: a LAN deployment over plain HTTP would silently drop a Secure
    cookie, and covers would stay broken with nothing to show why.
    """
    response.set_cookie(
        COVER_COOKIE_NAME,
        token,
        max_age=COVER_COOKIE_MAX_AGE_SECONDS,
        path=COVER_COOKIE_PATH,
        httponly=True,
        secure=secure,
        samesite="lax",
    )


def clear_cover_cookie(response: Response) -> None:
    response.delete_cookie(COVER_COOKIE_NAME, path=COVER_COOKIE_PATH)


def _user_from_token(token: str, db: Session, *, scope: str | None = None) -> User | None:
    """The account a token names, or None if it does not name one usable here.

    `scope` defaults to None, which means a full access token: a scoped token
    is refused everywhere its scope is not asked for. Defaulting the other way
    would make every new call site accept the cover cookie by omission.
    """
    try:
        payload = jwt.decode(token, secret_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    user_id = payload.get("sub")
    if user_id is None:
        return None
    if payload.get("scope") != scope:
        return None
    # A token from before the last restore names an id in a user table that no
    # longer exists. See settings_store.bump_token_epoch.
    if payload.get("epoch") != settings_store.token_epoch(db):
        return None
    return db.get(User, int(user_id))


def _switch_session(
    token: str | None, db: Session, *, scope: str | None = None
) -> User | None:
    """The test account a switch token names, or None if it names anything else.

    Only consulted under proxy auth, where the upstream owns identity and the
    one session this app issues itself is an admin switching into a test
    account. So the token is refused unless the account it names is still a
    switch target, which a directory-backed account never is: the acceptance is
    narrow by construction rather than by a claim somebody has to remember to
    set, and it narrows further the moment the flag comes off the row.

    That matters beyond tidiness. Accepting *any* valid token over the header
    would also revive tokens minted before a deployment moved to proxy auth,
    and those name real members with real libraries.

    A token that is expired, forged or no longer a switch target returns None,
    and the caller falls back to the header. Failing closed instead would
    strand whoever holds a stale one behind an error page, with no control on
    screen to clear it, and gains nothing: the header is the identity the
    deployment already authenticated.
    """
    if token is None:
        return None
    user = _user_from_token(token, db, scope=scope)
    return user if is_switch_target(user) else None


def get_current_user_for_cover(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Identity for the cover route, and for nothing else.

    Same rules as `get_current_user`, plus the cookie fallback described at
    `COVER_COOKIE_NAME`. Kept as a separate dependency rather than folded into
    `get_current_user` on purpose: accepting a cookie on every route is how a
    GET-only convenience becomes CSRF on the write endpoints.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if auth_mode() is AuthMode.PROXY:
        from auth_backends import user_from_proxy_headers

        # A switch session wins over the header here too, and the cookie is the
        # half that matters: an <img> sends no Authorization header, so without
        # it a switched admin sees the test account's library with a hole where
        # every cover it may see and the proxy identity may not used to be.
        switched = _switch_session(token, db)
        if switched is None:
            switched = _switch_session(
                request.cookies.get(COVER_COOKIE_NAME), db, scope=COVER_SCOPE
            )
        if switched is not None:
            return switched

        proxied = user_from_proxy_headers(db, request)
        if proxied is None:
            raise credentials_exception
        return proxied

    # The header still wins where there is one, so a fetch() for a cover
    # behaves identically to every other call. Each source is checked against
    # the scope it is supposed to carry: a full token from the header, a
    # covers-scoped one from the cookie, and neither accepted in the other's
    # place.
    if token is not None:
        user = _user_from_token(token, db)
    else:
        cookie = request.cookies.get(COVER_COOKIE_NAME)
        user = _user_from_token(cookie, db, scope=COVER_SCOPE) if cookie else None
    if user is None:
        raise credentials_exception
    return user


def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if auth_mode() is AuthMode.PROXY:
        # Imported here rather than at module scope: auth_backends imports this
        # module for verify_password, so a top-level import would be circular.
        from auth_backends import user_from_proxy_headers

        # An admin who exchanged a password for a session on a test account is
        # that account until the token is discarded, header or no header. That
        # is the whole of "switch back": drop the token and the proxy names the
        # admin again on the very next request.
        switched = _switch_session(token, db)
        if switched is not None:
            return switched

        proxied = user_from_proxy_headers(db, request)
        if proxied is None:
            raise credentials_exception
        return proxied

    if token is None:
        raise credentials_exception

    # Through the one helper rather than decoding again here. This route used
    # to carry its own copy of the same checks, which meant the epoch check
    # landed on the cover route and not on this one: the difference between a
    # restore ending every session and ending none of them.
    user = _user_from_token(token, db)
    if user is None:
        raise credentials_exception
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
