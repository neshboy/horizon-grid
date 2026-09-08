"""Unit tests for app.schemas.case's oversized-input rejection.

Regression coverage for a real bug found via live testing: CaseIOCAddRequest
.ioc_type and CaseNoteCreateRequest.anchor_type/anchor_ref were plain `str`
fields with no `max_length`, while their backing DB columns are
VARCHAR(64)/VARCHAR(64)/VARCHAR(2048) (see CaseIOC.ioc_type, CaseNote
.anchor_type, CaseNote.anchor_ref in app/models/case.py). An oversized value
sailed straight past request validation and crashed at the INSERT with an
unhandled asyncpg.exceptions.StringDataRightTruncationError -- surfaced to
the caller as a 500 -- instead of being rejected with a 422 the way
CaseCreateRequest.title/description and CaseNoteCreateRequest.body already
correctly are (this file's own header comment documents that exact pattern
for description/body). Confirmed live against the running stack before this
fix: POSTing a >64-char ioc_type/anchor_type or a >2048-char anchor_ref to
/cases/{id}/iocs or /cases/{id}/notes raised that DB-level exception; after
adding matching Field(max_length=...) caps here, pydantic now rejects them
with a ValidationError (422 at the API layer) before any DB call is made.
"""
import uuid

import pytest
from pydantic import ValidationError

from app.schemas.case import CaseIOCAddRequest, CaseNoteCreateRequest


def test_ioc_type_within_column_limit_is_accepted():
    req = CaseIOCAddRequest(ioc_value="1.2.3.4", ioc_type="ipv4")
    assert req.ioc_type == "ipv4"


def test_ioc_type_over_column_limit_is_rejected():
    # CaseIOC.ioc_type is VARCHAR(64) -- one char over must fail validation
    # rather than reach the database.
    with pytest.raises(ValidationError):
        CaseIOCAddRequest(ioc_value="1.2.3.4", ioc_type="x" * 65)


def test_ioc_type_at_column_limit_is_accepted():
    req = CaseIOCAddRequest(ioc_value="1.2.3.4", ioc_type="x" * 64)
    assert len(req.ioc_type) == 64


# Regression coverage for a separate real bug found via live testing:
# CaseIOCAddRequest.ioc_type had no `min_length`, unlike its sibling
# ioc_value (min_length=1 above) and unlike basket/lookup's ioc_type_hint
# (a real IOCType enum member, which can never be empty). An empty string
# sailed past request validation and was persisted verbatim as a real
# CaseIOC row with ioc_type="". Confirmed live against the running stack
# before this fix: POSTing {"ioc_value": "9.9.9.9", "ioc_type": ""} to
# /api/v1/cases/{case_id}/iocs returned 201, and a subsequent GET on the
# case showed the new IOC entry with "ioc_type":"" persisted. Fixed by
# adding matching Field(min_length=1) here, same as ioc_value.
def test_ioc_type_empty_string_is_rejected():
    with pytest.raises(ValidationError):
        CaseIOCAddRequest(ioc_value="9.9.9.9", ioc_type="")


def test_anchor_type_within_column_limit_is_accepted():
    note = CaseNoteCreateRequest(body="note body", anchor_type="ioc")
    assert note.anchor_type == "ioc"


def test_anchor_type_over_column_limit_is_rejected():
    # CaseNote.anchor_type is VARCHAR(64).
    with pytest.raises(ValidationError):
        CaseNoteCreateRequest(body="note body", anchor_type="y" * 65)


def test_anchor_ref_within_column_limit_is_accepted():
    note = CaseNoteCreateRequest(body="note body", anchor_ref="z" * 2048)
    assert len(note.anchor_ref) == 2048


def test_anchor_ref_over_column_limit_is_rejected():
    # CaseNote.anchor_ref is VARCHAR(2048).
    with pytest.raises(ValidationError):
        CaseNoteCreateRequest(body="note body", anchor_ref="z" * 2049)


def test_anchor_type_and_anchor_ref_remain_optional():
    # The fix must not turn these into required fields -- omitting them
    # entirely (the common case: a note with no anchor) must still work.
    note = CaseNoteCreateRequest(body="note body")
    assert note.anchor_type is None
    assert note.anchor_ref is None


# Regression coverage for a separate real bug found via live testing:
# CaseIOCAddRequest.lookup_id was a bare `Optional[str]` with no format
# validation, so app/api/routes/cases.py's add_case_ioc() had to do its own
# `uuid.UUID(payload.lookup_id)` coercion with no try/except around it. Any
# non-UUID string there raised an unhandled ValueError, surfaced to the
# caller as a plain-text 500 -- instead of the clean 422 every other
# UUID-bearing field in this API already gets from FastAPI/Pydantic's
# automatic path-param coercion. Confirmed live against the running stack
# before this fix: POSTing {"lookup_id": "not-a-real-uuid"} to
# /cases/{id}/iocs 500'd with "ValueError: badly formed hexadecimal UUID
# string" in the server log. Fixed by typing lookup_id as Optional[uuid.UUID]
# so pydantic rejects a malformed value before the route (or the DB) ever
# sees it.
def test_lookup_id_malformed_string_is_rejected():
    with pytest.raises(ValidationError):
        CaseIOCAddRequest(ioc_value="1.2.3.4", ioc_type="ipv4", lookup_id="not-a-real-uuid")


def test_lookup_id_valid_uuid_string_is_accepted_and_coerced():
    valid_id = uuid.uuid4()
    req = CaseIOCAddRequest(ioc_value="1.2.3.4", ioc_type="ipv4", lookup_id=str(valid_id))
    assert req.lookup_id == valid_id


def test_lookup_id_remains_optional():
    # Omitting lookup_id entirely (the common "manual add, no prior lookup"
    # case) must still work.
    req = CaseIOCAddRequest(ioc_value="1.2.3.4", ioc_type="ipv4")
    assert req.lookup_id is None
