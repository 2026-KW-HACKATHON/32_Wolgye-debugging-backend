"""미등록 차량 제보 (명세 tag vehicle-reports, #52): POST /buildings/{building_id}/vehicle-reports,
GET /vehicle-reports/{report_id}, GET /vehicle-reports/{report_id}/photo, GET /admin/buildings/{building_id}/vehicle-reports"""

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import BuildingAdmin, BuildingMember, CurrentUser, CursorParam, DbSession, LimitParam
from app.core.config import get_settings
from app.schemas.common import Page
from app.schemas.vehicle_report import VehicleReportCreated, VehicleReportDetail
from app.services import report_photos
from app.services import vehicle_reports as report_service
from app.services.pagination import DEFAULT_LIMIT

router = APIRouter(tags=["vehicle-reports"])


@router.post(
    "/buildings/{building_id}/vehicle-reports",
    response_model=VehicleReportCreated,
    status_code=status.HTTP_201_CREATED,
    summary="미등록 차량 사진 제보",
)
async def create_vehicle_report(
    building_id: int,
    user: BuildingMember,
    db: DbSession,
    photo: Annotated[UploadFile, File(description="차량 사진 (JPEG·PNG, 10MB 이하)")],
    plate: Annotated[str, Form(description="차량 번호. 공백 유무 모두 허용")],
    slot_id: Annotated[int, Form()],
) -> VehicleReportCreated:
    # 한도보다 1바이트 더 읽어 둔다. 넘치면 report_photos.process 가 400 (큰 파일을 끝까지 메모리에 올리지 않게)
    data = await photo.read(get_settings().report_photo_max_bytes + 1)
    return await report_service.create(db, user, building_id, data, plate, slot_id)


@router.get("/vehicle-reports/{report_id}", response_model=VehicleReportDetail, summary="제보 상세")
async def get_vehicle_report(report_id: int, user: CurrentUser, db: DbSession) -> VehicleReportDetail:
    return await report_service.get_detail(db, user, report_id)


@router.get(
    "/vehicle-reports/{report_id}/photo",
    response_class=FileResponse,
    summary="제보 사진",
    responses={200: {"content": {report_photos.MEDIA_TYPE: {}}}},
)
async def get_vehicle_report_photo(report_id: int, user: CurrentUser, db: DbSession) -> FileResponse:
    path = await report_service.photo_path(db, user, report_id)
    # 번호판이 찍힌 개인정보라 공유 캐시에 남기지 않는다
    return FileResponse(path, media_type=report_photos.MEDIA_TYPE, headers={"Cache-Control": "private, max-age=3600"})


@router.get(
    "/admin/buildings/{building_id}/vehicle-reports", response_model=Page[VehicleReportDetail], summary="제보 목록"
)
async def list_vehicle_reports(
    building_id: int, user: BuildingAdmin, db: DbSession, cursor: CursorParam = None, limit: LimitParam = DEFAULT_LIMIT
) -> Page[VehicleReportDetail]:
    page = await report_service.list_for_building(db, building_id, cursor, limit)
    return Page(items=page.items, next_cursor=page.next_cursor)
