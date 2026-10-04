"""#7 내 차량·반복 출차 서비스: 대표 차량, 삭제 규칙, 출차 예정 조회 규칙(docs/db-design-issues.md 2-2, 결정 10)."""

from datetime import UTC, date, datetime, time

import pytest
from sqlalchemy import select

from app.core.error_codes import ErrorCode
from app.core.weekdays import Weekday
from app.models.departure_schedule import DepartureSchedule
from app.models.vehicle import Vehicle
from app.schemas.common import KST
from app.schemas.my_vehicle import ExitSource, MyVehicleCreate, MyVehicleUpdate, RecurringSchedule, VehicleStatus
from app.services import departures, vehicles
from app.services.exceptions import ConflictError, NotFoundError
from tests.factories import make_building, make_garage, make_resident, make_slot, make_vehicle
from tests.factories_parking import make_assignment, make_departure

pytestmark = pytest.mark.anyio

# 2026-09-30 은 수요일
WED = date(2026, 9, 30)
THU = date(2026, 10, 1)
NOW = datetime(2026, 9, 30, 14, 40, tzinfo=KST)


def _old(hour: int) -> datetime:
    return datetime(2026, 9, 1, hour, tzinfo=UTC)


# ── 대표 차량 ──
async def test_create_default_clears_previous_default(db):
    user = await make_resident(db)
    first = await vehicles.create_my_vehicle(db, user, MyVehicleCreate(plate="12가 3456", is_default=True))
    second = await vehicles.create_my_vehicle(db, user, MyVehicleCreate(plate="78나9012", is_default=True))

    rows = {v.id: v for v in (await db.scalars(select(Vehicle).execution_options(populate_existing=True))).all()}
    assert rows[first.id].is_primary is False
    assert rows[second.id].is_primary is True
    assert rows[first.id].plate_no == "12가3456"  # 공백 없이 저장


async def test_default_of_other_owner_is_untouched(db):
    mine, other = await make_resident(db, "me@example.com"), await make_resident(db, "other@example.com")
    theirs = await vehicles.create_my_vehicle(db, other, MyVehicleCreate(plate="11가1111", is_default=True))
    await vehicles.create_my_vehicle(db, mine, MyVehicleCreate(plate="22나2222", is_default=True))

    row = await db.scalar(select(Vehicle).where(Vehicle.id == theirs.id).execution_options(populate_existing=True))
    assert row.is_primary is True


async def test_update_sets_default_and_alias(db):
    user = await make_resident(db)
    first = await vehicles.create_my_vehicle(db, user, MyVehicleCreate(plate="12가3456", is_default=True))
    second = await vehicles.create_my_vehicle(db, user, MyVehicleCreate(plate="78나9012", alias="가족 차"))

    updated = await vehicles.update_my_vehicle(db, user, second.id, MyVehicleUpdate(is_default=True))
    assert updated.is_default is True
    assert updated.alias == "가족 차"  # 보내지 않은 필드는 그대로

    items = await vehicles.list_my_vehicles(db, user)
    assert [(i.id, i.is_default) for i in items] == [(second.id, True), (first.id, False)]  # 대표 차량이 먼저


async def test_update_plate_conflict_and_same_plate(db):
    user = await make_resident(db)
    await make_vehicle(db, "99하9999")  # 주인 없는 미확인 차량도 번호판을 차지한다
    mine = await vehicles.create_my_vehicle(db, user, MyVehicleCreate(plate="12가3456"))

    same = await vehicles.update_my_vehicle(db, user, mine.id, MyVehicleUpdate(plate="12가 3456"))
    assert same.plate == "12가 3456"

    with pytest.raises(ConflictError) as exc:
        await vehicles.update_my_vehicle(db, user, mine.id, MyVehicleUpdate(plate="99하9999"))
    assert exc.value.code == ErrorCode.PLATE_EXISTS


