from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import DbSession
from app.models.vehicle import Vehicle
from app.schemas.vehicle import VehicleCreate, VehicleRead

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


@router.get("", response_model=list[VehicleRead])
async def list_vehicles(db: DbSession):
    result = await db.execute(select(Vehicle))
    return result.scalars().all()


@router.post("", response_model=VehicleRead, status_code=201)
async def create_vehicle(db: DbSession, payload: VehicleCreate):
    vehicle = Vehicle(**payload.model_dump())
    db.add(vehicle)
    await db.commit()
    await db.refresh(vehicle)
    return vehicle


@router.get("/{vehicle_id}", response_model=VehicleRead)
async def get_vehicle(db: DbSession, vehicle_id: int):
    vehicle = await db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return vehicle
