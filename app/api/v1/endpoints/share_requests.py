"""공유 요청 (명세 tag share-requests): POST /share-requests, GET /share-requests/{share_request_id}, GET /me/share-requests

담당: 건우 #12. 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, CursorParam, DbSession, LimitParam
from app.schemas.common import Page
from app.schemas.share_request_api import ShareRequestCreate, ShareRequestCreated, ShareRequestDetail
from app.services import share_requests as share_request_service
from app.services.pagination import DEFAULT_LIMIT

router = APIRouter(tags=["share-requests"])


@router.post(
    "/share-requests", response_model=ShareRequestCreated, status_code=status.HTTP_201_CREATED, summary="공유 요청하기"
)
async def create_share_request(payload: ShareRequestCreate, user: CurrentUser, db: DbSession) -> ShareRequestCreated:
    created = await share_request_service.create_for_user(db, user, **payload.model_dump())
    return ShareRequestCreated.from_model(created)


@router.get("/share-requests/{share_request_id}", response_model=ShareRequestDetail, summary="공유 요청 상세")
async def get_share_request(share_request_id: int, user: CurrentUser, db: DbSession) -> ShareRequestDetail:
    return ShareRequestDetail.from_view(await share_request_service.get_mine(db, user, share_request_id))


@router.get("/me/share-requests", response_model=Page[ShareRequestDetail], summary="내 공유 요청 목록")
async def list_my_share_requests(
    user: CurrentUser, db: DbSession, cursor: CursorParam = None, limit: LimitParam = DEFAULT_LIMIT
) -> Page[ShareRequestDetail]:
    page = await share_request_service.list_mine(db, user, cursor, limit)
    return Page(items=[ShareRequestDetail.from_view(r) for r in page.items], next_cursor=page.next_cursor)
