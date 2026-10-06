"""차량. 명세 API `/me/vehicles`(#7)용 함수.

명세 ↔ DB 이름: plate ↔ plate_no, alias ↔ nickname, is_default ↔ is_primary.
"""

from datetime import datetime

from sqlalchemy import delete, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import ErrorCode
from app.models.parking_assignment import ParkingAssignment
from app.models.resident import Resident
from app.models.vehicle import Vehicle
from app.schemas.common import KST
from app.schemas.my_vehicle import (
    ExitSource,
    MyVehicleCreate,
    MyVehicleUpdate,
    ParkingState,
    VehicleDetail,
    VehicleListItem,
    VehicleOwner,
    VehicleParking,
    VehicleSchedule,
    VehicleStatus,
)
from app.services import departures
from app.services.exceptions import ConflictError, NotFoundError
from app.services.slot_labels import slot_label

STATUS_TEXT = {VehicleStatus.PARKED: "현재 주차 중", VehicleStatus.OUT: "외부 출차"}
PLATE_EXISTS_MESSAGE = "이미 등록된 차량 번호입니다."


# ── 내 차량 (#7) ──────────────────────────────────────────────────────
async def get_owned_vehicle(db: AsyncSession, user: Resident, vehicle_id: int) -> Vehicle:
    """내 차량. 없거나 남의 차량이면 404 NOT_FOUND (존재 여부를 노출하지 않는다)."""
    vehicle = await db.get(Vehicle, vehicle_id)
    if vehicle is None or vehicle.owner_id != user.id:
        raise NotFoundError("차량을 찾을 수 없습니다.")
    return vehicle


async def _active_assignment(db: AsyncSession, vehicle_id: int) -> ParkingAssignment | None:
    return await db.scalar(
        select(ParkingAssignment).where(ParkingAssignment.vehicle_id == vehicle_id, ParkingAssignment.is_active)
    )


def _to_item(vehicle: Vehicle, parked: bool) -> VehicleListItem:
    status = VehicleStatus.PARKED if parked else VehicleStatus.OUT
    return VehicleListItem(
        id=vehicle.id,
        plate=vehicle.plate_no,
        alias=vehicle.nickname,
        color=vehicle.color,
        is_default=vehicle.is_primary,
        status=status,
        status_text=STATUS_TEXT[status],
    )


async def _ensure_plate_free(db: AsyncSession, plate: str, except_vehicle_id: int | None = None) -> None:
    """같은 번호판이 이미 있으면 409 PLATE_EXISTS (동시에 등록하면 UNIQUE 제약이 같은 코드로 막는다)."""
    stmt = exists().where(Vehicle.plate_no == plate)
    if except_vehicle_id is not None:
        stmt = stmt.where(Vehicle.id != except_vehicle_id)
    if await db.scalar(select(stmt)):
        raise ConflictError(PLATE_EXISTS_MESSAGE, code=ErrorCode.PLATE_EXISTS)


async def _clear_default(db: AsyncSession, owner_id: int, except_vehicle_id: int | None = None) -> None:
    """대표 차량은 사용자당 하나 (uq_primary_vehicle_per_owner) → 새로 지정하기 전에 기존 대표를 해제한다."""
    stmt = update(Vehicle).where(Vehicle.owner_id == owner_id, Vehicle.is_primary).values(is_primary=False)
    if except_vehicle_id is not None:
        stmt = stmt.where(Vehicle.id != except_vehicle_id)
    await db.execute(stmt)


async def list_my_vehicles(db: AsyncSession, user: Resident) -> list[VehicleListItem]:
    """내 차량 목록. 대표 차량이 먼저, 그다음 등록순."""
    vehicles = list(
        (
            await db.scalars(
                select(Vehicle).where(Vehicle.owner_id == user.id).order_by(Vehicle.is_primary.desc(), Vehicle.id)
            )
        ).all()
    )
    parked = set(
        (
            await db.scalars(
                select(ParkingAssignment.vehicle_id).where(
                    ParkingAssignment.is_active, ParkingAssignment.vehicle_id.in_([v.id for v in vehicles])
                )
            )
        ).all()
    )
    return [_to_item(v, v.id in parked) for v in vehicles]


