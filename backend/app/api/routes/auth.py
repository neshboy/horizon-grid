from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import get_current_user, CurrentUser
from app.auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.core import users as user_svc
from app.core.db import get_db
from app.models.user import Role, User
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)) -> UserResponse:
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Self-registration only bootstraps the very first admin. Every subsequent
    # account must be created by an existing admin from the Administration page,
    # so nobody accidentally lands as Analyst via the public form.
    user_count = await db.execute(select(User.id))
    if user_count.first():
        raise HTTPException(
            status_code=403,
            detail="Self-registration is closed. Ask an administrator to create your account from the Administration page.",
        )

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=Role.ADMIN,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserResponse(id=str(user.id), email=user.email, full_name=user.full_name, role=user.role)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        await user_svc.record_login_failure(payload.email)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    await user_svc.record_login_success(user.id, user.email)
    return TokenResponse(
        access_token=create_access_token(user.email, user.role.value, user.token_version),
        refresh_token=create_refresh_token(user.email, user.role.value, user.token_version),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload_body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    payload = decode_token(payload_body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    result = await db.execute(select(User).where(User.email == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    # Without this check, a refresh token issued before an administrator
    # reset this user's password would keep minting valid new access tokens
    # indefinitely -- get_current_user()'s check alone only guards routes
    # that take an access token, not this endpoint itself.
    if payload.get("token_version", 0) != user.token_version:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    return TokenResponse(
        access_token=create_access_token(user.email, user.role.value, user.token_version),
        refresh_token=create_refresh_token(user.email, user.role.value, user.token_version),
    )


@router.get("/me", response_model=UserResponse)
async def me(current: CurrentUser = Depends(get_current_user)) -> UserResponse:
    return UserResponse(id=str(current.id), email=current.email, full_name=current.full_name, role=current.role)
