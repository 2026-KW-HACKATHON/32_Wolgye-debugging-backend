from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.departure_schedule import DepartureSchedule
from app.schemas.departure_schedule import DepartureScheduleCreate
from app.services.exceptions import NotFoundError


async def list_departures(db: AsyncSession, vehicle_id: int | None = None) -> list[DepartureSchedule]:
    stmt = select(DepartureSchedule)
    if vehicle_id is not None:
        stmt = stmt.where(DepartureSchedule.vehicle_id == vehicle_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_departure(db: AsyncSession, payload: DepartureScheduleCreate) -> DepartureSchedule:
    schedule = DepartureSchedule(**payload.model_dump())
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)
    return schedule


async def get_departure(db: AsyncSession, schedule_id: int) -> DepartureSchedule:
    schedule = await db.get(DepartureSchedule, schedule_id)
    if not schedule:
        raise NotFoundError("Departure schedule not found")
    return schedule
