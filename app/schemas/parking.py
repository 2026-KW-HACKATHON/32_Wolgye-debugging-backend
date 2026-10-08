"""주차 배치·출차 일정·출차 (#8) 요청·응답 스키마. 명세 ParkingCreate / ParkingCreated 와 /parkings/{parking_id}/* 응답.

명세 ↔ DB 이름: is_long_term ↔ parking_assignments.is_permanent,
expected_exit_at(KST datetime) ↔ departure_schedules.scheduled_date + scheduled_time.
"""

from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, model_validator

from app.schemas.common import KST, KstDatetime
from app.schemas.my_vehicle import ExitSource, ParkingState


def _assume_kst(value: datetime) -> datetime:
    """시간대가 없는 값은 Asia/Seoul 로 본다 (명세는 +09:00 을 붙여 보낸다)."""
    return value.replace(tzinfo=KST) if value.tzinfo is None else value


# 요청 필드: 출차 예정 시각
ExitAt = Annotated[datetime, AfterValidator(_assume_kst)]


class _ExitTimeOrLongTerm(BaseModel):
    """상시 주차가 아니면 출차 예정 시각이 필요하다. 상시 주차면 expected_exit_at 은 무시한다."""

    is_long_term: bool = False  # 상시 주차
    expected_exit_at: ExitAt | None = None

    @model_validator(mode="after")
    def _require_exit_time(self):
        if not self.is_long_term and self.expected_exit_at is None:
            raise ValueError("상시 주차가 아니면 expected_exit_at 이 필요합니다.")
        return self


class ParkingCreate(_ExitTimeOrLongTerm):
    slot_id: int
    vehicle_id: int
    repeat_weekdays: bool = False  # 평일(월~금) 같은 시각으로 반복 일정도 함께 만든다 (이름은 복수형이지만 boolean)
    memo: str | None = None


class ParkingCreated(BaseModel):
    id: int
    slot_id: int
    state: ParkingState
    expected_exit_at: KstDatetime | None
    exit_source: ExitSource
    blocking: list[int]  # 이 배치로 막게 되는 칸


class ParkingScheduleUpdate(_ExitTimeOrLongTerm):
    """출차 일정 수정. is_long_term=true 면 상시 주차로 바꾼다 (backend #48)."""

    memo: str | None = None


class ParkingSchedule(BaseModel):
    parking_id: int
    expected_exit_at: KstDatetime | None  # 상시 주차면 null
    exit_source: ExitSource
    memo: str | None


class ParkingExited(BaseModel):
    id: int
    state: ParkingState
    actual_exit_at: KstDatetime
    on_time: bool  # 예정 시각 대비 정시 출차 여부
