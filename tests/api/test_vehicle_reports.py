"""#52 미등록 차량 제보 API: multipart 업로드, 사진 권한, 관리인 목록·알림 link."""

import pytest

from app.core.config import get_settings
from app.core.error_codes import ErrorCode
from app.models.resident import ResidentRole
from tests.factories import make_alley, make_building, make_garage, make_resident, make_slot
from tests.helpers import assert_error, auth_headers, jpeg

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def photo_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "report_photo_dir", str(tmp_path))
    return tmp_path


@pytest.fixture
async def villa(db):
    building = await make_building(db)
    slot = await make_slot(db, await make_garage(db, building), 1)
    return {
        "building": building,
        "slot": slot,
        "me": await make_resident(db, "me@example.com", building),
        "manager": await make_resident(db, "manager@example.com", building, role=ResidentRole.MANAGER),
    }


def _form(villa, photo=None, plate="45다 6789", content_type="image/jpeg"):
    return {
        "files": {"photo": ("car.jpg", jpeg() if photo is None else photo, content_type)},
        "data": {"plate": plate, "slot_id": str(villa["slot"].id)},
    }


async def _post(client, villa, user=None, **kwargs):
    return await client.post(
        f"/api/v1/buildings/{villa['building'].id}/vehicle-reports",
        headers=auth_headers(user or villa["me"]),
        **_form(villa, **kwargs),
    )


async def test_report_then_manager_sees_notification_detail_and_photo(client, db, villa):
    res = await _post(client, villa)
    assert res.status_code == 201, res.text
    body = res.json()
    assert set(body) == {
        "report_id", "vehicle_id", "parking_id", "slot_label", "occupant_type", "reward_tokens", "token_balance",
    }  # fmt: skip
    assert (body["slot_label"], body["occupant_type"], body["reward_tokens"], body["token_balance"]) == (
        "P1",
        "UNKNOWN",
        500,
        500,
    )
    report_id = body["report_id"]

    manager = auth_headers(villa["manager"])
    notices = (await client.get("/api/v1/notifications", headers=manager)).json()["items"]
    assert [(n["type"], n["title"], n["body"], n["link"]) for n in notices] == [
        ("VEHICLE_REPORT", "미등록 차량 제보", "P1 · 45다 6789", {"screen": "VEHICLE_REPORT", "id": report_id})
    ]

    detail = await client.get(f"/api/v1/vehicle-reports/{report_id}", headers=manager)
    assert detail.status_code == 200, detail.text
    assert detail.json()["plate"] == "45다 6789"
    assert detail.json()["photo_url"] == f"/vehicle-reports/{report_id}/photo"
    assert detail.json()["created_at"].endswith("+09:00")

    for headers in (manager, auth_headers(villa["me"])):
        photo = await client.get(f"/api/v1/vehicle-reports/{report_id}/photo", headers=headers)
        assert photo.status_code == 200
        assert photo.headers["content-type"] == "image/jpeg"
        assert photo.headers["cache-control"].startswith("private")
        assert photo.content[:2] == b"\xff\xd8"

    listing = await client.get(f"/api/v1/admin/buildings/{villa['building'].id}/vehicle-reports", headers=manager)
    assert [r["id"] for r in listing.json()["items"]] == [report_id]

    neighbor = auth_headers(await make_resident(db, "neighbor@example.com", villa["building"]))
    for path in (f"/api/v1/vehicle-reports/{report_id}", f"/api/v1/vehicle-reports/{report_id}/photo"):
        assert_error(await client.get(path, headers=neighbor), ErrorCode.NOT_FOUND)
    listing = await client.get(f"/api/v1/admin/buildings/{villa['building'].id}/vehicle-reports", headers=neighbor)
    assert_error(listing, ErrorCode.NOT_BUILDING_ADMIN)


async def test_rejects_bad_photo_plate_and_missing_fields(client, villa, monkeypatch):
    res = await _post(client, villa, photo=b"not an image", content_type="image/jpeg")
    assert res.status_code == 400
    assert assert_error(res, ErrorCode.INVALID_INPUT)["detail"]["field"] == "photo"

    res = await _post(client, villa, plate="45다")
    assert assert_error(res, ErrorCode.INVALID_INPUT)["detail"]["field"] == "plate"

    monkeypatch.setattr(get_settings(), "report_photo_max_bytes", 100)
    res = await _post(client, villa)
    assert assert_error(res, ErrorCode.INVALID_INPUT)["detail"]["field"] == "photo"

    res = await client.post(
        f"/api/v1/buildings/{villa['building'].id}/vehicle-reports",
        headers=auth_headers(villa["me"]),
        data={"plate": "45다6789", "slot_id": str(villa["slot"].id)},
    )
    assert_error(res, ErrorCode.INVALID_INPUT)  # photo 없음


async def test_non_member_forbidden(client, db, villa):
    other = await make_building(db, "INV002", "옆 빌라", alley=await make_alley(db, "다른 골목"))
    outsider = await make_resident(db, "out@example.com", other)
    res = await _post(client, villa, user=outsider)
    assert_error(res, ErrorCode.NOT_BUILDING_MEMBER)
