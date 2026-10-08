"""주차 배치·출차 일정 수정·출차 (#8).

- 배치: 내 차를 칸에 세운다. 배치 INSERT 와 출차 예정 INSERT 를 한 트랜잭션으로 한다.
- 막힘 판정은 app/services/blocking.py, 출차 예정은 app/services/departures.py, 알림은 app/services/notifications.py 를 쓴다.
- 시각은 Asia/Seoul 기준.
"""

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import ErrorCode
from app.models.garage import Garage
from app.models.notification import NotificationType
from app.models.parking_assignment import ParkingAssignment
from app.models.parking_slot import ParkingSlot
from app.models.resident import Resident
from app.models.vehicle import Vehicle
from app.schemas.common import KST
from app.schemas.my_vehicle import ExitSource, ParkingState
from app.schemas.parking import ParkingCreate, ParkingCreated, ParkingExited, ParkingSchedule, ParkingScheduleUpdate
from app.services import blocking, departures, notifications, share_requests
from app.services.exceptions import ConflictError, ForbiddenError, InvalidInputError, NotFoundError
from app.services.permissions import NOT_MEMBER_MESSAGE
from app.services.slot_labels import slot_label
from app.services.slot_reservations import reserved_slot_ids
from app.services.vehicles import get_owned_vehicle

SLOT_UNAVAILABLE_MESSAGE = "해당 칸을 사용할 수 없습니다."
REASON_INACTIVE = "관리인이 사용 중지한 칸"
REASON_RESERVED = "예약된 상태"
WEEKDAYS = [0, 1, 2, 3, 4]  # 월~금


def _ensure_future(exit_at: datetime, now: datetime) -> None:
    if exit_at <= now:
        raise InvalidInputError(detail={"field": "expected_exit_at", "reason": "출차 예정 시각은 지금 이후여야 합니다."})


def _ensure_within_share(exit_at: datetime | None, share_end: datetime | None) -> None:
    """공유 칸(다른 빌라 칸)은 공유가 끝나기 전에 나가야 한다. 상시 주차·공유 종료 후 출차·끝난 공유면 400 INVALID_INPUT."""
    if share_end is None:
        raise InvalidInputError(detail={"field": "expected_exit_at", "reason": "공유 이용 시간이 끝났습니다."})
    if exit_at is None or exit_at > share_end:
        raise InvalidInputError(
            detail={
                "field": "expected_exit_at",
                "reason": f"공유 이용 시간({share_end.astimezone(KST):%H:%M})까지 출차해야 합니다.",
                "share_ends_at": share_end.isoformat(),
            }
        )


async def _slot_building_id(db: AsyncSession, slot_id: int) -> int | None:
    return await db.scalar(
        select(Garage.building_id)
        .join(ParkingSlot, ParkingSlot.garage_id == Garage.id)
        .where(ParkingSlot.id == slot_id)
    )


async def _my_share_end(db: AsyncSession, user: Resident, slot_id: int, now: datetime) -> datetime | None:
    """slot_id 칸에서 지금 진행 중인 내 수락된 공유가 끝나는 시각. 없으면 None."""
    share = await blocking.accepted_share(db, slot_id, now)
    if share is None or share.requester_id != user.id:
        return None
    return share_requests.share_ends_at(share)


async def _lock_slot_with_neighbors(db: AsyncSession, slot_id: int) -> ParkingSlot | None:
    """대상 칸과 앞·뒤 칸을 잠근다 (동시에 배치해도 막힘·점유 검증이 어긋나지 않게). id 순서로 잠가 교착을 피한다."""
    front_id = select(ParkingSlot.front_slot_id).where(ParkingSlot.id == slot_id).scalar_subquery()
    rows = await db.scalars(
        select(ParkingSlot)
        .where(or_(ParkingSlot.id == slot_id, ParkingSlot.front_slot_id == slot_id, ParkingSlot.id == front_id))
        .order_by(ParkingSlot.id)
        .with_for_update()
    )
    return next((slot for slot in rows.all() if slot.id == slot_id), None)


async def _active_assignment_of_vehicle(db: AsyncSession, vehicle_id: int) -> ParkingAssignment | None:
    return await db.scalar(
        select(ParkingAssignment).where(ParkingAssignment.vehicle_id == vehicle_id, ParkingAssignment.is_active)
    )


