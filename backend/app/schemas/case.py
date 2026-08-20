from typing import Optional

from pydantic import BaseModel, Field

from app.models.case import CaseSeverity, CaseStatus


# Both columns are Postgres TEXT (unbounded at the DB level -- see
# app/models/case.py), so these caps are a pure application-level resource
# policy, not a DB-compatibility requirement: real gap fixed, there was no
# limit of any kind on either field, meaning a single request could write
# an arbitrarily large body straight into the database.
_MAX_DESCRIPTION_LENGTH = 20000
_MAX_NOTE_BODY_LENGTH = 10000


class CaseCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=_MAX_DESCRIPTION_LENGTH)
    severity: CaseSeverity = CaseSeverity.MEDIUM
    tags: list[str] = Field(default_factory=list)


class CaseUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=_MAX_DESCRIPTION_LENGTH)
    severity: Optional[CaseSeverity] = None
    status: Optional[CaseStatus] = None
    tags: Optional[list[str]] = None


class CaseIOCAddRequest(BaseModel):
    ioc_value: str = Field(min_length=1, max_length=2048)
    ioc_type: str
    lookup_id: Optional[str] = None


class CaseNoteCreateRequest(BaseModel):
    body: str = Field(min_length=1, max_length=_MAX_NOTE_BODY_LENGTH)
    anchor_type: Optional[str] = None
    anchor_ref: Optional[str] = None
