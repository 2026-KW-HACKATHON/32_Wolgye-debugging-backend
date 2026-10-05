"""#10 이동 요청 API와 규칙: POST /move-requests, GET /move-requests/{id}, POST /move-requests/{id}/done, GET /me/move-requests."""

from datetime import datetime

import pytest
from sqlalchemy import select

from app.core.error_codes import ErrorCode
from app.models.move_request import MoveRequest, MoveRequestStatus
from app.models.resident import ResidentRole
from app.schemas.common import KST
from app.services.move_requests import anonymous_label
from tests.factories import make_alley, make_building, make_resident, make_vehicle
from tests.factories_parking import make_assignment, make_spec_building
from tests.helpers import assert_error, auth_headers

pytestmark = pytest.mark.anyio

API = "/api/v1"
NEEDED_AT = "2026-09-30T15:00:00+09:00"


@pytest.mark.parametrize(
    ("unit_no", "expected"),
    [("101동 202호", "101동 입주민"), ("3동", "3동 입주민"), ("202호", "입주민"), (None, "입주민"), ("", "입주민")],
)
def test_anonymous_label(unit_no, expected):
    assert anonymous_label(unit_no) == expected


@pytest.fixture
async def villa(db):
    """P1 에 내 차, 앞 칸 P2 에 이웃 차, P3 에 외부 차량, P6 에 미확인 차량."""
    v = await make_spec_building(db)
    v["me"] = await make_resident(db, "me@example.com", v["building"])
    v["me"].unit_no = "101동 202호"
    v["neighbor"] = await make_resident(db, "neighbor@example.com", v["building"])
    v["neighbor"].unit_no = "101동 302호"
    v["manager"] = await make_resident(db, "manager@example.com", v["building"], role=ResidentRole.MANAGER)
    other = await make_building(db, "INV002", "옆 빌라", alley=await make_alley(db, "다른 골목"))
    v["outsider"] = await make_resident(db, "outsider@example.com", other)
    await db.commit()

    my_car = await make_vehicle(db, "12가3456", owner=v["me"])
    neighbor_car = await make_vehicle(db, "34나5678", owner=v["neighbor"])
    outsider_car = await make_vehicle(db, "56다1234", owner=v["outsider"])
    unknown_car = await make_vehicle(db, "99하9999")
    v["my_parking"] = await make_assignment(db, v["P1"], my_car)
    v["neighbor_parking"] = await make_assignment(
        db, v["P2"], neighbor_car, assigned_at=datetime(2026, 9, 30, 12, 10, tzinfo=KST)
    )
    v["outsider_parking"] = await make_assignment(db, v["P3"], outsider_car)
    v["unknown_parking"] = await make_assignment(db, v["P6"], unknown_car)
    return v


async def _request(client, user, parking, **body):
    payload = {"target_parking_id": parking.id, "needed_at": NEEDED_AT, **body}
    return await client.post(f"{API}/move-requests", json=payload, headers=auth_headers(user))


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/move-requests"),
        ("GET", "/move-requests/1"),
        ("POST", "/move-requests/1/done"),
        ("GET", "/me/move-requests?box=received"),
    ],
)
async def test_requires_login(client, method, path):
    res = await client.request(method, f"{API}{path}", json={})
    assert res.status_code == 401
    assert_error(res, ErrorCode.UNAUTHORIZED)


# ── POST /move-requests ──
async def test_create_saves_request_and_notifies_owner(client, db, villa):
    res = await _request(client, villa["me"], villa["neighbor_parking"], reason="외출 예정으로 출차가 필요합니다.")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body == {"id": body["id"], "status": "PENDING"}

    saved = await db.get(MoveRequest, body["id"])
    assert (saved.requester_id, saved.target_vehicle_id, saved.blocked_vehicle_id) == (
        villa["me"].id,
        villa["neighbor_parking"].vehicle_id,
        villa["my_parking"].vehicle_id,  # 막힌 차 = 요청자가 지금 세워 둔 차
    )
    assert saved.needed_by == datetime(2026, 9, 30, 15, 0, tzinfo=KST)

    # 수신자(그 차 주인)에게만 MOVE_REQUEST 알림. 요청자는 동까지만 표시
    items = (await client.get(f"{API}/notifications", headers=auth_headers(villa["neighbor"]))).json()["items"]
    assert [(n["type"], n["title"], n["body"], n["link"]) for n in items] == [
        ("MOVE_REQUEST", "주차 요청 도착", "101동 입주민", {"screen": "MOVE_REQUEST", "id": body["id"]})
    ]
    mine = (await client.get(f"{API}/notifications", headers=auth_headers(villa["me"]))).json()["items"]
    assert mine == []


