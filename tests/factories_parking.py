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


async def make_spec_building(db: AsyncSession, invite_code: str = "HANBIT01") -> dict:
    """명세 예시의 빌라 3 (월계 한빛빌라): 주차 구역 4개, 칸 8개 (P1~P8).

    앞 칸: P1 → P2, P4 → P5, P7 → P8. P5 는 사용 중지.
    돌려주는 dict: building, zones(이름 → Garage), P1~P8(칸).
    """
    from app.models.alley import Alley
    from app.models.building import Building
    from app.models.garage import Garage, GarageType

    alley = await _save(db, Alley(name="광운로19가길"))
    building = await _save(
        db, Building(alley_id=alley.id, name="월계 한빛빌라", address="서울 노원구 광운로19가길 12", invite_code=invite_code)
    )
    plan = [
        ("필로티 안쪽", GarageType.PILOTI_IN, 2),
        ("필로티 외부", GarageType.PILOTI_OUT, 1),
        ("건물 앞", GarageType.PILOTI_OUT, 3),
        ("골목", GarageType.ROADSIDE, 2),
    ]
    result: dict = {"building": building, "alley": alley, "zones": {}}
    ordinal = 0
    for sort_order, (name, garage_type, count) in enumerate(plan):
        garage = await _save(
            db, Garage(building_id=building.id, name=name, garage_type=garage_type, sort_order=sort_order)
        )
        result["zones"][name] = garage
        for number in range(1, count + 1):
            ordinal += 1
            x = float(ordinal)
            result[f"P{ordinal}"] = await _save(
                db,
                ParkingSlot(
                    garage_id=garage.id, number=number, render_x0=x, render_y0=0.0, render_x1=x + 2.5, render_y1=5.0
                ),
            )
    for inner, outer in (("P1", "P2"), ("P4", "P5"), ("P7", "P8")):
        result[inner].front_slot_id = result[outer].id
    result["P5"].is_active = False
    await db.commit()
    return result
