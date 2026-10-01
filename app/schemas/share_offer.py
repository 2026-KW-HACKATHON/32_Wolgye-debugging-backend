from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ShareOfferBase(BaseModel):
    slot_id: int
    start_date: date
    end_date: date
    available_weekdays: list[int] = Field(default_factory=lambda: list(range(7)))  # 0=월 ... 6=일
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=1, le=24)
    hourly_price: int = Field(default=0, ge=0)  # 시간당 토큰
    max_hours: int | None = None
    memo: str | None = None
    is_public: bool = True


class ShareOfferCreate(ShareOfferBase):
    host_id: int


class ShareOfferRead(ShareOfferBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    host_id: int
    created_at: datetime
