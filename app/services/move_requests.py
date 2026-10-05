"""이동 요청 (#10).

- 수신자는 저장하지 않는다: `target_vehicle.owner_id` (그 주차 건의 차 주인)
- 입주민은 같은 빌라 칸에 주차 중인 차에만, 관리인은 자기 빌라 칸의 외부 차량에도 요청할 수 있다
- 알림은 생성할 때만 (결정 2). "옮겼어요" 때는 보내지 않는다
- 익명 표시 (결정 16): `residents.unit_no` 의 "N동" → "101동 입주민", 없으면 "입주민"
"""

import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enum_maps import api_name
from app.core.error_codes import ErrorCode
from app.models.garage import Garage
from app.models.move_request import MoveRequest, MoveRequestStatus
from app.models.notification import NotificationType
from app.models.parking_assignment import ParkingAssignment
from app.models.parking_slot import ParkingSlot
from app.models.resident import Resident, ResidentRole
from app.models.vehicle import Vehicle
from app.schemas.common import KST
from app.schemas.move_request import (
    BlockedVehicle,
    MoveRequestBox,
    MoveRequestCreate,
    MoveRequestCreated,
    MoveRequestDetail,
    MoveRequestDone,
    MoveRequester,
    MoveRequestListItem,
    RequestedVehicle,
)
from app.services import notifications
from app.services.exceptions import ConflictError, ForbiddenError, InvalidInputError, NotFoundError
from app.services.permissions import ensure_building_member
from app.services.slot_labels import slot_labels

NOTIFICATION_TITLE = "주차 요청 도착"
_DONG = re.compile(r"\d+동")


def anonymous_label(unit_no: str | None) -> str:
    """ "101동 202호" → "101동 입주민". 동이 없으면 "입주민" (결정 16)."""
    match = _DONG.search(unit_no or "")
    return f"{match.group(0)} 입주민" if match else "입주민"


async def _active_assignments(db: AsyncSession, vehicle_ids: set[int]) -> dict[int, ParkingAssignment]:
    """차량별 지금 주차 중인 배치 (vehicle_id → 배치)."""
    if not vehicle_ids:
        return {}
    rows = await db.scalars(
        select(ParkingAssignment).where(ParkingAssignment.is_active, ParkingAssignment.vehicle_id.in_(vehicle_ids))
    )
    return {assignment.vehicle_id: assignment for assignment in rows.all()}


async def create(db: AsyncSession, user: Resident, payload: MoveRequestCreate) -> MoveRequestCreated:
    """이동 요청을 만들고 수신자(그 차 주인)에게 MOVE_REQUEST 알림을 보낸다.

    - 주차 건이 없거나 이미 출차했으면 404 NOT_FOUND
    - 내 빌라 칸이 아니거나, 관리인이 아닌데 외부 차량이면 403 NOT_BUILDING_MEMBER
    - 미확인 차량이면 400 INVALID_INPUT (detail.reason = UNKNOWN_VEHICLE), 내 차면 400 INVALID_INPUT
    - 같은 차에 대기 중인 요청이 있으면 409 MOVE_REQUEST_ALREADY_PENDING (detail.move_request_id)
    """
    row = (
        await db.execute(
            select(ParkingAssignment, Vehicle, Garage.building_id)
            .join(Vehicle, Vehicle.id == ParkingAssignment.vehicle_id)
            .join(ParkingSlot, ParkingSlot.id == ParkingAssignment.slot_id)
            .join(Garage, Garage.id == ParkingSlot.garage_id)
            .where(ParkingAssignment.id == payload.target_parking_id, ParkingAssignment.is_active)
        )
    ).first()
    if row is None:
        raise NotFoundError("주차 중인 차량을 찾을 수 없습니다.")
    _, target, building_id = row
    # 입주민·관리인 모두 자기 빌라 칸의 차에만. 그 칸에 선 외부 차량(공유 이용자)에는 관리인만 요청할 수 있다
    ensure_building_member(user, building_id)
    if target.owner_id is None:
        raise InvalidInputError("앱으로 연락할 수 없는 차량입니다.", detail={"reason": "UNKNOWN_VEHICLE"})
    if target.owner_id == user.id:
        raise InvalidInputError("내 차량에는 이동 요청을 보낼 수 없습니다.")
    owner = await db.get(Resident, target.owner_id)
    if owner.building_id != building_id and user.role != ResidentRole.MANAGER:
        raise ForbiddenError("외부 차량에는 관리인만 이동 요청을 보낼 수 있습니다.", code=ErrorCode.NOT_BUILDING_MEMBER)

    pending_id = await db.scalar(
        select(MoveRequest.id).where(
            MoveRequest.target_vehicle_id == target.id, MoveRequest.status == MoveRequestStatus.PENDING
        )
    )
    if pending_id is not None:
        raise ConflictError(
            "이 차량에 대기 중인 이동 요청이 이미 있습니다.",
            code=ErrorCode.MOVE_REQUEST_ALREADY_PENDING,
            detail={"move_request_id": pending_id},
        )

    # 막힌 차 = 요청자가 이 빌라에 지금 세워 둔 차 (없으면 NULL, 예: 관리인이 외부 차량에 보내는 요청)
    blocked_vehicle_id = await db.scalar(
        select(Vehicle.id)
        .join(ParkingAssignment, ParkingAssignment.vehicle_id == Vehicle.id)
        .join(ParkingSlot, ParkingSlot.id == ParkingAssignment.slot_id)
        .join(Garage, Garage.id == ParkingSlot.garage_id)
        .where(Vehicle.owner_id == user.id, ParkingAssignment.is_active, Garage.building_id == building_id)
        .order_by(Vehicle.is_primary.desc(), ParkingAssignment.assigned_at.desc())
        .limit(1)
    )

    move_request = MoveRequest(
        requester_id=user.id,
        target_vehicle_id=target.id,
        blocked_vehicle_id=blocked_vehicle_id,
        needed_by=payload.needed_at,
        reason=payload.reason,
    )
    db.add(move_request)
    await db.flush()
    await notifications.create(
        db,
        target.owner_id,
        NotificationType.MOVE_REQUEST,
        NOTIFICATION_TITLE,
        anonymous_label(user.unit_no),
        move_request_id=move_request.id,
    )
    await db.commit()
    return MoveRequestCreated(id=move_request.id, status=api_name(move_request.status))


