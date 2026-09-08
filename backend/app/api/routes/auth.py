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
from app.core.cache import RateLimiter
from app.core.config import get_settings
from app.core.db import get_db
from app.models.user import Role, User
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])

# Precomputed once at import time so login() below always has a valid bcrypt
# hash to compare against when no matching user row was found. See its use
# in login() for why this exists (a timing side-channel fix).
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-constant-time-login-checks")


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)) -> UserResponse:
    # Real bugs found live during overnight QA, both fixed here together:
    # (1) Email-enumeration oracle -- this used to check "email already
    # registered" BEFORE "registration closed", so an anonymous, unrated
    # caller got two distinguishable responses (400 vs 403) that directly
    # revealed whether an arbitrary email had a real account, at unlimited
    # speed. Checking "closed" first means every anonymous call gets the
    # exact same 403 once any user exists -- the only case that still
    # reaches the duplicate-email check is the empty-table bootstrap,
    # where no duplicate can exist yet anyway, so the oracle has nothing
    # left to reveal. (2) No throttling at all on a public, unauthenticated
    # endpoint -- keyed on the ATTEMPTED email (like login's own limiter,
    # not a single global bucket shared by every caller) so this bounds
    # repeated attempts against one candidate address without one heavy
    # caller exhausting a shared budget for everyone else.
    settings = get_settings()
    register_limiter = RateLimiter(
        f"register:{payload.email.lower()}",
        max_calls=settings.login_rate_limit_max_attempts,
        window_seconds=settings.login_rate_limit_window_seconds,
    )
    if not await register_limiter.allow():
        raise HTTPException(
            status_code=429,
            detail=f"Too many registration attempts for this address. Try again in under "
            f"{settings.login_rate_limit_window_seconds} seconds.",
        )

    # Self-registration only bootstraps the very first admin. Every subsequent
    # account must be created by an existing admin from the Administration page,
    # so nobody accidentally lands as Analyst via the public form.
    user_count = await db.execute(select(User.id))
    if user_count.first():
        raise HTTPException(
            status_code=403,
            detail="Self-registration is closed. Ask an administrator to create your account from the Administration page.",
        )

    # Email lookups/storage were
    # never case-normalized anywhere in the auth stack (only the rate-
    # limiter key above was ever lowercased) -- a correct password with a
    # different-case email was rejected as "invalid" even though the
    # account genuinely matched. Storing lowercased here, and looking up
    # lowercased at login below, makes email matching consistently
    # case-insensitive going forward (existing rows created before this
    # fix are not retroactively migrated).
    normalized_email = payload.email.lower()
    existing = await db.execute(select(User).where(User.email == normalized_email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=normalized_email,
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
    # Real gap fixed: failed logins were logged/audited but never throttled
    # at all -- nothing previously stopped an unlimited-speed brute-force
    # attempt against any known email. Keyed on the ATTEMPTED email
    # (case-normalized the same way registration/login lookups already
    # are) rather than source IP, since this app has no reverse-proxy-aware
    # trusted-IP configuration to safely extract a real client IP from --
    # an attacker-controlled IP is trivially fake at either FastAPI or a
    # naive X-Forwarded-For read, so a per-account limit is the honest,
    # exploit-resistant choice available right now.
    #
    # Real bug found live during overnight QA: this limiter used to be
    # checked BEFORE the password was verified, so the 429 fired for
    # *anyone* hitting that email -- including a caller supplying the
    # genuinely correct password. That let an unauthenticated attacker who
    # only knows the victim's email (no valid credential at all) trip the
    # limiter with wrong-password noise and keep the real owner's own
    # correct-password logins failing with 429 for as long as they kept
    # sending traffic, directly contradicting the "can never itself become
    # a way to lock a real admin out" intent below. Verifying the
    # credential first and only consulting/incrementing the limiter on the
    # failure path means a correct password always succeeds regardless of
    # how many bad attempts preceded it -- only a *string of wrong*
    # passwords/unknown emails against one address can ever be throttled.
    settings = get_settings()

    # See register()'s comment above -- this lookup was never actually
    # case-normalized despite this function's own pre-existing comment
    # claiming it was; confirmed live that a correct password with a
    # different-case email was rejected. Only the rate-limiter key a few
    # lines up was ever lowercased.
    result = await db.execute(select(User).where(User.email == payload.email.lower()))
    user = result.scalar_one_or_none()
    # Real timing side-channel fixed here, confirmed live against the running
    # stack: `not user or not verify_password(...)` used Python's `or`
    # short-circuiting, so verify_password() (bcrypt, deliberately slow) only
    # ever ran when a matching row was found. A nonexistent email returned
    # right after the SELECT (~350-390ms), while an existing email with a
    # wrong password paid the full bcrypt cost too (~750-910ms) -- an
    # unauthenticated caller could enumerate real account emails purely by
    # timing a handful of requests per address, no credentials or rate-limit
    # bypass needed. Always calling verify_password -- against the
    # precomputed dummy hash above when no user was found -- means every
    # wrong-credential response pays the same bcrypt cost either way. This
    # can never itself authenticate a nonexistent user: `not user` alone
    # already forces the failure branch below regardless of what
    # verify_password returns in that case.
    password_ok = verify_password(payload.password, user.hashed_password if user else _DUMMY_PASSWORD_HASH)
    # Shared across every branch below that cannot end in a usable session
    # (wrong password/unknown email, AND a disabled account -- even with the
    # correct password, since a disabled account can never successfully log
    # in regardless of request rate). Only the genuine success path at the
    # bottom of this function never touches this limiter, preserving the
    # "a correct password against an active account is never itself
    # throttled" guarantee described above.
    #
    # Real bug found live during overnight QA: the disabled-account check
    # used to live entirely outside this limiter (no RateLimiter reference
    # at all on that branch), so a caller holding a valid password for a
    # disabled account -- e.g. a leaked credential for a just-offboarded or
    # suspected-compromised employee, precisely the accounts most likely to
    # be disabled -- could hit this endpoint at unlimited speed, forcing a
    # full bcrypt verify_password() (~750-900ms of CPU per the timing
    # comment above) on every single request forever. Live-verified: 15
    # correct-password requests against a disabled account in under 60s
    # all returned 403 with no 429 ever appearing, while the same request
    # rate with a wrong password against the same disabled account was
    # throttled with a 429 after the configured max attempts, confirming
    # this branch alone was exempt.
    login_limiter = RateLimiter(
        f"login:{payload.email.lower()}",
        max_calls=settings.login_rate_limit_max_attempts,
        window_seconds=settings.login_rate_limit_window_seconds,
    )
    if not user or not password_ok:
        if not await login_limiter.allow():
            raise HTTPException(
                status_code=429,
                detail=f"Too many login attempts for this account. Try again in under "
                f"{settings.login_rate_limit_window_seconds} seconds.",
            )
        await user_svc.record_login_failure(payload.email)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        if not await login_limiter.allow():
            raise HTTPException(
                status_code=429,
                detail=f"Too many login attempts for this account. Try again in under "
                f"{settings.login_rate_limit_window_seconds} seconds.",
            )
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


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> None:
    """Real bug found live during overnight QA: there was no logout route
    at all -- the frontend's "Log out" only ever cleared localStorage
    client-side, so a still-unexpired access token (up to ~30 min) and its
    refresh token (up to 7 days) both kept working indefinitely after
    logout, e.g. if that token had already leaked (XSS, a shared/public
    machine, a synced browser profile). Bumping token_version is the exact
    mechanism app/core/users.py's reset_password() already uses to revoke
    a user's outstanding tokens immediately -- live-confirmed there that it
    works; this just wires the same mechanism to a self-service action
    instead of only an admin-initiated one."""
    user = await db.get(User, current.id)
    if user is not None:
        user.token_version += 1
        await db.commit()
