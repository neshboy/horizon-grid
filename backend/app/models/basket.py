"""IOC Basket: a lightweight per-analyst scratch space for collecting IOCs
across an investigation before comparing, bulk-investigating, or promoting
them into a Case. Deliberately has no status/workflow fields (that's what
Case is for) -- a basket item is just "this IOC, saved by this analyst."
"""
import uuid
from typing import Optional

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BasketItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "basket_items"
    __table_args__ = (UniqueConstraint("owner_id", "ioc_value", name="uq_basket_owner_ioc"),)

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
