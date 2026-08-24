"""Import every model module so Base.metadata is fully populated for Alembic autogenerate."""
from app.models.base import Base
from app.models.user import User, Role
from app.models.lookup import (
    IOCLookup,
    ProviderResultRecord,
    AISummaryRecord,
    CorrelationEdgeRecord,
    FinalAssessmentRecord,
    LookupStatus,
    Verdict,
)
from app.models.evidence import EvidenceItem, EvidenceType
from app.models.basket import BasketItem
from app.models.case import Case, CaseIOC, CaseNote, CaseReport, CaseStatus, CaseSeverity
from app.models.runtime_config import ProviderRuntimeConfig, ConfigAuditLog, ProviderKind
from app.models.security_assessment import (
    SecurityAssessmentRun,
    SecurityAssessmentFinding,
    SecurityAssessmentRunStatus,
    Severity,
)
from app.models.pentest import (
    PentestAssessment,
    PentestTarget,
    PentestFinding,
    PentestAssessmentStatus,
    PentestProfile,
    PentestTargetStatus,
    PentestFindingConfidence,
    PentestFindingStatus,
    PentestExploitAttempt,
    PentestExploitMode,
    PentestExploitStatus,
)

__all__ = [
    "Base",
    "User",
    "Role",
    "IOCLookup",
    "ProviderResultRecord",
    "AISummaryRecord",
    "CorrelationEdgeRecord",
    "FinalAssessmentRecord",
    "LookupStatus",
    "Verdict",
    "EvidenceItem",
    "EvidenceType",
    "BasketItem",
    "Case",
    "CaseIOC",
    "CaseNote",
    "CaseReport",
    "CaseStatus",
    "CaseSeverity",
    "ProviderRuntimeConfig",
    "ConfigAuditLog",
    "ProviderKind",
    "SecurityAssessmentRun",
    "SecurityAssessmentFinding",
    "SecurityAssessmentRunStatus",
    "Severity",
    "PentestAssessment",
    "PentestTarget",
    "PentestFinding",
    "PentestAssessmentStatus",
    "PentestProfile",
    "PentestTargetStatus",
    "PentestFindingConfidence",
    "PentestFindingStatus",
    "PentestExploitAttempt",
    "PentestExploitMode",
    "PentestExploitStatus",
]
