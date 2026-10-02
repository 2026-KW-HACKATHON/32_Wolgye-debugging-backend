"""알림 (명세 tag notifications): GET /notifications, POST /notifications/{notification_id}/read, POST /notifications/read-all

담당: 건우 #11. 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from fastapi import APIRouter

router = APIRouter(prefix="/notifications", tags=["notifications"])
