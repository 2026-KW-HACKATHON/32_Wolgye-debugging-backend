"""#7 내 차량·반복 출차 API: /me/vehicles, /me/vehicles/{vehicle_id}, /me/vehicles/{vehicle_id}/recurring-schedule."""

from datetime import date, time

import pytest

from app.core.error_codes import ErrorCode
from tests.factories import make_building, make_garage, make_resident, make_slot, make_vehicle
from tests.factories_parking import make_assignment, make_departure
from tests.helpers import assert_error, auth_headers

pytestmark = pytest.mark.anyio

BASE = "/api/v1/me/vehicles"


@pytest.fixture
async def user(db):
    return await make_resident(db, "me@example.com")


async def _create(client, user, **body) -> dict:
    res = await client.post(BASE, json=body, headers=auth_headers(user))
    assert res.status_code == 201, res.text
    return res.json()


# ── 인증 ──
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", BASE),
        ("POST", BASE),
        ("GET", f"{BASE}/1"),
        ("PATCH", f"{BASE}/1"),
        ("DELETE", f"{BASE}/1"),
        ("GET", f"{BASE}/1/recurring-schedule"),
        ("PUT", f"{BASE}/1/recurring-schedule"),
        ("DELETE", f"{BASE}/1/recurring-schedule"),
    ],
)
async def test_requires_login(client, method, path):
    res = await client.request(method, path, json={})
    assert res.status_code == 401
    assert_error(res, ErrorCode.UNAUTHORIZED)


# ── 등록·목록 ──
async def test_create_and_list(client, user):
    onboarding = await _create(client, user, plate="12가3456", color="흰색", is_default=True)
    assert onboarding == {
        "id": onboarding["id"],
        "plate": "12가 3456",
        "alias": None,
        "color": "흰색",
        "is_default": True,
        "status": "OUT",
        "status_text": "외부 출차",
    }
    added = await _create(client, user, plate="78나 9012", alias="가족 차")
    assert added["is_default"] is False and added["color"] is None

    res = await client.get(BASE, headers=auth_headers(user))
    assert res.status_code == 200
    assert [(i["plate"], i["is_default"]) for i in res.json()["items"]] == [("12가 3456", True), ("78나 9012", False)]


async def test_list_shows_only_my_vehicles(client, db, user):
    other = await make_resident(db, "other@example.com")
    await make_vehicle(db, "11가1111", owner=other)
    await make_vehicle(db, "22나2222")  # 미확인 차량

    res = await client.get(BASE, headers=auth_headers(user))
    assert res.json() == {"items": []}


@pytest.mark.parametrize(
    "body",
    [
        {},  # 번호판 없음
        {"plate": "서울12가3456"},  # 지역 번호판은 허용하지 않는다 (결정 24)
        {"plate": "12가345"},
        {"plate": "12가3456", "color": "분홍"},  # 색상 선택지 밖
        {"plate": "12가3456", "alias": "가" * 31},
    ],
)
async def test_create_invalid_input(client, user, body):
    res = await client.post(BASE, json=body, headers=auth_headers(user))
    assert res.status_code == 400
    assert_error(res, ErrorCode.INVALID_INPUT)


async def test_create_duplicate_plate(client, db, user):
    await _create(client, user, plate="12가3456")
    other = await make_resident(db, "other@example.com")

    res = await client.post(BASE, json={"plate": "12가 3456"}, headers=auth_headers(other))
    assert res.status_code == 409
    assert_error(res, ErrorCode.PLATE_EXISTS, "이미 등록된 차량 번호입니다.")


# ── 수정 ──
async def test_update(client, user):
    first = await _create(client, user, plate="12가3456", is_default=True)
    second = await _create(client, user, plate="78나9012")

    res = await client.patch(
        f"{BASE}/{second['id']}",
        json={"plate": "78나 9013", "alias": "가족 차", "is_default": True},
        headers=auth_headers(user),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["plate"], body["alias"], body["is_default"], body["status"]) == ("78나 9013", "가족 차", True, "OUT")

    items = (await client.get(BASE, headers=auth_headers(user))).json()["items"]
    assert {i["id"]: i["is_default"] for i in items} == {first["id"]: False, second["id"]: True}


async def test_update_errors(client, db, user):
    mine = await _create(client, user, plate="12가3456")
    other = await make_resident(db, "other@example.com")
    theirs = await make_vehicle(db, "78나9012", owner=other)

    invalid = await client.patch(f"{BASE}/{mine['id']}", json={"plate": "12-3456"}, headers=auth_headers(user))
    assert invalid.status_code == 400
    assert_error(invalid, ErrorCode.INVALID_INPUT)

    duplicate = await client.patch(f"{BASE}/{mine['id']}", json={"plate": "78나9012"}, headers=auth_headers(user))
    assert duplicate.status_code == 409
    assert_error(duplicate, ErrorCode.PLATE_EXISTS)

    # 남의 차량·없는 차량은 구분 없이 404
    for vehicle_id in (theirs.id, 99999):
        res = await client.patch(f"{BASE}/{vehicle_id}", json={"alias": "x"}, headers=auth_headers(user))
        assert res.status_code == 404
        assert_error(res, ErrorCode.NOT_FOUND)