async def test_create_invalid_input(client, villa):
    headers = auth_headers(villa["me"])
    missing = await client.post(f"{API}/move-requests", json={"target_parking_id": 1}, headers=headers)
    assert missing.status_code == 400
    assert_error(missing, ErrorCode.INVALID_INPUT)

    unknown = await _request(client, villa["me"], villa["unknown_parking"])
    assert unknown.status_code == 400
    error = assert_error(unknown, ErrorCode.INVALID_INPUT, "앱으로 연락할 수 없는 차량입니다.")
    assert error["detail"] == {"reason": "UNKNOWN_VEHICLE"}

    own = await _request(client, villa["me"], villa["my_parking"])
    assert own.status_code == 400
    assert_error(own, ErrorCode.INVALID_INPUT)


async def test_create_not_found_for_missing_or_exited_parking(client, db, villa):
    missing = await client.post(
        f"{API}/move-requests",
        json={"target_parking_id": 99999, "needed_at": NEEDED_AT},
        headers=auth_headers(villa["me"]),
    )
    assert missing.status_code == 404
    assert_error(missing, ErrorCode.NOT_FOUND)

    parking = villa["neighbor_parking"]
    parking.is_active, parking.released_at = False, datetime.now(KST)
    await db.commit()
    exited = await _request(client, villa["me"], parking)
    assert exited.status_code == 404
    assert_error(exited, ErrorCode.NOT_FOUND)


async def test_create_permissions(client, villa):
    # 다른 빌라 사람은 이 빌라 차에 요청할 수 없다
    outsider = await _request(client, villa["outsider"], villa["neighbor_parking"])
    assert outsider.status_code == 403
    assert_error(outsider, ErrorCode.NOT_BUILDING_MEMBER)

    # 입주민은 외부 차량에 요청할 수 없고, 관리인은 할 수 있다
    resident = await _request(client, villa["me"], villa["outsider_parking"])
    assert resident.status_code == 403
    assert_error(resident, ErrorCode.NOT_BUILDING_MEMBER)

    manager = await _request(client, villa["manager"], villa["outsider_parking"])
    assert manager.status_code == 201, manager.text


async def test_create_already_pending(client, villa):
    first = (await _request(client, villa["me"], villa["neighbor_parking"])).json()

    again = await _request(client, villa["manager"], villa["neighbor_parking"])
    assert again.status_code == 409
    error = assert_error(again, ErrorCode.MOVE_REQUEST_ALREADY_PENDING, "이 차량에 대기 중인 이동 요청이 이미 있습니다.")
    assert error["detail"] == {"move_request_id": first["id"]}

    # 처리되면 다시 요청할 수 있다
    await client.post(f"{API}/move-requests/{first['id']}/done", headers=auth_headers(villa["neighbor"]))
    assert (await _request(client, villa["manager"], villa["neighbor_parking"])).status_code == 201


# ── GET /move-requests/{id} ──
async def test_detail_for_receiver_and_requester(client, villa):
    created = (
        await _request(client, villa["me"], villa["neighbor_parking"], reason="외출 예정으로 출차가 필요합니다.")
    ).json()

    res = await client.get(f"{API}/move-requests/{created['id']}", headers=auth_headers(villa["neighbor"]))
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body) == {
        "id", "status", "requested_at", "responded_at", "requester", "my_vehicle", "blocked_vehicle", "reason",
    }  # fmt: skip
    assert body["responded_at"] is None  # 아직 PENDING
    assert (body["id"], body["status"], body["reason"]) == (created["id"], "PENDING", "외출 예정으로 출차가 필요합니다.")
    assert body["requested_at"].endswith("+09:00")
    assert body["requester"] == {"label": "101동 입주민"}  # 동까지만
    assert body["my_vehicle"] == {"plate": "34나 5678", "slot_label": "P2", "parked_at": "2026-09-30T12:10:00+09:00"}
    assert body["blocked_vehicle"] == {"plate": "12가 3456", "slot_label": "P1", "needed_at": NEEDED_AT}

    # 요청자도 볼 수 있고, 관계없는 사람에게는 없는 것처럼 보인다
    assert (await client.get(f"{API}/move-requests/{created['id']}", headers=auth_headers(villa["me"]))).status_code == 200
    for user, request_id in ((villa["manager"], created["id"]), (villa["me"], 99999)):
        res = await client.get(f"{API}/move-requests/{request_id}", headers=auth_headers(user))
        assert res.status_code == 404
        assert_error(res, ErrorCode.NOT_FOUND)


