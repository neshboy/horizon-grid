from typing import Optional

from pydantic import BaseModel, Field

from app.ioc.types import IOCType


class BasketAddRequest(BaseModel):
    # Real gap found live during overnight QA: no length bound at all here,
    # inconsistent with every other schema modeling "an IOC value"
    # (LookupCreateRequest.value and CaseIOCAddRequest.ioc_value both cap
    # at 2048 -- "no real IOC is anywhere near this long" per the former's
    # own comment). Matching that same cap here closes the gap rather than
    # letting an arbitrarily large string reach basket_items with no guard.
    ioc_value: str = Field(min_length=1, max_length=2048)
    ioc_type_hint: Optional[IOCType] = None
    note: Optional[str] = None


class BasketItemResponse(BaseModel):
    id: str
    ioc_value: str
    ioc_type: str
    note: Optional[str] = None
    latest_lookup_id: Optional[str] = None
    created_at: str

    model_config = {"from_attributes": True}
