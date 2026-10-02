"""내 정보 (명세 tag users): GET·PATCH /users/me

담당: 건우 #6. 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from fastapi import APIRouter

router = APIRouter(prefix="/users", tags=["users"])
