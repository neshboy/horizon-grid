"""SQLAlchemy declarative base and shared mixins."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    # index=True: created_at is the primary ORDER BY / WHERE column for
    # nearly every list and dashboard query across every table that uses
    # this mixin (see migration b3f0587f2493, which adds the matching
    # index to the 20 already-existing tables -- this only affects schema
    # generation for new tables/fresh installs going forward).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
