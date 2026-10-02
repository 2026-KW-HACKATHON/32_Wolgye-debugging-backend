"""관리인 공유 조건·공유 요청 API (#13)."""

import pytest
from sqlalchemy import func, select

from app.core.error_codes import ErrorCode
from app.models.notification import Notification
from app.models.resident import ResidentRole
from app.models.share_offer import ShareOffer
from app.models.share_request import ShareRequest, ShareRequestStatus
from tests.factories import (
    make_building,
    make_garage,
    make_resident,
    make_share_offer,
    make_share_request,
    make_slot,
    make_vehicle,
)
from tests.helpers import assert_error, auth_headers

pytestmark = pytest.mark.anyio


@pytest.fixture
async def world(db):
    building = await make_building(db)
    garage = await make_garage(db, building, name="골목")
    slot1 = await make_slot(db, garage, 1)
    slot2 = await make_slot(db, garage, 2)
    admin = await make_resident(db, "admin@example.com", building=building, role=ResidentRole.MANAGER)
    resident = await make_resident(db, "res@example.com", building=building)
    other = await make_building(db, invite_code="INV002", name="옆빌라")
    requester = await make_resident(db, "req@example.com", building=other, token_balance=100)
    requester.name = "홍길동"
    requester.unit_no = "101동 201호"
    await db.commit()
    other_admin = await make_resident(db, "oadmin@example.com", building=other, role=ResidentRole.MANAGER)
    offer = await make_share_offer(db, slot1, admin, hourly_price=2, max_hours=4)
    return {
        "building": building, "slot1": slot1, "slot2": slot2, "admin": admin, "resident": resident,
        "requester": requester, "other_admin": other_admin, "offer": offer,
    }


# ── 공유 조건 ──
async def test_list_offers(client, world):
    res = await client.get(
        f"/api/v1/admin/buildings/{world['building'].id}/share-offers", headers=auth_headers(world["admin"])
    )
    assert res.status_code == 200
    item = res.json()["items"][0]
    assert item["id"] == world["offer"].id
    assert item["slot_label"] == "P1"
    assert item["weekdays"] == ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    assert item["host_id"] == world["admin"].id
    assert item["max_hours"] == 4


async def test_offers_require_admin(client, world):
    url = f"/api/v1/admin/buildings/{world['building'].id}/share-offers"
    res = await client.get(url, headers=auth_headers(world["resident"]))
    assert res.status_code == 403
    assert_error(res, ErrorCode.NOT_BUILDING_ADMIN)
    res = await client.get(url, headers=auth_headers(world["other_admin"]))
    assert res.status_code == 403


async def test_offers_unknown_building_404(client, world):
    res = await client.get("/api/v1/admin/buildings/9999/share-offers", headers=auth_headers(world["admin"]))
    assert res.status_code == 404


async def test_create_offers(client, world):
    res = await client.post(
        f"/api/v1/admin/buildings/{world['building'].id}/share-offers",
        headers=auth_headers(world["admin"]),
        json={
            "slot_ids": [world["slot1"].id, world["slot2"].id],
            "weekdays": ["MON", "SUN"],
            "start_hour": 7,
            "end_hour": 23,
            "hourly_price": 2,
            "max_hours": None,
            "memo": "이용 후 칸 비워주세요",
        },
    )
    assert res.status_code == 201
    items = res.json()["items"]
    assert [i["slot_id"] for i in items] == [world["slot1"].id, world["slot2"].id]
    assert items[0]["weekdays"] == ["MON", "SUN"]
    assert items[0]["max_hours"] is None
    assert items[0]["is_public"] is True
    assert items[1]["slot_label"] == "P2"


async def test_create_offers_rolls_back_when_one_slot_invalid(client, db, world):
    world["slot2"].is_active = False
    await db.commit()
    res = await client.post(
        f"/api/v1/admin/buildings/{world['building'].id}/share-offers",
        headers=auth_headers(world["admin"]),
        json={"slot_ids": [world["slot1"].id, world["slot2"].id], "start_hour": 7, "end_hour": 23},
    )
    assert res.status_code == 400
    error = assert_error(res, ErrorCode.INVALID_INPUT, "사용 중지된 칸은 공유할 수 없습니다.")
    assert error["detail"] == {"slot_id": world["slot2"].id}
    assert await db.scalar(select(func.count()).select_from(ShareOffer)) == 1  # world 의 기존 하나만


async def test_create_offers_validates_hours(client, world):
    res = await client.post(
        f"/api/v1/admin/buildings/{world['building'].id}/share-offers",
        headers=auth_headers(world["admin"]),
        json={"slot_ids": [world["slot1"].id], "start_hour": 10, "end_hour": 10},
    )
    assert res.status_code == 400
    assert_error(res, ErrorCode.INVALID_INPUT)


