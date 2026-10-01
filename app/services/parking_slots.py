from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.garage import Garage
from app.models.parking_slot import ParkingSlot
from app.schemas.parking_slot import ParkingSlotCreate
from app.services.exceptions import NotFoundError


async def list_parking_slots(db: AsyncSession, building_id: int | None = None) -> list[ParkingSlot]:
    stmt = select(ParkingSlot)
    if building_id is not None:
        stmt = stmt.join(Garage).where(Garage.building_id == building_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_parking_slot(db: AsyncSession, payload: ParkingSlotCreate) -> ParkingSlot:
    slot = ParkingSlot(**payload.model_dump())
    db.add(slot)
    await db.commit()
    await db.refresh(slot)
    return slot


async def get_parking_slot(db: AsyncSession, slot_id: int) -> ParkingSlot:
    slot = await db.get(ParkingSlot, slot_id)
    if not slot:
        raise NotFoundError("Parking slot not found")
    return slot
