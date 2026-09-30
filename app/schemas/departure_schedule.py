from datetime import date, time

from pydantic import BaseModel, ConfigDict, Field


class DepartureScheduleBase(BaseModel):
    scheduled_date: date
    scheduled_time: time
    repeat_weekdays: list[int] = Field(default_factory=list)  # 0=월 ... 6=일
    memo: str | None = None


class DepartureScheduleCreate(DepartureScheduleBase):
    vehicle_id: int


class DepartureScheduleRead(DepartureScheduleBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    vehicle_id: int
    is_ai_estimated: bool
