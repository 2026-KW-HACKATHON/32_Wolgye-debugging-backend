"""미등록 차량 사진 제보 (#52).

제보 한 번 = 미확인 차량 배치 + 제보 저장 + 관리인 알림(VEHICLE_REPORT) + 제보자 보상 토큰. 한 트랜잭션이고,
사진 파일은 commit 직전에 저장해 실패하면 지운다. 사진 처리는 app/services/report_photos.py.

정책 (#52 질문 → 임시 결정, 설정으로 바꿀 수 있다)
- 하루(KST) 제보 횟수 REPORT_DAILY_LIMIT(3) 을 넘으면 제보 자체를 막는다 → 409 REPORT_LIMIT_EXCEEDED
- 관리인도 제보·보상할 수 있다. 제보자 본인에게는 알림을 보내지 않는다
- 제보 상세·사진은 제보자 본인과 그 빌라 관리인만 본다. 그 밖에는 있는지도 알리지 않게 404
"""

import asyncio
from datetime import datetime, time
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.error_codes import ErrorCode
from app.core.plates import format_plate, is_valid_plate, normalize_plate
from app.models.notification import NotificationType
from app.models.resident import Resident, ResidentRole
from app.models.vehicle_report import VehicleReport
from app.schemas.admin import OccupantType
from app.schemas.common import KST
from app.schemas.vehicle_report import VehicleReportCreated, VehicleReportDetail, VehicleReportReporter
from app.services import admin, notifications, report_photos, tokens
from app.services.exceptions import ConflictError, InvalidInputError, NotFoundError
from app.services.pagination import DEFAULT_LIMIT, CursorPage, paginate
from app.services.slot_labels import slot_label, slot_labels

REWARD_MEMO = "미등록 차량 제보 보상"
NOTIFICATION_TITLE = "미등록 차량 제보"


def photo_url(report_id: int) -> str:
    return f"/vehicle-reports/{report_id}/photo"


async def _ensure_under_daily_limit(db: AsyncSession, user: Resident, now: datetime) -> None:
    """제보자 행을 잠가 같은 사람의 동시 제보도 차례로 센다."""
    await db.execute(select(Resident.id).where(Resident.id == user.id).with_for_update())
    start = datetime.combine(now.astimezone(KST).date(), time(0), tzinfo=KST)
    count = await db.scalar(
        select(func.count(VehicleReport.id)).where(
            VehicleReport.reporter_id == user.id, VehicleReport.created_at >= start
        )
    )
    limit = get_settings().report_daily_limit
    if count >= limit:
        raise ConflictError("오늘은 더 제보할 수 없어요.", code=ErrorCode.REPORT_LIMIT_EXCEEDED, detail={"limit": limit})


