"""#12(차고지 탐색·공유 요청) 테스트용 추가 팩토리. 공용 tests/factories.py 를 건드리지 않으려고 따로 둔다."""

from dataclasses import dataclass
from datetime import date, datetime, time

from geoalchemy2.elements import WKTElement
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alley import Alley
from app.models.building import Building
from app.models.departure_schedule import DepartureSchedule
from app.models.garage import Garage
from app.models.parking_assignment import ParkingAssignment
from app.models.parking_slot import ParkingSlot
from app.models.resident import Resident, ResidentRole
from app.models.share_offer import ShareOffer
from app.models.share_request import ShareRequest, ShareRequestStatus
from app.models.vehicle import Vehicle
from tests.factories import (
    make_alley,
    make_building,
    make_garage,
    make_resident,
    make_share_offer,
    make_slot,
    make_vehicle,
)


async def _save[T](db: AsyncSession, obj: T) -> T:
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


async def set_location(db: AsyncSession, building: Building, lat: float, lng: float) -> Building:
    building.location = WKTElement(f"POINT({lng} {lat})", srid=4326)
    return await _save(db, building)


async def park(db: AsyncSession, slot: ParkingSlot, vehicle: Vehicle, is_permanent: bool = False) -> ParkingAssignment:
    return await _save(db, ParkingAssignment(slot_id=slot.id, vehicle_id=vehicle.id, is_permanent=is_permanent))


async def make_departure(
    db: AsyncSession,
    vehicle: Vehicle,
    day: date,
    at: time,
    repeat_weekdays: list[int] | None = None,
    is_ai_estimated: bool = False,
    created_at: datetime | None = None,
) -> DepartureSchedule:
    row = DepartureSchedule(
        vehicle_id=vehicle.id,
        scheduled_date=day,
        scheduled_time=at,
        repeat_weekdays=repeat_weekdays or [],
        is_ai_estimated=is_ai_estimated,
    )
    if created_at is not None:
        row.created_at = created_at
    return await _save(db, row)


async def make_request_on(
    db: AsyncSession,
    offer: ShareOffer,
    requester_id: int,
    day: date,
    start_hour: int,
    end_hour: int,
    status: ShareRequestStatus = ShareRequestStatus.ACCEPTED,
    vehicle: Vehicle | None = None,
) -> ShareRequest:
    return await _save(
        db,
        ShareRequest(
            offer_id=offer.id,
            slot_id=offer.slot_id,
            requester_id=requester_id,
            vehicle_id=vehicle.id if vehicle else None,
            request_date=day,
            start_hour=start_hour,
            end_hour=end_hour,
            total_price=(end_hour - start_hour) * offer.hourly_price,
            status=status,
        ),
    )


@dataclass
class ShareScenario:
    """같은 골목에 내 빌라(mine)와 옆 빌라(next_door), 다른 골목에 먼 빌라(far).

    옆 빌라: 주차 구역 2개(zone_a: 칸 1·2 = P1·P2, zone_b: 칸 1 = P3). P2·P3 에 공유 조건(관리인 host)이 걸려 있다.
    공유 조건 기본값: 2026-10-01 ~ 9999-12-31, 매일 06~22시, 시간당 2토큰, 최대 4시간.
    """

    alley: Alley
    mine: Building
    next_door: Building
    far: Building
    me: Resident
    my_vehicle: Vehicle
    host: Resident
    neighbor: Resident  # 옆 빌라 입주민
    zone_a: Garage
    zone_b: Garage
    p1: ParkingSlot
    p2: ParkingSlot
    p3: ParkingSlot
    offer_p2: ShareOffer
    offer_p3: ShareOffer


async def make_scenario(db: AsyncSession, my_tokens: int = 100) -> ShareScenario:
    alley = await make_alley(db)
    mine = await make_building(db, "MINE01", "우리빌라", alley)
    next_door = await make_building(db, "NEXT01", "햇살빌라", alley)
    far = await make_building(db, "FAR001", "먼빌라", await make_alley(db, "다른골목"))
    me = await make_resident(db, "me@example.com", mine, token_balance=my_tokens)
    host = await make_resident(db, "host@example.com", next_door, role=ResidentRole.MANAGER)
    neighbor = await make_resident(db, "neighbor@example.com", next_door)
    zone_a = await make_garage(db, next_door, "골목")
    zone_b = await make_garage(db, next_door, "건물 앞")
    zone_a.sort_order, zone_b.sort_order = 1, 2
    await db.commit()
    p1, p2 = await make_slot(db, zone_a, 1), await make_slot(db, zone_a, 2)
    p3 = await make_slot(db, zone_b, 1)
    offers = [
        await make_share_offer(
            db, slot, host, hourly_price=2, end_date=date(9999, 12, 31), start_hour=6, end_hour=22, max_hours=4
        )
        for slot in (p2, p3)
    ]
    return ShareScenario(
        alley=alley,
        mine=mine,
        next_door=next_door,
        far=far,
        me=me,
        my_vehicle=await make_vehicle(db, "12가3456", me),
        host=host,
        neighbor=neighbor,
        zone_a=zone_a,
        zone_b=zone_b,
        p1=p1,
        p2=p2,
        p3=p3,
        offer_p2=offers[0],
        offer_p3=offers[1],
    )
