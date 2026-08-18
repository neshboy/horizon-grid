"""Runtime-mutable provider/AI configuration -- the DB-backed replacement for
"change a value in .env and restart the process" (see app/core/config.py's
Settings, which is a process-lifetime-frozen @lru_cache singleton).

Every AI backend and every IOC provider gets exactly one row here per
(kind, provider_id). Credentials are stored encrypted (app/core/crypto.py),
never in plaintext. `is_active` is only meaningful for kind=AI -- exactly one
AI row should have is_active=True at a time, enforced by
app/core/runtime_config.py's service layer (not a DB constraint, since
"exactly one true" isn't expressible as a simple column constraint without a
partial unique index the app doesn't need elsewhere).
"""
import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ProviderKind(str, enum.Enum):
    AI = "ai"
    IOC = "ioc"


class ProviderRuntimeConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "provider_runtime_configs"
    __table_args__ = (UniqueConstraint("kind", "provider_id", name="uq_provider_runtime_kind_id"),)

    kind: Mapped[ProviderKind] = mapped_column(Enum(ProviderKind), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Fernet ciphertext of a JSON object, e.g. {"api_key": "..."} or
    # {"base_url": "..."} -- shape varies by provider, same as the
    # `credentials: dict[str, str]` bodies connection_test.py already uses.
    encrypted_credentials: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Non-secret extras: custom endpoint URL for a generic API provider,
    # provider-type tag ("api_compatible") for user-added AI providers, etc.
    extra_config: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    last_test_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_ok: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    last_test_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ProviderRuntimeConfig {self.kind.value}:{self.provider_id} enabled={self.enabled}>"


class ConfigAuditLog(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "config_audit_log"

    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # Denormalized so the log stays readable even if the user is later
    # deleted -- audit history shouldn't go blank because an account did.
    actor_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    # Human-readable description ONLY -- never a secret value. Callers
    # (app/core/runtime_config.py) are responsible for never interpolating
    # a credential into this field.
    detail: Mapped[str] = mapped_column(String(1000), nullable=False, default="")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ConfigAuditLog {self.action} @ {self.timestamp}>"
