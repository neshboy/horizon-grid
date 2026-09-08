"""Admin user-management API -- the backend for the RBAC admin console.
Every route is gated by require_permission("user:manage"), which
ROLE_PERMISSIONS (app/models/user.py) grants to Role.ADMIN only. This is the
actual authorization boundary: nothing here trusts the frontend to hide a
button, and every route re-derives the caller's role from the database on
every request (app/auth/rbac.py's get_current_user()), not from the JWT.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.rbac import CurrentUser, require_permission
from app.core import users as svc
from app.models.user import ROLE_PERMISSIONS, Role
from app.schemas.admin import (
    CreateUserRequest,
    ResetPasswordRequest,
    SetActiveRequest,
    UpdateUserRequest,
    UserListResponse,
    UserStatsResponse,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=UserListResponse)
async def list_users(
    search: str = "",
    role: Optional[Role] = None,
    is_active: Optional[bool] = None,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    user: CurrentUser = Depends(require_permission("user:manage")),
):
    return await svc.list_users(search, role, is_active, page, page_size, sort_by, sort_dir)


@router.get("/users/stats", response_model=UserStatsResponse)
async def user_stats(user: CurrentUser = Depends(require_permission("user:manage"))):
    return await svc.get_stats()


@router.get("/roles")
async def list_roles(user: CurrentUser = Depends(require_permission("user:manage"))):
    """Read-only view of the fixed role -> permission matrix, so the admin
    console's Roles & Permissions page never hardcodes a second copy of
    ROLE_PERMISSIONS that could silently drift out of sync with it."""
    return [{"role": r.value, "permissions": sorted(ROLE_PERMISSIONS[r])} for r in Role]


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(payload: CreateUserRequest, user: CurrentUser = Depends(require_permission("user:manage"))):
    try:
        return await svc.create_user(
            payload.email, payload.password, payload.full_name, payload.role, user.id, user.email
        )
    except svc.DuplicateEmailError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/users/{user_id}")
async def update_user(
    user_id: uuid.UUID, payload: UpdateUserRequest, user: CurrentUser = Depends(require_permission("user:manage"))
):
    try:
        return await svc.update_user(user_id, user.id, user.email, full_name=payload.full_name, role=payload.role)
    except svc.LastAdminError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except svc.SelfRoleChangeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except svc.UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/users/{user_id}/active")
async def set_user_active(
    user_id: uuid.UUID, payload: SetActiveRequest, user: CurrentUser = Depends(require_permission("user:manage"))
):
    try:
        return await svc.set_user_active(user_id, payload.is_active, user.id, user.email)
    except svc.LastAdminError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except svc.SelfDeactivationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except svc.UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: uuid.UUID,
    payload: ResetPasswordRequest,
    user: CurrentUser = Depends(require_permission("user:manage")),
):
    try:
        return await svc.reset_password(user_id, payload.new_password, user.id, user.email)
    except svc.UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
