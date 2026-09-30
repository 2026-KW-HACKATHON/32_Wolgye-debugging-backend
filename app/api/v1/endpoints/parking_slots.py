from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import DbSession
from app.models.parking_slot import ParkingSlot
from app.models.parking_zone import ParkingZone
from app.schemas.parking_slot import ParkingSlotCreate, ParkingSlotRead

router = APIRouter(prefix="/parking-slots", tags=["parking-slots"])


@router.get("", response_model=list[ParkingSlotRead])
async def list_parking_slots(db: DbSession, building_id: int | None = None):
    stmt = select(ParkingSlot)
    if building_id is not None:
        stmt = stmt.join(ParkingZone).where(ParkingZone.building_id == building_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("", response_model=ParkingSlotRead, status_code=201)
async def create_parking_slot(db: DbSession, payload: ParkingSlotCreate):
    slot = ParkingSlot(**payload.model_dump())
    db.add(slot)
    await db.commit()
    await db.refresh(slot)
    return slot


@router.get("/{slot_id}", response_model=ParkingSlotRead)
async def get_parking_slot(db: DbSession, slot_id: int):
    slot = await db.get(ParkingSlot, slot_id)
    if not slot:
        raise HTTPException(status_code=404, detail="Parking slot not found")
    return slot
