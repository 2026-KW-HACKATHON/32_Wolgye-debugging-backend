from fastapi import APIRouter

from app.api.deps import DbSession
from app.schemas.alley import AlleyCreate, AlleyRead
from app.services import alleys as alley_service

router = APIRouter(prefix="/alleys", tags=["alleys"])


@router.get("", response_model=list[AlleyRead])
async def list_alleys(db: DbSession):
    return await alley_service.list_alleys(db)


@router.post("", response_model=AlleyRead, status_code=201)
async def create_alley(db: DbSession, payload: AlleyCreate):
    return await alley_service.create_alley(db, payload)


@router.get("/{alley_id}", response_model=AlleyRead)
async def get_alley(db: DbSession, alley_id: int):
    return await alley_service.get_alley(db, alley_id)