async def _received(db: AsyncSession, user: Resident, move_request_id: int) -> tuple[MoveRequest, Vehicle]:
    """내가 받은(= 내 차가 대상인) 이동 요청과 그 차. 없으면 404 NOT_FOUND."""
    row = (
        await db.execute(
            select(MoveRequest, Vehicle)
            .join(Vehicle, Vehicle.id == MoveRequest.target_vehicle_id)
            .where(MoveRequest.id == move_request_id)
            .with_for_update(of=MoveRequest)
        )
    ).first()
    if row is None or row[1].owner_id != user.id:
        raise NotFoundError("이동 요청을 찾을 수 없습니다.")
    return row[0], row[1]


async def get_detail(db: AsyncSession, user: Resident, move_request_id: int) -> MoveRequestDetail:
    """이동 요청 수신 화면. 수신자(대상 차 주인)와 요청자만 볼 수 있다. 아니면 404 NOT_FOUND."""
    move_request = await db.get(MoveRequest, move_request_id)
    target = await db.get(Vehicle, move_request.target_vehicle_id) if move_request else None
    if move_request is None or user.id not in (move_request.requester_id, target.owner_id):
        raise NotFoundError("이동 요청을 찾을 수 없습니다.")

    blocked = await db.get(Vehicle, move_request.blocked_vehicle_id) if move_request.blocked_vehicle_id else None
    requester = await db.get(Resident, move_request.requester_id)
    assignments = await _active_assignments(db, {v.id for v in (target, blocked) if v is not None})
    labels = await slot_labels(db, {a.slot_id for a in assignments.values()})

    def label_of(vehicle: Vehicle) -> str | None:
        assignment = assignments.get(vehicle.id)
        return labels[assignment.slot_id] if assignment else None

    target_assignment = assignments.get(target.id)
    return MoveRequestDetail(
        id=move_request.id,
        status=api_name(move_request.status),
        requested_at=move_request.created_at,
        requester=MoveRequester(label=anonymous_label(requester.unit_no)),
        my_vehicle=RequestedVehicle(
            plate=target.plate_no,
            slot_label=label_of(target),
            parked_at=target_assignment.assigned_at if target_assignment else None,
        ),
        blocked_vehicle=(
            BlockedVehicle(plate=blocked.plate_no, slot_label=label_of(blocked), needed_at=move_request.needed_by)
            if blocked is not None
            else None
        ),
        reason=move_request.reason,
    )


async def done(db: AsyncSession, user: Resident, move_request_id: int, now: datetime | None = None) -> MoveRequestDone:
    """ "옮겼어요": 대기 중인 요청을 MOVED 로 바꾸고 응답 시각을 남긴다. 알림은 보내지 않는다 (결정 2).

    내가 받은 요청이 아니면 404, 이미 처리됐으면 409 ALREADY_DECIDED (detail.status).
    """
    move_request, _ = await _received(db, user, move_request_id)
    if move_request.status != MoveRequestStatus.PENDING:
        raise ConflictError(
            "이미 처리된 요청입니다.",
            code=ErrorCode.ALREADY_DECIDED,
            detail={"status": api_name(move_request.status)},
        )
    move_request.status = MoveRequestStatus.MOVED
    move_request.responded_at = now or datetime.now(KST)
    await db.commit()
    return MoveRequestDone(
        id=move_request.id, status=api_name(move_request.status), responded_at=move_request.responded_at
    )


async def list_mine(db: AsyncSession, user: Resident, box: MoveRequestBox) -> list[MoveRequestListItem]:
    """내 이동 요청 최신순. received = 내 차가 대상인 요청(상대 = 요청자), sent = 내가 보낸 요청(상대 = 대상 차 주인)."""
    requester_unit = select(Resident.unit_no).where(Resident.id == MoveRequest.requester_id).scalar_subquery()
    owner_unit = (
        select(Resident.unit_no)
        .join(Vehicle, Vehicle.owner_id == Resident.id)
        .where(Vehicle.id == MoveRequest.target_vehicle_id)
        .scalar_subquery()
    )
    if box is MoveRequestBox.RECEIVED:
        stmt = (
            select(MoveRequest, requester_unit)
            .join(Vehicle, Vehicle.id == MoveRequest.target_vehicle_id)
            .where(Vehicle.owner_id == user.id)
        )
    else:
        stmt = select(MoveRequest, owner_unit).where(MoveRequest.requester_id == user.id)
    rows = await db.execute(stmt.order_by(MoveRequest.id.desc()))
    return [
        MoveRequestListItem(
            id=move_request.id,
            status=api_name(move_request.status),
            requested_at=move_request.created_at,
            counterpart_label=anonymous_label(unit_no),
            needed_at=move_request.needed_by,
        )
        for move_request, unit_no in rows.all()
    ]
