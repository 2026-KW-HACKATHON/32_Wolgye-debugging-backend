"""#14 관리인 API: 대시보드·칸 목록·칸 설정·미확인 차량 등록."""

from datetime import date, datetime

import pytest
from sqlalchemy import select

from app.core.error_codes import ErrorCode
from app.models.parking_assignment import ParkingAssignment
from app.models.resident import ResidentRole
from app.models.vehicle import Vehicle
from app.services.admin import KST
from tests.factories import (
    make_building,
    make_garage,
    make_resident,
    make_share_offer,
    make_slot,
    make_vehicle,
)
from tests.helpers import assert_error, auth_headers

pytestmark = pytest.mark.anyio


@pytest.fixture
async def setup(db):
    building = await make_building(db)
    garage = await make_garage(db, building, name="건물 앞")
    s1, s2 = await make_slot(db, garage, 1), await make_slot(db, garage, 2)
    admin = await make_resident(db, "admin@example.com", building, role=ResidentRole.MANAGER)
    resident = await make_resident(db, "res@example.com", building)
    return {"building": building, "garage": garage, "s1": s1, "s2": s2, "admin": admin, "resident": resident}


# ── 대시보드 ──
async def test_dashboard_ok(client, setup):
    b = setup["building"]
    res = await client.get(
        f"/api/v1/admin/buildings/{b.id}/dashboard", params={"month": "2026-09"}, headers=auth_headers(setup["admin"])
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["building"] == {"id": b.id, "name": b.name}
    assert body["pending_requests"] == []
    assert body["realtime"] == {"available_count": 2, "vehicles": []}
    assert body["congestion"]["total_slots"] == 2
    assert len(body["congestion"]["days"]) == 30
    assert body["congestion"]["days"][0] == {"date": "2026-09-01", "peak_occupied": 0}
    assert body["ai_insight"] is None


async def test_dashboard_invalid_month(client, setup):
    b = setup["building"]
    headers = auth_headers(setup["admin"])
    res = await client.get(f"/api/v1/admin/buildings/{b.id}/dashboard", params={"month": "2026-9"}, headers=headers)
    assert res.status_code == 400
    assert_error(res, ErrorCode.INVALID_INPUT)
    res = await client.get(f"/api/v1/admin/buildings/{b.id}/dashboard", params={"month": "2026-13"}, headers=headers)
    assert res.status_code == 400
    assert_error(res, ErrorCode.INVALID_INPUT)


async def test_dashboard_resident_forbidden(client, setup):
    res = await client.get(
        f"/api/v1/admin/buildings/{setup['building'].id}/dashboard", headers=auth_headers(setup["resident"])
    )
    assert res.status_code == 403
    assert_error(res, ErrorCode.NOT_BUILDING_ADMIN)


async def test_dashboard_other_building_admin_forbidden(client, db, setup):
    other = await make_building(db, invite_code="INV002", name="햇살빌라")
    other_admin = await make_resident(db, "oa@example.com", other, role=ResidentRole.MANAGER)
    res = await client.get(f"/api/v1/admin/buildings/{setup['building'].id}/dashboard", headers=auth_headers(other_admin))
    assert res.status_code == 403
    assert_error(res, ErrorCode.NOT_BUILDING_ADMIN)


async def test_dashboard_building_not_found(client, setup):
    res = await client.get("/api/v1/admin/buildings/9999/dashboard", headers=auth_headers(setup["admin"]))
    assert res.status_code == 404
    assert_error(res, ErrorCode.NOT_FOUND)


# ── 칸 목록 ──
async def test_list_slots(client, db, setup):
    s1, s2 = setup["s1"], setup["s2"]
    v = await make_vehicle(db, "12가3456", setup["resident"])
    db.add(ParkingAssignment(slot_id=s1.id, vehicle_id=v.id))
    await db.commit()
    today = datetime.now(KST).date()
    offer = await make_share_offer(db, s2, setup["admin"], start_date=today, end_date=date(9999, 12, 31))
    # 공유 중단된 조건은 무시
    await make_share_offer(db, s1, setup["admin"], start_date=today, end_date=date(9999, 12, 31), is_public=False)

    res = await client.get(f"/api/v1/admin/buildings/{setup['building'].id}/slots", headers=auth_headers(setup["admin"]))
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert items[0] == {
        "slot_id": s1.id,
        "zone_id": setup["garage"].id,
        "number": 1,
        "label": "건물 앞 1번",
        "is_active": True,
        "occupied": True,
        "share_offer_id": None,
    }
    assert items[1]["occupied"] is False
    assert items[1]["share_offer_id"] == offer.id


async def test_list_slots_forbidden(client, setup):
    res = await client.get(
        f"/api/v1/admin/buildings/{setup['building'].id}/slots", headers=auth_headers(setup["resident"])
    )
    assert res.status_code == 403
    assert_error(res, ErrorCode.NOT_BUILDING_ADMIN)


# ── 칸 설정 ──
async def test_update_slot(client, setup):
    s2 = setup["s2"]
    res = await client.patch(
        f"/api/v1/admin/slots/{s2.id}", json={"is_active": False}, headers=auth_headers(setup["admin"])
    )
    assert res.status_code == 200, res.text
    assert res.json()["is_active"] is False
    assert res.json()["label"] == "건물 앞 2번"

    res = await client.get(f"/api/v1/admin/buildings/{setup['building'].id}/slots", headers=auth_headers(setup["admin"]))
    assert res.json()["items"][1]["is_active"] is False


async def test_update_slot_forbidden(client, setup):
    res = await client.patch(
        f"/api/v1/admin/slots/{setup['s1'].id}", json={"is_active": False}, headers=auth_headers(setup["resident"])
    )
    assert res.status_code == 403
    assert_error(res, ErrorCode.NOT_BUILDING_ADMIN)


async def test_update_slot_not_found(client, setup):
    res = await client.patch("/api/v1/admin/slots/9999", json={"is_active": False}, headers=auth_headers(setup["admin"]))
    assert res.status_code == 404
    assert_error(res, ErrorCode.NOT_FOUND)


# ── 미확인 차량 ──
async def test_create_unknown_vehicle(client, db, setup):
    b, s1 = setup["building"], setup["s1"]
    res = await client.post(
        f"/api/v1/admin/buildings/{b.id}/unknown-vehicles",
        json={"slot_id": s1.id, "plate": "45다 6789"},
        headers=auth_headers(setup["admin"]),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["occupant_type"] == "UNKNOWN"
    vehicle = await db.get(Vehicle, body["vehicle_id"])
    assert vehicle.plate_no == "45다6789"
    assert vehicle.owner_id is None
    assignment = await db.get(ParkingAssignment, body["parking_id"])
    assert assignment.slot_id == s1.id and assignment.is_active

    dash = await client.get(f"/api/v1/admin/buildings/{b.id}/dashboard", headers=auth_headers(setup["admin"]))
    vehicles = dash.json()["realtime"]["vehicles"]
    assert vehicles == [
        {"slot_id": s1.id, "slot_label": "건물 앞 1번", "plate": "45다 6789", "occupant_type": "UNKNOWN", "can_request_move": False}
    ]


async def test_create_unknown_vehicle_slot_occupied(client, db, setup):
    b, s1 = setup["building"], setup["s1"]
    v = await make_vehicle(db, "12가3456", setup["resident"])
    db.add(ParkingAssignment(slot_id=s1.id, vehicle_id=v.id))
    await db.commit()
    res = await client.post(
        f"/api/v1/admin/buildings/{b.id}/unknown-vehicles",
        json={"slot_id": s1.id, "plate": "45다6789"},
        headers=auth_headers(setup["admin"]),
    )
    assert res.status_code == 409
    assert_error(res, ErrorCode.SLOT_OCCUPIED)
    # 차량도 만들어지지 않는다
    assert await db.scalar(select(Vehicle).where(Vehicle.plate_no == "45다6789")) is None


async def test_create_unknown_vehicle_reuses_ownerless_and_rejects_owned_plate(client, db, setup):
    b = setup["building"]
    headers = auth_headers(setup["admin"])
    unknown = await make_vehicle(db, "45다6789", None)
    res = await client.post(
        f"/api/v1/admin/buildings/{b.id}/unknown-vehicles", json={"slot_id": setup["s1"].id, "plate": "45다6789"}, headers=headers
    )
    assert res.status_code == 201
    assert res.json()["vehicle_id"] == unknown.id

    await make_vehicle(db, "12가3456", setup["resident"])
    res = await client.post(
        f"/api/v1/admin/buildings/{b.id}/unknown-vehicles", json={"slot_id": setup["s2"].id, "plate": "12가 3456"}, headers=headers
    )
    assert res.status_code == 409
    assert_error(res, ErrorCode.PLATE_EXISTS)


async def test_create_unknown_vehicle_errors(client, db, setup):
    b = setup["building"]
    headers = auth_headers(setup["admin"])
    url = f"/api/v1/admin/buildings/{b.id}/unknown-vehicles"

    res = await client.post(url, json={"slot_id": setup["s1"].id, "plate": "서울12가3456"}, headers=headers)
    assert res.status_code == 400
    assert_error(res, ErrorCode.INVALID_INPUT)

    other = await make_building(db, invite_code="INV002", name="햇살빌라")
    other_slot = await make_slot(db, await make_garage(db, other), 1)
    res = await client.post(url, json={"slot_id": other_slot.id, "plate": "45다6789"}, headers=headers)
    assert res.status_code == 404
    assert_error(res, ErrorCode.NOT_FOUND)

    setup["s2"].is_active = False
    await db.commit()
    res = await client.post(url, json={"slot_id": setup["s2"].id, "plate": "45다6789"}, headers=headers)
    assert res.status_code == 409
    assert_error(res, ErrorCode.SLOT_UNAVAILABLE)

    res = await client.post(url, json={"slot_id": setup["s1"].id, "plate": "45다6789"}, headers=auth_headers(setup["resident"]))
    assert res.status_code == 403
    assert_error(res, ErrorCode.NOT_BUILDING_ADMIN)

    res = await client.post(
        "/api/v1/admin/buildings/9999/unknown-vehicles", json={"slot_id": setup["s1"].id, "plate": "45다6789"}, headers=headers
    )
    assert res.status_code == 404
