"""#8 주차 배치·출차 API: POST /parkings, PUT /parkings/{parking_id}/schedule, POST /parkings/{parking_id}/exit."""

from datetime import datetime, timedelta

import pytest

from app.core.error_codes import ErrorCode
from app.schemas.common import KST
from tests.factories import make_alley, make_building, make_garage, make_resident, make_slot, make_vehicle
from tests.factories_parking import make_assignment
from tests.helpers import assert_error, auth_headers

pytestmark = pytest.mark.anyio

BASE = "/api/v1/parkings"


def _later(hours: int = 3) -> str:
    """지금부터 hours 시간 뒤 (초 단위 없이, +09:00)."""
    at = datetime.now(KST).replace(second=0, microsecond=0) + timedelta(hours=hours)
    return at.isoformat()


@pytest.fixture
async def setup(db):
    building = await make_building(db)
    garage = await make_garage(db, building, name="필로티 안쪽")
    inner, outer = await make_slot(db, garage, 1), await make_slot(db, garage, 2)
    inner.front_slot_id = outer.id
    await db.commit()
    me = await make_resident(db, "me@example.com", building)
    neighbor = await make_resident(db, "neighbor@example.com", building)
    return {
        "inner": inner,
        "outer": outer,
        "me": me,
        "neighbor": neighbor,
        "my_car": await make_vehicle(db, "12가3456", owner=me),
        "neighbor_car": await make_vehicle(db, "34나5678", owner=neighbor),
    }


async def _park(client, user, slot, vehicle, **body):
    body.setdefault("expected_exit_at", _later())
    return await client.post(BASE, json={"slot_id": slot.id, "vehicle_id": vehicle.id, **body}, headers=auth_headers(user))


@pytest.mark.parametrize(("method", "path"), [("POST", BASE), ("PUT", f"{BASE}/1/schedule"), ("POST", f"{BASE}/1/exit")])
async def test_requires_login(client, method, path):
    res = await client.request(method, path, json={})
    assert res.status_code == 401
    assert_error(res, ErrorCode.UNAUTHORIZED)


# ── POST /parkings ──
async def test_create_parking(client, setup):
    exit_at = _later()
    res = await _park(client, setup["me"], setup["inner"], setup["my_car"], expected_exit_at=exit_at, memo="출근")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body == {
        "id": body["id"],
        "slot_id": setup["inner"].id,
        "state": "PARKED",
        "expected_exit_at": exit_at,
        "exit_source": "MANUAL",
        "blocking": [],
    }

    # 차량 상세에도 주차 위치와 출차 예정이 보인다
    detail = await client.get(f"/api/v1/me/vehicles/{setup['my_car'].id}", headers=auth_headers(setup["me"]))
    assert detail.json()["parking"]["parking_id"] == body["id"]
    assert detail.json()["parking"]["slot_label"] == "P1"
    assert detail.json()["schedule"]["expected_exit_at"] == exit_at
    assert detail.json()["schedule"]["exit_source"] == "MANUAL"
    assert detail.json()["schedule"]["memo"] == "출근"  # 배치할 때 적은 메모 (#33)


async def test_create_long_term(client, setup):
    res = await client.post(
        BASE,
        json={"slot_id": setup["inner"].id, "vehicle_id": setup["my_car"].id, "is_long_term": True},
        headers=auth_headers(setup["me"]),
    )
    assert res.status_code == 201, res.text
    assert (res.json()["expected_exit_at"], res.json()["exit_source"]) == (None, "NONE")


@pytest.mark.parametrize(
    "body",
    [
        {},  # slot_id, vehicle_id 없음
        {"slot_id": 1, "vehicle_id": 1},  # 상시 주차가 아닌데 출차 시간이 없음
        {"slot_id": 1, "vehicle_id": 1, "expected_exit_at": "내일"},
    ],
)
async def test_create_invalid_input(client, setup, body):
    res = await client.post(BASE, json=body, headers=auth_headers(setup["me"]))
    assert res.status_code == 400
    assert_error(res, ErrorCode.INVALID_INPUT)


async def test_create_past_exit_time(client, setup):
    res = await _park(client, setup["me"], setup["inner"], setup["my_car"], expected_exit_at=_later(-1))
    assert res.status_code == 400
    assert assert_error(res, ErrorCode.INVALID_INPUT)["detail"]["field"] == "expected_exit_at"


async def test_create_not_found(client, setup):
    not_mine = await _park(client, setup["me"], setup["inner"], setup["neighbor_car"])
    assert not_mine.status_code == 404
    assert_error(not_mine, ErrorCode.NOT_FOUND)

    no_slot = await client.post(
        BASE,
        json={"slot_id": 99999, "vehicle_id": setup["my_car"].id, "expected_exit_at": _later()},
        headers=auth_headers(setup["me"]),
    )
    assert no_slot.status_code == 404
    assert_error(no_slot, ErrorCode.NOT_FOUND)


async def test_create_other_building_slot(client, db, setup):
    other = await make_building(db, "INV002", "옆 빌라", alley=await make_alley(db, "다른 골목"))
    other_slot = await make_slot(db, await make_garage(db, other))

    res = await _park(client, setup["me"], other_slot, setup["my_car"])
    assert res.status_code == 403
    assert_error(res, ErrorCode.NOT_BUILDING_MEMBER)


