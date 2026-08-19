"""Pydantic schemas for the Security Assessment Toolkit API
(app/api/routes/security_assessment.py)."""
from typing import Optional

from pydantic import BaseModel, Field


class RunAssessmentRequest(BaseModel):
    tool_ids: list[str] = Field(min_length=1)
    profile: str
    # Caller must retype the exact target value being assessed -- the
    # mandatory, explicit scope-confirmation step. Checked against the
    # lookup's own seed ioc_value server-side; never trusted at face value.
    target_confirmation: str
    authorization_confirmed: bool = False


class ToolProfileResponse(BaseModel):
    tool_id: str
    tool_name: str
    profile_id: str
    name: str
    description: str
    supported_types: list[str]


class ToolHealthResponse(BaseModel):
    tool_id: str
    tool_name: str
    available: bool


class FindingResponse(BaseModel):
    id: str
    tool_id: str
    finding_type: str
    severity: str
    title: str
    description: str
    target_detail: Optional[str] = None
    cve_ids: list[str] = []
    evidence: dict = {}
    created_at: str


class RunResponse(BaseModel):
    id: str
    lookup_id: str
    target: str
    tool_ids: list[str]
    profile: str
    status: str
    requested_by: Optional[str] = None
    authorization_confirmed_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    findings: list[FindingResponse] = []
