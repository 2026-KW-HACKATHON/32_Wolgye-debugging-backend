"""관리인 대시보드·칸 설정·미확인 차량 (#14) 요청·응답 스키마. 명세 AdminDashboard / AdminSlot."""

import enum
from datetime import date

from pydantic import BaseModel

from app.schemas.common import KstDatetime, PlateIn


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
    created_at: KstDatetime


class ShareHours(BaseModel):
    """공유 이용 시간 (Asia/Seoul, 정시). end_hour = 24 는 다음 날 0시."""

    start_hour: int
    end_hour: int


class RealtimeVehicle(BaseModel):
    slot_id: int
    slot_label: str
    plate: str | None  # "12가 3456". 차량을 고르지 않은 공유 예약(parked=false)이면 null
    occupant_type: OccupantType
    can_request_move: bool  # 주차 중(parked)이고 미확인 차량이 아닐 때만 true
    parked: bool  # true = 주차 중(활성 배치), false = 지금 이용 시간인 공유 예약만 있고 아직 주차 안 함 (#53)
    share: ShareHours | None  # 이 칸·차량의 지금 이용 중인 수락된 공유. 없으면 null


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
