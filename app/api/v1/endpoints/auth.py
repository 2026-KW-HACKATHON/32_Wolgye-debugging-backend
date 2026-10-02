"""인증 (명세 tag auth): POST /auth/signup, /auth/login, /auth/refresh, /auth/password-reset

담당: 건우 #6. 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from fastapi import APIRouter, Response, status

from app.api.deps import DbSession
from app.schemas.auth import AuthTokens, LoginRequest, PasswordResetRequest, RefreshRequest, SignupRequest, TokenPair
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=AuthTokens, status_code=status.HTTP_201_CREATED)
async def signup(payload: SignupRequest, db: DbSession):
    return await auth_service.signup(db, payload)


@router.post("/login", response_model=AuthTokens)
async def login(payload: LoginRequest, db: DbSession):
    return await auth_service.login(db, payload)


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest, db: DbSession):
    return await auth_service.refresh(db, payload.refresh_token)


@router.post("/password-reset", status_code=status.HTTP_202_ACCEPTED, response_class=Response)
async def password_reset(payload: PasswordResetRequest):
    """가입 여부와 관계없이 항상 202, 아무 동작도 하지 않는다 (결정 4)."""
    return Response(status_code=status.HTTP_202_ACCEPTED)
