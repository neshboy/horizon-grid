"""Pydantic schemas for the admin user-management API
(app/api/routes/admin.py)."""
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from app.models.user import Role
from app.schemas.auth import _MAX_PASSWORD_LENGTH


class UserListItem(BaseModel):
    id: str
    email: str
    full_name: str
    role: Role
    is_active: bool
    created_at: str
    last_login_at: Optional[str] = None


class UserListResponse(BaseModel):
    items: list[UserListItem]
    total: int
    page: int
    page_size: int


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=_MAX_PASSWORD_LENGTH)
    full_name: str = ""
    role: Role = Role.ANALYST


class UpdateUserRequest(BaseModel):
    full_name: Optional[str] = None
    role: Optional[Role] = None


class SetActiveRequest(BaseModel):
    is_active: bool


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=_MAX_PASSWORD_LENGTH)


class UserStatsResponse(BaseModel):
    total_users: int
    active_users: int
    disabled_users: int
    by_role: dict[str, int]
    recent_logins: list[dict]


class RolePermissionsResponse(BaseModel):
    role: Role
    permissions: list[str]
