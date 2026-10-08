"""#52 미등록 차량 사진 제보: 제보 한 번 = 미확인 차량 배치 + 제보 + 관리인 알림 + 보상 토큰."""

from datetime import datetime

import pytest
from PIL import Image
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.error_codes import ErrorCode
from app.models.notification import Notification, NotificationType
from app.models.parking_assignment import ParkingAssignment
from app.models.resident import Resident, ResidentRole
from app.models.token_transfer import TokenTransfer
from app.models.vehicle import Vehicle
from app.models.vehicle_report import VehicleReport
from app.schemas.common import KST
from app.services import report_photos, vehicle_reports
from app.services.exceptions import ConflictError, InvalidInputError, NotFoundError
from tests.factories import make_alley, make_building, make_garage, make_resident, make_slot, make_vehicle
from tests.factories_parking import make_assignment
from tests.helpers import jpeg

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 8, 14, 0, tzinfo=KST)


@pytest.fixture(autouse=True)
def photo_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "report_photo_dir", str(tmp_path))
    return tmp_path


@pytest.fixture
async def villa(db):
    building = await make_building(db)
    garage = await make_garage(db, building, name="필로티")
    slots = [await make_slot(db, garage, n) for n in (1, 2, 3, 4, 5)]
    slots[4].is_active = False
    await db.commit()
    return {
        "building": building,
        "slots": slots,
        "me": await make_resident(db, "me@example.com", building, token_balance=1000),
        "manager": await make_resident(db, "manager@example.com", building, role=ResidentRole.MANAGER),
        "manager2": await make_resident(db, "manager2@example.com", building, role=ResidentRole.MANAGER),
    }


async def _report(db, villa, slot_index=0, plate="45다 6789", photo=None, user=None, now=NOW):
    return await vehicle_reports.create(
        db, user or villa["me"], villa["building"].id, jpeg() if photo is None else photo, plate, villa["slots"][slot_index].id, now=now
    )


async def _count(db, model, *where) -> int:
    return await db.scalar(select(func.count()).select_from(model).where(*where))


async def test_report_registers_unknown_vehicle_notifies_managers_and_rewards(db, villa, photo_dir):
    created = await _report(db, villa)

    assert (created.slot_label, created.occupant_type, created.reward_tokens) == ("P1", "UNKNOWN", 500)
    assert created.token_balance == 1500
    vehicle = await db.get(Vehicle, created.vehicle_id)
    assert (vehicle.plate_no, vehicle.owner_id) == ("45다6789", None)
    assignment = await db.get(ParkingAssignment, created.parking_id)
    assert (assignment.slot_id, assignment.is_active) == (villa["slots"][0].id, True)

    report = await db.get(VehicleReport, created.report_id)
    assert (report.reporter_id, report.plate_no, report.reward_amount) == (villa["me"].id, "45다6789", 500)
    assert (photo_dir / report.photo_key).is_file()

    notices = (await db.scalars(select(Notification).order_by(Notification.resident_id))).all()
    assert [n.resident_id for n in notices] == [villa["manager"].id, villa["manager2"].id]
    assert {(n.type, n.title, n.body, n.vehicle_report_id) for n in notices} == {
        (NotificationType.VEHICLE_REPORT, "미등록 차량 제보", "P1 · 45다 6789", report.id)
    }
    transfer = await db.scalar(select(TokenTransfer))
    assert (transfer.sender_id, transfer.receiver_id, transfer.amount, transfer.memo) == (
        None,
        villa["me"].id,
        500,
        "미등록 차량 제보 보상",
    )


async def test_manager_report_does_not_notify_self(db, villa):
    await _report(db, villa, user=villa["manager"])
    assert await _count(db, Notification) == 1  # manager2 에게만


async def test_photo_strips_exif_and_shrinks(db, villa, photo_dir):
    created = await _report(db, villa, photo=jpeg((4000, 3000), exif=True))
    report = await db.get(VehicleReport, created.report_id)
    with Image.open(photo_dir / report.photo_key) as saved:
        assert saved.format == "JPEG"
        assert saved.size == (1600, 1200)
        assert not saved.getexif()


async def test_png_is_accepted(db, villa):
    created = await _report(db, villa, photo=jpeg(fmt="PNG"))
    assert created.slot_label == "P1"


@pytest.mark.parametrize(
    ("photo", "plate", "field"),
    [
        (b"not an image", "45다6789", "photo"),
        (b"", "45다6789", "photo"),
        ("gif", "45다6789", "photo"),
        (None, "45다", "plate"),
    ],
)
async def test_invalid_input_leaves_nothing(db, villa, photo_dir, photo, plate, field):
    if photo == "gif":
        photo = jpeg(fmt="GIF")
    with pytest.raises(InvalidInputError) as exc:
        await _report(db, villa, photo=photo, plate=plate)
    assert exc.value.detail["field"] == field
    assert await _count(db, VehicleReport) == 0
    assert list(photo_dir.iterdir()) == []


