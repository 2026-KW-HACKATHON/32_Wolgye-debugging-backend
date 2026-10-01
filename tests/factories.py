"""테스트 데이터 생성 헬퍼. API 가 아직 없는 리소스(구역·주민 등)는 세션으로 직접 넣는다."""

from datetime import date, time

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.building import Building
from app.models.parking_slot import ParkingSlot
from app.models.parking_zone import ParkingZone, ZoneType
from app.models.resident import Resident
from app.models.share_request import ShareRequest, ShareRequestStatus
from app.models.vehicle import Vehicle


async def _save[T](db: AsyncSession, obj: T) -> T:
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


async def make_building(db: AsyncSession, invite_code: str = "INV001", name: str = "월계빌라") -> Building:
    return await _save(db, Building(name=name, address="서울 노원구 월계동 1", invite_code=invite_code))


async def make_zone(db: AsyncSession, building: Building, name: str = "필로티 안쪽") -> ParkingZone:
    return await _save(db, ParkingZone(building_id=building.id, name=name, zone_type=ZoneType.PILOTI_IN))


async def make_slot(db: AsyncSession, zone: ParkingZone, number: int = 1, is_shareable: bool = False) -> ParkingSlot:
    return await _save(db, ParkingSlot(zone_id=zone.id, number=number, is_shareable=is_shareable))


async def make_resident(db: AsyncSession, email: str = "a@example.com", building: Building | None = None) -> Resident:
    return await _save(
        db,
        Resident(
            email=email,
            password_hash="x",
            nickname=email.split("@")[0],
            building_id=building.id if building else None,
        ),
    )


async def make_vehicle(db: AsyncSession, plate_no: str = "12가3456", owner: Resident | None = None) -> Vehicle:
    return await _save(db, Vehicle(plate_no=plate_no, owner_id=owner.id if owner else None))


async def make_share_request(
    db: AsyncSession,
    slot: ParkingSlot,
    requester: Resident,
    status: ShareRequestStatus = ShareRequestStatus.PENDING,
    start: time = time(10),
    end: time = time(12),
) -> ShareRequest:
    return await _save(
        db,
        ShareRequest(
            slot_id=slot.id,
            requester_id=requester.id,
            request_date=date(2026, 10, 2),
            start_time=start,
            end_time=end,
            status=status,
        ),
    )
