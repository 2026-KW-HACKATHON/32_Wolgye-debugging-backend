"""이동 요청 (명세 tag move-requests): POST /move-requests, GET /move-requests/{move_request_id}, POST /move-requests/{move_request_id}/done, GET /me/move-requests

담당: 현서 #10. 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.move_request import (
    MoveRequestBox,
    MoveRequestCreate,
    MoveRequestCreated,
    MoveRequestDetail,
    MoveRequestDone,
    MoveRequestList,
)
from app.services import move_requests as move_request_service

router = APIRouter(tags=["move-requests"])


@router.post(
    "/move-requests", response_model=MoveRequestCreated, status_code=status.HTTP_201_CREATED, summary="이동 요청 보내기"
)
async def create_move_request(payload: MoveRequestCreate, user: CurrentUser, db: DbSession) -> MoveRequestCreated:
    return await move_request_service.create(db, user, payload)


@router.get("/move-requests/{move_request_id}", response_model=MoveRequestDetail, summary="이동 요청 수신 화면")
async def get_move_request(move_request_id: int, user: CurrentUser, db: DbSession) -> MoveRequestDetail:
    return await move_request_service.get_detail(db, user, move_request_id)


@router.post("/move-requests/{move_request_id}/done", response_model=MoveRequestDone, summary="옮겼어요")
async def done_move_request(move_request_id: int, user: CurrentUser, db: DbSession) -> MoveRequestDone:
    return await move_request_service.done(db, user, move_request_id)


@router.get("/me/move-requests", response_model=MoveRequestList, summary="내 이동 요청 목록")
async def list_my_move_requests(
    user: CurrentUser, db: DbSession, box: Annotated[MoveRequestBox, Query(description="받은 요청 / 보낸 요청")]
) -> MoveRequestList:
    return MoveRequestList(items=await move_request_service.list_mine(db, user, box))