async def test_photo_too_large(db, villa, monkeypatch):
    monkeypatch.setattr(get_settings(), "report_photo_max_bytes", 100)
    with pytest.raises(InvalidInputError) as exc:
        await _report(db, villa)
    assert exc.value.detail["field"] == "photo"


async def test_slot_and_plate_rules_reject_without_reward(db, villa, photo_dir):
    owner = await make_resident(db, "owner@example.com", villa["building"])
    await make_vehicle(db, "11가1111", owner=owner)
    parked = await make_vehicle(db, "22나2222")
    await make_assignment(db, villa["slots"][1], parked)
    other = await make_building(db, "INV002", "옆 빌라", alley=await make_alley(db, "다른 골목"))
    other_slot = await make_slot(db, await make_garage(db, other), 1)

    cases = [
        (dict(slot_index=1), ConflictError, ErrorCode.SLOT_OCCUPIED),
        (dict(slot_index=4), ConflictError, ErrorCode.SLOT_UNAVAILABLE),
        (dict(plate="11가 1111"), ConflictError, ErrorCode.PLATE_EXISTS),
        (dict(plate="22나2222"), ConflictError, ErrorCode.VEHICLE_ALREADY_PARKED),
    ]
    for kwargs, error, code in cases:
        with pytest.raises(error) as exc:
            await _report(db, villa, **kwargs)
        assert exc.value.code == code

    with pytest.raises(NotFoundError):  # 다른 빌라 칸
        await vehicle_reports.create(db, villa["me"], villa["building"].id, jpeg(), "45다6789", other_slot.id, now=NOW)

    assert await _count(db, VehicleReport) == 0
    assert await _count(db, Notification) == 0
    assert await _count(db, TokenTransfer) == 0
    assert await db.scalar(select(Resident.token_balance).where(Resident.id == villa["me"].id)) == 1000
    assert list(photo_dir.iterdir()) == []


async def test_daily_limit(db, villa):
    for i in range(3):
        await _report(db, villa, slot_index=i, plate=f"4{i}다6789")
    with pytest.raises(ConflictError) as exc:
        await _report(db, villa, slot_index=3, plate="49다6789")
    assert exc.value.code == ErrorCode.REPORT_LIMIT_EXCEEDED

    tomorrow = datetime(2026, 10, 9, 0, 0, tzinfo=KST)  # KST 자정이 지나면 다시 셀 수 있다
    created = await _report(db, villa, slot_index=3, plate="49다6789", now=tomorrow)
    assert created.slot_label == "P4"


async def test_db_failure_removes_saved_photo(db, villa, photo_dir, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(vehicle_reports.tokens, "transfer", boom)
    with pytest.raises(RuntimeError):
        await _report(db, villa)
    assert list(photo_dir.iterdir()) == []


async def test_detail_visible_to_reporter_and_building_manager_only(db, villa, photo_dir):
    created = await _report(db, villa)
    neighbor = await make_resident(db, "neighbor@example.com", villa["building"])
    other_manager = await make_resident(
        db, "om@example.com", await make_building(db, "INV002", "옆 빌라", alley=await make_alley(db, "다른 골목")), role=ResidentRole.MANAGER
    )

    for viewer in (villa["me"], villa["manager"]):
        detail = await vehicle_reports.get_detail(db, viewer, created.report_id)
        assert (detail.plate, detail.slot_label, detail.status) == ("45다 6789", "P1", "SUBMITTED")
        assert (detail.reporter.id, detail.reporter.name) == (villa["me"].id, "me")
        assert detail.photo_url == f"/vehicle-reports/{created.report_id}/photo"
        assert (await vehicle_reports.photo_path(db, viewer, created.report_id)).is_file()
    for viewer in (neighbor, other_manager):
        with pytest.raises(NotFoundError):
            await vehicle_reports.get_detail(db, viewer, created.report_id)
        with pytest.raises(NotFoundError):
            await vehicle_reports.photo_path(db, viewer, created.report_id)

    report = await db.get(VehicleReport, created.report_id)
    report_photos.delete(report.photo_key)
    with pytest.raises(NotFoundError):  # 파일이 사라졌으면 404
        await vehicle_reports.photo_path(db, villa["me"], created.report_id)


async def test_list_for_building_latest_first(db, villa):
    first = await _report(db, villa, slot_index=0, plate="41다6789")
    second = await _report(db, villa, slot_index=1, plate="42다6789")
    page = await vehicle_reports.list_for_building(db, villa["building"].id, limit=1)
    assert [r.id for r in page.items] == [second.report_id]
    rest = await vehicle_reports.list_for_building(db, villa["building"].id, cursor=page.next_cursor)
    assert [r.id for r in rest.items] == [first.report_id]
