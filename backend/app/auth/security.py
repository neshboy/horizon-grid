"""Password hashing and JWT access/refresh token helpers."""
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(plain_password, hashed_password)


def _create_token(
    subject: str, role: str, token_version: int, expires_delta: timedelta, token_type: str
) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "role": role,
        "token_version": token_version,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(subject: str, role: str, token_version: int = 0) -> str:
    settings = get_settings()
    return _create_token(
        subject, role, token_version, timedelta(minutes=settings.access_token_expire_minutes), "access"
    )


def create_refresh_token(subject: str, role: str, token_version: int = 0) -> str:
    settings = get_settings()
    return _create_token(
        subject, role, token_version, timedelta(days=settings.refresh_token_expire_days), "refresh"
    )


def decode_token(token: str) -> Optional[dict[str, Any]]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
