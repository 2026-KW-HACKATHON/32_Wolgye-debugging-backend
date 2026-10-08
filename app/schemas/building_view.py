"""배치도·실시간 현황·배치 추천·홈 (#9) 응답 스키마.
명세 BuildingLayout / BuildingStatus / SlotStatus / SlotRecommendation / Home.
"""

import enum

from pydantic import BaseModel

from app.core.enum_maps import BuildingRole
from app.schemas.admin import OccupantType
from app.schemas.common import KstDatetime, PlateOut
from app.schemas.my_vehicle import ExitSource, ParkingState
from app.schemas.notification import NotificationItem
from app.schemas.user import AlleyRef


# ── 배치도 (GET /buildings/{building_id}/layout) ──
class SlotRect(BaseModel):
    """건물 기준 로컬 좌표(미터). DB render_x0..y1."""

    x0: float
    y0: float
    x1: float
    y1: float


class LayoutSlot(BaseModel):
    id: int
    number: int  # 주차 구역 안 번호
    label: str  # 빌라 안 순번 P1, P2 …
    front_slot_id: int | None  # 이 칸 바로 앞(출구 쪽) 칸
    is_active: bool
    rect: SlotRect | None  # 좌표가 하나라도 없으면 null


class LayoutZone(BaseModel):
    """주차 구역 (DB garages)."""

    id: int
    name: str
    zone_type: str  # 명세 ZoneType: PILOTI_IN / PILOTI_OUT / ROADSIDE
    sort_order: int
    slots: list[LayoutSlot]


class BuildingLayout(BaseModel):
    building_id: int
    name: str
    site_key: str | None  # FE 배치도 사이트 파일 키 (public/sites/{site_key}.json). null 이면 칸 rect 로 그린다
    alley: AlleyRef
    zones: list[LayoutZone]


# ── 실시간 현황 (GET /buildings/{building_id}/status) ──
class SlotState(enum.StrEnum):
    """명세 SlotState."""

    EMPTY = "EMPTY"
    SOON_EXIT = "SOON_EXIT"  # 출차 예정이 1시간 이내 (결정 13)
    OCCUPIED = "OCCUPIED"
    UNAVAILABLE = "UNAVAILABLE"  # is_active=false


class SlotParking(BaseModel):
    id: int
    is_mine: bool
    plate: PlateOut
    occupant_type: OccupantType
    expected_exit_at: KstDatetime | None
    exit_source: ExitSource


class SlotStatus(BaseModel):
    slot_id: int
    state: SlotState
    parking: SlotParking | None
    blocked_by: list[int]  # 이 칸의 차를 막고 있는 칸
    blocking: list[int]  # 이 칸의 차가 막고 있는 칸


class BuildingStatus(BaseModel):
    updated_at: KstDatetime
    slots: list[SlotStatus]


# ── 배치 추천 (GET /buildings/{building_id}/slots/recommendations) ──
class SlotTag(enum.StrEnum):
    """명세 SlotTag (열린 질문 19)."""

    RECOMMENDED = "RECOMMENDED"
    EMPTY = "EMPTY"
    OCCUPIED = "OCCUPIED"
    UNAVAILABLE = "UNAVAILABLE"


class SlotRecommendation(BaseModel):
    slot_id: int
    tag: SlotTag
    label: str
    reason: str | None = None  # RECOMMENDED 일 때만
    will_block: list[int] | None = None  # EMPTY 일 때만
    unavailable_reason: str | None = None  # UNAVAILABLE 일 때만


class SlotRecommendations(BaseModel):
    slots: list[SlotRecommendation]


# ── 홈 (GET /me/home) ──
class HomeBuilding(BaseModel):
    id: int
    name: str
    role: BuildingRole


class HomeSummary(BaseModel):
    available: int  # 가능 = 빈칸 + 1시간 내 비는 칸
    soon_exit: int
    blocked: int  # 막힌 입주민 차량 수
    empty: int


class HomeVehicle(BaseModel):
    id: int
    plate: PlateOut
    color: str | None


class HomeParking(BaseModel):
    parking_id: int
    vehicle: HomeVehicle
    slot_label: str
    state: ParkingState
    expected_exit_at: KstDatetime | None


class HomeBlockAlert(BaseModel):
    blocking_parking_id: int
    message: str


class HomeAdmin(BaseModel):
    pending_share_requests: int


class Home(BaseModel):
    building: HomeBuilding
    unread_notification_count: int
    summary: HomeSummary
    my_parking: HomeParking | None
    block_alert: HomeBlockAlert | None
    admin: HomeAdmin | None  # 관리인일 때만
    recent_notifications: list[NotificationItem]
