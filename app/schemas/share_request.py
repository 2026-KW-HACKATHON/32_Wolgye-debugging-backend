from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.share_request import ShareRequestStatus


class ShareRequestBase(BaseModel):
    offer_id: int
    vehicle_id: int | None = None
    request_date: date
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=1, le=24)  # 24 = 자정


class ShareRequestCreate(ShareRequestBase):
    requester_id: int

    @model_validator(mode="after")
    def check_hours(self) -> Self:
        if self.start_hour >= self.end_hour:
            raise ValueError("start_hour must be before end_hour")
        return self


class ShareRequestRead(ShareRequestBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slot_id: int
    requester_id: int
    total_price: int  # 토큰
    status: ShareRequestStatus
    reject_reason: str | None = None
    created_at: datetime
    responded_at: datetime | None = None


class ShareRequestDecision(BaseModel):
    status: Literal[ShareRequestStatus.ACCEPTED, ShareRequestStatus.REJECTED]
    reject_reason: str | None = None
