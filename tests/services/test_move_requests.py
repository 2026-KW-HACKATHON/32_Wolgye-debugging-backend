"""#10 이동 요청 서비스 규칙: 막힌 차 결정, 대기 중 요청 하나, 응답 시각 기록."""

from datetime import datetime

import pytest
from sqlalchemy import select

from app.core.error_codes import ErrorCode
from app.models.move_request import MoveRequest, MoveRequestStatus
from app.models.notification import Notification, NotificationType
from app.models.resident import ResidentRole
from app.schemas.common import KST
from app.schemas.move_request import MoveRequestBox, MoveRequestCreate
from app.services import move_requests
from app.services.exceptions import ConflictError, ForbiddenError, InvalidInputError, NotFoundError
from tests.factories import make_resident, make_vehicle
from tests.factories_parking import make_assignment, make_spec_building

pytestmark = pytest.mark.anyio

NEEDED_AT = datetime(2026, 9, 30, 15, 0, tzinfo=KST)
NOW = datetime(2026, 9, 30, 14, 41, tzinfo=KST)


@pytest.fixture
async def villa(db):
    """앞 칸 P2 에 이웃 차. 나(me)는 아직 차를 세우지 않았다."""
    v = await make_spec_building(db)
    v["me"] = await make_resident(db, "me@example.com", v["building"])
    v["neighbor"] = await make_resident(db, "neighbor@example.com", v["building"])
    v["manager"] = await make_resident(db, "manager@example.com", v["building"], role=ResidentRole.MANAGER)
    v["my_car"] = await make_vehicle(db, "12가3456", owner=v["me"])
    v["neighbor_car"] = await make_vehicle(db, "34나5678", owner=v["neighbor"])
    v["neighbor_parking"] = await make_assignment(db, v["P2"], v["neighbor_car"])
    return v


def _payload(parking, reason: str | None = None) -> MoveRequestCreate:
    return MoveRequestCreate(target_parking_id=parking.id, needed_at=NEEDED_AT, reason=reason)


async def test_blocked_vehicle_is_requesters_parked_car_or_null(db, villa):
    # 요청자가 세워 둔 차가 없으면 막힌 차는 NULL
    first = await move_requests.create(db, villa["me"], _payload(villa["neighbor_parking"]))
    saved = await db.get(MoveRequest, first.id)
    assert (saved.blocked_vehicle_id, saved.status, saved.needed_by) == (None, MoveRequestStatus.PENDING, NEEDED_AT)
    await move_requests.done(db, villa["neighbor"], first.id, now=NOW)

    # 세워 둔 차가 있으면 그 차
    await make_assignment(db, villa["P1"], villa["my_car"])
    second = await move_requests.create(db, villa["me"], _payload(villa["neighbor_parking"]))
    assert (await db.get(MoveRequest, second.id)).blocked_vehicle_id == villa["my_car"].id


async def test_create_sends_one_notification_in_same_transaction(db, villa):
    created = await move_requests.create(db, villa["me"], _payload(villa["neighbor_parking"], "나가야 해요"))

    (sent,) = (await db.scalars(select(Notification))).all()
    assert (sent.resident_id, sent.type, sent.move_request_id) == (
        villa["neighbor"].id,
        NotificationType.MOVE_REQUEST,
        created.id,
    )


async def test_only_one_pending_request_per_vehicle(db, villa):
    first = await move_requests.create(db, villa["me"], _payload(villa["neighbor_parking"]))

    with pytest.raises(ConflictError) as exc:
        await move_requests.create(db, villa["manager"], _payload(villa["neighbor_parking"]))
    assert exc.value.code == ErrorCode.MOVE_REQUEST_ALREADY_PENDING
    assert exc.value.detail == {"move_request_id": first.id}


async def test_create_rejects_unknown_own_and_external_targets(db, villa):
    unknown = await make_assignment(db, villa["P6"], await make_vehicle(db, "99하9999"))
    with pytest.raises(InvalidInputError) as exc:
        await move_requests.create(db, villa["me"], _payload(unknown))
    assert exc.value.detail == {"reason": "UNKNOWN_VEHICLE"}

    mine = await make_assignment(db, villa["P1"], villa["my_car"])
    with pytest.raises(InvalidInputError):
        await move_requests.create(db, villa["me"], _payload(mine))

    visitor = await make_resident(db, "visitor@example.com")  # 이 빌라 소속이 아닌 공유 이용자
    external = await make_assignment(db, villa["P3"], await make_vehicle(db, "56다1234", owner=visitor))
    with pytest.raises(ForbiddenError) as forbidden:
        await move_requests.create(db, villa["me"], _payload(external))
    assert forbidden.value.code == ErrorCode.NOT_BUILDING_MEMBER
    assert (await move_requests.create(db, villa["manager"], _payload(external))).status == "PENDING"


async def test_done_records_response_time_and_rejects_others(db, villa):
    created = await move_requests.create(db, villa["me"], _payload(villa["neighbor_parking"]))

    with pytest.raises(NotFoundError):  # 받은 사람이 아니다
        await move_requests.done(db, villa["manager"], created.id, now=NOW)

    result = await move_requests.done(db, villa["neighbor"], created.id, now=NOW)
    assert (result.status, result.responded_at) == ("MOVED", NOW)

    with pytest.raises(ConflictError) as exc:
        await move_requests.done(db, villa["neighbor"], created.id, now=NOW)
    assert exc.value.code == ErrorCode.ALREADY_DECIDED


async def test_list_boxes(db, villa):
    created = await move_requests.create(db, villa["me"], _payload(villa["neighbor_parking"]))

    received = await move_requests.list_mine(db, villa["neighbor"], MoveRequestBox.RECEIVED)
    sent = await move_requests.list_mine(db, villa["me"], MoveRequestBox.SENT)
    assert [i.id for i in received] == [i.id for i in sent] == [created.id]
    assert await move_requests.list_mine(db, villa["me"], MoveRequestBox.RECEIVED) == []
    assert await move_requests.list_mine(db, villa["neighbor"], MoveRequestBox.SENT) == []
