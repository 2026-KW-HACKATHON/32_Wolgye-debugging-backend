"""홈 집계 (명세 tag home): GET /me/home

담당: 현서 #9. 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.building_view import Home
from app.services import home as home_service

router = APIRouter(tags=["home"])


@router.get("/me/home", response_model=Home, summary="홈 화면 한 번에 조회")
async def get_home(user: CurrentUser, db: DbSession) -> Home:
    return await home_service.get_home(db, user)
