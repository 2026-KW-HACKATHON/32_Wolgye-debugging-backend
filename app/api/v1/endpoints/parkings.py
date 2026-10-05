"""주차 배치·출차 (명세 tag parkings): POST /parkings, PUT /parkings/{parking_id}/schedule, POST /parkings/{parking_id}/exit

담당: 현서 #8. 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.parking import ParkingCreate, ParkingCreated, ParkingExited, ParkingSchedule, ParkingScheduleUpdate
from app.services import parkings as parking_service

router = APIRouter(prefix="/parkings", tags=["parkings"])


@router.post("", response_model=ParkingCreated, status_code=status.HTTP_201_CREATED, summary="여기에 배치하기")
async def create_parking(payload: ParkingCreate, user: CurrentUser, db: DbSession) -> ParkingCreated:
    return await parking_service.create_parking(db, user, payload)


@router.put("/{parking_id}/schedule", response_model=ParkingSchedule, summary="출차 일정 수정")
async def update_parking_schedule(
    parking_id: int, payload: ParkingScheduleUpdate, user: CurrentUser, db: DbSession
) -> ParkingSchedule:
    return await parking_service.update_schedule(db, user, parking_id, payload)


@router.post("/{parking_id}/exit", response_model=ParkingExited, summary="출차 처리")
async def exit_parking(parking_id: int, user: CurrentUser, db: DbSession) -> ParkingExited:
    return await parking_service.exit_parking(db, user, parking_id)
