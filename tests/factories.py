"""테스트 데이터 생성 헬퍼. API 가 아직 없는 리소스(차고지·주민 등)는 세션으로 직접 넣는다."""

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alley import Alley
from app.models.building import Building
from app.models.garage import Garage, GarageType
from app.models.parking_slot import ParkingSlot
from app.models.resident import Resident, ResidentRole
from app.models.share_offer import ShareOffer
from app.models.share_request import ShareRequest, ShareRequestStatus
from app.models.vehicle import Vehicle


async def _save[T](db: AsyncSession, obj: T) -> T:
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


async def make_alley(db: AsyncSession, name: str = "광운로19가길") -> Alley:
    return await _save(db, Alley(name=name))


async def make_building(
    db: AsyncSession, invite_code: str = "INV001", name: str = "월계빌라", alley: Alley | None = None
) -> Building:
    alley = alley or await make_alley(db)
    return await _save(
        db, Building(alley_id=alley.id, name=name, address="서울 노원구 월계동 1", invite_code=invite_code)
    )


async def make_garage(db: AsyncSession, building: Building, name: str = "필로티 안쪽") -> Garage:
    return await _save(db, Garage(building_id=building.id, name=name, garage_type=GarageType.PILOTI_IN))


async def make_slot(db: AsyncSession, garage: Garage, number: int = 1) -> ParkingSlot:
    return await _save(db, ParkingSlot(garage_id=garage.id, number=number))


async def make_resident(
    db: AsyncSession,
    email: str = "a@example.com",
    building: Building | None = None,
    token_balance: int = 0,
    role: ResidentRole = ResidentRole.RESIDENT,
) -> Resident:
    return await _save(
        db,
        Resident(
            email=email,
            password_hash="x",
            nickname=email.split("@")[0],
            building_id=building.id if building else None,
            token_balance=token_balance,
            role=role,
        ),
    )


async def make_vehicle(db: AsyncSession, plate_no: str = "12가3456", owner: Resident | None = None) -> Vehicle:
    return await _save(db, Vehicle(plate_no=plate_no, owner_id=owner.id if owner else None))


async def make_share_offer(
    db: AsyncSession,
    slot: ParkingSlot,
    host: Resident,
    hourly_price: int = 0,
    start_date: date = date(2026, 10, 1),
    end_date: date = date(2026, 10, 31),
    available_weekdays: list[int] | None = None,
    start_hour: int = 6,
    end_hour: int = 22,
    max_hours: int | None = None,
    is_public: bool = True,
) -> ShareOffer:
    return await _save(
        db,
        ShareOffer(
            slot_id=slot.id,
            host_id=host.id,
            hourly_price=hourly_price,
            start_date=start_date,
            end_date=end_date,
            available_weekdays=available_weekdays if available_weekdays is not None else list(range(7)),
            start_hour=start_hour,
            end_hour=end_hour,
            max_hours=max_hours,
            is_public=is_public,
        ),
    )


async def make_share_request(
    db: AsyncSession,
    offer: ShareOffer,
    requester: Resident,
    status: ShareRequestStatus = ShareRequestStatus.PENDING,
    start_hour: int = 10,
    end_hour: int = 12,
) -> ShareRequest:
    return await _save(
        db,
        ShareRequest(
            offer_id=offer.id,
            slot_id=offer.slot_id,
            requester_id=requester.id,
            request_date=date(2026, 10, 2),
            start_hour=start_hour,
            end_hour=end_hour,
            total_price=(end_hour - start_hour) * offer.hourly_price,
            status=status,
        ),
    )
