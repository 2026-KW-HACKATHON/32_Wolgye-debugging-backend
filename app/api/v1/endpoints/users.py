"""내 정보 (명세 tag users): GET·PATCH /users/me

담당: 건우 #6. 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.user import ProfileUpdate, UserMe
from app.services import users as users_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserMe)
async def get_me(user: CurrentUser, db: DbSession):
    return await users_service.get_me(db, user)


@router.patch("/me", response_model=UserMe)
async def update_me(payload: ProfileUpdate, user: CurrentUser, db: DbSession):
    return await users_service.update_me(db, user, payload)
