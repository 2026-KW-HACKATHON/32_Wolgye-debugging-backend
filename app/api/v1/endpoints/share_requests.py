from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import DbSession
from app.models.share_request import ShareRequest, ShareRequestStatus
from app.schemas.share_request import ShareRequestCreate, ShareRequestDecision, ShareRequestRead

router = APIRouter(prefix="/share-requests", tags=["share-requests"])


@router.get("", response_model=list[ShareRequestRead])
async def list_share_requests(db: DbSession, status: ShareRequestStatus | None = None):
    stmt = select(ShareRequest)
    if status is not None:
        stmt = stmt.where(ShareRequest.status == status)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("", response_model=ShareRequestRead, status_code=201)
async def create_share_request(db: DbSession, payload: ShareRequestCreate):
    """입주민이 옆 빌라 골목 공유 칸을 시간제로 요청 (화면 4 상단)."""
    share_request = ShareRequest(**payload.model_dump())
    db.add(share_request)
    await db.commit()
    await db.refresh(share_request)
    return share_request


@router.post("/{request_id}/decision", response_model=ShareRequestRead)
async def decide_share_request(db: DbSession, request_id: int, payload: ShareRequestDecision):
    """관리자가 수락/거절 (화면 4: 거절 / 수락 버튼)."""
    share_request = await db.get(ShareRequest, request_id)
    if not share_request:
        raise HTTPException(status_code=404, detail="Share request not found")
    if share_request.status != ShareRequestStatus.PENDING:
        raise HTTPException(status_code=409, detail="Already decided")

    share_request.status = payload.status
    share_request.reject_reason = payload.reject_reason
    share_request.responded_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(share_request)
    return share_request
