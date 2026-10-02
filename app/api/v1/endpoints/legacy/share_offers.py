from fastapi import APIRouter

from app.api.deps import DbSession
from app.schemas.share_offer import ShareOfferCreate, ShareOfferRead
from app.services import share_offers as share_offer_service

router = APIRouter(prefix="/share-offers", tags=["share-offers"])


@router.get("", response_model=list[ShareOfferRead])
async def list_share_offers(db: DbSession, slot_id: int | None = None, public_only: bool = False):
    return await share_offer_service.list_share_offers(db, slot_id, public_only)


@router.post("", response_model=ShareOfferRead, status_code=201)
async def create_share_offer(db: DbSession, payload: ShareOfferCreate):
    """관리인이 칸을 기간·요일·시간·시간당 토큰으로 공유 (차고지 등록 n45)."""
    return await share_offer_service.create_share_offer(db, payload)


@router.get("/{offer_id}", response_model=ShareOfferRead)
async def get_share_offer(db: DbSession, offer_id: int):
    return await share_offer_service.get_share_offer(db, offer_id)
