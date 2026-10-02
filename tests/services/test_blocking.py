"""#9 막힘 판정 (결정 1): 앞 칸(front_slot_id)의 차가 내 차보다 늦게 나가면 막힘."""

from datetime import date, datetime, time

import pytest

from app.models.share_request import ShareRequestStatus
from app.schemas.common import KST
from app.services import blocking, share_requests
from tests.factories import (
    make_alley,
    make_building,
    make_garage,
    make_resident,
    make_share_offer,
    make_share_request,
    make_slot,
    make_vehicle,
)
from tests.factories_parking import make_assignment, make_departure

pytestmark = pytest.mark.anyio

WED = date(2026, 9, 30)
NOW = datetime(2026, 9, 30, 14, 40, tzinfo=KST)


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 30, hour, minute, tzinfo=KST)


@pytest.mark.parametrize(
    ("my_exit", "front_exit", "expected"),
    [
        (_at(18, 30), _at(21), True),  # 앞 차가 더 늦게 나감
        (_at(18, 30), _at(8), False),  # 앞 차가 먼저 나감
        (_at(18, 30), _at(18, 30), False),  # 같은 시각이면 막힘이 아님
        (_at(18, 30), None, True),  # 앞 차 출차 시간 없음 → 늦게 나가는 것으로 본다
        (None, _at(21), False),  # 내 차 출차 시간 없음(상시 주차) → 막힘으로 보지 않는다
        (None, None, False),
    ],
)
def test_is_blocked(my_exit, front_exit, expected):
    assert blocking.is_blocked(my_exit, front_exit) is expected


@pytest.fixture
async def lane(db):
    """안쪽 칸 inner 의 앞 칸이 outer. 둘 다 같은 빌라 입주민 차를 세울 수 있다."""
    building = await make_building(db)
    garage = await make_garage(db, building)
    outer = await make_slot(db, garage, 2)
    inner = await make_slot(db, garage, 1)
    inner.front_slot_id = outer.id
    await db.commit()
    me = await make_resident(db, "me@example.com", building)
    neighbor = await make_resident(db, "neighbor@example.com", building)
    return {
        "building": building,
        "garage": garage,
        "inner": inner,
        "outer": outer,
        "my_car": await make_vehicle(db, "12가3456", owner=me),
        "front_car": await make_vehicle(db, "34나5678", owner=neighbor),
    }


async def _map(db, lane):
    blocks = await blocking.building_block_map(db, lane["building"].id, NOW)
    return blocks[lane["inner"].id], blocks[lane["outer"].id]


async def test_blocked_when_front_car_leaves_later(db, lane):
    """명세 예시: 1001(18:30 출차)의 앞 칸 1002(21:00 출차) → 1001 은 blocked_by [1002]."""
    await make_assignment(db, lane["inner"], lane["my_car"])
    await make_assignment(db, lane["outer"], lane["front_car"])
    await make_departure(db, lane["my_car"], WED, time(18, 30))
    await make_departure(db, lane["front_car"], WED, time(21, 0))

    inner, outer = await _map(db, lane)
    assert inner.blocked_by == [lane["outer"].id] and inner.blocking == []
    assert outer.blocking == [lane["inner"].id] and outer.blocked_by == []
    assert await blocking.blocked_by(db, lane["inner"].id, NOW) == [lane["outer"].id]
    assert await blocking.blocked_by(db, lane["outer"].id, NOW) == []


async def test_not_blocked_when_front_car_leaves_earlier(db, lane):
    await make_assignment(db, lane["inner"], lane["my_car"])
    await make_assignment(db, lane["outer"], lane["front_car"])
    await make_departure(db, lane["my_car"], WED, time(18, 30))
    await make_departure(db, lane["front_car"], WED, time(15, 0))

    inner, outer = await _map(db, lane)
    assert inner.blocked_by == [] and outer.blocking == []
    assert await blocking.blocked_by(db, lane["inner"].id, NOW) == []


