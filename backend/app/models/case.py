"""Lightweight case management: groups IOCs/lookups/notes/reports under one
investigation with a status workflow, for analysts who need to track a
multi-IOC incident rather than a single one-off lookup.
"""
import enum
import uuid
from typing import Optional

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CaseStatus(str, enum.Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    CONTAINED = "contained"
    RESOLVED = "resolved"
    FALSE_POSITIVE = "false_positive"
    CLOSED = "closed"


class CaseSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Case(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "cases"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    analyst_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    severity: Mapped[CaseSeverity] = mapped_column(Enum(CaseSeverity), default=CaseSeverity.MEDIUM, nullable=False)
    status: Mapped[CaseStatus] = mapped_column(Enum(CaseStatus), default=CaseStatus.OPEN, nullable=False, index=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)

    iocs: Mapped[list["CaseIOC"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    notes: Mapped[list["CaseNote"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    reports: Mapped[list["CaseReport"]] = relationship(back_populates="case", cascade="all, delete-orphan")


class CaseIOC(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "case_iocs"

    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False, index=True)
    ioc_value: Mapped[str] = mapped_column(String(2048), nullable=False)
    ioc_type: Mapped[str] = mapped_column(String(64), nullable=False)
    lookup_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ioc_lookups.id"), nullable=True
    )
    added_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    case: Mapped["Case"] = relationship(back_populates="iocs")


class CaseNote(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A free-text analyst note, optionally anchored to a specific IOC, evidence
    item, graph node, or timeline event within the case (anchor_type/anchor_ref
    are deliberately loose strings rather than FKs -- notes can point at a
    graph node id or timeline event id that has no dedicated table)."""

    __tablename__ = "case_notes"

    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False, index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    anchor_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # "ioc" | "evidence" | "graph_node" | "timeline_event" | "provider_result"
    anchor_ref: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)

    case: Mapped["Case"] = relationship(back_populates="notes")


class CaseReport(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "case_reports"

    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False, index=True)
    report_type: Mapped[str] = mapped_column(String(64), nullable=False)  # matches ReportType literal in app/ai/schemas.py
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    generated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    context: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    case: Mapped["Case"] = relationship(back_populates="reports")
