"""Admin-facing user management service layer for the RBAC admin console --
list/search/paginate, create, edit (full name/role), enable/disable, and
password reset. Every mutation is audit-logged via app/core/audit.py.

Role/is_active changes need no session-invalidation logic: app/auth/rbac.py's
get_current_user() always re-reads both columns from the database on every
request rather than trusting the JWT's embedded `role` claim, so a role
change or a disable already takes effect on the user's very next request.

No hard-delete. app/models/case.py's analyst_id/added_by/author_id/
generated_by and app/models/basket.py's owner_id are all NOT NULL foreign
keys to users.id -- deleting a user who has ever created a case, added
evidence, authored a note, or owned a basket would either violate those
constraints or require cascading away real investigation data. Disabling
is the deletion mechanism here, which also matches "preserve audit
integrity, prefer disable over delete."

Last-admin protection is race-safe: both set_user_active() and
update_user()'s role-demotion path take a `SELECT ... FOR UPDATE` lock on
every ADMIN-role row before counting how many active admins would remain.
Postgres serializes any other transaction that tries to lock an overlapping
row, so two concurrent requests that each try to disable a *different* one
of the platform's last two admins can no longer both succeed (the second
one blocks until the first commits, then correctly sees zero remaining and
is rejected) -- a bare row-lock on only the request's own target row would
not catch that case.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.auth.security import hash_password
from app.core.audit import record_audit
from app.core.db import new_session
from app.models.user import Role, User

logger = logging.getLogger(__name__)


class UserManagementError(Exception):
    """Base for user-facing 4xx conditions raised by this service."""


class LastAdminError(UserManagementError):
    pass


class SelfRoleChangeError(UserManagementError):
    pass


class DuplicateEmailError(UserManagementError):
    pass


class UserNotFoundError(UserManagementError):
    pass


def _serialize(user: User) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role.value,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat(),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


async def _lock_all_admin_rows(db) -> list[User]:
    return (
        (await db.execute(select(User).where(User.role == Role.ADMIN).with_for_update()))
        .scalars()
        .all()
    )


def _remaining_active_admins(locked_admins: list[User], excluding: uuid.UUID) -> int:
    return sum(1 for a in locked_admins if a.id != excluding and a.is_active)


async def list_users(
    search: str = "",
    role: Optional[Role] = None,
    is_active: Optional[bool] = None,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
) -> dict:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    sort_columns = {
        "email": User.email,
        "full_name": User.full_name,
        "role": User.role,
        "created_at": User.created_at,
        "last_login_at": User.last_login_at,
    }
    column = sort_columns.get(sort_by, User.created_at)
    order = column.asc() if sort_dir == "asc" else column.desc()

    async with new_session() as db:
        filters = []
        if search:
            like = f"%{search.lower()}%"
            filters.append(or_(func.lower(User.email).like(like), func.lower(User.full_name).like(like)))
        if role is not None:
            filters.append(User.role == role)
        if is_active is not None:
            filters.append(User.is_active.is_(is_active))

        count_stmt = select(func.count()).select_from(User)
        list_stmt = select(User).order_by(order).offset((page - 1) * page_size).limit(page_size)
        for f in filters:
            count_stmt = count_stmt.where(f)
            list_stmt = list_stmt.where(f)

        total = (await db.execute(count_stmt)).scalar_one()
        rows = (await db.execute(list_stmt)).scalars().all()
        return {
            "items": [_serialize(u) for u in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


async def get_stats() -> dict:
    async with new_session() as db:
        total = (await db.execute(select(func.count()).select_from(User))).scalar_one()
        active = (
            await db.execute(select(func.count()).select_from(User).where(User.is_active.is_(True)))
        ).scalar_one()
        by_role = {}
        for r in Role:
            by_role[r.value] = (
                await db.execute(select(func.count()).select_from(User).where(User.role == r))
            ).scalar_one()
        recent = (
            (
                await db.execute(
                    select(User)
                    .where(User.last_login_at.is_not(None))
                    .order_by(User.last_login_at.desc())
                    .limit(5)
                )
            )
            .scalars()
            .all()
        )
        return {
            "total_users": total,
            "active_users": active,
            "disabled_users": total - active,
            "by_role": by_role,
            "recent_logins": [{"email": u.email, "last_login_at": u.last_login_at.isoformat()} for u in recent],
        }


async def create_user(
    email: str, password: str, full_name: str, role: Role, actor_user_id: Optional[uuid.UUID], actor_email: str
) -> dict:
    async with new_session() as db:
        existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing is not None:
            raise DuplicateEmailError(f"Email {email!r} is already registered")
        user = User(email=email, hashed_password=hash_password(password), full_name=full_name, role=role)
        db.add(user)
        try:
            await db.commit()
        except IntegrityError as exc:
            raise DuplicateEmailError(f"Email {email!r} is already registered") from exc
        await db.refresh(user)
        result = _serialize(user)
    await record_audit(
        "user.create", f"Created user '{email}' with role '{role.value}'.", actor_user_id, actor_email
    )
    return result


async def update_user(
    user_id: uuid.UUID,
    actor_user_id: Optional[uuid.UUID],
    actor_email: str,
    full_name: Optional[str] = None,
    role: Optional[Role] = None,
) -> dict:
    async with new_session() as db:
        locked_admins = await _lock_all_admin_rows(db)
        user = (await db.execute(select(User).where(User.id == user_id).with_for_update())).scalar_one_or_none()
        if user is None:
            raise UserNotFoundError(f"No such user: {user_id}")

        changes = []
        if full_name is not None and full_name != user.full_name:
            user.full_name = full_name
            changes.append("full_name")

        if role is not None and role != user.role:
            if user.id == actor_user_id:
                raise SelfRoleChangeError(
                    "Administrators cannot change their own role. Ask another administrator to do it."
                )
            if user.role == Role.ADMIN and role != Role.ADMIN and user.is_active:
                if _remaining_active_admins(locked_admins, excluding=user.id) == 0:
                    raise LastAdminError("Cannot remove the ADMIN role from the last active administrator.")
            old_role = user.role
            user.role = role
            changes.append(f"role ({old_role.value} -> {role.value})")

        if changes:
            await db.commit()
            await db.refresh(user)
        result = _serialize(user)

    if changes:
        await record_audit(
            "user.update", f"Updated user '{result['email']}': {', '.join(changes)}.", actor_user_id, actor_email
        )
    return result


async def set_user_active(
    user_id: uuid.UUID, is_active: bool, actor_user_id: Optional[uuid.UUID], actor_email: str
) -> dict:
    async with new_session() as db:
        locked_admins = await _lock_all_admin_rows(db)
        user = (await db.execute(select(User).where(User.id == user_id).with_for_update())).scalar_one_or_none()
        if user is None:
            raise UserNotFoundError(f"No such user: {user_id}")

        if not is_active and user.role == Role.ADMIN and user.is_active:
            if _remaining_active_admins(locked_admins, excluding=user.id) == 0:
                raise LastAdminError("Cannot disable the last active administrator.")

        user.is_active = is_active
        await db.commit()
        await db.refresh(user)
        result = _serialize(user)

    await record_audit(
        "user.enable" if is_active else "user.disable",
        f"{'Enabled' if is_active else 'Disabled'} user '{result['email']}'.",
        actor_user_id,
        actor_email,
    )
    return result


async def reset_password(
    user_id: uuid.UUID, new_password: str, actor_user_id: Optional[uuid.UUID], actor_email: str
) -> dict:
    async with new_session() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is None:
            raise UserNotFoundError(f"No such user: {user_id}")
        user.hashed_password = hash_password(new_password)
        # Invalidates every access/refresh token already issued to this
        # user (see app/auth/rbac.py's get_current_user() and
        # app/api/routes/auth.py's refresh()) -- otherwise a session started
        # before this reset would keep working under the OLD password's
        # tokens until they naturally expire.
        user.token_version += 1
        await db.commit()
        await db.refresh(user)
        result = _serialize(user)

    await record_audit(
        "user.password_reset",
        f"Administrator reset the password for user '{result['email']}'.",
        actor_user_id,
        actor_email,
    )
    return result


async def record_login_success(user_id: uuid.UUID, email: str) -> None:
    async with new_session() as db:
        db_user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
        db_user.last_login_at = datetime.now(timezone.utc)
        await db.commit()
    logger.info("Successful login for %r", email)
    await record_audit("auth.login", f"User '{email}' logged in.", user_id, email)


async def record_login_failure(email: str) -> None:
    # Previously the only trace of this was a Postgres config_audit_log row --
    # invisible to anyone watching `docker logs` in real time, so a live
    # credential-stuffing attack showed up only as a wall of identical bare
    # "401 Unauthorized" access-log lines with no indication which accounts
    # were being targeted.
    logger.warning("Failed login attempt for %r", email)
    await record_audit("auth.login_failed", f"Failed login attempt for email '{email}'.")
