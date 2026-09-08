import uuid
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
    # Matches CaseIOC.ioc_type's VARCHAR(64) column (app/models/case.py) --
    # same "real gap fixed" pattern as description/body above: without this
    # cap, an oversized value isn't rejected with a 422 here, it sails
    # through to the INSERT and blows up as an unhandled 500
    # (asyncpg.exceptions.StringDataRightTruncationError).
    ioc_type: str = Field(min_length=1, max_length=64)
    # Real bug found live during overnight QA: this was a bare `Optional[str]`
    # with no format validation, so add_case_ioc() (app/api/routes/cases.py)
    # had to do its own `uuid.UUID(payload.lookup_id)` coercion with no
    # try/except, and any non-UUID string here crashed the whole request with
    # an unhandled 500 (ValueError: badly formed hexadecimal UUID string)
    # instead of a clean 422 -- unlike every path-param UUID in this API
    # (e.g. case_id above), which FastAPI/Pydantic already validates
    # automatically. Typing this as Optional[uuid.UUID] gets that same
    # automatic 422 for free and lets the route use payload.lookup_id as-is.
    lookup_id: Optional[uuid.UUID] = None


class CaseNoteCreateRequest(BaseModel):
    body: str = Field(min_length=1, max_length=_MAX_NOTE_BODY_LENGTH)
    # Matches CaseNote.anchor_type/anchor_ref's VARCHAR(64)/VARCHAR(2048)
    # columns (app/models/case.py) -- same reasoning as ioc_type above.
    anchor_type: Optional[str] = Field(default=None, max_length=64)
    anchor_ref: Optional[str] = Field(default=None, max_length=2048)
