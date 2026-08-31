import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from auth import (
    clear_cover_cookie,
    create_access_token,
    create_cover_token,
    hash_password,
    require_admin,
    set_cover_cookie,
    verify_password,
)
from auth_backends import authenticate, local_signup_allowed
from config import auth_mode, registration_enabled
from dependencies import CurrentUser, DbSession
from enums import AuthMode
from models import User, is_switch_target
from ratelimit import client_address, login_key, login_limiter, register_limiter
from schemas import AuthConfigOut, LoginRequest, Token, UserCreate, UserOut

logger = logging.getLogger("endpaper.auth")

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/config", response_model=AuthConfigOut)
def auth_config() -> AuthConfigOut:
    """Public: the login page reads this before anyone holds a token.

    Read per request rather than captured at import, so closing registration
    takes effect without restarting the container.
    """
    return AuthConfigOut(
        # The frontend uses this to decide what to render: `proxy` means show
        # no auth screen at all, `ldap` means a login form with no signup tab.
        auth_mode=auth_mode(),
        registration_enabled=local_signup_allowed() and registration_enabled(),
    )


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserCreate, request: Request, response: Response, db: DbSession
) -> Token:
    # Both refusals come BEFORE the limiter, deliberately. Under ldap or proxy
    # auth, and with signups closed, this route cannot create an account at
    # all, so charging the caller for the attempt spends a real budget on a
    # certain 403. That budget is keyed on the source address, which behind a
    # reverse proxy is one key for everybody. The limiter now guards only the
    # path that can actually mint an account.
    if not local_signup_allowed():
        raise HTTPException(status_code=403, detail=_signup_refusal())
    if not registration_enabled():
        raise HTTPException(status_code=403, detail="Registration is disabled")

    register_limiter.check(client_address(request))

    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")

    # Whoever registers first becomes the admin. There is no other way to
    # become one, and no endpoint grants the flag afterwards.
    is_first = db.query(User).count() == 0
    # **The address is set here rather than only on the settings screen**, which
    # is the one moment somebody is already typing their details. `UserCreate`
    # normalises it, so "" from a form nobody filled in arrives as None and the
    # account is created exactly as it was before the field existed.
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        is_admin=is_first,
        email=payload.email,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(db, user.id, user.username)
    set_cover_cookie(
        response, create_cover_token(db, user.id, user.username), secure=_is_https(request)
    )
    return Token(
        access_token=token,
        user=UserOut.model_validate(user),
    )


def _signup_refusal() -> str:
    """Why this deployment will not create an account, in words that are true.

    One sentence used to answer for both directory modes, and in proxy mode it
    named something that need not exist: the upstream may be an SSO portal, an
    OIDC provider or a header set by the reverse proxy itself, with no
    directory anywhere. Telling somebody to ask a directory administrator who
    does not exist is worse than saying nothing.
    """
    if auth_mode() is AuthMode.PROXY:
        return "Accounts are managed by whoever signs you in, not here."
    return "Accounts are managed by the directory, not here."


@router.post("/login", response_model=Token)
def login(
    payload: LoginRequest, request: Request, response: Response, db: DbSession
) -> Token:
    key = login_key(payload.username, request)
    login_limiter.check(key)

    # Dispatches to the configured backend. In proxy mode this always returns
    # None: there is nothing to check here because the proxy already did it.
    user = authenticate(db, payload.username, payload.password)
    if user is None:
        # One message for both cases, deliberately: distinguishing "no such
        # user" from "wrong password" lets an attacker enumerate accounts.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    # Getting it right clears the count, so a member who mistyped a few times
    # is not left rationed for the rest of the window.
    login_limiter.reset(key)
    token = create_access_token(db, user.id, user.username)
    # Also as a cookie, scoped to /covers alone, because an <img> tag cannot
    # send the Authorization header this token normally travels in. See
    # auth.COVER_COOKIE_NAME for why that is safe on that route and nowhere
    # else.
    set_cover_cookie(
        response, create_cover_token(db, user.id, user.username), secure=_is_https(request)
    )
    return Token(
        access_token=token,
        user=UserOut.model_validate(user),
    )


@router.post("/switch", response_model=Token)
def switch_account(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> Token:
    """Exchange a password an admin supplies for a session on a test account.

    A login performed on another account's behalf, not impersonation, and the
    difference is the password: it is required and checked the ordinary way.
    The admin knows it because the admin set it. Drop that check and this
    becomes a button that reads anybody's library.

    `LoginRequest`, not a schema of its own, because this **is** a login and
    the same two reasons apply: the registration length floor must not lock out
    a password set before it, and a 422 saying "too short" is a different
    answer from a 401 saying "wrong".

    The two refusals differ here, unlike at `/auth/login`, and can. That route
    answers one message for both cases so nobody can enumerate accounts; this
    one is called by an admin who may already list every account. So a name
    that is not a test account is a **404**, which is true of it as far as this
    route is concerned, and a wrong password is a **401**.

    Rate limited on the same counter as `/auth/login`, keyed the same way. The
    caller holds an admin token, so this is not the first line of defence; it
    is that a password check reachable over HTTP is a password check worth
    bounding, and this one hands back a session on a different account.
    """
    key = login_key(payload.username, request)
    login_limiter.check(key)

    target = db.query(User).filter(User.username == payload.username).first()
    # `is_switch_target` is the rule, in one place, and it is what keeps a
    # directory-backed member out: an admin able to mint a session for one
    # could read that member's private books.
    if not is_switch_target(target):
        raise HTTPException(status_code=404, detail="No such test account")

    # `or ""` is for the type checker alone: being a switch target already
    # means having a hash. An empty one fails the check rather than raising.
    if not verify_password(payload.password, target.password_hash or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password for that account",
        )

    login_limiter.reset(key)
    # WARNING, and it names both accounts. This is the one action in the app
    # that puts one member's session in another member's hands, and
    # `auth_backends` already sets the precedent: the consequential things are
    # logged loudly, because the record of the last incident was an INFO line
    # nobody was reading.
    logger.warning(
        "Admin %r switched into the test account %r",
        current_user.username,
        target.username,
    )

    token = create_access_token(db, target.id, target.username)
    # Exactly like /auth/login, cover cookie included: an <img> cannot send the
    # Authorization header, so without it the switched session has no covers.
    set_cover_cookie(
        response,
        create_cover_token(db, target.id, target.username),
        secure=_is_https(request),
    )
    return Token(access_token=token, user=UserOut.model_validate(target))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> Response:
    """Drop the cover cookie.

    The access token lives in the browser and signing out discards it there,
    but the cookie is ours and would otherwise sit in the browser until it
    expired: on a shared machine, the next person's first page load would still
    fetch covers as the person who left.

    No authentication required, and none wanted. This only deletes something
    the caller already holds, and demanding a valid token would mean an expired
    session could never clear its own cookie.
    """
    response.status_code = status.HTTP_204_NO_CONTENT
    clear_cover_cookie(response)
    return response


def _is_https(request: Request) -> bool:
    """Whether the browser's connection was secure, not ours to the proxy.

    A Secure cookie is silently dropped over plain HTTP, so a LAN deployment
    without a certificate would lose its covers with nothing to explain why.
    The forwarded header is what carries the browser's side of it.
    """
    return (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "") == "https"
    )


@router.get("/me", response_model=UserOut)
def me(current_user: CurrentUser) -> User:
    return current_user
