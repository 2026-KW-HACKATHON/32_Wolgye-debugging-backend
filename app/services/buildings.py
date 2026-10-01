from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.building import Building
from app.schemas.building import BuildingCreate
from app.services.exceptions import NotFoundError


async def list_buildings(db: AsyncSession) -> list[Building]:
    result = await db.execute(select(Building))
    return list(result.scalars().all())


async def create_building(db: AsyncSession, payload: BuildingCreate) -> Building:
    building = Building(**payload.model_dump())
    db.add(building)
    await db.commit()
    await db.refresh(building)
    return building


async def get_building(db: AsyncSession, building_id: int) -> Building:
    building = await db.get(Building, building_id)
    if not building:
        raise NotFoundError("Building not found")
    return building
