"""홈 집계 (#9): GET /me/home. 여러 카드를 한 번에 그리기 위한 값들을 모은다.

요약 칩 (명세 열린 질문 1):
- 빈칸(empty) = 비어 있는 사용 가능 칸 수
- 곧 출차(soon_exit) = 1시간 안에 비는 칸 수 (결정 13)
- 가능(available) = 빈칸 + 곧 출차
- 막힘(blocked) = 막힌 입주민 차량 수
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enum_maps import role_to_api
from app.core.error_codes import ErrorCode
from app.models.building import Building
from app.models.garage import Garage
from app.models.notification import Notification
from app.models.parking_assignment import ParkingAssignment
from app.models.parking_slot import ParkingSlot
from app.models.resident import Resident, ResidentRole
from app.models.share_request import ShareRequest, ShareRequestStatus
from app.models.vehicle import Vehicle
from app.schemas.admin import OccupantType
from app.schemas.building_view import (
    Home,
    HomeAdmin,
    HomeBlockAlert,
    HomeBuilding,
    HomeParking,
    HomeSummary,
    HomeVehicle,
    SlotState,
)
from app.schemas.common import KST
from app.schemas.my_vehicle import ParkingState
from app.schemas.notification import NotificationItem
from app.services import blocking
from app.services.building_view import BuildingSnapshot, snapshot
from app.services.exceptions import ForbiddenError
from app.services.permissions import NOT_MEMBER_MESSAGE
from app.services.slot_labels import slot_label

RECENT_NOTIFICATIONS = 2  # 와이어프레임 홈 화면의 "최근 알림" 카드 수


def summarize(snap: BuildingSnapshot, now: datetime) -> HomeSummary:
    states = [snap.state(slot, now) for slot in snap.slots]
    empty = states.count(SlotState.EMPTY)
    soon_exit = states.count(SlotState.SOON_EXIT)
    blocked = sum(
        1
        for slot_id, occupant in snap.occupants.items()
        if occupant.kind is OccupantType.RESIDENT and snap.blocks[slot_id].blocked_by
    )
    return HomeSummary(available=empty + soon_exit, soon_exit=soon_exit, blocked=blocked, empty=empty)


async def _my_parking(db: AsyncSession, user: Resident) -> ParkingAssignment | None:
    """내 차의 주차 중인 배치. 여러 대가 주차 중이면 대표 차량, 그다음 최근에 세운 차."""
    return (
        await db.scalars(
            select(ParkingAssignment)
            .join(Vehicle, Vehicle.id == ParkingAssignment.vehicle_id)
            .where(Vehicle.owner_id == user.id, ParkingAssignment.is_active)
            .order_by(Vehicle.is_primary.desc(), ParkingAssignment.assigned_at.desc(), ParkingAssignment.id.desc())
            .limit(1)
        )
    ).first()


async def get_home(db: AsyncSession, user: Resident, now: datetime | None = None) -> Home:
    """소속 빌라가 없으면 403 NOT_BUILDING_MEMBER."""
    if user.building_id is None:
        raise ForbiddenError(NOT_MEMBER_MESSAGE, code=ErrorCode.NOT_BUILDING_MEMBER)
    now = now or datetime.now(KST)
    building = await db.get(Building, user.building_id)
    snap = await snapshot(db, building.id, now)

    my_parking = block_alert = None
    assignment = await _my_parking(db, user)
    if assignment is not None:
        # 다른 빌라 칸(공유 이용)에 세워 둔 경우에도 보여준다
        occupant = snap.occupants.get(assignment.slot_id) or (
            await blocking.occupants(db, [assignment.slot_id], now)
        )[assignment.slot_id]
        my_parking = HomeParking(
            parking_id=assignment.id,
            vehicle=HomeVehicle(
                id=occupant.vehicle.id, plate=occupant.vehicle.plate_no, color=occupant.vehicle.color
            ),
            slot_label=snap.labels.get(assignment.slot_id) or await slot_label(db, assignment.slot_id),
            state=ParkingState.PARKED,
            expected_exit_at=occupant.exit_at,
        )
        blockers = snap.blocks[assignment.slot_id].blocked_by if assignment.slot_id in snap.blocks else []
        if blockers:
            blocker = blockers[0]
            block_alert = HomeBlockAlert(
                blocking_parking_id=snap.occupants[blocker].assignment.id,
                message=f"내 차량이 {snap.labels[blocker]} 차량에 의해 막혀 있습니다.",
            )

    admin = None
    if user.role == ResidentRole.MANAGER:
        pending = await db.scalar(
            select(func.count(ShareRequest.id))
            .join(ParkingSlot, ParkingSlot.id == ShareRequest.slot_id)
            .join(Garage, Garage.id == ParkingSlot.garage_id)
            .where(Garage.building_id == building.id, ShareRequest.status == ShareRequestStatus.PENDING)
        )
        admin = HomeAdmin(pending_share_requests=pending or 0)

    unread = await db.scalar(
        select(func.count(Notification.id)).where(Notification.resident_id == user.id, Notification.is_read.is_(False))
    )
    recent = await db.scalars(
        select(Notification)
        .where(Notification.resident_id == user.id)
        .order_by(Notification.id.desc())
        .limit(RECENT_NOTIFICATIONS)
    )

    return Home(
        building=HomeBuilding(id=building.id, name=building.name, role=role_to_api(user.role)),
        unread_notification_count=unread or 0,
        summary=summarize(snap, now),
        my_parking=my_parking,
        block_alert=block_alert,
        admin=admin,
        recent_notifications=[NotificationItem.from_model(n) for n in recent.all()],
    )
