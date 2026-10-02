"""관리인 공유 조건·공유 요청 (명세 tag admin): /admin/buildings/{building_id}/share-offers, /admin/share-offers/{offer_id}, /admin/buildings/{building_id}/share-requests, PATCH /admin/share-requests/{share_request_id}

담당: 건우 #13. 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from fastapi import APIRouter

router = APIRouter(prefix="/admin", tags=["admin"])
