from fastapi import APIRouter, HTTPException, Request, Response, status

from auth import (
    clear_cover_cookie,
    create_access_token,
    create_cover_token,
    hash_password,
    set_cover_cookie,
)
from auth_backends import authenticate, local_signup_allowed
from config import auth_mode, registration_enabled
from dependencies import CurrentUser, DbSession
from enums import AuthMode
from models import User
from ratelimit import client_address, login_key, login_limiter, register_limiter
from schemas import AuthConfigOut, LoginRequest, Token, UserCreate, UserOut

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
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        is_admin=is_first,
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
