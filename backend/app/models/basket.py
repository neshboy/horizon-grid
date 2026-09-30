"""IOC Basket: a lightweight per-analyst scratch space for collecting IOCs
across an investigation before comparing, bulk-investigating, or promoting
them into a Case. Deliberately has no status/workflow fields (that's what
Case is for) -- a basket item is just "this IOC, saved by this analyst."
"""
import uuid
from typing import Optional

from sqlalchemy import ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BasketItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "basket_items"

    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    ioc_value: Mapped[str] = mapped_column(String(2048), nullable=False)
    ioc_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Most recent completed lookup for this IOC, if one exists -- lets basket
    # actions (compare, investigate-all) reuse existing intelligence instead
    # of re-running providers for an IOC already investigated this session.
    latest_lookup_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ioc_lookups.id"), nullable=True
    )
    note: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    # Case-insensitive on the DB side too, not just in add_to_basket()'s
    # pre-insert dedup SELECT (func.lower(BasketItem.ioc_value) ==
    # ioc_value.lower()): a plain UniqueConstraint("owner_id", "ioc_value")
    # is case-sensitive, so two concurrent adds of the same logical IOC in
    # different casing (e.g. "EXAMPLE.COM" vs "example.com") both pass that
    # SELECT and both successfully INSERT -- Postgres sees them as distinct
    # values -- leaving two rows for one logical IOC and never raising the
    # IntegrityError add_to_basket()'s rollback/re-SELECT recovery path
    # expects. A functional unique index on (owner_id, lower(ioc_value))
    # makes the constraint itself case-insensitive, so that race raises
    # IntegrityError like the same-casing race already does. Named
    # differently from the original uq_basket_owner_ioc UniqueConstraint it
    # replaces (see the migration that swaps them) to keep the two distinct
    # in alembic's history.
    __table_args__ = (
        Index("uq_basket_owner_ioc_ci", owner_id, func.lower(ioc_value), unique=True),
    )
