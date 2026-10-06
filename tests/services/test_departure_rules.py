"""출차 예정 조회 규칙 (services/departures.py). #15 에서 departure_lookup.py 를 합치면서 옮겨 온 테스트."""

from datetime import UTC, date, datetime, time

import pytest

from app.schemas.common import KST
from app.schemas.my_vehicle import ExitSource
from app.services.departures import next_departure, next_departures
from tests.factories import make_resident, make_vehicle
from tests.factories_share import make_departure

pytestmark = pytest.mark.anyio

WED = date(2026, 10, 7)  # 수요일
NOW = datetime(2026, 10, 7, 14, 40, tzinfo=KST)


@pytest.fixture
async def vehicle(db):
    return await make_vehicle(db, owner=await make_resident(db))


async def test_one_off_today(db, vehicle):
    await make_departure(db, vehicle, WED, time(15, 30))

    dep = await next_departure(db, vehicle.id, NOW)

    assert dep.at == datetime(2026, 10, 7, 15, 30, tzinfo=KST)
    assert dep.source == ExitSource.MANUAL


async def test_user_entered_beats_ai_estimated(db, vehicle):
    await make_departure(
        db, vehicle, WED, time(16), is_ai_estimated=False, created_at=datetime(2026, 10, 1, tzinfo=UTC)
    )
    await make_departure(db, vehicle, WED, time(15), is_ai_estimated=True, created_at=datetime(2026, 10, 6, tzinfo=UTC))

    dep = await next_departure(db, vehicle.id, NOW)

    assert dep.at.hour == 16 and dep.source == ExitSource.MANUAL


async def test_one_off_beats_recurring_then_latest_created(db, vehicle):
    await make_departure(db, vehicle, date(2026, 10, 1), time(9), repeat_weekdays=[2])  # 매주 수요일, 더 최신이 아님
    await make_departure(db, vehicle, WED, time(18), created_at=datetime(2026, 10, 1, tzinfo=UTC))
    await make_departure(db, vehicle, WED, time(19), created_at=datetime(2026, 10, 2, tzinfo=UTC))

    dep = await next_departure(db, vehicle.id, NOW)

    assert dep.at.hour == 19 and dep.source == ExitSource.MANUAL


async def test_recurring_applies_from_start_date_on_weekdays(db, vehicle):
    # 목요일(3)만 반복, 시작일은 오늘 → 다음 출차는 내일(목) 08:00
    await make_departure(db, vehicle, WED, time(8), repeat_weekdays=[3])

    dep = await next_departure(db, vehicle.id, NOW)

    assert dep.at == datetime(2026, 10, 8, 8, tzinfo=KST)
    assert dep.source == ExitSource.RECURRING


async def test_recurring_not_before_start_date(db, vehicle):
    await make_departure(db, vehicle, date(2026, 10, 9), time(8), repeat_weekdays=[2, 3, 4])  # 금요일부터 시작

    dep = await next_departure(db, vehicle.id, NOW)

    assert dep.at.date() == date(2026, 10, 9)


async def test_today_even_if_time_passed_and_past_days_ignored(db, vehicle):
    await make_departure(db, vehicle, date(2026, 10, 6), time(23))  # 어제
    await make_departure(db, vehicle, WED, time(8))  # 오늘, 이미 지남

    dep = await next_departure(db, vehicle.id, NOW)

    assert dep.at == datetime(2026, 10, 7, 8, tzinfo=KST)


async def test_ai_estimated_source(db, vehicle):
    await make_departure(db, vehicle, date(2026, 10, 8), time(7), is_ai_estimated=True)

    assert (await next_departure(db, vehicle.id, NOW)).source == ExitSource.AI_ESTIMATED


async def test_none_and_batch(db, vehicle):
    other = await make_vehicle(db, "34나5678", await make_resident(db, "b@example.com"))
    await make_departure(db, other, date(2026, 10, 8), time(7))

    assert await next_departure(db, vehicle.id, NOW) is None
    assert set(await next_departures(db, [vehicle.id, other.id], NOW)) == {other.id}
