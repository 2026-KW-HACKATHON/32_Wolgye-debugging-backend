"""차량·주차·출차 테스트 데이터 (현서 #7~#10). 공용 tests/factories.py 에 없는 것만 둔다."""

from datetime import date, datetime, time

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.departure_schedule import DepartureSchedule
from app.models.parking_assignment import ParkingAssignment
from app.models.parking_slot import ParkingSlot
from app.models.vehicle import Vehicle


async def _save[T](db: AsyncSession, obj: T) -> T:
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


async def make_assignment(
    db: AsyncSession,
    slot: ParkingSlot,
    vehicle: Vehicle,
    assigned_at: datetime | None = None,
    is_permanent: bool = False,
) -> ParkingAssignment:
    """주차 중인 배치 (is_active=True)."""
    assignment = ParkingAssignment(slot_id=slot.id, vehicle_id=vehicle.id, is_permanent=is_permanent)
    if assigned_at is not None:
        assignment.assigned_at = assigned_at
    return await _save(db, assignment)


async def make_departure(
    db: AsyncSession,
    vehicle: Vehicle,
    scheduled_date: date,
    scheduled_time: time,
    repeat_weekdays: list[int] | None = None,
    is_ai_estimated: bool = False,
    created_at: datetime | None = None,
) -> DepartureSchedule:
    """출차 일정. repeat_weekdays 를 주면 반복 일정 (0=월 ~ 6=일)."""
    schedule = DepartureSchedule(
        vehicle_id=vehicle.id,
        scheduled_date=scheduled_date,
        scheduled_time=scheduled_time,
        repeat_weekdays=repeat_weekdays or [],
        is_ai_estimated=is_ai_estimated,
    )
    if created_at is not None:
        schedule.created_at = created_at
    return await _save(db, schedule)
