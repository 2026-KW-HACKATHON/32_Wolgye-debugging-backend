"""인증 (명세 tag auth): POST /auth/signup, /auth/login, /auth/refresh, /auth/password-reset

담당: 건우 #6. 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["auth"])
