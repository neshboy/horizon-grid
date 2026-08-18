from typing import Optional

from pydantic import BaseModel, Field

from app.models.case import CaseSeverity, CaseStatus


class CaseCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    severity: CaseSeverity = CaseSeverity.MEDIUM
    tags: list[str] = Field(default_factory=list)


class CaseUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[CaseSeverity] = None
    status: Optional[CaseStatus] = None
    tags: Optional[list[str]] = None


class CaseIOCAddRequest(BaseModel):
    ioc_value: str
    ioc_type: str
    lookup_id: Optional[str] = None


class CaseNoteCreateRequest(BaseModel):
    body: str = Field(min_length=1)
    anchor_type: Optional[str] = None
    anchor_ref: Optional[str] = None
