from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle
from app.schemas.vehicle import VehicleCreate
from app.services.exceptions import NotFoundError


async def list_vehicles(db: AsyncSession) -> list[Vehicle]:
    result = await db.execute(select(Vehicle))
    return list(result.scalars().all())


async def create_vehicle(db: AsyncSession, payload: VehicleCreate) -> Vehicle:
    vehicle = Vehicle(**payload.model_dump())
    db.add(vehicle)
    await db.commit()
    await db.refresh(vehicle)
    return vehicle


async def get_vehicle(db: AsyncSession, vehicle_id: int) -> Vehicle:
    vehicle = await db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise NotFoundError("Vehicle not found")
    return vehicle
