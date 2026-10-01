from fastapi import APIRouter

from app.api.deps import DbSession
from app.schemas.vehicle import VehicleCreate, VehicleRead
from app.services import vehicles as vehicle_service

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


@router.get("", response_model=list[VehicleRead])
async def list_vehicles(db: DbSession):
    return await vehicle_service.list_vehicles(db)


@router.post("", response_model=VehicleRead, status_code=201)
async def create_vehicle(db: DbSession, payload: VehicleCreate):
    return await vehicle_service.create_vehicle(db, payload)


@router.get("/{vehicle_id}", response_model=VehicleRead)
async def get_vehicle(db: DbSession, vehicle_id: int):
    return await vehicle_service.get_vehicle(db, vehicle_id)
