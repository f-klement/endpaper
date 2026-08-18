from datetime import datetime

from pydantic import BaseModel, Field

from enums import AuthMode

# bcrypt only hashes the first 72 bytes; anything beyond it is not merely
# useless but actively misleading, since two passwords sharing a 72-byte prefix
# are the same password. The floor is a real (if modest) strength requirement,
# there was none at all before.
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72


class UserCreate(BaseModel):
    """Registration. The length floor is a policy for *new* passwords only."""

    username: str = Field(min_length=1, max_length=50, pattern=r"^\S.*$")
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_BYTES)


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
    """A member as seen by other members. Deliberately has no password field."""

    id: int
    username: str
    is_admin: bool
    created_at: datetime
    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class AuthConfigOut(BaseModel):
    """Read by the login page before anyone holds a token."""

    auth_mode: AuthMode
    registration_enabled: bool
