"""공유 요청 (명세 tag share-requests): POST /share-requests, GET /share-requests/{share_request_id}, GET /me/share-requests

담당: 건우 #12. 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from fastapi import APIRouter

router = APIRouter(tags=["share-requests"])
