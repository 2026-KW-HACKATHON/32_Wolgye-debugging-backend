from fastapi import APIRouter

from app.api.deps import DbSession
from app.schemas.departure_schedule import DepartureScheduleCreate, DepartureScheduleRead
from app.services import departures as departure_service

router = APIRouter(prefix="/departures", tags=["departures"])


@router.get("", response_model=list[DepartureScheduleRead])
async def list_departures(db: DbSession, vehicle_id: int | None = None):
    return await departure_service.list_departures(db, vehicle_id)


@router.post("", response_model=DepartureScheduleRead, status_code=201)
async def create_departure(db: DbSession, payload: DepartureScheduleCreate):
    """차 배치 화면(2)에서 '내일 몇 시에 나가요' 등록 시 호출."""
    return await departure_service.create_departure(db, payload)


@router.get("/{schedule_id}", response_model=DepartureScheduleRead)
async def get_departure(db: DbSession, schedule_id: int):
    return await departure_service.get_departure(db, schedule_id)
