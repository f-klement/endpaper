from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field

import mailer
from enums import AuthMode, ThemeMode, VerificationProvenance

# bcrypt only hashes the first 72 bytes; anything beyond it is not merely
# useless but actively misleading, since two passwords sharing a 72-byte prefix
# are the same password. The floor is a real (if modest) strength requirement,
# there was none at all before.
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72


def _an_address_or_nothing(value: str | None) -> str | None:
    """One address, or nothing, whichever route is asking.

    Checked with `mailer.looks_like_address`, the rule the household address
    already passes, so this app has one answer to "is that an address" rather
    than two that drift. It is also the header injection control: it refuses
    whitespace anywhere, **a trailing newline included**, every control and non
    printing character, and the comma and semicolon that turn one `To` header
    into two.

    The trailing newline is named because it is the one spelling this rule used
    to accept: `looks_like_address` was anchored with `$` under `match`, which
    matches before a final newline. The `.strip()` below happened to hide it and
    is not what stops it. See `mailer.looks_like_address`.

    An empty or blank string is nothing rather than a refusal. A member clearing
    the field types nothing into it, and a 422 for "" would make "remove my
    address" the one edit the form could not express. At registration the same
    spelling is the ordinary case: a browser sends "" for a field nobody filled
    in.
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if not mailer.looks_like_address(stripped):
        raise ValueError("That is not an address.")
    return stripped


#: An address as every route that takes one accepts it.
#:
#: **One alias rather than the same field written out twice**, because the two
#: routes that take an address are the same question asked at two moments:
#: `PUT /users/me/email` edits one and `POST /auth/register` sets it while the
#: account is being made. `MAX_ADDRESS` and the column's `String(320)` agree,
#: and the bound is enforced here because SQLite would not enforce it.
AddressField = Annotated[
    str | None,
    Field(max_length=mailer.MAX_ADDRESS),
    AfterValidator(_an_address_or_nothing),
]


class UserCreate(BaseModel):
    """Registration. The length floor is a policy for *new* passwords only.

    **The address is optional and stays optional**, which is the whole of the
    compatibility story: an account with none must keep working, because that is
    every account that existed before the column did. A client that sends no
    `email` creates exactly the account it created before.
    """

    username: str = Field(min_length=1, max_length=50, pattern=r"^\S.*$")
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_BYTES)
    email: AddressField = None


class LoginRequest(BaseModel):
    """Sign-in. Deliberately does NOT enforce the registration password policy.

    Two reasons. Accounts created before the policy existed have shorter
    passwords, and validating length here would lock those members out of their
    own library rather than merely asking them to pick a better one. And a 422
    for "too short" is a different response from a 401 for "wrong", which tells
    an attacker something about the stored password.
    """

    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_BYTES)


class UserOut(BaseModel):
    """A member as seen by other members. Deliberately has no password field.

    **And deliberately no address.** This is served inside every book payload
    and by the member list, so a field here is disclosed to every member who can
    see a book. `MemberEmailOut` is where an address is served, on the four
    routes named in `routers/users.py` and nowhere else;
    `tests/test_house_rules.py::TestAnAddressIsServedOnlyWhereItIsNamed` fails
    if **any** other model puts one in front of a caller, and it asks pydantic
    for the wire name, so an alias does not get past it.
    """

    id: int
    username: str
    is_admin: bool
    created_at: datetime
    model_config = {"from_attributes": True}


class MemberEmailOut(BaseModel):
    """One member's address, on the only routes that serve one.

    **One model for the caller's own address and for an admin reading
    somebody's**, rather than two. The two differ in who may ask, which is the
    route's business, and not in what an address is. Two models would be two
    entries in the guard above and two places for the next field to be added to
    one of.

    `id` and `username` are on it even for `GET /me/email`, where the caller
    already knows both. They cost nothing there and they are what makes the
    admin list a list of members rather than a list of strings.

    `editable` is per row, not per deployment: `auth_backends.directory_owns_email`
    reads that member's own `auth_source`, so a local test account stays
    editable in a library running LDAP. The client draws a read only field
    saying the address comes from the directory when it is false; the server
    refuses the write regardless, because a client is not a control.

    **`from_directory` is not the negation of `editable`, and that is the whole
    reason it exists.** Three cases, and the two flags separate them where one
    could not:

    | account | `from_directory` | `editable` |
    |---|---|---|
    | local | false | true |
    | directory, no address attribute configured | **true** | **true** |
    | directory, an address attribute configured | true | false |
    | `auth_source` spelled as nothing this build knows | false | true |

    **The fourth row is why this is computed from the named directories rather
    than from "not local".** `users.auth_source` carries no `CheckConstraint`,
    which `auth_backends.directory_owns_email` states and depends on, so a
    restored or hand edited row can hold anything. Under `!= LOCAL` such a row
    read as a directory account and its owner was told a directory they do not
    have supplies no address.

    The middle row is #103's open question and the one nobody could be told
    about: the account appeared at a first sign in with nobody filling in a
    form, and the directory carries no address, so it has none and its owner is
    the only person who can give it one. `editable` alone says "you may type
    here" and cannot say why the box is empty. This is what lets the screen say
    the directory did not supply one rather than leaving a member to infer it.

    It discloses no address and widens nothing: this model is already restricted
    to the four routes in `routers/users.py`, and the caller is the member
    themselves or an admin.
    """

    id: int
    username: str
    email: str | None = None
    editable: bool
    #: Required, not defaulted, so the pair is published with one strength.
    #: `_member_email` is the only constructor and always sets it, and a default
    #: would make the generated client read `from_directory?: boolean` beside
    #: `editable: boolean` for two halves of one deliberately paired fact.
    from_directory: bool


class EmailUpdate(BaseModel):
    """An address, or null to clear it. The rule is `AddressField`."""

    email: AddressField = None


#: What a palette or wallpaper id may look like.
#:
#: Which ids exist is the frontend's business: the palettes are CSS blocks and
#: the wallpapers are drawing code, and a server that held the list would have
#: to be redeployed to add one. What the server does own is the shape, so a
#: stored value cannot be a megabyte of anything or carry characters that mean
#: something to whatever reads it back.
_APPEARANCE_ID = r"^[a-z0-9-]{1,30}$"


class AppearanceOut(BaseModel):
    """One member's own appearance. Never another member's.

    Deliberately not part of `UserOut`, which is served inside every book
    payload and the member list: appearance on that schema would tell everyone
    in the library what everyone else's library looks like.

    Every field is nullable and null means "has not chosen", which is what a
    new account and every directory shadow account start as. The client then
    follows the system for the mode, uses the house palette, and picks a
    different wallpaper each visit.
    """

    palette: str | None = None
    mode: ThemeMode | None = None
    wallpaper: str | None = None


class AppearanceUpdate(BaseModel):
    """A whole appearance, replaced.

    A PUT rather than a PATCH, because for all three fields null is a value a
    member can actually choose ("follow the system", "the house palette", "a
    different wallpaper every time"). Under PATCH semantics an explicit null
    and an absent key are the same JSON, so clearing a preference and leaving
    it alone would be indistinguishable without inspecting `model_fields_set`.
    """

    palette: str | None = Field(default=None, pattern=_APPEARANCE_ID)
    mode: ThemeMode | None = None
    wallpaper: str | None = Field(default=None, pattern=_APPEARANCE_ID)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class RegistrationOut(BaseModel):
    """What registering produced: a session, or an account with something to prove.

    **The token is optional and that is the whole shape of the account policy.**
    Where accounts are open to people outside the household, a new account may do
    nothing until its address is confirmed, so handing back a session would hand
    back the thing the policy exists to withhold. Where the policy is off,
    nothing changes and the token is there, exactly as this route has always
    answered.

    Two fields rather than a nullable token alone, because "there is no token"
    and "you have something to do next" are different sentences and only the
    second is one a screen can render.
    """

    verification_required: bool
    token: Token | None = None


#: What a one time code may look like on the way in.
#:
#: Generous rather than exact: `accounts.normalise_code` strips spacing and case
#: before anything compares, so the schema's job is to bound the length rather
#: than to re-state the alphabet. A pattern here would be a second spelling of
#: `accounts.CODE_ALPHABET` and the two would drift.
MAX_CODE_LENGTH = 64


class ResetRequest(BaseModel):
    """A member, signed out, asking to be let back in.

    No password and no address: this asks a person to act and grants nothing, so
    there is nothing to check. The username is what the admin's queue is read
    against.
    """

    username: str = Field(min_length=1, max_length=50)


class ResetRedeem(BaseModel):
    """A code an admin read out, and the password it is being spent on.

    `MIN_PASSWORD_LENGTH` applies here and deliberately not at sign in: this is a
    **new** password, so the registration policy is the right one, and there is
    no account created before the policy for it to lock out.
    """

    username: str = Field(min_length=1, max_length=50)
    code: str = Field(min_length=1, max_length=MAX_CODE_LENGTH)
    new_password: str = Field(
        min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_BYTES
    )


class VerificationRequest(BaseModel):
    """Send the confirmation code for this account again."""

    username: str = Field(min_length=1, max_length=50)


class VerificationRedeem(BaseModel):
    """The confirmation code that arrived by mail."""

    username: str = Field(min_length=1, max_length=50)
    code: str = Field(min_length=1, max_length=MAX_CODE_LENGTH)


class ResetCodeOut(BaseModel):
    """The one time code an approval produced, shown once and never again.

    **The only model in the application carrying a `code`**, which is not an
    incidental fact: it is stored as a bcrypt hash, so there is no second route
    that could serve it even by accident, and
    `tests/test_house_rules.py::TestAOneTimeCodeIsServedOnlyWhereItIsNamed`
    fails if another model grows the field.
    """

    code: str
    expires_at: datetime


class ResetRequestOut(BaseModel):
    """One pending request, as the admin's queue shows it.

    Carries no code and no hash. `approved_at`, `approved_by` and
    `code_expires_at` are what the queue needs in order to say a request has
    already been granted and until when, since the code itself was shown once
    and cannot be shown again: after a reload the plaintext is gone from the
    browser and these three are all an admin has left of it.
    """

    user_id: int
    username: str
    requested_at: datetime
    expires_at: datetime
    approved_at: datetime | None = None
    approved_by: str | None = None
    code_expires_at: datetime | None = None


class MemberVerificationOut(BaseModel):
    """One member's verification state, for the admin panel that overrides it.

    **Deliberately no address**, though the screen behind it is about addresses:
    `MemberEmailOut` is where an address is served and this is not one of those
    four routes. `has_address` is what the screen actually needs, because the
    question it answers is whether a code could have been sent at all.
    """

    id: int
    username: str
    verified_at: datetime | None = None
    verification_source: VerificationProvenance | None = None
    verified_by: str | None = None
    has_address: bool
    #: False for a directory account, which this app never held a credential for.
    applies: bool


class MySecurityOut(BaseModel):
    """What happened to the caller's own account, and who did it.

    The member's half of the admin confirmed reset. A reset that left no mark on
    the account would be indistinguishable from a quiet takeover, which is the
    property the flow exists to keep, so this is served on its own route rather
    than being a field on `UserOut`: that schema is inside every book payload and
    the member list, and who reset whose password is nobody else's business.
    """

    password_reset_at: datetime | None = None
    password_reset_approved_by: str | None = None
    verified_at: datetime | None = None
    verification_source: VerificationProvenance | None = None
    verified_by: str | None = None


class AuthConfigOut(BaseModel):
    """Read by the login page before anyone holds a token."""

    auth_mode: AuthMode
    registration_enabled: bool
    #: Whether this deployment will reset a local password at all. False under
    #: ldap and proxy, where the credential is somebody else's, and the login
    #: page draws no recovery link rather than one that answers 403.
    password_reset_enabled: bool
    #: Whether a new account has to confirm its address before it may sign in.
    #: The login page needs it to ask for an address at registration and to draw
    #: the confirmation form.
    verification_required: bool
