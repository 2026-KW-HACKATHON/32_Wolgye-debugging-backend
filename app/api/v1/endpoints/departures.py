from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import DbSession
from app.models.departure_schedule import DepartureSchedule
from app.schemas.departure_schedule import DepartureScheduleCreate, DepartureScheduleRead

router = APIRouter(prefix="/departures", tags=["departures"])


@router.get("", response_model=list[DepartureScheduleRead])
async def list_departures(db: DbSession, vehicle_id: int | None = None):
    stmt = select(DepartureSchedule)
    if vehicle_id is not None:
        stmt = stmt.where(DepartureSchedule.vehicle_id == vehicle_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("", response_model=DepartureScheduleRead, status_code=201)
async def create_departure(db: DbSession, payload: DepartureScheduleCreate):
    """차 배치 화면(2)에서 '내일 몇 시에 나가요' 등록 시 호출."""
    schedule = DepartureSchedule(**payload.model_dump())
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)
    return schedule


@router.get("/{schedule_id}", response_model=DepartureScheduleRead)
async def get_departure(db: DbSession, schedule_id: int):
    schedule = await db.get(DepartureSchedule, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Departure schedule not found")
    return schedule
