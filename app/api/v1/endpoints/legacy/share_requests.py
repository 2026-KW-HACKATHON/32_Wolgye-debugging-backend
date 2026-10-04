from fastapi import APIRouter

from app.api.deps import DbSession
from app.models.share_request import ShareRequestStatus
from app.schemas.share_request import ShareRequestDecision, ShareRequestRead
from app.services import share_requests as share_request_service

router = APIRouter(prefix="/share-requests", tags=["share-requests"])
# POST /share-requests 는 새 API(endpoints/share_requests.py)로 옮겼다 (#12, 결정 27)


@router.get("", response_model=list[ShareRequestRead])
async def list_share_requests(db: DbSession, status: ShareRequestStatus | None = None):
    return await share_request_service.list_share_requests(db, status)


@router.post("/{request_id}/decision", response_model=ShareRequestRead)
async def decide_share_request(db: DbSession, request_id: int, payload: ShareRequestDecision):
    """관리자가 수락/거절 (화면 4: 거절 / 수락 버튼)."""
    return await share_request_service.decide(db, request_id, payload)