async def test_update_offer_keeps_existing_total_price(client, db, world):
    req = await make_share_request(db, world["offer"], world["requester"], start_hour=10, end_hour=12)
    res = await client.patch(
        f"/api/v1/admin/share-offers/{world['offer'].id}",
        headers=auth_headers(world["admin"]),
        json={"hourly_price": 5, "is_public": False, "weekdays": ["SAT"]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["hourly_price"] == 5
    assert body["is_public"] is False
    assert body["weekdays"] == ["SAT"]
    assert body["start_hour"] == world["offer"].start_hour
    total = await db.scalar(select(ShareRequest.total_price).where(ShareRequest.id == req.id))
    assert total == 4


async def test_update_offer_bad_hours_400(client, world):
    res = await client.patch(
        f"/api/v1/admin/share-offers/{world['offer'].id}",
        headers=auth_headers(world["admin"]),
        json={"start_hour": 23},  # 기존 end_hour 22 보다 늦음
    )
    assert res.status_code == 400
    assert_error(res, ErrorCode.INVALID_INPUT)


async def test_update_offer_permissions(client, world):
    url = f"/api/v1/admin/share-offers/{world['offer'].id}"
    res = await client.patch(url, headers=auth_headers(world["other_admin"]), json={"is_public": False})
    assert res.status_code == 403
    assert_error(res, ErrorCode.NOT_BUILDING_ADMIN)
    res = await client.patch("/api/v1/admin/share-offers/9999", headers=auth_headers(world["admin"]), json={})
    assert res.status_code == 404
    assert_error(res, ErrorCode.NOT_FOUND)


async def test_delete_offer_cascades_requests(client, db, world):
    await make_share_request(db, world["offer"], world["requester"])
    url = f"/api/v1/admin/share-offers/{world['offer'].id}"

    res = await client.delete(url, headers=auth_headers(world["resident"]))
    assert res.status_code == 403

    res = await client.delete(url, headers=auth_headers(world["admin"]))
    assert res.status_code == 204
    assert await db.scalar(select(func.count()).select_from(ShareOffer)) == 0
    assert await db.scalar(select(func.count()).select_from(ShareRequest)) == 0

    res = await client.delete(url, headers=auth_headers(world["admin"]))
    assert res.status_code == 404


# ── 공유 요청 목록 ──
async def test_list_requests_counts_filter_search(client, db, world):
    vehicle = await make_vehicle(db, "21가3456", owner=world["requester"])
    pending = await make_share_request(db, world["offer"], world["requester"], start_hour=13, end_hour=17)
    pending.vehicle_id = vehicle.id
    await db.commit()
    await make_share_request(
        db, world["offer"], world["requester"], status=ShareRequestStatus.ACCEPTED, start_hour=8, end_hour=10
    )
    await make_share_request(db, world["offer"], world["requester"], status=ShareRequestStatus.REJECTED)
    url = f"/api/v1/admin/buildings/{world['building'].id}/share-requests"
    headers = auth_headers(world["admin"])

    res = await client.get(url, headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["counts"] == {"PENDING": 1, "APPROVED": 1, "REJECTED": 1}
    assert len(body["items"]) == 3
    assert body["next_cursor"] is None
    item = body["items"][-1]
    assert item["id"] == pending.id
    assert item["requester"] == {"name": "홍길동", "unit": "101동 201호"}
    assert item["plate"] == "21가 3456"
    assert item["slot_label"] == "P1"
    assert item["request_date"] == "2026-10-02"
    assert (item["start_hour"], item["end_hour"], item["total_price"]) == (13, 17, 8)
    assert item["status"] == "PENDING"

    res = await client.get(url, headers=headers, params={"status": "APPROVED"})
    assert [i["status"] for i in res.json()["items"]] == ["APPROVED"]

    res = await client.get(url, headers=headers, params={"q": "21가 34"})
    assert [i["id"] for i in res.json()["items"]] == [pending.id]
    res = await client.get(url, headers=headers, params={"q": "홍길"})
    assert len(res.json()["items"]) == 3

    res = await client.get(url, headers=headers, params={"limit": 2})
    page1 = res.json()
    assert len(page1["items"]) == 2 and page1["next_cursor"] is not None
    res = await client.get(url, headers=headers, params={"limit": 2, "cursor": page1["next_cursor"]})
    assert [i["id"] for i in res.json()["items"]] == [pending.id]


async def test_list_requests_requires_admin(client, world):
    res = await client.get(
        f"/api/v1/admin/buildings/{world['building'].id}/share-requests", headers=auth_headers(world["resident"])
    )
    assert res.status_code == 403
    assert_error(res, ErrorCode.NOT_BUILDING_ADMIN)


# ── 수락 / 거절 ──
async def test_approve(client, db, world):
    req = await make_share_request(db, world["offer"], world["requester"], start_hour=10, end_hour=12)
    res = await client.patch(
        f"/api/v1/admin/share-requests/{req.id}", headers=auth_headers(world["admin"]), json={"status": "APPROVED"}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "APPROVED"
    assert body["reject_reason"] is None
    assert body["responded_at"].endswith("+09:00")
    assert await db.scalar(select(func.count()).select_from(Notification)) == 1


async def test_reject_with_preset_reason(client, world, db):
    req = await make_share_request(db, world["offer"], world["requester"])
    res = await client.patch(
        f"/api/v1/admin/share-requests/{req.id}",
        headers=auth_headers(world["admin"]),
        json={"status": "REJECTED", "reject_reason": "주차 구역 용량 초과"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "REJECTED"
    assert res.json()["reject_reason"] == "주차 구역 용량 초과"


async def test_approve_insufficient_tokens_stays_pending(client, db, world):
    world["requester"].token_balance = 1
    await db.commit()
    req = await make_share_request(db, world["offer"], world["requester"], start_hour=10, end_hour=12)
    res = await client.patch(
        f"/api/v1/admin/share-requests/{req.id}", headers=auth_headers(world["admin"]), json={"status": "APPROVED"}
    )
    assert res.status_code == 409
    error = assert_error(res, ErrorCode.INSUFFICIENT_TOKENS)
    assert error["detail"] == {"required": 4, "balance": 1}
    status = await db.scalar(select(ShareRequest.status).where(ShareRequest.id == req.id))
    assert status == ShareRequestStatus.PENDING


async def test_approve_overlap_conflict(client, db, world):
    await make_share_request(
        db, world["offer"], world["requester"], status=ShareRequestStatus.ACCEPTED, start_hour=10, end_hour=12
    )
    req = await make_share_request(db, world["offer"], world["requester"], start_hour=11, end_hour=12)
    res = await client.patch(
        f"/api/v1/admin/share-requests/{req.id}", headers=auth_headers(world["admin"]), json={"status": "APPROVED"}
    )
    assert res.status_code == 409
    assert_error(res, ErrorCode.GARAGE_TIME_CONFLICT)


async def test_decide_already_decided(client, db, world):
    req = await make_share_request(db, world["offer"], world["requester"], status=ShareRequestStatus.ACCEPTED)
    res = await client.patch(
        f"/api/v1/admin/share-requests/{req.id}", headers=auth_headers(world["admin"]), json={"status": "REJECTED"}
    )
    assert res.status_code == 409
    error = assert_error(res, ErrorCode.ALREADY_DECIDED)
    assert error["detail"] == {"status": "APPROVED"}


async def test_decide_permissions_and_not_found(client, db, world):
    req = await make_share_request(db, world["offer"], world["requester"])
    url = f"/api/v1/admin/share-requests/{req.id}"
    res = await client.patch(url, headers=auth_headers(world["other_admin"]), json={"status": "APPROVED"})
    assert res.status_code == 403
    assert_error(res, ErrorCode.NOT_BUILDING_ADMIN)
    res = await client.patch(url, headers=auth_headers(world["requester"]), json={"status": "APPROVED"})
    assert res.status_code == 403
    res = await client.patch(
        "/api/v1/admin/share-requests/9999", headers=auth_headers(world["admin"]), json={"status": "APPROVED"}
    )
    assert res.status_code == 404
    res = await client.patch(url, headers=auth_headers(world["admin"]), json={"status": "PENDING"})
    assert res.status_code == 400


async def test_update_offer_null_for_required_field_400(client, world):
    res = await client.patch(
        f"/api/v1/admin/share-offers/{world['offer'].id}",
        headers=auth_headers(world["admin"]),
        json={"hourly_price": None},
    )
    assert res.status_code == 400
    assert_error(res, ErrorCode.INVALID_INPUT)


async def test_update_offer_clears_nullable_fields(client, world):
    res = await client.patch(
        f"/api/v1/admin/share-offers/{world['offer'].id}",
        headers=auth_headers(world["admin"]),
        json={"max_hours": None, "memo": None},
    )
    assert res.status_code == 200
    assert res.json()["max_hours"] is None
    assert res.json()["memo"] is None


async def test_admin_share_endpoints_require_login(client, world):
    res = await client.get(f"/api/v1/admin/buildings/{world['building'].id}/share-offers")
    assert res.status_code == 401
    assert_error(res, ErrorCode.UNAUTHORIZED)
