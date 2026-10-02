"""차고지 탐색 (명세 tag garages): GET /garages, GET /garages/{garage_id}

담당: 건우 #12. 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from fastapi import APIRouter

router = APIRouter(prefix="/garages", tags=["garages"])
