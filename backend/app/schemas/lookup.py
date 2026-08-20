from typing import Any, Optional

from pydantic import BaseModel, Field

from app.ioc.types import IOCType
from app.models.lookup import LookupStatus, Verdict


class LookupCreateRequest(BaseModel):
    # Real gap fixed: no length cap at all previously -- no real IOC (IP,
    # domain, hash, or URL) is anywhere near this long; 2048 matches the
    # VARCHAR(2048) cap already enforced on provider_results/evidence_items'
    # source_url (app/providers/base.py's ProviderResult.__post_init__), so
    # a value this size is guaranteed to fit everywhere it flows without a
    # separate silent truncation downstream.
    value: str = Field(min_length=1, max_length=2048)
    ioc_type_hint: Optional[IOCType] = None
    # None = every enabled provider that supports the detected IOC type
    # (the existing default behavior). A non-None list restricts the
    # investigation to just those provider_ids -- Phase 22/23 of the
    # runtime-provider architecture ("control which providers participate").
    provider_ids: Optional[list[str]] = None
    # None = whichever AI backend is currently active platform-wide. A
    # specific backend name runs THIS investigation with that backend
    # without changing the global active-backend setting.
    ai_backend: Optional[str] = None


class LookupSummary(BaseModel):
    id: str
    ioc_value: str
    ioc_type: str
    status: LookupStatus
    final_verdict: Optional[Verdict] = None
    risk_score: Optional[float] = None
    confidence_score: Optional[float] = None
    created_at: str

    model_config = {"from_attributes": True}


class ProviderResultResponse(BaseModel):
    provider_id: str
    provider_name: str
    category: str
    status: str
    data: dict[str, Any]
    source_url: Optional[str] = None
    error_message: Optional[str] = None
    latency_ms: Optional[int] = None


class LookupDetailResponse(BaseModel):
    id: str
    ioc_value: str
    ioc_type: str
    status: LookupStatus
    final_verdict: Optional[Verdict] = None
    risk_score: Optional[float] = None
    confidence_score: Optional[float] = None
    final_assessment: Optional[dict[str, Any]] = None
    provider_results: list[ProviderResultResponse] = []
    ai_summaries: list[dict[str, Any]] = []
    created_at: str

    model_config = {"from_attributes": True}
