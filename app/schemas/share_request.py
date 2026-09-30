from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.models.share_request import ShareRequestStatus


class ShareRequestBase(BaseModel):
    slot_id: int
    vehicle_id: int | None = None
    request_date: date
    start_time: time
    end_time: time


class ShareRequestCreate(ShareRequestBase):
    requester_id: int


class ShareRequestRead(ShareRequestBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    requester_id: int
    status: ShareRequestStatus
    reject_reason: str | None = None
    created_at: datetime
    responded_at: datetime | None = None


class ShareRequestDecision(BaseModel):
    status: Literal[ShareRequestStatus.ACCEPTED, ShareRequestStatus.REJECTED]
    reject_reason: str | None = None