async def create(
    db: AsyncSession,
    user: Resident,
    building_id: int,
    photo: bytes,
    plate: str,
    slot_id: int,
    now: datetime | None = None,
) -> VehicleReportCreated:
    """POST /buildings/{building_id}/vehicle-reports. 빌라 회원 확인은 엔드포인트(BuildingMember)가 한다.

    - 사진이 JPEG·PNG 가 아니거나 비었거나 너무 크면, 번호판 형식이 틀리면 400 INVALID_INPUT (detail.field)
    - 하루 한도 초과 409 REPORT_LIMIT_EXCEEDED
    - 칸·번호판 규칙은 admin.place_unknown_vehicle (404 / SLOT_UNAVAILABLE / SLOT_OCCUPIED / PLATE_EXISTS / VEHICLE_ALREADY_PARKED)
    """
    now = now or datetime.now(KST)
    settings = get_settings()
    if not is_valid_plate(plate):
        raise InvalidInputError("차량 번호를 확인해 주세요.", detail={"field": "plate", "reason": "예: 12가 3456"})
    plate_no = normalize_plate(plate)
    jpeg = await asyncio.to_thread(report_photos.process, photo)

    await _ensure_under_daily_limit(db, user, now)
    assignment = await admin.place_unknown_vehicle(db, building_id, slot_id, plate_no)
    label = await slot_label(db, slot_id)

    key = report_photos.save(jpeg)
    try:
        report = VehicleReport(
            building_id=building_id,
            reporter_id=user.id,
            slot_id=slot_id,
            vehicle_id=assignment.vehicle_id,
            parking_assignment_id=assignment.id,
            plate_no=plate_no,
            photo_key=key,
            reward_amount=settings.report_token_reward,
            created_at=now,
        )
        db.add(report)
        await db.flush()

        manager_ids = await db.scalars(
            select(Resident.id).where(
                Resident.building_id == building_id, Resident.role == ResidentRole.MANAGER, Resident.id != user.id
            )
        )
        for manager_id in manager_ids.all():
            await notifications.create(
                db,
                manager_id,
                NotificationType.VEHICLE_REPORT,
                NOTIFICATION_TITLE,
                f"{label} · {format_plate(plate_no)}",
                vehicle_report_id=report.id,
            )
        await tokens.transfer(db, None, user.id, settings.report_token_reward, memo=REWARD_MEMO)
        balance = await db.scalar(select(Resident.token_balance).where(Resident.id == user.id))
        await db.commit()
    except BaseException:
        report_photos.delete(key)
        raise

    return VehicleReportCreated(
        report_id=report.id,
        vehicle_id=assignment.vehicle_id,
        parking_id=assignment.id,
        slot_label=label,
        occupant_type=OccupantType.UNKNOWN,
        reward_tokens=settings.report_token_reward,
        token_balance=balance,
    )


async def _visible_report(db: AsyncSession, user: Resident, report_id: int) -> VehicleReport:
    """제보자 본인 또는 그 빌라 관리인만. 아니면 404 NOT_FOUND."""
    report = await db.get(VehicleReport, report_id)
    if report is None:
        raise NotFoundError("제보를 찾을 수 없습니다.")
    is_manager = user.role == ResidentRole.MANAGER and user.building_id == report.building_id
    if report.reporter_id != user.id and not is_manager:
        raise NotFoundError("제보를 찾을 수 없습니다.")
    return report


async def _details(db: AsyncSession, reports: list[VehicleReport]) -> list[VehicleReportDetail]:
    labels = await slot_labels(db, {r.slot_id for r in reports})
    names = {
        resident.id: resident.name or resident.nickname
        for resident in (
            await db.scalars(select(Resident).where(Resident.id.in_({r.reporter_id for r in reports})))
        ).all()
    }
    return [
        VehicleReportDetail(
            id=r.id,
            building_id=r.building_id,
            plate=r.plate_no,
            slot_label=labels[r.slot_id],
            photo_url=photo_url(r.id),
            reporter=VehicleReportReporter(id=r.reporter_id, name=names[r.reporter_id]),
            status=r.status.name,
            created_at=r.created_at,
        )
        for r in reports
    ]


async def get_detail(db: AsyncSession, user: Resident, report_id: int) -> VehicleReportDetail:
    """GET /vehicle-reports/{report_id}."""
    return (await _details(db, [await _visible_report(db, user, report_id)]))[0]


async def photo_path(db: AsyncSession, user: Resident, report_id: int) -> Path:
    """GET /vehicle-reports/{report_id}/photo 의 파일 경로. 파일이 없으면(볼륨 유실 등) 404."""
    report = await _visible_report(db, user, report_id)
    path = report_photos.path_of(report.photo_key)
    if not path.is_file():
        raise NotFoundError("사진을 찾을 수 없습니다.")
    return path


async def list_for_building(
    db: AsyncSession, building_id: int, cursor: str | None = None, limit: int = DEFAULT_LIMIT
) -> CursorPage[VehicleReportDetail]:
    """GET /admin/buildings/{building_id}/vehicle-reports. 최신순 (결정 14). 관리인 확인은 엔드포인트(BuildingAdmin)."""
    page = await paginate(
        db, select(VehicleReport).where(VehicleReport.building_id == building_id), VehicleReport.id, cursor, limit
    )
    return CursorPage(items=await _details(db, page.items), next_cursor=page.next_cursor)
