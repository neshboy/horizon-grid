"""Shared append-only audit log -- originally scoped to provider/AI
configuration changes only (app/core/runtime_config.py), now reused by user
and authentication management (app/core/users.py, app/api/routes/auth.py)
since the underlying table (ConfigAuditLog / config_audit_log) was already
fully generic in shape (actor, action, human-readable detail), despite its
provider-config-scoped name.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from app.core.db import new_session
from app.models.runtime_config import ConfigAuditLog

logger = logging.getLogger(__name__)


async def record_audit(
    action: str, detail: str, actor_user_id=None, actor_email: Optional[str] = None
) -> None:
    """`detail` must be human-readable description text ONLY -- never a
    credential/password/token value. Callers must not interpolate a secret
    into it."""
    async with new_session() as db:
        db.add(
            ConfigAuditLog(
                timestamp=datetime.now(timezone.utc),
                actor_user_id=actor_user_id,
                actor_email=actor_email,
                action=action,
                detail=detail,
            )
        )
        await db.commit()


async def list_audit_log(limit: int = 200) -> list[dict]:
    async with new_session() as db:
        rows = (
            await db.execute(
                select(ConfigAuditLog).order_by(ConfigAuditLog.timestamp.desc()).limit(limit)
            )
        ).scalars().all()
        return [
            {
                "id": str(r.id),
                "timestamp": r.timestamp.isoformat(),
                "actor_email": r.actor_email,
                "action": r.action,
                "detail": r.detail,
            }
            for r in rows
        ]
