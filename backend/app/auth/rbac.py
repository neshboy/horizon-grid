"""FastAPI dependencies for authentication and permission-based authorization."""
import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import decode_token
from app.core.db import get_db
from app.models.user import ROLE_PERMISSIONS, Role, User

# HTTPBearer (not OAuth2PasswordBearer) because /auth/login takes a JSON body,
# not the OAuth2 password-grant's form-encoded username/password -- using
# OAuth2PasswordBearer here would make Swagger's "Authorize" button POST form
# data to /auth/login and get a 422, since that endpoint expects JSON.
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    id: uuid.UUID
    email: str
    role: Role
    full_name: str = ""


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not credentials:
        raise credentials_error
    payload = decode_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        raise credentials_error

    result = await db.execute(select(User).where(User.email == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise credentials_error
    # A token issued before an administrator-initiated password reset (see
    # app/core/users.py's reset_password()) embeds the OLD token_version --
    # reject it immediately rather than letting it keep working until it
    # naturally expires. payload.get(..., 0) treats a pre-this-feature JWT
    # (no claim at all) as version 0, matching every existing user's
    # initial column value, so this never forces an unrelated logout.
    if payload.get("token_version", 0) != user.token_version:
        raise credentials_error
    return CurrentUser(id=user.id, email=user.email, role=user.role, full_name=user.full_name)


def require_permission(permission: str):
    """Dependency factory: require_permission('lookup:create') gates a route
    to only roles whose ROLE_PERMISSIONS set includes that permission."""

    async def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if permission not in ROLE_PERMISSIONS.get(user.role, set()):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role.value}' lacks permission '{permission}'",
            )
        return user

    return _check
