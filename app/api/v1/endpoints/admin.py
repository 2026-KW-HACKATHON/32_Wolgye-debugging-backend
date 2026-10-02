"""관리인 대시보드·칸·미확인 차량 (명세 tag admin): GET /admin/buildings/{building_id}/dashboard, /slots, PATCH /admin/slots/{slot_id}, POST /admin/buildings/{building_id}/unknown-vehicles

담당: 건우 #14. 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from fastapi import APIRouter

router = APIRouter(prefix="/admin", tags=["admin"])
