"""#9 API: GET /buildings/{id}/layout, /status, /slots/recommendations, GET /me/home."""

from datetime import datetime, timedelta

import pytest

from app.core.error_codes import ErrorCode
from app.models.resident import ResidentRole
from app.schemas.common import KST
from tests.factories import make_alley, make_building, make_resident, make_vehicle
from tests.factories_parking import make_assignment, make_departure, make_spec_building
from tests.helpers import assert_error, auth_headers

pytestmark = pytest.mark.anyio

API = "/api/v1"


def _later(hours: int) -> datetime:
    return datetime.now(KST).replace(second=0, microsecond=0) + timedelta(hours=hours)


@pytest.fixture
async def villa(db):
    """P1 에 내 차(5시간 뒤 출차), 앞 칸 P2 에 이웃 차(8시간 뒤 출차). 나머지는 비어 있고 P5 는 사용 중지."""
    v = await make_spec_building(db)
    v["me"] = await make_resident(db, "me@example.com", v["building"])
    v["neighbor"] = await make_resident(db, "neighbor@example.com", v["building"])
    v["manager"] = await make_resident(db, "manager@example.com", v["building"], role=ResidentRole.MANAGER)
    other = await make_building(db, "INV002", "옆 빌라", alley=await make_alley(db, "다른 골목"))
    v["outsider"] = await make_resident(db, "outsider@example.com", other)
    v["my_car"] = await make_vehicle(db, "12가3456", owner=v["me"])
    v["spare_car"] = await make_vehicle(db, "78나9012", owner=v["me"])
    neighbor_car = await make_vehicle(db, "34나5678", owner=v["neighbor"])
    v["my_parking"] = await make_assignment(db, v["P1"], v["my_car"])
    v["neighbor_parking"] = await make_assignment(db, v["P2"], neighbor_car)
    mine, theirs = _later(5), _later(8)
    await make_departure(db, v["my_car"], mine.date(), mine.time())
    await make_departure(db, neighbor_car, theirs.date(), theirs.time())
    v["my_exit"] = mine
    return v


def _url(villa, path: str) -> str:
    return f"{API}/buildings/{villa['building'].id}/{path}"


# ── 권한 (세 엔드포인트 공통) ──
@pytest.mark.parametrize("path", ["layout", "status", "slots/recommendations?vehicle_id=1"])
async def test_building_endpoints_permissions(client, villa, path):
    unauthorized = await client.get(_url(villa, path))
    assert unauthorized.status_code == 401
    assert_error(unauthorized, ErrorCode.UNAUTHORIZED)

    forbidden = await client.get(_url(villa, path), headers=auth_headers(villa["outsider"]))
    assert forbidden.status_code == 403
    assert_error(forbidden, ErrorCode.NOT_BUILDING_MEMBER)

    missing = await client.get(f"{API}/buildings/99999/{path}", headers=auth_headers(villa["me"]))
    assert missing.status_code == 404
    assert_error(missing, ErrorCode.NOT_FOUND)


# ── 배치도 ──
async def test_layout(client, villa):
    res = await client.get(_url(villa, "layout"), headers=auth_headers(villa["me"]))
    assert res.status_code == 200, res.text
    body = res.json()

    assert set(body) == {"building_id", "name", "site_key", "alley", "zones"}
    assert (body["building_id"], body["name"]) == (villa["building"].id, "월계 한빛빌라")
    assert body["site_key"] is None  # 사이트 파일이 없는 빌라 → FE 가 rect 로 그린다
    assert body["alley"] == {"id": villa["alley"].id, "name": "광운로19가길"}
    assert [(z["name"], z["zone_type"]) for z in body["zones"]] == [
        ("필로티 안쪽", "PILOTI_IN"),
        ("필로티 외부", "PILOTI_OUT"),
        ("건물 앞", "PILOTI_OUT"),
        ("골목", "ROADSIDE"),
    ]
    first = body["zones"][0]["slots"][0]
    assert first == {
        "id": villa["P1"].id,
        "number": 1,
        "label": "P1",
        "front_slot_id": villa["P2"].id,
        "is_active": True,
        "rect": {"x0": 1.0, "y0": 0.0, "x1": 3.5, "y1": 5.0},
    }
    assert [s["label"] for z in body["zones"] for s in z["slots"]] == [f"P{i}" for i in range(1, 9)]


# ── 실시간 현황 ──
async def test_status(client, villa):
    res = await client.get(_url(villa, "status"), headers=auth_headers(villa["me"]))
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["updated_at"].endswith("+09:00")
    slots = body["slots"]
    assert [s["slot_id"] for s in slots] == [villa[f"P{i}"].id for i in range(1, 9)]
    assert [s["state"] for s in slots] == [
        "OCCUPIED", "OCCUPIED", "EMPTY", "EMPTY", "UNAVAILABLE", "EMPTY", "EMPTY", "EMPTY",
    ]  # fmt: skip
    assert slots[0] == {
        "slot_id": villa["P1"].id,
        "state": "OCCUPIED",
        "parking": {
            "id": villa["my_parking"].id,
            "is_mine": True,
            "plate": "12가 3456",
            "occupant_type": "RESIDENT",
            "expected_exit_at": villa["my_exit"].isoformat(),
            "exit_source": "MANUAL",
        },
        "blocked_by": [villa["P2"].id],
        "blocking": [],
    }
    assert (slots[1]["parking"]["is_mine"], slots[1]["blocking"]) == (False, [villa["P1"].id])
    assert slots[2] == {"slot_id": villa["P3"].id, "state": "EMPTY", "parking": None, "blocked_by": [], "blocking": []}

    # 같은 빌라의 다른 입주민에게는 is_mine 이 반대
    neighbor = await client.get(_url(villa, "status"), headers=auth_headers(villa["neighbor"]))
    assert [s["parking"]["is_mine"] for s in neighbor.json()["slots"][:2]] == [False, True]


