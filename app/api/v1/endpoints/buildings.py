"""빌라 (명세 tag buildings): POST /buildings/join, GET /buildings/{building_id}/layout, /status, /slots/recommendations

담당: 건우 #6 (join), 현서 #9 (layout·status·slots/recommendations). 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import BuildingMember, CurrentUser, DbSession
from app.schemas.building_view import BuildingLayout, BuildingStatus, SlotRecommendations
from app.schemas.parking import ExitAt
from app.schemas.user import JoinBuildingRequest, JoinBuildingResult
from app.services import building_view as building_view_service
from app.services import recommendations as recommendation_service
from app.services import users as users_service

router = APIRouter(prefix="/buildings", tags=["buildings"])


@router.post("/join", response_model=JoinBuildingResult)
async def join_building(payload: JoinBuildingRequest, user: CurrentUser, db: DbSession):
    return await users_service.join_building(db, user, payload.invite_code)


@router.get("/{building_id}/layout", response_model=BuildingLayout, summary="배치도")
async def get_layout(building_id: int, user: BuildingMember, db: DbSession) -> BuildingLayout:
    return await building_view_service.get_layout(db, building_id)


@router.get("/{building_id}/status", response_model=BuildingStatus, summary="실시간 현황")
async def get_status(building_id: int, user: BuildingMember, db: DbSession) -> BuildingStatus:
    return await building_view_service.get_status(db, user, building_id)


@router.get(
    "/{building_id}/slots/recommendations",
    response_model=SlotRecommendations,
    response_model_exclude_none=True,  # 태그에 해당하는 필드만 내려준다 (reason / will_block / unavailable_reason)
    summary="배치 등록 화면 태그·추천",
)
async def get_slot_recommendations(
    building_id: int,
    user: BuildingMember,
    db: DbSession,
    vehicle_id: Annotated[int, Query()],
    expected_exit_at: Annotated[ExitAt | None, Query(description="상시 주차면 생략")] = None,
) -> SlotRecommendations:
    return await recommendation_service.recommend(db, user, building_id, vehicle_id, expected_exit_at)
