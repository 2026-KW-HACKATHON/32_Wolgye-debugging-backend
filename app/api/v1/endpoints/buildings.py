from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import DbSession
from app.models.building import Building
from app.schemas.building import BuildingCreate, BuildingRead

router = APIRouter(prefix="/buildings", tags=["buildings"])


@router.get("", response_model=list[BuildingRead])
async def list_buildings(db: DbSession):
    result = await db.execute(select(Building))
    return result.scalars().all()


@router.post("", response_model=BuildingRead, status_code=201)
async def create_building(db: DbSession, payload: BuildingCreate):
    building = Building(**payload.model_dump())
    db.add(building)
    await db.commit()
    await db.refresh(building)
    return building


@router.get("/{building_id}", response_model=BuildingRead)
async def get_building(db: DbSession, building_id: int):
    building = await db.get(Building, building_id)
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")
    return building