async def test_others_vehicle_is_not_found(db):
    me, other = await make_resident(db, "me@example.com"), await make_resident(db, "other@example.com")
    theirs = await make_vehicle(db, owner=other)

    for call in (
        vehicles.get_my_vehicle(db, me, theirs.id),
        vehicles.update_my_vehicle(db, me, theirs.id, MyVehicleUpdate(alias="x")),
        vehicles.delete_my_vehicle(db, me, theirs.id),
        departures.get_recurring(db, me, theirs.id),
    ):
        with pytest.raises(NotFoundError) as exc:
            await call
        assert exc.value.code == ErrorCode.NOT_FOUND


# ── 삭제 ──
async def test_delete_parked_vehicle_conflict_then_ok(db):
    building = await make_building(db)
    slot = await make_slot(db, await make_garage(db, building))
    user = await make_resident(db, building=building)
    vehicle = await make_vehicle(db, owner=user)
    assignment = await make_assignment(db, slot, vehicle)
    await make_departure(db, vehicle, WED, time(18, 30))

    with pytest.raises(ConflictError) as exc:
        await vehicles.delete_my_vehicle(db, user, vehicle.id)
    assert exc.value.code == ErrorCode.VEHICLE_ALREADY_PARKED
    assert exc.value.detail == {"parking_id": assignment.id}

    assignment.is_active = False
    assignment.released_at = NOW
    await db.commit()
    await vehicles.delete_my_vehicle(db, user, vehicle.id)

    assert await db.scalar(select(Vehicle.id).where(Vehicle.id == vehicle.id)) is None
    assert (await db.scalars(select(DepartureSchedule.id))).all() == []  # 출차 일정도 함께 삭제


# ── 출차 예정 조회 규칙 ──
async def test_departure_on_manual_beats_ai_and_recurring(db):
    vehicle = await make_vehicle(db, owner=await make_resident(db))
    rows = [
        await make_departure(db, vehicle, WED, time(18, 0), is_ai_estimated=True),
        await make_departure(db, vehicle, date(2026, 9, 1), time(7, 30), repeat_weekdays=[0, 1, 2, 3, 4]),
        await make_departure(db, vehicle, WED, time(18, 30), created_at=_old(1)),
    ]

    wed = departures.departure_on(rows, WED)
    assert (wed.at, wed.source) == (datetime(2026, 9, 30, 18, 30, tzinfo=KST), ExitSource.MANUAL)
    # 직접 입력이 없는 날은 반복 일정
    thu = departures.departure_on(rows, THU)
    assert (thu.at, thu.source) == (datetime(2026, 10, 1, 7, 30, tzinfo=KST), ExitSource.RECURRING)
    # 반복 요일이 아닌 날(토요일), 반복 시작일 이전에는 없음
    assert departures.departure_on(rows, date(2026, 10, 3)) is None
    assert departures.departure_on(rows, date(2026, 8, 31)) is None


async def test_departure_on_same_kind_latest_wins_and_ai_only(db):
    vehicle = await make_vehicle(db, owner=await make_resident(db))
    older = await make_departure(db, vehicle, WED, time(17, 0), created_at=_old(1))
    newer = await make_departure(db, vehicle, WED, time(19, 0), created_at=_old(2))
    ai = await make_departure(db, vehicle, THU, time(8, 0), is_ai_estimated=True)

    assert departures.departure_on([newer, older], WED).at.hour == 19
    assert departures.departure_on([ai], THU).source == ExitSource.AI_ESTIMATED


async def test_next_departure_today_even_if_passed_else_nearest(db):
    vehicle = await make_vehicle(db, owner=await make_resident(db))
    assert await departures.next_departure(db, vehicle.id, NOW) is None

    await make_departure(db, vehicle, date(2026, 9, 29), time(9, 0))  # 지난 날짜는 보지 않는다
    await make_departure(db, vehicle, date(2026, 9, 1), time(7, 30), repeat_weekdays=[3])  # 매주 목요일
    nearest = await departures.next_departure(db, vehicle.id, NOW)
    assert (nearest.at, nearest.source) == (datetime(2026, 10, 1, 7, 30, tzinfo=KST), ExitSource.RECURRING)

    await make_departure(db, vehicle, WED, time(9, 0))  # 오늘 09:00 (이미 지남)
    today = await departures.next_departure(db, vehicle.id, NOW)
    assert (today.at, today.source) == (datetime(2026, 9, 30, 9, 0, tzinfo=KST), ExitSource.MANUAL)


