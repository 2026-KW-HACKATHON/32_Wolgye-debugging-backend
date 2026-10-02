"""#8 주차 배치·출차 일정·출차 서비스 규칙."""

from datetime import date, datetime, time

import pytest
from sqlalchemy import select

from app.core.error_codes import ErrorCode
from app.models.departure_schedule import DepartureSchedule
from app.models.notification import Notification, NotificationType
from app.models.parking_assignment import ParkingAssignment
from app.models.share_request import ShareRequestStatus
from app.schemas.common import KST
from app.schemas.my_vehicle import ExitSource, ParkingState
from app.schemas.parking import ParkingCreate, ParkingScheduleUpdate
from app.services import parkings, share_requests
from app.services.exceptions import ConflictError, ForbiddenError, InvalidInputError, NotFoundError
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

# 2026-09-30 은 수요일
NOW = datetime(2026, 9, 30, 14, 40, tzinfo=KST)
TODAY = date(2026, 9, 30)


def _at(hour: int, minute: int = 0, day: int = 30, month: int = 9) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=KST)


@pytest.fixture
async def lane(db):
    """안쪽 칸 inner 의 앞 칸이 outer 인 빌라와, 입주민 me·neighbor."""
    building = await make_building(db)
    garage = await make_garage(db, building, name="필로티 안쪽")
    inner = await make_slot(db, garage, 1)
    outer = await make_slot(db, garage, 2)
    inner.front_slot_id = outer.id
    await db.commit()
    me = await make_resident(db, "me@example.com", building)
    neighbor = await make_resident(db, "neighbor@example.com", building)
    return {
        "building": building,
        "garage": garage,
        "inner": inner,
        "outer": outer,
        "me": me,
        "neighbor": neighbor,
        "my_car": await make_vehicle(db, "12가3456", owner=me),
        "neighbor_car": await make_vehicle(db, "34나5678", owner=neighbor),
    }


def _create(slot, vehicle, **kwargs) -> ParkingCreate:
    kwargs.setdefault("expected_exit_at", _at(18, 30))
    return ParkingCreate(slot_id=slot.id, vehicle_id=vehicle.id, **kwargs)