async def create_parking(
    db: AsyncSession, user: Resident, payload: ParkingCreate, now: datetime | None = None
) -> ParkingCreated:
    """내 차를 칸에 배치한다.

    - 내 차량이 아니거나 칸이 없으면 404 NOT_FOUND
    - 다른 빌라 칸이면 403 NOT_BUILDING_MEMBER. 단, 그 칸에 지금 진행 중인 내 수락된 공유가 있으면 주차할 수 있다
      (공유 칸은 상시 주차할 수 없고, 출차 예정이 공유 종료 시각을 넘으면 400 INVALID_INPUT, backend #51)
    - 이 차가 이미 주차 중이면 409 VEHICLE_ALREADY_PARKED (detail.parking_id)
    - 비활성 칸이거나 지금부터 내 출차 시각까지 다른 사람의 수락된 공유가 있으면 409 SLOT_UNAVAILABLE (detail.reason),
      다른 차가 있으면 409 SLOT_OCCUPIED
    """
    now = now or datetime.now(KST)
    exit_at = None if payload.is_long_term else payload.expected_exit_at
    if exit_at is not None:
        _ensure_future(exit_at, now)

    vehicle = await get_owned_vehicle(db, user, payload.vehicle_id)
    slot = await _lock_slot_with_neighbors(db, payload.slot_id)
    if slot is None:
        raise NotFoundError("칸을 찾을 수 없습니다.")
    building_id = await db.scalar(select(Garage.building_id).where(Garage.id == slot.garage_id))

    if user.building_id != building_id:
        share_end = await _my_share_end(db, user, slot.id, now)
        if share_end is None:
            raise ForbiddenError(NOT_MEMBER_MESSAGE, code=ErrorCode.NOT_BUILDING_MEMBER)
        _ensure_within_share(exit_at, share_end)

    parked = await _active_assignment_of_vehicle(db, vehicle.id)
    if parked is not None:
        raise ConflictError(
            "이미 주차 중인 차량입니다.", code=ErrorCode.VEHICLE_ALREADY_PARKED, detail={"parking_id": parked.id}
        )
    if not slot.is_active:
        raise ConflictError(
            SLOT_UNAVAILABLE_MESSAGE, code=ErrorCode.SLOT_UNAVAILABLE, detail={"reason": REASON_INACTIVE}
        )
    occupied = await db.scalar(
        select(ParkingAssignment.id).where(ParkingAssignment.slot_id == slot.id, ParkingAssignment.is_active)
    )
    if occupied is not None:
        raise ConflictError("이미 다른 차량이 주차 중인 칸입니다.", code=ErrorCode.SLOT_OCCUPIED)
    # 지금부터 내 출차 시각까지(상시 주차면 그 이후 전부) 다른 사람의 수락된 공유가 있으면 예약된 칸
    if await reserved_slot_ids(db, [slot.id], now, exit_at, except_requester_id=user.id):
        raise ConflictError(
            SLOT_UNAVAILABLE_MESSAGE, code=ErrorCode.SLOT_UNAVAILABLE, detail={"reason": REASON_RESERVED}
        )

    assignment = ParkingAssignment(slot_id=slot.id, vehicle_id=vehicle.id, is_permanent=payload.is_long_term)
    db.add(assignment)
    if exit_at is not None:
        await departures.set_one_off(db, vehicle.id, exit_at, payload.memo, now)
        if payload.repeat_weekdays:
            local = exit_at.astimezone(KST)
            await departures.set_recurring(
                db, vehicle.id, WEEKDAYS, local.time().replace(tzinfo=None), payload.memo, now.astimezone(KST).date()
            )
    await db.flush()
    blocked_slots = await blocking.blocking_slots(db, slot.id, now)
    await db.commit()

    return ParkingCreated(
        id=assignment.id,
        slot_id=slot.id,
        state=ParkingState.PARKED,
        expected_exit_at=exit_at,
        exit_source=ExitSource.MANUAL if exit_at is not None else ExitSource.NONE,
        blocking=blocked_slots,
    )


async def _my_active_parking(db: AsyncSession, user: Resident, parking_id: int) -> ParkingAssignment:
    """내 차의 주차 중인 배치. 없거나, 남의 차이거나, 이미 출차했으면 404 NOT_FOUND."""
    assignment = await db.scalar(
        select(ParkingAssignment)
        .join(Vehicle, Vehicle.id == ParkingAssignment.vehicle_id)
        .where(ParkingAssignment.id == parking_id, ParkingAssignment.is_active, Vehicle.owner_id == user.id)
        .with_for_update(of=ParkingAssignment)
    )
    if assignment is None:
        raise NotFoundError("주차 중인 배치를 찾을 수 없습니다.")
    return assignment