async def test_detail_without_blocked_vehicle(client, villa):
    """관리인이 외부 차량에 보낸 요청은 막힌 차가 없다."""
    created = (await _request(client, villa["manager"], villa["outsider_parking"])).json()

    body = (await client.get(f"{API}/move-requests/{created['id']}", headers=auth_headers(villa["outsider"]))).json()
    assert body["blocked_vehicle"] is None
    assert body["requester"] == {"label": "입주민"}  # 동 정보가 없으면 "입주민"
    assert (body["my_vehicle"]["plate"], body["my_vehicle"]["slot_label"]) == ("56다 1234", "P3")


# ── POST /move-requests/{id}/done ──
async def test_done(client, db, villa):
    created = (await _request(client, villa["me"], villa["neighbor_parking"])).json()
    url = f"{API}/move-requests/{created['id']}/done"

    # 요청자는 "옮겼어요"를 누를 수 없다 (받은 사람만)
    requester = await client.post(url, headers=auth_headers(villa["me"]))
    assert requester.status_code == 404
    assert_error(requester, ErrorCode.NOT_FOUND)

    res = await client.post(url, headers=auth_headers(villa["neighbor"]))
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["id"], body["status"]) == (created["id"], "MOVED")
    assert body["responded_at"].endswith("+09:00")

    saved = await db.scalar(
        select(MoveRequest).where(MoveRequest.id == created["id"]).execution_options(populate_existing=True)
    )
    assert saved.status == MoveRequestStatus.MOVED and saved.responded_at is not None

    # 처리 완료 화면에 다시 들어와도 옮긴 시각을 알 수 있다 (#33)
    detail = (await client.get(f"{API}/move-requests/{created['id']}", headers=auth_headers(villa["me"]))).json()
    assert (detail["status"], detail["responded_at"]) == ("MOVED", body["responded_at"])

    # 결정 2: "옮겼어요" 때는 요청자에게 알림을 보내지 않는다
    assert (await client.get(f"{API}/notifications", headers=auth_headers(villa["me"]))).json()["items"] == []

    again = await client.post(url, headers=auth_headers(villa["neighbor"]))
    assert again.status_code == 409
    assert assert_error(again, ErrorCode.ALREADY_DECIDED, "이미 처리된 요청입니다.")["detail"] == {"status": "MOVED"}


# ── GET /me/move-requests ──
async def test_list_received_and_sent(client, villa):
    first = (await _request(client, villa["me"], villa["neighbor_parking"])).json()
    await client.post(f"{API}/move-requests/{first['id']}/done", headers=auth_headers(villa["neighbor"]))
    second = (await _request(client, villa["manager"], villa["neighbor_parking"])).json()

    received = await client.get(
        f"{API}/me/move-requests", params={"box": "received"}, headers=auth_headers(villa["neighbor"])
    )
    assert received.status_code == 200, received.text
    items = received.json()["items"]
    assert [(i["id"], i["status"], i["counterpart_label"]) for i in items] == [
        (second["id"], "PENDING", "입주민"),  # 최신순. 관리인은 동 정보가 없다
        (first["id"], "MOVED", "101동 입주민"),
    ]
    assert set(items[0]) == {"id", "status", "requested_at", "counterpart_label", "needed_at"}
    assert items[0]["needed_at"] == NEEDED_AT

    sent = await client.get(f"{API}/me/move-requests", params={"box": "sent"}, headers=auth_headers(villa["me"]))
    assert [(i["id"], i["counterpart_label"]) for i in sent.json()["items"]] == [(first["id"], "101동 입주민")]

    empty = await client.get(f"{API}/me/move-requests", params={"box": "sent"}, headers=auth_headers(villa["neighbor"]))
    assert empty.json() == {"items": []}


@pytest.mark.parametrize("params", [{}, {"box": "all"}])
async def test_list_requires_valid_box(client, villa, params):
    res = await client.get(f"{API}/me/move-requests", params=params, headers=auth_headers(villa["me"]))
    assert res.status_code == 400
    assert_error(res, ErrorCode.INVALID_INPUT)
