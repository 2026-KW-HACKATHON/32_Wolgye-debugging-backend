"""#9 전날 밤 막힘 알림 작업 (결정 15): 내일 출차할 차를 막고 있는 차의 주인에게 BLOCK_ALERT."""

from datetime import date, datetime, time

import pytest
from sqlalchemy import select

from app.jobs.block_alert import send_block_alerts
from app.models.notification import Notification, NotificationType
from app.schemas.common import KST
from tests.factories import make_resident, make_vehicle
from tests.factories_parking import make_assignment, make_departure, make_spec_building

pytestmark = pytest.mark.anyio

NIGHT = datetime(2026, 9, 30, 22, 0, tzinfo=KST)  # 수요일 밤
TODAY, TOMORROW = date(2026, 9, 30), date(2026, 10, 1)


@pytest.fixture
async def villa(db):
    """안쪽 P1 에 내 차, 앞 칸 P2 에 이웃 차."""
    v = await make_spec_building(db)
    v["me"] = await make_resident(db, "me@example.com", v["building"])
    v["neighbor"] = await make_resident(db, "neighbor@example.com", v["building"])
    v["my_car"] = await make_vehicle(db, "12가3456", owner=v["me"])
    v["neighbor_car"] = await make_vehicle(db, "34나5678", owner=v["neighbor"])
    await make_assignment(db, v["P1"], v["my_car"])
    v["front"] = await make_assignment(db, v["P2"], v["neighbor_car"])
    return v


async def _sent(db) -> list[Notification]:
    return list((await db.scalars(select(Notification).order_by(Notification.id))).all())


async def test_alerts_owner_of_blocking_car(db, villa):
    await make_departure(db, villa["my_car"], TOMORROW, time(7, 30))
    await make_departure(db, villa["neighbor_car"], TOMORROW, time(9, 0))  # 더 늦게 나간다 → 내 차를 막는다

    assert await send_block_alerts(db, now=NIGHT) == 1
    (alert,) = await _sent(db)
    assert (alert.resident_id, alert.type, alert.title, alert.body) == (
        villa["neighbor"].id,
        NotificationType.BLOCK_ALERT,
        "내일 출차 안내",
        "내 차량이 내일 07:30 출차하는 차량을 막고 있어요",
    )
    assert (alert.move_request_id, alert.share_request_id) == (None, None)


async def test_no_alert_when_front_car_leaves_first_or_tonight(db, villa):
    await make_departure(db, villa["my_car"], TOMORROW, time(7, 30))
    await make_departure(db, villa["neighbor_car"], TOMORROW, time(6, 0))  # 먼저 나간다
    assert await send_block_alerts(db, now=NIGHT) == 0

    await make_departure(db, villa["neighbor_car"], TODAY, time(23, 0))  # 오늘 밤에 나간다
    assert await send_block_alerts(db, now=NIGHT) == 0
    assert await _sent(db) == []


async def test_no_alert_when_blocked_car_is_not_leaving_tomorrow(db, villa):
    await make_departure(db, villa["my_car"], date(2026, 10, 2), time(7, 30))  # 모레 출차
    await make_departure(db, villa["neighbor_car"], date(2026, 10, 3), time(9, 0))
    assert await send_block_alerts(db, now=NIGHT) == 0


async def test_unknown_blocking_car_is_skipped(db, villa):
    """앞 칸이 주인 없는 미확인 차량이면 막힘이지만 알릴 사람이 없다."""
    villa["front"].is_active, villa["front"].released_at = False, NIGHT
    await db.commit()
    await make_assignment(db, villa["P2"], await make_vehicle(db, "99하9999"))
    await make_departure(db, villa["my_car"], TOMORROW, time(7, 30))

    assert await send_block_alerts(db, now=NIGHT) == 0
