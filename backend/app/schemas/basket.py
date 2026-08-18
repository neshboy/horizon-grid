from typing import Optional

from pydantic import BaseModel

from app.ioc.types import IOCType


class BasketAddRequest(BaseModel):
    ioc_value: str
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