# ── 차량 상세 ──
async def test_detail_not_parked_and_parked(db):
    building = await make_building(db)
    slot = await make_slot(db, await make_garage(db, building, name="필로티 안쪽"), number=1)
    user = await make_resident(db, building=building)
    vehicle = await make_vehicle(db, owner=user)

    out = await vehicles.get_my_vehicle(db, user, vehicle.id, now=NOW)
    assert out.parking is None and out.schedule is None
    assert out.owner.name == user.nickname  # 이름이 없으면 닉네임

    assignment = await make_assignment(db, slot, vehicle, assigned_at=datetime(2026, 9, 30, 8, 30, tzinfo=KST))
    await make_departure(db, vehicle, WED, time(18, 30))
    parked = await vehicles.get_my_vehicle(db, user, vehicle.id, now=NOW)
    assert parked.parking.parking_id == assignment.id
    assert parked.parking.slot_label == "P1"
    assert parked.schedule.expected_exit_at == datetime(2026, 9, 30, 18, 30, tzinfo=KST)
    assert parked.schedule.exit_source == ExitSource.MANUAL
    assert parked.schedule.elapsed_minutes == 370

    items = await vehicles.list_my_vehicles(db, user)
    assert items[0].status == VehicleStatus.PARKED and items[0].status_text == "현재 주차 중"


async def test_detail_permanent_or_no_schedule_is_none_source(db):
    building = await make_building(db)
    garage = await make_garage(db, building)
    user = await make_resident(db, building=building)
    permanent = await make_vehicle(db, "11가1111", owner=user)
    plain = await make_vehicle(db, "22나2222", owner=user)
    await make_assignment(db, await make_slot(db, garage, 1), permanent, is_permanent=True)
    await make_assignment(db, await make_slot(db, garage, 2), plain)
    await make_departure(db, permanent, WED, time(18, 30))  # 상시 주차면 일정이 있어도 쓰지 않는다

    for vehicle in (permanent, plain):
        detail = await vehicles.get_my_vehicle(db, user, vehicle.id, now=NOW)
        assert detail.schedule.expected_exit_at is None
        assert detail.schedule.exit_source == ExitSource.NONE


# ── 반복 출차 ──
async def test_recurring_put_replaces_single_row_and_delete(db):
    user = await make_resident(db)
    vehicle = await make_vehicle(db, owner=user)
    one_off = await make_departure(db, vehicle, WED, time(18, 30))

    with pytest.raises(NotFoundError):
        await departures.get_recurring(db, user, vehicle.id)

    first = RecurringSchedule(days=[Weekday.FRI, Weekday.MON, Weekday.MON], time="07:30", memo="출근")
    saved = await departures.put_recurring(db, user, vehicle.id, first, now=NOW)
    assert saved.days == [Weekday.MON, Weekday.FRI]  # 중복 제거·월요일부터
    assert saved.time == time(7, 30)

    await departures.put_recurring(db, user, vehicle.id, RecurringSchedule(days=["SAT"], time="10:00"), now=NOW)
    rows = (await db.scalars(select(DepartureSchedule).order_by(DepartureSchedule.id))).all()
    recurring = [r for r in rows if r.repeat_weekdays]
    assert len(recurring) == 1  # 차량당 하나
    assert (recurring[0].repeat_weekdays, recurring[0].scheduled_time, recurring[0].scheduled_date, recurring[0].memo) == (
        [5],
        time(10, 0),
        WED,
        None,
    )

    await departures.delete_recurring(db, user, vehicle.id)
    await departures.delete_recurring(db, user, vehicle.id)  # 없어도 성공
    remaining = (await db.scalars(select(DepartureSchedule.id))).all()
    assert remaining == [one_off.id]  # 일회성 일정은 남는다
