from fastapi import APIRouter

from app.api.deps import DbSession
from app.schemas.parking_slot import ParkingSlotCreate, ParkingSlotRead
from app.services import parking_slots as parking_slot_service

router = APIRouter(prefix="/parking-slots", tags=["parking-slots"])


@router.get("", response_model=list[ParkingSlotRead])
async def list_parking_slots(db: DbSession, building_id: int | None = None):
    return await parking_slot_service.list_parking_slots(db, building_id)


@router.post("", response_model=ParkingSlotRead, status_code=201)
async def create_parking_slot(db: DbSession, payload: ParkingSlotCreate):
    return await parking_slot_service.create_parking_slot(db, payload)


@router.get("/{slot_id}", response_model=ParkingSlotRead)
async def get_parking_slot(db: DbSession, slot_id: int):
    return await parking_slot_service.get_parking_slot(db, slot_id)
