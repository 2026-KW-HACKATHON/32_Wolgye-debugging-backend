"""주차 배치·출차 (명세 tag parkings): POST /parkings, PUT /parkings/{parking_id}/schedule, POST /parkings/{parking_id}/exit

담당: 현서 #8. 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from fastapi import APIRouter

router = APIRouter(prefix="/parkings", tags=["parkings"])
