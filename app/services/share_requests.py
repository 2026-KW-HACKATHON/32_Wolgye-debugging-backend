from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import ErrorCode
from app.models.resident import Resident
from app.models.share_offer import ShareOffer
from app.models.share_request import ShareRequest, ShareRequestStatus
from app.schemas.share_request import ShareRequestCreate, ShareRequestDecision
from app.services import tokens
from app.services.exceptions import ConflictError, NotFoundError


async def list_share_requests(db: AsyncSession, status: ShareRequestStatus | None = None) -> list[ShareRequest]:
    stmt = select(ShareRequest)
    if status is not None:
        stmt = stmt.where(ShareRequest.status == status)
    result = await db.execute(stmt)
    return list(result.scalars().all())


def _check_within_offer(offer: ShareOffer, payload: ShareRequestCreate) -> None:
    """요청이 공유 조건(공개·기간·요일·시간·최대 시간) 안에 있는지."""
    if not offer.is_public:
        raise ConflictError("Share offer is not public")
    day = payload.request_date
    if not (offer.start_date <= day <= offer.end_date) or day.weekday() not in offer.available_weekdays:
        raise ConflictError("Requested date is outside the share offer")
    if payload.start_hour < offer.start_hour or payload.end_hour > offer.end_hour:
        raise ConflictError("Requested hours are outside the share offer")
    if offer.max_hours is not None and payload.end_hour - payload.start_hour > offer.max_hours:
        raise ConflictError("Requested hours exceed max_hours")


async def create_share_request(db: AsyncSession, payload: ShareRequestCreate) -> ShareRequest:
    offer = await db.get(ShareOffer, payload.offer_id)
    if not offer:
        raise NotFoundError("Share offer not found")
    _check_within_offer(offer, payload)
    if payload.requester_id == offer.host_id:
        raise ConflictError("Cannot request own share offer")

    total_price = (payload.end_hour - payload.start_hour) * offer.hourly_price
    # 요청 단계에서 미리 알려준다. 실제 차감은 수락할 때 (그 사이 잔액이 바뀔 수 있음).
    requester = await db.get(Resident, payload.requester_id)
    if requester is not None and requester.token_balance < total_price:
        raise ConflictError("Not enough tokens", code=ErrorCode.INSUFFICIENT_TOKENS)

    share_request = ShareRequest(**payload.model_dump(), slot_id=offer.slot_id, total_price=total_price)
    db.add(share_request)
    await db.commit()
    await db.refresh(share_request)
    return share_request


async def get_share_request(db: AsyncSession, request_id: int) -> ShareRequest:
    share_request = await db.get(ShareRequest, request_id)
    if not share_request:
        raise NotFoundError("Share request not found")
    return share_request


async def decide(db: AsyncSession, request_id: int, payload: ShareRequestDecision) -> ShareRequest:
    """PENDING 인 요청만 수락/거절할 수 있다. 수락하면 요청자의 토큰을 offer.host 에게 넘긴다."""
    # 같은 요청을 동시에 수락해 토큰이 두 번 빠지지 않도록 행을 잠근다
    share_request = await db.scalar(
        select(ShareRequest).where(ShareRequest.id == request_id).with_for_update()
    )
    if not share_request:
        raise NotFoundError("Share request not found")
    if share_request.status != ShareRequestStatus.PENDING:
        raise ConflictError("Already decided", code=ErrorCode.ALREADY_DECIDED)

    share_request.status = payload.status
    share_request.reject_reason = payload.reject_reason
    share_request.responded_at = datetime.now(UTC)

    if payload.status == ShareRequestStatus.ACCEPTED and share_request.total_price > 0:
        await db.flush()  # 시간 겹침(EXCLUDE)을 토큰 이동보다 먼저 확인
        offer = await db.get(ShareOffer, share_request.offer_id)
        await tokens.transfer(
            db,
            sender_id=share_request.requester_id,
            receiver_id=offer.host_id,
            amount=share_request.total_price,
            share_request_id=share_request.id,
        )

    await db.commit()
    await db.refresh(share_request)
    return share_request


async def accepted_share_at(db: AsyncSession, slot_id: int, at: datetime) -> ShareRequest | None:
    """at 시각(timezone-aware)에 slot_id 칸에서 진행 중인 **수락된** 공유 요청. 없으면 None.

    공유 시간은 Asia/Seoul 기준 `request_date + start_hour` 이상 ~ `request_date + end_hour` 미만으로 본다
    (end_hour = 24 는 다음 날 0시). 같은 칸에 수락된 요청끼리는 시간이 겹치지 않으므로(EXCLUDE 제약) 최대 하나다.

    현서 #8(주차 등록 시 공유 이용 칸 확인)이 호출한다. commit 하지 않는다.

    TODO(#12): 건우가 구현한다.
    """
    raise NotImplementedError("#12 에서 구현")
