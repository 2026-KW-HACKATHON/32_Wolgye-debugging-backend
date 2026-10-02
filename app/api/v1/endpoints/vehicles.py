"""내 차량·반복 출차 (명세 tag vehicles): /me/vehicles, /me/vehicles/{vehicle_id}, /me/vehicles/{vehicle_id}/recurring-schedule

담당: 현서 #7. 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from fastapi import APIRouter

router = APIRouter(prefix="/me/vehicles", tags=["vehicles"])
