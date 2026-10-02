"""빌라 (명세 tag buildings): POST /buildings/join, GET /buildings/{building_id}/layout, /status, /slots/recommendations

담당: 건우 #6 (join), 현서 #9 (layout·status·slots/recommendations). 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from fastapi import APIRouter

router = APIRouter(prefix="/buildings", tags=["buildings"])
