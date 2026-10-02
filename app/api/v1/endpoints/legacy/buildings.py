from fastapi import APIRouter

from app.api.deps import DbSession
from app.schemas.building import BuildingCreate, BuildingRead
from app.services import buildings as building_service

router = APIRouter(prefix="/buildings", tags=["buildings"])


@router.get("", response_model=list[BuildingRead])
async def list_buildings(db: DbSession):
    return await building_service.list_buildings(db)


@router.post("", response_model=BuildingRead, status_code=201)
async def create_building(db: DbSession, payload: BuildingCreate):
    return await building_service.create_building(db, payload)


@router.get("/{building_id}", response_model=BuildingRead)
async def get_building(db: DbSession, building_id: int):
    return await building_service.get_building(db, building_id)
