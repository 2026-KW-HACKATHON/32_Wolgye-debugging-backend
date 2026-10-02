"""내 차량·반복 출차 (명세 tag vehicles): /me/vehicles, /me/vehicles/{vehicle_id}, /me/vehicles/{vehicle_id}/recurring-schedule

담당: 현서 #7. 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.my_vehicle import (
    MyVehicleCreate,
    MyVehicleUpdate,
    RecurringSchedule,
    VehicleDetail,
    VehicleListItem,
    VehicleListResponse,
)
from app.services import departures as departure_service
from app.services import vehicles as vehicle_service

router = APIRouter(prefix="/me/vehicles", tags=["vehicles"])


@router.get("", response_model=VehicleListResponse, summary="차량 관리 목록")
async def list_my_vehicles(user: CurrentUser, db: DbSession) -> VehicleListResponse:
    return VehicleListResponse(items=await vehicle_service.list_my_vehicles(db, user))


@router.post("", response_model=VehicleListItem, status_code=status.HTTP_201_CREATED, summary="차량 등록")
async def create_my_vehicle(payload: MyVehicleCreate, user: CurrentUser, db: DbSession) -> VehicleListItem:
    return await vehicle_service.create_my_vehicle(db, user, payload)


@router.get("/{vehicle_id}", response_model=VehicleDetail, summary="차량 상세")
async def get_my_vehicle(vehicle_id: int, user: CurrentUser, db: DbSession) -> VehicleDetail:
    return await vehicle_service.get_my_vehicle(db, user, vehicle_id)


@router.patch("/{vehicle_id}", response_model=VehicleListItem, summary="차량 정보 수정")
async def update_my_vehicle(
    vehicle_id: int, payload: MyVehicleUpdate, user: CurrentUser, db: DbSession
) -> VehicleListItem:
    return await vehicle_service.update_my_vehicle(db, user, vehicle_id, payload)


@router.delete("/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT, summary="차량 삭제")
async def delete_my_vehicle(vehicle_id: int, user: CurrentUser, db: DbSession) -> Response:
    await vehicle_service.delete_my_vehicle(db, user, vehicle_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{vehicle_id}/recurring-schedule", response_model=RecurringSchedule, summary="반복 출차 일정 조회")
async def get_recurring_schedule(vehicle_id: int, user: CurrentUser, db: DbSession) -> RecurringSchedule:
    return await departure_service.get_recurring(db, user, vehicle_id)


@router.put("/{vehicle_id}/recurring-schedule", response_model=RecurringSchedule, summary="반복 출차 일정 설정")
async def put_recurring_schedule(
    vehicle_id: int, payload: RecurringSchedule, user: CurrentUser, db: DbSession
) -> RecurringSchedule:
    return await departure_service.put_recurring(db, user, vehicle_id, payload)


@router.delete(
    "/{vehicle_id}/recurring-schedule", status_code=status.HTTP_204_NO_CONTENT, summary="반복 출차 일정 해제"
)
async def delete_recurring_schedule(vehicle_id: int, user: CurrentUser, db: DbSession) -> Response:
    await departure_service.delete_recurring(db, user, vehicle_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