# ── 상세 ──
async def test_detail(client, db):
    building = await make_building(db)
    slot = await make_slot(db, await make_garage(db, building, name="필로티 안쪽"), number=1)
    user = await make_resident(db, "me@example.com", building)
    vehicle = await make_vehicle(db, owner=user)

    out = await client.get(f"{BASE}/{vehicle.id}", headers=auth_headers(user))
    assert out.status_code == 200, out.text
    assert out.json()["parking"] is None and out.json()["schedule"] is None

    assignment = await make_assignment(db, slot, vehicle, is_permanent=True)
    parked = (await client.get(f"{BASE}/{vehicle.id}", headers=auth_headers(user))).json()
    assert parked["plate"] == "12가 3456"
    assert parked["owner"] == {"name": "me", "unit": None}
    assert parked["parking"]["parking_id"] == assignment.id
    assert parked["parking"]["slot_id"] == slot.id
    assert parked["parking"]["slot_label"] == "P1"
    assert parked["parking"]["state"] == "PARKED"
    assert parked["parking"]["entered_at"].endswith("+09:00")  # 응답 시각은 KST (결정 28)
    assert parked["schedule"]["expected_exit_at"] is None
    assert parked["schedule"]["exit_source"] == "NONE"


async def test_detail_not_mine(client, db, user):
    other = await make_resident(db, "other@example.com")
    theirs = await make_vehicle(db, owner=other)

    res = await client.get(f"{BASE}/{theirs.id}", headers=auth_headers(user))
    assert res.status_code == 404
    assert_error(res, ErrorCode.NOT_FOUND)


# ── 삭제 ──
async def test_delete(client, db):
    building = await make_building(db)
    slot = await make_slot(db, await make_garage(db, building))
    user = await make_resident(db, "me@example.com", building)
    parked = await make_vehicle(db, "12가3456", owner=user)
    free = await make_vehicle(db, "78나9012", owner=user)
    assignment = await make_assignment(db, slot, parked)

    conflict = await client.delete(f"{BASE}/{parked.id}", headers=auth_headers(user))
    assert conflict.status_code == 409
    error = assert_error(conflict, ErrorCode.VEHICLE_ALREADY_PARKED, "주차 중인 차량은 삭제할 수 없습니다.")
    assert error["detail"] == {"parking_id": assignment.id}

    ok = await client.delete(f"{BASE}/{free.id}", headers=auth_headers(user))
    assert ok.status_code == 204
    assert ok.content == b""

    again = await client.delete(f"{BASE}/{free.id}", headers=auth_headers(user))
    assert again.status_code == 404
    assert_error(again, ErrorCode.NOT_FOUND)


# ── 반복 출차 ──
async def test_recurring_schedule_flow(client, db, user):
    vehicle = await make_vehicle(db, owner=user)
    url = f"{BASE}/{vehicle.id}/recurring-schedule"

    none = await client.get(url, headers=auth_headers(user))
    assert none.status_code == 404
    assert_error(none, ErrorCode.NOT_FOUND)

    body = {"days": ["MON", "TUE", "WED", "THU", "FRI"], "time": "07:30", "memo": "출근 일정"}
    saved = await client.put(url, json=body, headers=auth_headers(user))
    assert saved.status_code == 200, saved.text
    assert saved.json() == body

    changed = await client.put(url, json={"days": ["SUN", "SAT"], "time": "10:00"}, headers=auth_headers(user))
    assert changed.json() == {"days": ["SAT", "SUN"], "time": "10:00", "memo": None}
    assert (await client.get(url, headers=auth_headers(user))).json() == changed.json()

    deleted = await client.delete(url, headers=auth_headers(user))
    assert deleted.status_code == 204
    assert (await client.get(url, headers=auth_headers(user))).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"days": [], "time": "07:30"},
        {"days": ["MON"]},
        {"days": ["MONDAY"], "time": "07:30"},
        {"days": ["MON"], "time": "7:30"},
        {"days": ["MON"], "time": "24:00"},
    ],
)
async def test_recurring_schedule_invalid_input(client, db, user, body):
    vehicle = await make_vehicle(db, owner=user)

    res = await client.put(f"{BASE}/{vehicle.id}/recurring-schedule", json=body, headers=auth_headers(user))
    assert res.status_code == 400
    assert_error(res, ErrorCode.INVALID_INPUT)


async def test_recurring_schedule_not_mine(client, db, user):
    other = await make_resident(db, "other@example.com")
    theirs = await make_vehicle(db, owner=other)
    await make_departure(db, theirs, date(2026, 9, 1), time(7, 30), repeat_weekdays=[0])
    url = f"{BASE}/{theirs.id}/recurring-schedule"

    for res in (
        await client.get(url, headers=auth_headers(user)),
        await client.put(url, json={"days": ["MON"], "time": "07:30"}, headers=auth_headers(user)),
        await client.delete(url, headers=auth_headers(user)),
    ):
        assert res.status_code == 404
        assert_error(res, ErrorCode.NOT_FOUND)


# ── 온보딩 (결정 9: onboarding_step 은 계산값) ──
async def test_first_vehicle_completes_onboarding(client, db):
    user = await make_resident(db, "me@example.com", await make_building(db))
    me = "/api/v1/users/me"

    before = await client.get(me, headers=auth_headers(user))
    assert before.json()["onboarding_step"] == "REGISTER_VEHICLE"

    vehicle = await _create(client, user, plate="12가3456", color="흰색", is_default=True)
    assert (await client.get(me, headers=auth_headers(user))).json()["onboarding_step"] == "DONE"

    # 차량을 모두 지우면 다시 등록 단계로 돌아간다
    await client.delete(f"{BASE}/{vehicle['id']}", headers=auth_headers(user))
    assert (await client.get(me, headers=auth_headers(user))).json()["onboarding_step"] == "REGISTER_VEHICLE"
