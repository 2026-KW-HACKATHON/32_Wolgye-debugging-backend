"""이동 요청 (명세 tag move-requests): POST /move-requests, GET /move-requests/{move_request_id}, POST /move-requests/{move_request_id}/done, GET /me/move-requests

담당: 현서 #10. 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from fastapi import APIRouter

router = APIRouter(tags=["move-requests"])
