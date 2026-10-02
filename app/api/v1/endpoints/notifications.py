"""알림 (명세 tag notifications): GET /notifications, POST /notifications/{notification_id}/read, POST /notifications/read-all

담당: 건우 #11. 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, CursorParam, DbSession, LimitParam
from app.schemas.common import Page
from app.schemas.notification import NotificationItem
from app.services import notifications as notification_service
from app.services.pagination import DEFAULT_LIMIT

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=Page[NotificationItem], summary="알림 목록")
async def list_notifications(
    user: CurrentUser, db: DbSession, cursor: CursorParam = None, limit: LimitParam = DEFAULT_LIMIT
) -> Page[NotificationItem]:
    page = await notification_service.list_for(db, user, cursor, limit)
    return Page(items=[NotificationItem.from_model(n) for n in page.items], next_cursor=page.next_cursor)


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT, summary="전체 읽음 처리")
async def read_all_notifications(user: CurrentUser, db: DbSession) -> Response:
    await notification_service.mark_all_read(db, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT, summary="알림 읽음 처리")
async def read_notification(notification_id: int, user: CurrentUser, db: DbSession) -> Response:
    await notification_service.mark_read(db, user, notification_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