async def create_my_vehicle(db: AsyncSession, user: Resident, payload: MyVehicleCreate) -> VehicleListItem:
    await _ensure_plate_free(db, payload.plate)
    if payload.is_default:
        await _clear_default(db, user.id)
    vehicle = Vehicle(
        plate_no=payload.plate,
        owner_id=user.id,
        color=payload.color,
        nickname=payload.alias,
        is_primary=payload.is_default,
    )
    db.add(vehicle)
    await db.commit()
    await db.refresh(vehicle)
    return _to_item(vehicle, parked=False)


async def update_my_vehicle(
    db: AsyncSession, user: Resident, vehicle_id: int, payload: MyVehicleUpdate
) -> VehicleListItem:
    """보낸 필드만 바꾼다. plate·is_default 에 null 을 보내면 바꾸지 않는다."""
    vehicle = await get_owned_vehicle(db, user, vehicle_id)
    changes = payload.model_dump(exclude_unset=True)

    plate = changes.get("plate")
    if plate is not None and plate != vehicle.plate_no:
        await _ensure_plate_free(db, plate, except_vehicle_id=vehicle.id)
        vehicle.plate_no = plate
    if "alias" in changes:
        vehicle.nickname = changes["alias"]
    is_default = changes.get("is_default")
    if is_default is not None:
        if is_default:
            await _clear_default(db, user.id, except_vehicle_id=vehicle.id)
        vehicle.is_primary = is_default

    await db.commit()
    await db.refresh(vehicle)
    return _to_item(vehicle, parked=await _active_assignment(db, vehicle.id) is not None)


async def delete_my_vehicle(db: AsyncSession, user: Resident, vehicle_id: int) -> None:
    """내 차량 삭제. 주차 중이면 409 VEHICLE_ALREADY_PARKED. 주차 이력·출차 일정은 FK CASCADE 로 함께 지워진다."""
    vehicle = await get_owned_vehicle(db, user, vehicle_id)
    assignment = await _active_assignment(db, vehicle.id)
    if assignment is not None:
        raise ConflictError(
            "주차 중인 차량은 삭제할 수 없습니다.",
            code=ErrorCode.VEHICLE_ALREADY_PARKED,
            detail={"parking_id": assignment.id},
        )
    # ORM delete 는 관계를 lazy load 하므로(async 에서 불가) DELETE 문으로 지우고 DB CASCADE 에 맡긴다
    await db.execute(delete(Vehicle).where(Vehicle.id == vehicle.id))
    await db.commit()


async def get_my_vehicle(
    db: AsyncSession, user: Resident, vehicle_id: int, now: datetime | None = None
) -> VehicleDetail:
    """차량 상세. 주차 중이 아니면 parking, schedule 은 None."""
    vehicle = await get_owned_vehicle(db, user, vehicle_id)
    now = now or datetime.now(KST)

    parking = schedule = None
    assignment = await _active_assignment(db, vehicle.id)
    if assignment is not None:
        parking = VehicleParking(
            parking_id=assignment.id,
            slot_id=assignment.slot_id,
            slot_label=await slot_label(db, assignment.slot_id),
            entered_at=assignment.assigned_at,
            state=ParkingState.PARKED,
        )
        # 상시 주차는 출차 시간이 없다 (결정 10: NONE)
        departure = None if assignment.is_permanent else await departures.next_departure(db, vehicle.id, now)
        schedule = VehicleSchedule(
            expected_exit_at=departure.at if departure else None,
            exit_source=departure.source if departure else ExitSource.NONE,
            elapsed_minutes=max(0, int((now - assignment.assigned_at).total_seconds() // 60)),
            memo=departure.memo if departure else None,
        )

    return VehicleDetail(
        id=vehicle.id,
        plate=vehicle.plate_no,
        color=vehicle.color,
        owner=VehicleOwner(name=user.name or user.nickname, unit=user.unit_no),
        parking=parking,
        schedule=schedule,
    )
