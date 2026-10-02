"""관리인 대시보드·칸·미확인 차량 (명세 tag admin): GET /admin/buildings/{building_id}/dashboard, /slots, PATCH /admin/slots/{slot_id}, POST /admin/buildings/{building_id}/unknown-vehicles

담당: 건우 #14. 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import BuildingAdmin, CurrentUser, DbSession
from app.schemas.admin import (
    AdminDashboard,
    AdminSlot,
    AdminSlotList,
    AdminSlotUpdate,
    UnknownVehicleCreate,
    UnknownVehicleCreated,
)
from app.services import admin as admin_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/buildings/{building_id}/dashboard", response_model=AdminDashboard)
async def get_dashboard(
    building_id: int,
    user: BuildingAdmin,
    db: DbSession,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$", examples=["2026-09"])] = None,
) -> AdminDashboard:
    return await admin_service.get_dashboard(db, building_id, month)


@router.get("/buildings/{building_id}/slots", response_model=AdminSlotList)
async def list_slots(building_id: int, user: BuildingAdmin, db: DbSession) -> AdminSlotList:
    return AdminSlotList(items=await admin_service.list_slots(db, building_id))


@router.patch("/slots/{slot_id}", response_model=AdminSlot)
async def update_slot(slot_id: int, payload: AdminSlotUpdate, user: CurrentUser, db: DbSession) -> AdminSlot:
    return await admin_service.update_slot(db, user, slot_id, payload)


@router.post(
    "/buildings/{building_id}/unknown-vehicles",
    response_model=UnknownVehicleCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_unknown_vehicle(
    building_id: int, payload: UnknownVehicleCreate, user: BuildingAdmin, db: DbSession
) -> UnknownVehicleCreated:
    return await admin_service.register_unknown_vehicle(db, building_id, payload)
