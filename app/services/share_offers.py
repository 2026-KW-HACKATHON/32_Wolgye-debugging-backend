from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.share_offer import ShareOffer
from app.schemas.share_offer import ShareOfferCreate
from app.services.exceptions import NotFoundError


async def list_share_offers(
    db: AsyncSession, slot_id: int | None = None, public_only: bool = False
) -> list[ShareOffer]:
    stmt = select(ShareOffer)
    if slot_id is not None:
        stmt = stmt.where(ShareOffer.slot_id == slot_id)
    if public_only:
        stmt = stmt.where(ShareOffer.is_public)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_share_offer(db: AsyncSession, payload: ShareOfferCreate) -> ShareOffer:
    offer = ShareOffer(**payload.model_dump())
    db.add(offer)
    await db.commit()
    await db.refresh(offer)
    return offer


async def get_share_offer(db: AsyncSession, offer_id: int) -> ShareOffer:
    offer = await db.get(ShareOffer, offer_id)
    if not offer:
        raise NotFoundError("Share offer not found")
    return offer
