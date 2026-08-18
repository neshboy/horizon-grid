"""User and RBAC models."""
import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Role(str, enum.Enum):
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.ANALYST, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Embedded in every issued JWT and re-checked on every request
    # (app/auth/rbac.py's get_current_user()); bumped by
    # app/core/users.py's reset_password() so an administrator-initiated
    # password reset immediately invalidates every access/refresh token
    # already issued to this user, not just future logins. A JWT predating
    # this column has no "token_version" claim at all, which the check
    # treats as 0 -- so this ships with zero forced logouts.
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.email} ({self.role})>"


# Permission matrix consumed by app/auth/rbac.py's require_role dependency.
#
# "dashboard:read" is granted to ALL THREE roles deliberately -- it gates
# read-only, operational-visibility endpoints only (GET /dashboard/kpis, the
# real GET /providers/health), never anything credential-management or
# write-capable. Analysts/viewers seeing the operational picture (queue
# depth, provider health, AI reliability) is intentional, not an oversight.
ROLE_PERMISSIONS: dict[Role, set[str]] = {
    Role.ADMIN: {
        "lookup:create", "lookup:read", "lookup:export",
        "provider:manage", "user:manage", "audit:read",
        "evidence:read", "analysis:generate", "hunting:generate", "copilot:query",
        "basket:manage", "case:create", "case:read", "case:write", "case:close",
        "security_assessment:create", "security_assessment:read",
        "dashboard:read",
    },
    Role.ANALYST: {
        "lookup:create", "lookup:read", "lookup:export",
        "evidence:read", "analysis:generate", "hunting:generate", "copilot:query",
        "basket:manage", "case:create", "case:read", "case:write", "case:close",
        "security_assessment:create", "security_assessment:read",
        "dashboard:read",
    },
    Role.VIEWER: {
        "lookup:read", "evidence:read", "case:read", "security_assessment:read",
        "dashboard:read",
    },
}
