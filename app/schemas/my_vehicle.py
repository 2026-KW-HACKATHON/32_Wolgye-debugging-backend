"""내 차량·반복 출차 (#7) 요청·응답 스키마. 명세 VehicleListItem / VehicleCreate / VehicleUpdate / VehicleDetail / RecurringSchedule.

구 API 의 app/schemas/vehicle.py 와 이름이 겹치지 않도록 파일을 따로 둔다 (구 스키마는 #15에서 삭제).
명세 ↔ DB 이름: plate ↔ plate_no, alias ↔ nickname, is_default ↔ is_primary (변환은 app/services/vehicles.py).
"""

import enum
import re
from datetime import time
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, PlainSerializer

from app.schemas.common import KstDatetime, PlateIn, PlateOut, Weekday

VehicleColor = Literal["검정", "흰색", "은색", "회색", "파랑", "빨강", "기타"]


class VehicleStatus(enum.StrEnum):
    """명세 VehicleStatus."""

    PARKED = "PARKED"  # 현재 주차 중
    OUT = "OUT"  # 외부 출차


class ParkingState(enum.StrEnum):
    """명세 ParkingState."""

    PARKED = "PARKED"
    EXITED = "EXITED"


class ExitSource(enum.StrEnum):
    """명세 ExitSource. 컬럼 없이 계산한다 (결정 10, app/services/departures.py)."""

    MANUAL = "MANUAL"
    RECURRING = "RECURRING"
    AI_ESTIMATED = "AI_ESTIMATED"
    NONE = "NONE"


_TIME_OF_DAY = re.compile(r"^(\d{2}):(\d{2})$")


def _parse_time_of_day(value: object) -> object:
    """ "07:30" → time(7, 30). 형식이 다르거나 없는 시각이면 400 INVALID_INPUT."""
    if not isinstance(value, str):
        return value
    match = _TIME_OF_DAY.match(value)
    if match is None:
        raise ValueError("시각은 HH:MM 형식이어야 합니다 (예: 07:30).")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValueError("시각은 00:00~23:59 사이여야 합니다.")
    return time(hour, minute)


# 명세 TimeOfDay: 요청·응답 모두 "07:30"
TimeOfDay = Annotated[
    time,
    BeforeValidator(_parse_time_of_day),
    PlainSerializer(lambda v: v.strftime("%H:%M"), return_type=str, when_used="json"),
]


# ── 차량 ──
class VehicleListItem(BaseModel):
    id: int
    plate: PlateOut
    alias: str | None
    color: str | None
    is_default: bool
    status: VehicleStatus
    status_text: str


class VehicleListResponse(BaseModel):
    items: list[VehicleListItem]


class MyVehicleCreate(BaseModel):
    plate: PlateIn
    color: VehicleColor | None = None
    alias: str | None = Field(default=None, max_length=30)
    is_default: bool = False


class MyVehicleUpdate(BaseModel):
    """보낸 필드만 바꾼다. alias 는 null 을 보내면 비운다."""

    plate: PlateIn | None = None
    alias: str | None = Field(default=None, max_length=30)
    is_default: bool | None = None


class VehicleOwner(BaseModel):
    name: str
    unit: str | None


class VehicleParking(BaseModel):
    parking_id: int
    slot_id: int
    slot_label: str
    entered_at: KstDatetime
    state: ParkingState


class VehicleSchedule(BaseModel):
    expected_exit_at: KstDatetime | None
    exit_source: ExitSource
    elapsed_minutes: int
    memo: str | None  # 출차 예정에 적어 둔 메모. 출차 예정이 없으면 null


class VehicleDetail(BaseModel):
    id: int
    plate: PlateOut
    color: str | None
    owner: VehicleOwner
    parking: VehicleParking | None  # 주차 중이 아니면 null
    schedule: VehicleSchedule | None  # 주차 중이 아니면 null


# ── 반복 출차 ──
class RecurringSchedule(BaseModel):
    days: list[Weekday] = Field(min_length=1)
    time: TimeOfDay
    memo: str | None = None
