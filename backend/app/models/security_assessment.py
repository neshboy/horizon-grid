"""Persisted models for the Security Assessment Toolkit: one authorized run
per invocation, and the discrete findings it produces. Distinct from
app/models/lookup.py's ProviderResultRecord/EvidenceItem -- those hold
passive-provider data queried automatically for every investigation; these
hold active-check results, produced only by an explicit, authorization-gated
POST /api/v1/security-assessment/{lookup_id}/run call (see
app/api/routes/security_assessment.py). See app/security_assessment/ for the
tool adapters that populate these rows.
"""
import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SecurityAssessmentRunStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Severity(str, enum.Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SecurityAssessmentRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "security_assessment_runs"

    lookup_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ioc_lookups.id"), nullable=False, index=True
    )
    requested_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # The exact value the caller retyped to confirm scope (app/api/routes/
    # security_assessment.py rejects the request unless this matches the
    # lookup's own seed ioc_value) -- kept verbatim here as part of the
    # authorization record, not just checked-and-discarded.
    target: Mapped[str] = mapped_column(String(2048), nullable=False)
    tool_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    profile: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[SecurityAssessmentRunStatus] = mapped_column(
        Enum(SecurityAssessmentRunStatus), default=SecurityAssessmentRunStatus.PENDING, nullable=False
    )
    authorization_confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    lookup: Mapped["IOCLookup"] = relationship(back_populates="security_assessment_runs")  # noqa: F821
    findings: Mapped[list["SecurityAssessmentFinding"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class SecurityAssessmentFinding(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "security_assessment_findings"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_assessment_runs.id"), nullable=False, index=True
    )
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    finding_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[Severity] = mapped_column(Enum(Severity), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_detail: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    cve_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # The concrete data the severity/claim was derived from -- e.g. the raw
    # port/service banner, the parsed certificate fields, the response
    # headers actually observed. Never AI-generated; see
    # app/security_assessment/base.py's Finding dataclass and each tool's
    # deterministic severity rules.
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    run: Mapped["SecurityAssessmentRun"] = relationship(back_populates="findings")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SecurityAssessmentFinding {self.tool_id}:{self.finding_type} severity={self.severity}>"
