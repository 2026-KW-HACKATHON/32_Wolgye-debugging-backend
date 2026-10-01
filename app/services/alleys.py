from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alley import Alley
from app.schemas.alley import AlleyCreate
from app.services.exceptions import NotFoundError


async def list_alleys(db: AsyncSession) -> list[Alley]:
    result = await db.execute(select(Alley))
    return list(result.scalars().all())


async def create_alley(db: AsyncSession, payload: AlleyCreate) -> Alley:
    alley = Alley(**payload.model_dump())
    db.add(alley)
    await db.commit()
    await db.refresh(alley)
    return alley


async def get_alley(db: AsyncSession, alley_id: int) -> Alley:
    alley = await db.get(Alley, alley_id)
    if not alley:
        raise NotFoundError("Alley not found")
    return alley
