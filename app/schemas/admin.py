"""관리인 대시보드·칸 설정·미확인 차량 (#14) 요청·응답 스키마. 명세 AdminDashboard / AdminSlot."""

import enum
from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.common import PlateIn


class OccupantType(enum.StrEnum):
    """명세 OccupantType: 입주민 차량 / 외부·공유 이용자 / 미확인."""

    RESIDENT = "RESIDENT"
    EXTERNAL = "EXTERNAL"
    UNKNOWN = "UNKNOWN"


# ── 대시보드 ──
class BuildingRef(BaseModel):
    id: int
    name: str


class MaskedRequester(BaseModel):
    name: str  # "박○○"
    temperature: float


class PendingRequestItem(BaseModel):
    id: int
    requester: MaskedRequester
    slot_label: str
    request_date: date
    start_hour: int
    end_hour: int
    total_price: int
    created_at: datetime


class RealtimeVehicle(BaseModel):
    slot_id: int
    slot_label: str
    plate: str  # "12가 3456"
    occupant_type: OccupantType
    can_request_move: bool


class Realtime(BaseModel):
    available_count: int
    vehicles: list[RealtimeVehicle]


class CongestionDay(BaseModel):
    date: date
    peak_occupied: int


class Congestion(BaseModel):
    month: str  # 조회한 달 "YYYY-MM" (KST). 쿼리 month 를 생략하면 이번 달
    total_slots: int
    days: list[CongestionDay]


class AdminDashboard(BaseModel):
    building: BuildingRef
    pending_requests: list[PendingRequestItem]
    realtime: Realtime
    congestion: Congestion
    ai_insight: None = None  # 향후 기능. 지금은 항상 null


# ── 칸 ──
class AdminSlot(BaseModel):
    slot_id: int
    zone_id: int
    number: int
    label: str
    is_active: bool
    occupied: bool
    share_offer_id: int | None


class AdminSlotList(BaseModel):
    items: list[AdminSlot]


class AdminSlotUpdate(BaseModel):
    is_active: bool | None = None  # 생략하면 바꾸지 않는다


# ── 미확인 차량 ──
class UnknownVehicleCreate(BaseModel):
    slot_id: int
    plate: PlateIn


class UnknownVehicleCreated(BaseModel):
    parking_id: int
    vehicle_id: int
    occupant_type: OccupantType
