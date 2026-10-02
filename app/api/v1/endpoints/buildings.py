"""빌라 (명세 tag buildings): POST /buildings/join, GET /buildings/{building_id}/layout, /status, /slots/recommendations

담당: 건우 #6 (join), 현서 #9 (layout·status·slots/recommendations). 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.user import JoinBuildingRequest, JoinBuildingResult
from app.services import users as users_service

router = APIRouter(prefix="/buildings", tags=["buildings"])


@router.post("/join", response_model=JoinBuildingResult)
async def join_building(payload: JoinBuildingRequest, user: CurrentUser, db: DbSession):
    return await users_service.join_building(db, user, payload.invite_code)
