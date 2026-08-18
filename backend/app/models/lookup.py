"""Persisted models for an IOC investigation: the lookup itself, each provider's
raw result, the AI summaries, and the correlation edges discovered for the graph.
"""
import enum
import uuid
from typing import Optional

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class LookupStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Verdict(str, enum.Enum):
    HIGHLY_MALICIOUS = "highly_malicious"
    MALICIOUS = "malicious"
    SUSPICIOUS = "suspicious"
    UNKNOWN = "unknown"
    LIKELY_BENIGN = "likely_benign"
    BENIGN = "benign"
    SCANNER = "scanner"
    TOR_EXIT_NODE = "tor_exit_node"
    VPN = "vpn"
    CDN = "cdn"
    CLOUD_INFRASTRUCTURE = "cloud_infrastructure"
    DORMANT_INFRASTRUCTURE = "dormant_infrastructure"


class IOCLookup(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ioc_lookups"

    ioc_value: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    ioc_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[LookupStatus] = mapped_column(
        Enum(LookupStatus), default=LookupStatus.PENDING, nullable=False
    )
    requested_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # Final assessment (see app/ai/schemas.py for the FinalAssessment/RiskAssessment shape
    # persisted here). risk_score/confidence_score mirror final_assessment["risk"]["overall_risk_score"]/
    # ["confidence_score"] for cheap querying/listing without deserializing the whole JSONB blob.
    #
    # risk_score, confidence_score, and final_assessment["risk"]["malicious_probability"]/["severity"]
    # are DETERMINISTIC, not AI-generated: app/scoring/engine.py::score_investigation() computes them
    # from ProviderResult/CorrelationResult/Security-Assessment-finding data BEFORE any AI call, and
    # app/ai/service.py::generate_final_assessment() overwrites those same fields with the deterministic
    # values after the AI responds, regardless of what the AI itself emitted for them (see that
    # function's docstring for exactly how and why). The AI's role is narrower than the field name
    # historically implied: it is told these numbers as given facts and writes final_verdict/
    # verdict_rationale/executive_summary/etc. -- the narrative EXPLAINING the score -- consistent with
    # them; it no longer decides the numbers themselves. This also means final_verdict, while still
    # AI-authored, is constrained to agree with a number it did not choose (FinalAssessment's own
    # _verdict_must_agree_with_risk validator enforces this against the final, deterministic values,
    # not just whatever the AI originally emitted).
    final_verdict: Mapped[Optional[Verdict]] = mapped_column(Enum(Verdict), nullable=True)
    risk_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    final_assessment: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    provider_results: Mapped[list["ProviderResultRecord"]] = relationship(
        back_populates="lookup", cascade="all, delete-orphan"
    )
    ai_summaries: Mapped[list["AISummaryRecord"]] = relationship(
        back_populates="lookup", cascade="all, delete-orphan"
    )
    correlation_edges: Mapped[list["CorrelationEdgeRecord"]] = relationship(
        back_populates="lookup", cascade="all, delete-orphan"
    )
    evidence_items: Mapped[list["EvidenceItem"]] = relationship(  # noqa: F821
        back_populates="lookup", cascade="all, delete-orphan"
    )
    security_assessment_runs: Mapped[list["SecurityAssessmentRun"]] = relationship(  # noqa: F821
        back_populates="lookup", cascade="all, delete-orphan"
    )


class ProviderResultRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "provider_results"

    lookup_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ioc_lookups.id"), nullable=False, index=True
    )
    provider_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    provider_name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    source_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    lookup: Mapped["IOCLookup"] = relationship(back_populates="provider_results")


class AISummaryRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ai_summaries"

    lookup_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ioc_lookups.id"), nullable=False, index=True
    )
    # Null provider_id => this row is the final consolidated assessment, not a per-provider one.
    provider_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False)

    lookup: Mapped["IOCLookup"] = relationship(back_populates="ai_summaries")


class CorrelationEdgeRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A single edge discovered by the correlation engine, mirrored into Neo4j
    for graph traversal but kept here too so a lookup's graph can be rebuilt
    from Postgres alone if Neo4j is unavailable."""

    __tablename__ = "correlation_edges"

    lookup_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ioc_lookups.id"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_value: Mapped[str] = mapped_column(String(2048), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_value: Mapped[str] = mapped_column(String(2048), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    provenance: Mapped[str] = mapped_column(String(128), nullable=False)  # which provider asserted this
    # WHAT KIND of source asserted this, distinct from `provenance` above
    # (WHICH provider). One of "threat_intel" / "security_assessment" /
    # "local_observation" / "ai_interpretation" -- see
    # app/core/provenance.py. Existing rows default to "threat_intel" since
    # every provider that existed before this column did some form of
    # external intelligence lookup, never a local active observation.
    provenance_category: Mapped[str] = mapped_column(String(32), nullable=False, default="threat_intel")

    lookup: Mapped["IOCLookup"] = relationship(back_populates="correlation_edges")


class FinalAssessmentRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Every final assessment ever generated for a lookup -- not just the
    most recent one. IOCLookup.final_assessment/final_verdict/risk_score
    remain the PRIMARY assessment shown by default (from the original
    investigation run), but the AI-comparison feature ("analyze the same
    evidence with Groq instead of Ollama") re-runs generate_final_assessment
    against a different backend without re-querying any provider, and each
    result is durable here -- comparisons survive a page refresh rather than
    existing only in frontend state for as long as the tab stays open."""

    __tablename__ = "final_assessment_records"

    lookup_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ioc_lookups.id"), nullable=False, index=True
    )
    ai_backend: Mapped[str] = mapped_column(String(64), nullable=False)
    ai_model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Mirrors app/ai/schemas.py's FinalAssessment.ai_outcome ("success" /
    # "skipped_no_evidence" / "failed") as a real column, same rationale as
    # ai_backend/ai_model above: a caller can tell a genuine AI generation
    # failure apart from a correct no-evidence skip without deserializing the
    # JSONB `assessment` blob. See alembic/versions/6716ed40b9f2 for how
    # existing rows (predating this column) were backfilled.
    ai_outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    assessment: Mapped[dict] = mapped_column(JSONB, nullable=False)
    requested_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    lookup: Mapped["IOCLookup"] = relationship()