async def _departures(db, vehicle) -> list[DepartureSchedule]:
    rows = await db.scalars(
        select(DepartureSchedule)
        .where(DepartureSchedule.vehicle_id == vehicle.id)
        .order_by(DepartureSchedule.id)
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


async def _notifications(db) -> list[Notification]:
    return list((await db.scalars(select(Notification).order_by(Notification.id))).all())


# ── 배치 ──
async def test_create_parking_saves_assignment_and_exit_time(db, lane):
    created = await parkings.create_parking(db, lane["me"], _create(lane["inner"], lane["my_car"], memo="출근"), now=NOW)

    assert (created.slot_id, created.state, created.blocking) == (lane["inner"].id, ParkingState.PARKED, [])
    assert (created.expected_exit_at, created.exit_source) == (_at(18, 30), ExitSource.MANUAL)
    assignment = await db.get(ParkingAssignment, created.id)
    assert (assignment.is_active, assignment.is_permanent, assignment.vehicle_id) == (True, False, lane["my_car"].id)
    rows = await _departures(db, lane["my_car"])
    assert [(r.scheduled_date, r.scheduled_time, r.repeat_weekdays, r.memo) for r in rows] == [
        (TODAY, time(18, 30), [], "출근")
    ]


async def test_create_long_term_has_no_exit_time(db, lane):
    payload = ParkingCreate(slot_id=lane["inner"].id, vehicle_id=lane["my_car"].id, is_long_term=True)
    created = await parkings.create_parking(db, lane["me"], payload, now=NOW)

    assert (created.expected_exit_at, created.exit_source) == (None, ExitSource.NONE)
    assert (await db.get(ParkingAssignment, created.id)).is_permanent is True
    assert await _departures(db, lane["my_car"]) == []


async def test_create_with_weekday_repeat_also_saves_recurring(db, lane):
    payload = _create(lane["inner"], lane["my_car"], expected_exit_at=_at(7, 30, day=1, month=10), repeat_weekdays=True)
    await parkings.create_parking(db, lane["me"], payload, now=NOW)

    rows = await _departures(db, lane["my_car"])
    assert sorted((r.scheduled_date, r.scheduled_time, tuple(r.repeat_weekdays)) for r in rows) == [
        (TODAY, time(7, 30), (0, 1, 2, 3, 4)),  # 반복 일정: 설정한 날부터 평일
        (date(2026, 10, 1), time(7, 30), ()),  # 이번 주차 건의 출차 예정
    ]


async def test_create_replaces_stale_one_off_schedules(db, lane):
    await make_departure(db, lane["my_car"], TODAY, time(23, 0))  # 이전 주차 건이 남긴 일정
    await parkings.create_parking(db, lane["me"], _create(lane["inner"], lane["my_car"]), now=NOW)

    assert [r.scheduled_time for r in await _departures(db, lane["my_car"])] == [time(18, 30)]


async def test_create_reports_slots_it_blocks(db, lane):
    """안쪽 차(18:30 출차) 앞 칸에 더 늦게 나가는 차(21:00)를 세우면 blocking 에 안쪽 칸이 들어간다."""
    await parkings.create_parking(db, lane["me"], _create(lane["inner"], lane["my_car"]), now=NOW)
    late = await parkings.create_parking(
        db, lane["neighbor"], _create(lane["outer"], lane["neighbor_car"], expected_exit_at=_at(21)), now=NOW
    )
    assert late.blocking == [lane["inner"].id]


async def test_create_errors(db, lane):
    me, my_car, inner, outer = lane["me"], lane["my_car"], lane["inner"], lane["outer"]

    with pytest.raises(NotFoundError):  # 남의 차량
        await parkings.create_parking(db, me, _create(inner, lane["neighbor_car"]), now=NOW)
    with pytest.raises(NotFoundError):  # 없는 칸
        await parkings.create_parking(
            db, me, ParkingCreate(slot_id=99999, vehicle_id=my_car.id, expected_exit_at=_at(18)), now=NOW
        )
    with pytest.raises(InvalidInputError):  # 지난 시각
        await parkings.create_parking(db, me, _create(inner, my_car, expected_exit_at=_at(9)), now=NOW)

    inner.is_active = False
    await db.commit()
    with pytest.raises(ConflictError) as inactive:
        await parkings.create_parking(db, me, _create(inner, my_car), now=NOW)
    assert inactive.value.code == ErrorCode.SLOT_UNAVAILABLE
    assert inactive.value.detail == {"reason": "관리인이 사용 중지한 칸"}

    await make_assignment(db, outer, lane["neighbor_car"])
    with pytest.raises(ConflictError) as occupied:
        await parkings.create_parking(db, me, _create(outer, my_car), now=NOW)
    assert occupied.value.code == ErrorCode.SLOT_OCCUPIED

    spare = await make_slot(db, lane["garage"], 3)
    with pytest.raises(ConflictError) as parked:  # 이웃 차는 이미 outer 에 주차 중
        await parkings.create_parking(db, lane["neighbor"], _create(spare, lane["neighbor_car"]), now=NOW)
    assert parked.value.code == ErrorCode.VEHICLE_ALREADY_PARKED
    assert set(parked.value.detail) == {"parking_id"}


async def test_other_building_slot_needs_my_accepted_share(db, lane, monkeypatch):
    """다른 빌라 칸은 403. 그 칸에서 진행 중인 내 수락된 공유가 있으면 주차할 수 있고, 남의 공유 시간이면 입주민도 못 세운다."""
    other = await make_building(db, "INV002", "옆 빌라", alley=await make_alley(db, "다른 골목"))
    visitor = await make_resident(db, "visitor@example.com", other)
    visitor_car = await make_vehicle(db, "56다1234", owner=visitor)

    with pytest.raises(ForbiddenError) as forbidden:
        await parkings.create_parking(db, visitor, _create(lane["outer"], visitor_car), now=NOW)
    assert forbidden.value.code == ErrorCode.NOT_BUILDING_MEMBER

    host = await make_resident(db, "host@example.com", lane["building"])
    offer = await make_share_offer(db, lane["outer"], host)
    share = await make_share_request(db, offer, visitor, ShareRequestStatus.ACCEPTED, start_hour=13, end_hour=17)

    async def fake_accepted_share_at(db, slot_id, at):
        return share if slot_id == lane["outer"].id else None

    monkeypatch.setattr(share_requests, "accepted_share_at", fake_accepted_share_at)

    with pytest.raises(ConflictError) as reserved:  # 입주민이라도 남의 공유 시간에는 세울 수 없다
        await parkings.create_parking(db, lane["me"], _create(lane["outer"], lane["my_car"]), now=NOW)
    assert reserved.value.code == ErrorCode.SLOT_UNAVAILABLE
    assert reserved.value.detail == {"reason": "예약된 상태"}

    created = await parkings.create_parking(
        db, visitor, _create(lane["outer"], visitor_car, expected_exit_at=_at(17)), now=NOW
    )
    assert created.slot_id == lane["outer"].id


# ── 출차 일정 수정 ──
async def test_update_schedule_replaces_exit_time(db, lane):
    created = await parkings.create_parking(db, lane["me"], _create(lane["inner"], lane["my_car"]), now=NOW)

    tomorrow = _at(7, 0, day=1, month=10)
    updated = await parkings.update_schedule(
        db, lane["me"], created.id, ParkingScheduleUpdate(expected_exit_at=tomorrow, memo="늦게 출근"), now=NOW
    )
    assert (updated.parking_id, updated.expected_exit_at, updated.exit_source, updated.memo) == (
        created.id,
        tomorrow,
        ExitSource.MANUAL,
        "늦게 출근",
    )
    rows = await _departures(db, lane["my_car"])
    assert [(r.scheduled_date, r.scheduled_time) for r in rows] == [(date(2026, 10, 1), time(7, 0))]  # 오늘 값은 지움


async def test_update_schedule_makes_long_term_timed(db, lane):
    payload = ParkingCreate(slot_id=lane["inner"].id, vehicle_id=lane["my_car"].id, is_long_term=True)
    created = await parkings.create_parking(db, lane["me"], payload, now=NOW)

    await parkings.update_schedule(db, lane["me"], created.id, ParkingScheduleUpdate(expected_exit_at=_at(20)), now=NOW)
    assignment = await db.scalar(
        select(ParkingAssignment).where(ParkingAssignment.id == created.id).execution_options(populate_existing=True)
    )
    assert assignment.is_permanent is False


async def test_update_schedule_earlier_notifies_blocker(db, lane):
    """출차 시간을 앞당겨 앞 칸 차에 막히게 되면 앞 칸 차 주인에게 BLOCK_ALERT. 늦추면 보내지 않는다."""
    mine = await parkings.create_parking(
        db, lane["me"], _create(lane["inner"], lane["my_car"], expected_exit_at=_at(22)), now=NOW
    )
    await parkings.create_parking(
        db, lane["neighbor"], _create(lane["outer"], lane["neighbor_car"], expected_exit_at=_at(21)), now=NOW
    )

    await parkings.update_schedule(db, lane["me"], mine.id, ParkingScheduleUpdate(expected_exit_at=_at(23)), now=NOW)
    assert await _notifications(db) == []  # 늦춤 → 알림 없음

    await parkings.update_schedule(db, lane["me"], mine.id, ParkingScheduleUpdate(expected_exit_at=_at(18)), now=NOW)
    sent = await _notifications(db)
    assert [(n.resident_id, n.type, n.body) for n in sent] == [
        (lane["neighbor"].id, NotificationType.BLOCK_ALERT, "내 차량이 18:00 출차하는 차량을 막고 있어요")
    ]

    # 21:30 → 21:10 으로 앞당겨도 앞 차(21:00)가 먼저 나가므로 막히지 않는다
    await parkings.update_schedule(db, lane["me"], mine.id, ParkingScheduleUpdate(expected_exit_at=_at(21, 30)), now=NOW)
    await parkings.update_schedule(db, lane["me"], mine.id, ParkingScheduleUpdate(expected_exit_at=_at(21, 10)), now=NOW)
    assert len(await _notifications(db)) == 1  # 앞당겼어도 막는 차가 없으면 보내지 않는다


async def test_update_schedule_errors(db, lane):
    created = await parkings.create_parking(db, lane["me"], _create(lane["inner"], lane["my_car"]), now=NOW)
    later = ParkingScheduleUpdate(expected_exit_at=_at(20))

    with pytest.raises(NotFoundError):  # 남의 주차 건
        await parkings.update_schedule(db, lane["neighbor"], created.id, later, now=NOW)
    with pytest.raises(NotFoundError):
        await parkings.update_schedule(db, lane["me"], 99999, later, now=NOW)
    with pytest.raises(InvalidInputError):
        await parkings.update_schedule(
            db, lane["me"], created.id, ParkingScheduleUpdate(expected_exit_at=_at(9)), now=NOW
        )

    await parkings.exit_parking(db, lane["me"], created.id, now=NOW)
    with pytest.raises(NotFoundError):  # 이미 출차
        await parkings.update_schedule(db, lane["me"], created.id, later, now=NOW)


# ── 출차 ──
async def test_exit_releases_and_notifies_neighbors(db, lane):
    other = await make_building(db, "INV002", "옆 빌라", alley=await make_alley(db, "다른 골목"))
    await make_resident(db, "far@example.com", other)
    created = await parkings.create_parking(db, lane["me"], _create(lane["inner"], lane["my_car"]), now=NOW)

    exited = await parkings.exit_parking(db, lane["me"], created.id, now=_at(18, 25))
    assert (exited.id, exited.state, exited.actual_exit_at, exited.on_time) == (
        created.id,
        ParkingState.EXITED,
        _at(18, 25),
        True,
    )
    assignment = await db.scalar(
        select(ParkingAssignment).where(ParkingAssignment.id == created.id).execution_options(populate_existing=True)
    )
    assert (assignment.is_active, assignment.released_at) == (False, _at(18, 25))

    # 같은 빌라 입주민에게만, 본인은 제외
    sent = await _notifications(db)
    assert [(n.resident_id, n.type, n.title, n.body) for n in sent] == [
        (lane["neighbor"].id, NotificationType.EXIT_DONE, "출차 완료 안내", "필로티 안쪽 1번 비어 있음")
    ]

    with pytest.raises(NotFoundError):  # 두 번 출차할 수 없다
        await parkings.exit_parking(db, lane["me"], created.id, now=_at(18, 26))


async def test_exit_on_time_flag(db, lane):
    late = await parkings.create_parking(db, lane["me"], _create(lane["inner"], lane["my_car"]), now=NOW)
    assert (await parkings.exit_parking(db, lane["me"], late.id, now=_at(19))).on_time is False

    long_term = await parkings.create_parking(
        db, lane["me"], ParkingCreate(slot_id=lane["inner"].id, vehicle_id=lane["my_car"].id, is_long_term=True), now=NOW
    )
    assert (await parkings.exit_parking(db, lane["me"], long_term.id, now=_at(19))).on_time is True  # 예정 시각 없음

    again = await parkings.create_parking(
        db, lane["me"], _create(lane["inner"], lane["my_car"], expected_exit_at=_at(23)), now=NOW
    )
    with pytest.raises(NotFoundError):  # 남의 주차 건
        await parkings.exit_parking(db, lane["neighbor"], again.id, now=_at(19))