async def test_front_car_without_exit_time_blocks(db, lane):
    """앞 칸이 상시 주차·미확인 차량이거나 출차 일정이 없으면 늦게 나가는 것으로 본다."""
    await make_assignment(db, lane["inner"], lane["my_car"])
    await make_departure(db, lane["my_car"], WED, time(18, 30))

    unknown = await make_vehicle(db, "99하9999")  # 주인 없는 미확인 차량
    assignment = await make_assignment(db, lane["outer"], unknown)
    assert (await _map(db, lane))[0].blocked_by == [lane["outer"].id]

    assignment.is_active, assignment.released_at = False, NOW
    await db.commit()
    assert (await _map(db, lane))[0].blocked_by == []  # 앞 칸이 비면 막힘이 아니다

    await make_assignment(db, lane["outer"], lane["front_car"], is_permanent=True)
    await make_departure(db, lane["front_car"], WED, time(15, 0))  # 상시 주차면 일정이 있어도 쓰지 않는다
    assert (await _map(db, lane))[0].blocked_by == [lane["outer"].id]


async def test_my_car_without_exit_time_is_not_blocked(db, lane):
    await make_assignment(db, lane["inner"], lane["my_car"], is_permanent=True)
    await make_assignment(db, lane["outer"], lane["front_car"])
    await make_departure(db, lane["front_car"], WED, time(21, 0))

    inner, outer = await _map(db, lane)
    assert inner.blocked_by == [] and outer.blocking == []


async def test_empty_slots_and_slots_without_front(db, lane):
    blocks = await blocking.building_block_map(db, lane["building"].id, NOW)
    assert set(blocks) == {lane["inner"].id, lane["outer"].id}  # 막힘이 없는 칸도 포함
    assert all(b.blocked_by == [] and b.blocking == [] for b in blocks.values())

    # 안쪽 칸만 차가 있으면 막힘이 아니다
    await make_assignment(db, lane["inner"], lane["my_car"])
    await make_departure(db, lane["my_car"], WED, time(18, 30))
    assert (await _map(db, lane))[0].blocked_by == []
    assert await blocking.blocked_by(db, 99999, NOW) == []  # 없는 칸


async def test_other_building_is_not_in_map(db, lane):
    other = await make_building(db, "INV002", "옆 빌라", alley=await make_alley(db, "다른 골목"))
    other_slot = await make_slot(db, await make_garage(db, other))

    blocks = await blocking.building_block_map(db, lane["building"].id, NOW)
    assert other_slot.id not in blocks


async def test_external_car_exit_time_is_share_end(db, lane, monkeypatch):
    """외부 차량(공유 이용자)의 출차 시간 = 그 칸에서 진행 중인 수락된 공유의 종료 시각."""
    visitor = await make_resident(db, "visitor@example.com")  # 다른 빌라(소속 없음) 사용자
    visitor_car = await make_vehicle(db, "56다1234", owner=visitor)
    host = await make_resident(db, "host@example.com", lane["building"])
    offer = await make_share_offer(db, lane["outer"], host)
    share = await make_share_request(db, offer, visitor, ShareRequestStatus.ACCEPTED, start_hour=13, end_hour=17)
    share.request_date = WED
    await db.commit()
    assert blocking.share_end_at(share) == _at(17)

    await make_assignment(db, lane["inner"], lane["my_car"])
    await make_assignment(db, lane["outer"], visitor_car)
    await make_departure(db, lane["my_car"], WED, time(18, 30))

    # #12 전까지 accepted_share_at 은 스텁 → 외부 차량의 출차 시간을 모르므로 늦게 나가는 것으로 본다
    assert (await _map(db, lane))[0].blocked_by == [lane["outer"].id]

    async def fake_accepted_share_at(db, slot_id, at):
        return share if slot_id == lane["outer"].id else None

    monkeypatch.setattr(share_requests, "accepted_share_at", fake_accepted_share_at)
    assert (await _map(db, lane))[0].blocked_by == []  # 공유가 17:00 에 끝나고 내 차는 18:30 출차

    share.end_hour = 24
    assert blocking.share_end_at(share) == datetime(2026, 10, 1, 0, 0, tzinfo=KST)
    assert (await _map(db, lane))[0].blocked_by == [lane["outer"].id]
