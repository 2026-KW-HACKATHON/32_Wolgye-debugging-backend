"""홈 집계 (명세 tag home): GET /me/home

담당: 현서 #9. 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from fastapi import APIRouter

router = APIRouter(tags=["home"])
