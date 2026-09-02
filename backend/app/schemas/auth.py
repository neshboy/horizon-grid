from pydantic import BaseModel, EmailStr, Field

from app.models.user import Role

# bcrypt (via passlib) hard-fails with an uncaught PasswordSizeError past
# 4096 bytes -- confirmed live: a 4097-char password crashed both
# /auth/register and /auth/login with an unhandled 500 before this field
# constraint existed. 72 is bcrypt's own actual security-relevant limit
# (everything past 72 bytes is silently ignored by the algorithm itself,
# not just passlib's outer guard), so capping here also stops a client
# from believing a 500-character password adds any real entropy beyond the
# first 72 bytes.
_MAX_PASSWORD_LENGTH = 72


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=_MAX_PASSWORD_LENGTH)
    # Same class of gap as the password field above, found live during
    # overnight QA via the sibling admin-create-user endpoint (schemas/
    # admin.py's CreateUserRequest): full_name has no bound here either,
    # and app/models/user.py's column is String(255) -- an oversized value
    # would crash this, the very first bootstrap-admin registration, with
    # an unhandled 500 instead of a clean 422.
    full_name: str = Field(default="", max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=_MAX_PASSWORD_LENGTH)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: Role

    model_config = {"from_attributes": True}