# ── 배치 추천 ──
async def test_recommendations(client, villa):
    res = await client.get(
        _url(villa, "slots/recommendations"),
        params={"vehicle_id": villa["spare_car"].id, "expected_exit_at": _later(3).isoformat()},
        headers=auth_headers(villa["me"]),
    )
    assert res.status_code == 200, res.text
    slots = {s["label"]: s for s in res.json()["slots"]}

    assert list(slots) == [f"P{i}" for i in range(1, 9)]
    assert slots["P1"] == {"slot_id": villa["P1"].id, "tag": "OCCUPIED", "label": "P1"}
    assert slots["P5"] == {
        "slot_id": villa["P5"].id,
        "tag": "UNAVAILABLE",
        "label": "P5",
        "unavailable_reason": "관리인이 사용 중지한 칸이에요",
    }
    # 가장 안쪽 빈 칸은 P7 (앞 칸 P8). P4 의 앞 칸 P5 는 사용 중지 칸이라 차가 없다 → P4 도 안쪽이지만 P 번호가 빠른 쪽
    recommended = [label for label, s in slots.items() if s["tag"] == "RECOMMENDED"]
    assert recommended == ["P4"]
    assert slots["P4"]["reason"] == "앞 칸이 비어 있고 다른 차를 막지 않는 가장 안쪽 칸이에요"
    assert slots["P7"] == {"slot_id": villa["P7"].id, "tag": "EMPTY", "label": "P7", "will_block": []}


async def test_recommendations_long_term_and_errors(client, villa):
    url = _url(villa, "slots/recommendations")
    headers = auth_headers(villa["me"])

    long_term = await client.get(url, params={"vehicle_id": villa["spare_car"].id}, headers=headers)
    assert long_term.status_code == 200, long_term.text
    assert sum(s["tag"] == "RECOMMENDED" for s in long_term.json()["slots"]) == 1

    missing = await client.get(url, headers=headers)  # vehicle_id 없음
    assert missing.status_code == 400
    assert_error(missing, ErrorCode.INVALID_INPUT)

    past = await client.get(
        url, params={"vehicle_id": villa["spare_car"].id, "expected_exit_at": _later(-1).isoformat()}, headers=headers
    )
    assert past.status_code == 400
    assert_error(past, ErrorCode.INVALID_INPUT)

    not_mine = await client.get(url, params={"vehicle_id": 99999}, headers=headers)
    assert not_mine.status_code == 404
    assert_error(not_mine, ErrorCode.NOT_FOUND)


# ── 홈 ──
async def test_home(client, villa):
    res = await client.get(f"{API}/me/home", headers=auth_headers(villa["me"]))
    assert res.status_code == 200, res.text
    body = res.json()

    assert set(body) == {
        "building", "unread_notification_count", "summary", "my_parking", "block_alert", "admin", "recent_notifications",
    }  # fmt: skip
    assert body["building"] == {"id": villa["building"].id, "name": "월계 한빛빌라", "role": "RESIDENT"}
    assert body["summary"] == {"available": 5, "soon_exit": 0, "blocked": 1, "empty": 5}
    assert body["my_parking"] == {
        "parking_id": villa["my_parking"].id,
        "vehicle": {"id": villa["my_car"].id, "plate": "12가 3456", "color": None},
        "slot_label": "P1",
        "state": "PARKED",
        "expected_exit_at": villa["my_exit"].isoformat(),
    }
    assert body["block_alert"] == {
        "blocking_parking_id": villa["neighbor_parking"].id,
        "message": "내 차량이 P2 차량에 의해 막혀 있습니다.",
    }
    assert body["admin"] is None
    assert (body["unread_notification_count"], body["recent_notifications"]) == (0, [])


async def test_home_for_manager_and_without_building(client, db, villa):
    manager = await client.get(f"{API}/me/home", headers=auth_headers(villa["manager"]))
    assert manager.status_code == 200, manager.text
    assert manager.json()["building"]["role"] == "ADMIN"
    assert manager.json()["admin"] == {"pending_share_requests": 0}
    assert (manager.json()["my_parking"], manager.json()["block_alert"]) == (None, None)

    loner = await make_resident(db, "loner@example.com")
    forbidden = await client.get(f"{API}/me/home", headers=auth_headers(loner))
    assert forbidden.status_code == 403
    assert_error(forbidden, ErrorCode.NOT_BUILDING_MEMBER)

    unauthorized = await client.get(f"{API}/me/home")
    assert unauthorized.status_code == 401
    assert_error(unauthorized, ErrorCode.UNAUTHORIZED)
