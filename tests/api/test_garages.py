"""차고지 API: GET /garages, GET /garages/{garage_id}. 시간에 따라 바뀌는 규칙은 tests/services/test_garages.py 에서 본다."""

from datetime import date

import pytest

from app.core.error_codes import ErrorCode
from tests.factories import make_share_offer
from tests.factories_share import make_scenario
from tests.helpers import assert_error, auth_headers

pytestmark = pytest.mark.anyio


@pytest.fixture
async def sc(db):
    sc = await make_scenario(db)
    # 언제 돌려도 "지금 이용 가능" 이 되도록 매일 0~24시로 연다
    for offer in (sc.offer_p2, sc.offer_p3):
        offer.start_date, offer.end_date, offer.start_hour, offer.end_hour = date(2026, 1, 1), date(9999, 12, 31), 0, 24
    sc.offer_p3.hourly_price = 0
    await db.commit()
    return sc


async def test_list(client, sc):
    res = await client.get("/api/v1/garages", headers=auth_headers(sc.me))

    assert res.status_code == 200
    body = res.json()
    assert body["next_cursor"] is None
    assert [item["slot_id"] for item in body["items"]] == [sc.p3.id, sc.p2.id]
    p2 = body["items"][1]
    assert p2["garage_id"] == sc.next_door.id and p2["building_name"] == "햇살빌라"
    assert p2["slot_label"] == "P2" and p2["title"] == "햇살빌라 · P2"
    assert p2["availability"] == "AVAILABLE" and p2["hourly_price"] == 2 and p2["max_hours"] == 4
    assert p2["weekdays_only"] is False and p2["estimated_free_at"] is None and p2["estimate_source"] is None
    assert p2["info"].startswith("지금 이용 가능")


async def test_list_filter_query_and_pagination(client, sc):
    headers = auth_headers(sc.me)

    free = await client.get("/api/v1/garages", params={"filter": "free"}, headers=headers)
    assert [item["slot_id"] for item in free.json()["items"]] == [sc.p3.id]
    found = await client.get("/api/v1/garages", params={"q": "햇살", "lat": 37.62, "lng": 127.06}, headers=headers)
    assert len(found.json()["items"]) == 2
    page = await client.get("/api/v1/garages", params={"limit": 1}, headers=headers)
    assert page.json()["next_cursor"] == str(sc.p3.id)
    rest = await client.get("/api/v1/garages", params={"limit": 1, "cursor": str(sc.p3.id)}, headers=headers)
    assert [item["slot_id"] for item in rest.json()["items"]] == [sc.p2.id]


@pytest.mark.parametrize(
    "params", [{"filter": "cheap"}, {"limit": 51}, {"cursor": "abc"}, {"lat": 37.62}, {"lat": "north", "lng": 1}]
)
async def test_list_invalid_input(client, sc, params):
    res = await client.get("/api/v1/garages", params=params, headers=auth_headers(sc.me))

    assert res.status_code == 400
    assert_error(res, ErrorCode.INVALID_INPUT)


async def test_list_requires_auth(client, sc):
    res = await client.get("/api/v1/garages")

    assert res.status_code == 401
    assert_error(res, ErrorCode.UNAUTHORIZED)


async def test_detail(client, db, sc):
    await make_share_offer(
        db, sc.p1, sc.host, hourly_price=1, start_hour=7, end_hour=23, max_hours=6, end_date=date(9999, 12, 31)
    )

    res = await client.get(f"/api/v1/garages/{sc.next_door.id}", headers=auth_headers(sc.me))

    assert res.status_code == 200
    body = res.json()
    assert body["id"] == sc.next_door.id and body["name"] == "햇살빌라" and body["address"]
    assert body["site_key"] is None
    assert body["alley"] == {"id": sc.alley.id, "name": sc.alley.name}
    assert body["summary"] == {"start_hour": 0, "end_hour": 24, "min_hourly_price": 0, "max_hours": 6}
    assert [(s["slot_id"], s["label"]) for s in body["slots"]] == [(sc.p1.id, "P1"), (sc.p2.id, "P2"), (sc.p3.id, "P3")]
    p2 = body["slots"][1]
    assert p2["zone"] == {"id": sc.zone_a.id, "name": "골목"} and p2["number"] == 2
    assert p2["state"] == "AVAILABLE" and p2["estimated_free_at"] is None and p2["in_use_until"] is None
    assert p2["offer"]["id"] == sc.offer_p2.id
    assert p2["offer"]["weekdays"] == ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    assert (p2["offer"]["start_hour"], p2["offer"]["end_hour"], p2["offer"]["hourly_price"]) == (0, 24, 2)
    assert p2["offer"]["max_hours"] == 4 and "memo" in p2["offer"]


async def test_detail_not_found(client, sc):
    for garage_id in (sc.far.id, sc.mine.id, 999999):
        res = await client.get(f"/api/v1/garages/{garage_id}", headers=auth_headers(sc.me))
        assert res.status_code == 404
        assert_error(res, ErrorCode.NOT_FOUND)


async def test_detail_requires_auth(client, sc):
    res = await client.get(f"/api/v1/garages/{sc.next_door.id}")

    assert res.status_code == 401
    assert_error(res, ErrorCode.UNAUTHORIZED)
