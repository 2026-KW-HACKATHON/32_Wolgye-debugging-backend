from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.share_request import ShareRequest, ShareRequestStatus
from app.schemas.share_request import ShareRequestCreate, ShareRequestDecision
from app.services.exceptions import ConflictError, NotFoundError


async def list_share_requests(db: AsyncSession, status: ShareRequestStatus | None = None) -> list[ShareRequest]:
    stmt = select(ShareRequest)
    if status is not None:
        stmt = stmt.where(ShareRequest.status == status)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_share_request(db: AsyncSession, payload: ShareRequestCreate) -> ShareRequest:
    share_request = ShareRequest(**payload.model_dump())
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
    """PENDING 인 요청만 수락/거절할 수 있다."""
    share_request = await get_share_request(db, request_id)
    if share_request.status != ShareRequestStatus.PENDING:
        raise ConflictError("Already decided")

    share_request.status = payload.status
    share_request.reject_reason = payload.reject_reason
    share_request.responded_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(share_request)
    return share_request