async def _notify_blockers(db: AsyncSession, assignment: ParkingAssignment, exit_at: datetime, now: datetime) -> None:
    """이 차를 막고 있는 차의 주인에게 BLOCK_ALERT. 주인 없는 미확인 차량은 건너뛴다."""
    blocker_slots = await blocking.blocked_by(db, assignment.slot_id, now)
    if not blocker_slots:
        return
    owner_ids = await db.scalars(
        select(Vehicle.owner_id)
        .join(ParkingAssignment, ParkingAssignment.vehicle_id == Vehicle.id)
        .where(ParkingAssignment.is_active, ParkingAssignment.slot_id.in_(blocker_slots), Vehicle.owner_id.is_not(None))
    )
    exit_text = exit_at.astimezone(KST).strftime("%H:%M")
    for owner_id in set(owner_ids.all()):
        await notifications.create(
            db, owner_id, NotificationType.BLOCK_ALERT, "막힘 알림", f"내 차량이 {exit_text} 출차하는 차량을 막고 있어요"
        )


async def update_schedule(
    db: AsyncSession, user: Resident, parking_id: int, payload: ParkingScheduleUpdate, now: datetime | None = None
) -> ParkingSchedule:
    """배치는 그대로 두고 출차 예정만 바꾼다.

    - 출차 시각을 주면 그 시각으로 바꾼다. 상시 주차였다면 시간이 생기므로 상시 주차를 푼다.
      출차 시간을 앞당겼고(없던 시간이 생긴 경우 포함) 이 차를 막는 차가 있으면 막는 차 주인에게 즉시 BLOCK_ALERT.
    - is_long_term=true 면 상시 주차로 바꾼다 (backend #48). 직접 입력한 오늘 이후 일회성 일정은 지우고
      반복 일정은 그대로 둔다 (상시 주차인 동안에는 보지 않는다). 출차 시각이 없으므로 exit_source 는 NONE,
      메모를 둘 일정 행이 없으므로 memo 는 null 이다.
    공유 칸(다른 빌라 칸)이면 공유 종료 시각을 넘길 수 없고 상시 주차로 바꿀 수 없다 (400 INVALID_INPUT, backend #51).
    """
    now = now or datetime.now(KST)
    exit_at = None if payload.is_long_term else payload.expected_exit_at
    if exit_at is not None:
        _ensure_future(exit_at, now)
    assignment = await _my_active_parking(db, user, parking_id)
    if await _slot_building_id(db, assignment.slot_id) != user.building_id:
        _ensure_within_share(exit_at, await _my_share_end(db, user, assignment.slot_id, now))

    if exit_at is None:
        assignment.is_permanent = True
        await departures.delete_upcoming_one_offs(db, assignment.vehicle_id, now)
        await db.commit()
        return ParkingSchedule(parking_id=assignment.id, expected_exit_at=None, exit_source=ExitSource.NONE, memo=None)

    previous = None
    if not assignment.is_permanent:
        departure = await departures.next_departure(db, assignment.vehicle_id, now)
        previous = departure.at if departure else None

    assignment.is_permanent = False
    await departures.set_one_off(db, assignment.vehicle_id, exit_at, payload.memo, now)
    await db.flush()
    if previous is None or exit_at < previous:
        await _notify_blockers(db, assignment, exit_at, now)
    await db.commit()

    return ParkingSchedule(
        parking_id=assignment.id,
        expected_exit_at=exit_at,
        exit_source=ExitSource.MANUAL,
        memo=payload.memo,
    )


async def exit_parking(db: AsyncSession, user: Resident, parking_id: int, now: datetime | None = None) -> ParkingExited:
    """출차: 배치를 끝내고(`is_active=false`, `released_at=now`) 같은 빌라 입주민에게 EXIT_DONE 을 보낸다.

    on_time = 출차 예정 시각 이전에 나갔는지. 예정 시각이 없으면(상시 주차 등) True.
    """
    now = now or datetime.now(KST)
    assignment = await _my_active_parking(db, user, parking_id)

    expected = None
    if not assignment.is_permanent:
        departure = await departures.next_departure(db, assignment.vehicle_id, now)
        expected = departure.at if departure else None

    assignment.is_active = False
    assignment.released_at = now

    building_id = await _slot_building_id(db, assignment.slot_id)
    body = f"{await slot_label(db, assignment.slot_id)} 비어 있음"
    neighbor_ids = await db.scalars(
        select(Resident.id).where(Resident.building_id == building_id, Resident.id != user.id)
    )
    for resident_id in neighbor_ids.all():
        await notifications.create(db, resident_id, NotificationType.EXIT_DONE, "출차 완료 안내", body)
    await db.commit()

    return ParkingExited(
        id=assignment.id,
        state=ParkingState.EXITED,
        actual_exit_at=now,
        on_time=expected is None or now <= expected,
    )