async def test_create_conflicts(client, db, setup):
    setup["inner"].is_active = False
    await db.commit()
    inactive = await _park(client, setup["me"], setup["inner"], setup["my_car"])
    assert inactive.status_code == 409
    error = assert_error(inactive, ErrorCode.SLOT_UNAVAILABLE, "해당 칸을 사용할 수 없습니다.")
    assert error["detail"] == {"reason": "관리인이 사용 중지한 칸"}

    assignment = await make_assignment(db, setup["outer"], setup["neighbor_car"])
    occupied = await _park(client, setup["me"], setup["outer"], setup["my_car"])
    assert occupied.status_code == 409
    assert_error(occupied, ErrorCode.SLOT_OCCUPIED, "이미 다른 차량이 주차 중인 칸입니다.")

    setup["inner"].is_active = True
    await db.commit()
    parked = await _park(client, setup["neighbor"], setup["inner"], setup["neighbor_car"])
    assert parked.status_code == 409
    error = assert_error(parked, ErrorCode.VEHICLE_ALREADY_PARKED, "이미 주차 중인 차량입니다.")
    assert error["detail"] == {"parking_id": assignment.id}


# ── PUT /parkings/{parking_id}/schedule ──
async def test_update_schedule(client, setup):
    parking = (await _park(client, setup["me"], setup["inner"], setup["my_car"])).json()
    new_exit = _later(5)

    res = await client.put(
        f"{BASE}/{parking['id']}/schedule",
        json={"expected_exit_at": new_exit, "memo": "늦게 출근"},
        headers=auth_headers(setup["me"]),
    )
    assert res.status_code == 200, res.text
    assert res.json() == {
        "parking_id": parking["id"],
        "expected_exit_at": new_exit,
        "exit_source": "MANUAL",
        "memo": "늦게 출근",
    }

    # 출차 일정 수정 화면에서 다시 볼 수 있다 (#33). 메모 없이 수정하면 비워진다
    url = f"/api/v1/me/vehicles/{setup['my_car'].id}"
    assert (await client.get(url, headers=auth_headers(setup["me"]))).json()["schedule"]["memo"] == "늦게 출근"
    await client.put(
        f"{BASE}/{parking['id']}/schedule", json={"expected_exit_at": new_exit}, headers=auth_headers(setup["me"])
    )
    assert (await client.get(url, headers=auth_headers(setup["me"]))).json()["schedule"]["memo"] is None


async def test_update_schedule_earlier_sends_block_alert(client, setup):
    mine = (await _park(client, setup["me"], setup["inner"], setup["my_car"], expected_exit_at=_later(6))).json()
    await _park(client, setup["neighbor"], setup["outer"], setup["neighbor_car"], expected_exit_at=_later(4))

    res = await client.put(
        f"{BASE}/{mine['id']}/schedule", json={"expected_exit_at": _later(2)}, headers=auth_headers(setup["me"])
    )
    assert res.status_code == 200, res.text

    items = (await client.get("/api/v1/notifications", headers=auth_headers(setup["neighbor"]))).json()["items"]
    assert [(n["type"], n["title"], n["link"]) for n in items] == [
        ("BLOCK_ALERT", "막힘 알림", {"screen": "HOME", "id": None})
    ]


async def test_update_schedule_errors(client, setup):
    parking = (await _park(client, setup["me"], setup["inner"], setup["my_car"])).json()
    url = f"{BASE}/{parking['id']}/schedule"

    missing = await client.put(url, json={}, headers=auth_headers(setup["me"]))
    assert missing.status_code == 400
    assert_error(missing, ErrorCode.INVALID_INPUT)

    past = await client.put(url, json={"expected_exit_at": _later(-1)}, headers=auth_headers(setup["me"]))
    assert past.status_code == 400
    assert_error(past, ErrorCode.INVALID_INPUT)

    # 남의 주차 건·없는 주차 건은 구분 없이 404
    for target, user in ((url, setup["neighbor"]), (f"{BASE}/99999/schedule", setup["me"])):
        res = await client.put(target, json={"expected_exit_at": _later()}, headers=auth_headers(user))
        assert res.status_code == 404
        assert_error(res, ErrorCode.NOT_FOUND)


# ── POST /parkings/{parking_id}/exit ──
async def test_exit(client, setup):
    parking = (await _park(client, setup["me"], setup["inner"], setup["my_car"])).json()

    forbidden = await client.post(f"{BASE}/{parking['id']}/exit", headers=auth_headers(setup["neighbor"]))
    assert forbidden.status_code == 404
    assert_error(forbidden, ErrorCode.NOT_FOUND)

    res = await client.post(f"{BASE}/{parking['id']}/exit", headers=auth_headers(setup["me"]))
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["id"], body["state"], body["on_time"]) == (parking["id"], "EXITED", True)
    assert body["actual_exit_at"].endswith("+09:00")

    # 같은 빌라 입주민에게 출차 완료 알림, 차량은 다시 "외부 출차"
    items = (await client.get("/api/v1/notifications", headers=auth_headers(setup["neighbor"]))).json()["items"]
    assert [(n["type"], n["title"], n["body"], n["link"]) for n in items] == [
        ("EXIT_DONE", "출차 완료 안내", "P1 비어 있음", None)
    ]
    vehicles = (await client.get("/api/v1/me/vehicles", headers=auth_headers(setup["me"]))).json()["items"]
    assert vehicles[0]["status"] == "OUT"

    again = await client.post(f"{BASE}/{parking['id']}/exit", headers=auth_headers(setup["me"]))
    assert again.status_code == 404
    assert_error(again, ErrorCode.NOT_FOUND)

    # 출차한 칸에는 다시 세울 수 있다
    assert (await _park(client, setup["me"], setup["inner"], setup["my_car"])).status_code == 201
