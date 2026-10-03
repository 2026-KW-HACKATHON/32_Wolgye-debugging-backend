"""공유 요청 API (명세): POST /share-requests, GET /share-requests/{id}, GET /me/share-requests.

구 API(`POST /share-requests` 의 옛 본문) 테스트는 결정 27에 따라 지우고 이 파일로 바꿨다.
"""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.error_codes import ErrorCode
from app.models.notification import Notification, NotificationType
from app.models.share_request import ShareRequestStatus
from app.schemas.common import KST
from tests.factories import make_resident, make_vehicle
from tests.factories_share import make_request_on, make_scenario
from tests.helpers import assert_error, auth_headers

pytestmark = pytest.mark.anyio

TOMORROW = (datetime.now(KST) + timedelta(days=1)).date()


@pytest.fixture
async def sc(db):
    sc = await make_scenario(db, my_tokens=10)
    for offer in (sc.offer_p2, sc.offer_p3):
        offer.start_date = date(2026, 1, 1)  # 언제 돌려도 내일이 기간 안
    await db.commit()
    return sc


def _body(sc, **overrides):
    body = {
        "offer_id": sc.offer_p2.id,
        "vehicle_id": sc.my_vehicle.id,
        "request_date": TOMORROW.isoformat(),
        "start_hour": 10,
        "end_hour": 13,
    }
    return body | overrides


async def test_create(client, sc, session_factory):
    res = await client.post("/api/v1/share-requests", json=_body(sc), headers=auth_headers(sc.me))

    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "PENDING" and body["total_price"] == 6 and isinstance(body["id"], int)
    async with session_factory() as s:
        note = (await s.scalars(select(Notification))).one()
    assert note.resident_id == sc.host.id and note.type == NotificationType.SHARE_REQUEST
    assert note.share_request_id == body["id"] and note.body.startswith("P2 · ")


async def test_create_without_vehicle(client, sc):
    res = await client.post("/api/v1/share-requests", json=_body(sc, vehicle_id=None), headers=auth_headers(sc.me))

    assert res.status_code == 201


@pytest.mark.parametrize(
    ("overrides", "message", "detail"),
    [
        ({"start_hour": 4, "end_hour": 8}, "운영 시간 밖입니다.", {"start_hour": 6, "end_hour": 22}),
        ({"start_hour": 10, "end_hour": 15}, "최대 이용 시간을 초과했습니다.", {"max_hours": 4}),
        ({"start_hour": 13, "end_hour": 10}, None, None),
        ({"end_hour": 25}, None, None),
        ({"request_date": "2026-13-01"}, None, None),
        ({"request_date": (TOMORROW - timedelta(days=3)).isoformat()}, "이미 지난 시간에는 요청할 수 없습니다.", None),
    ],
)
async def test_create_invalid_input(client, sc, overrides, message, detail):
    res = await client.post("/api/v1/share-requests", json=_body(sc, **overrides), headers=auth_headers(sc.me))

    assert res.status_code == 400
    error = assert_error(res, ErrorCode.INVALID_INPUT, message)
    if detail is not None:
        assert error["detail"] == detail


async def test_create_on_own_offer_is_invalid(client, sc):
    res = await client.post("/api/v1/share-requests", json=_body(sc, vehicle_id=None), headers=auth_headers(sc.host))

    assert res.status_code == 400
    assert_error(res, ErrorCode.INVALID_INPUT, "내가 연 공유 조건에는 요청할 수 없습니다.")


async def test_create_not_found(client, db, sc):
    others = await make_vehicle(db, "99가9999", sc.neighbor)
    for body in (_body(sc, offer_id=999999), _body(sc, vehicle_id=others.id)):
        res = await client.post("/api/v1/share-requests", json=body, headers=auth_headers(sc.me))
        assert res.status_code == 404
        assert_error(res, ErrorCode.NOT_FOUND)


async def test_create_time_conflict(client, db, sc):
    await make_request_on(db, sc.offer_p2, sc.neighbor.id, TOMORROW, 12, 14)

    res = await client.post("/api/v1/share-requests", json=_body(sc), headers=auth_headers(sc.me))

    assert res.status_code == 409
    assert_error(res, ErrorCode.GARAGE_TIME_CONFLICT, "요청한 시간에 이미 다른 예약이 있습니다.")


async def test_create_insufficient_tokens(client, db, sc):
    poor = await make_resident(db, "poor@example.com", sc.mine, token_balance=4)

    res = await client.post("/api/v1/share-requests", json=_body(sc, vehicle_id=None), headers=auth_headers(poor))

    assert res.status_code == 409
    error = assert_error(res, ErrorCode.INSUFFICIENT_TOKENS, "토큰이 부족합니다.")
    assert error["detail"] == {"required": 6, "balance": 4}


async def test_create_requires_auth(client, sc):
    res = await client.post("/api/v1/share-requests", json=_body(sc))

    assert res.status_code == 401
    assert_error(res, ErrorCode.UNAUTHORIZED)


async def test_get_and_list_mine(client, db, sc):
    created = (await client.post("/api/v1/share-requests", json=_body(sc), headers=auth_headers(sc.me))).json()
    accepted = await make_request_on(db, sc.offer_p3, sc.me.id, TOMORROW, 15, 17)
    rejected = await make_request_on(db, sc.offer_p3, sc.me.id, TOMORROW, 18, 19, status=ShareRequestStatus.REJECTED)
    rejected.reject_reason = "시간 불가"
    await db.commit()

    res = await client.get(f"/api/v1/share-requests/{created['id']}", headers=auth_headers(sc.me))

    assert res.status_code == 200
    body = res.json()
    assert body["id"] == created["id"] and body["status"] == "PENDING" and body["reject_reason"] is None
    assert body["garage"] == {"id": sc.next_door.id, "name": "햇살빌라"}
    assert body["slot_id"] == sc.p2.id and body["slot_label"] == "P2"
    assert body["request_date"] == TOMORROW.isoformat()
    assert (body["start_hour"], body["end_hour"], body["total_price"]) == (10, 13, 6)

    res = await client.get("/api/v1/me/share-requests", headers=auth_headers(sc.me))

    assert res.status_code == 200
    items = res.json()["items"]
    assert [(i["id"], i["status"], i["slot_label"]) for i in items] == [
        (rejected.id, "REJECTED", "P3"),
        (accepted.id, "APPROVED", "P3"),
        (created["id"], "PENDING", "P2"),
    ]
    assert items[0]["reject_reason"] == "시간 불가"
    assert res.json()["next_cursor"] is None


async def test_get_others_request_is_not_found(client, db, sc):
    created = (await client.post("/api/v1/share-requests", json=_body(sc), headers=auth_headers(sc.me))).json()
    stranger = await make_resident(db, "stranger@example.com", sc.mine)

    for rid in (created["id"], 999999):
        res = await client.get(f"/api/v1/share-requests/{rid}", headers=auth_headers(stranger))
        assert res.status_code == 404
        assert_error(res, ErrorCode.NOT_FOUND)
    mine = await client.get("/api/v1/me/share-requests", headers=auth_headers(stranger))
    assert mine.json()["items"] == []


async def test_list_mine_invalid_limit_and_auth(client, sc):
    res = await client.get("/api/v1/me/share-requests", params={"limit": 0}, headers=auth_headers(sc.me))
    assert res.status_code == 400
    assert_error(res, ErrorCode.INVALID_INPUT)

    for url in ("/api/v1/me/share-requests", "/api/v1/share-requests/1"):
        res = await client.get(url)
        assert res.status_code == 401
        assert_error(res, ErrorCode.UNAUTHORIZED)
