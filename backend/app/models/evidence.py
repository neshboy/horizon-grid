"""Evidence ledger: every claim the platform makes about an IOC traces back to
one of these rows. Rows are built deterministically (app/evidence/builder.py)
from provider summaries and correlation edges -- never written directly by an
AI call -- so any AI-generated explanation (WHY, Challenge, Score Explanation,
Copilot) can cite an evidence_id and have that citation checked against a real,
independently-reproducible fact instead of trusting the model's say-so.
"""
import enum
import uuid
from typing import Optional

from sqlalchemy import Enum, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EvidenceType(str, enum.Enum):
    DETECTION = "detection"
    REPUTATION = "reputation"
    RELATIONSHIP = "relationship"
    MALWARE_ASSOCIATION = "malware_association"
    THREAT_ACTOR_ASSOCIATION = "threat_actor_association"
    CAMPAIGN_ASSOCIATION = "campaign_association"
    MITRE_TECHNIQUE = "mitre_technique"
    INFRASTRUCTURE = "infrastructure"
    OTHER = "other"


class EvidenceItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "evidence_items"

    lookup_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ioc_lookups.id"), nullable=False, index=True
    )
    evidence_type: Mapped[EvidenceType] = mapped_column(Enum(EvidenceType), nullable=False, index=True)

    # "Source" = human-readable origin (e.g. "VirusTotal", "Correlation Engine");
    # provider_id is the machine-readable provider_id when the source is a
    # connector, null when the source is the correlation engine itself.
    source_label: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)

    claim: Mapped[str] = mapped_column(Text, nullable=False)
    interpretation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)  # 0-100 scale, matches RiskAssessment

    related_ioc_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    related_ioc_value: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)

    source_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    observed_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # provider-reported timestamp, kept as-is (mixed formats across providers)
    raw_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # Same "what kind of source" axis as CorrelationEdgeRecord.provenance_category
    # (app/models/lookup.py) -- see app/core/provenance.py.
    provenance_category: Mapped[str] = mapped_column(String(32), nullable=False, default="threat_intel")

    lookup: Mapped["IOCLookup"] = relationship(back_populates="evidence_items")  # noqa: F821
