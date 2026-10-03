"""차고지 탐색·상세 (services/garages.py). 기준 시각: 2026-10-07(수) 14:40 KST."""

from datetime import date, datetime, time

import pytest

from app.models.share_request import ShareRequestStatus
from app.schemas.common import KST
from app.services import garages
from app.services.exceptions import InvalidInputError, NotFoundError
from tests.factories import make_building, make_garage, make_resident, make_share_offer, make_slot, make_vehicle
from tests.factories_share import make_departure, make_request_on, make_scenario, park, set_location

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 7, 14, 40, tzinfo=KST)
TODAY = NOW.date()


@pytest.fixture
async def sc(db):
    return await make_scenario(db)


async def _list(db, user, **kwargs):
    return await garages.list_garages(db, user, now=NOW, **kwargs)


def _by_slot(page):
    return {e.slot_id: e for e in page.items}


async def test_lists_shared_slots_of_other_buildings_in_my_alley(db, sc):
    # 먼 골목 빌라·우리 빌라·비공개·비활성 칸의 공유 조건은 나오지 않는다
    far_slot = await make_slot(db, await make_garage(db, sc.far))
    await make_share_offer(db, far_slot, sc.host)
    my_slot = await make_slot(db, await make_garage(db, sc.mine))
    await make_share_offer(db, my_slot, sc.me)
    await make_share_offer(db, sc.p1, sc.host, is_public=False)
    inactive = await make_slot(db, sc.zone_b, 2)
    inactive.is_active = False
    await db.commit()
    await make_share_offer(db, inactive, sc.host)

    page = await _list(db, sc.me)

    assert [e.slot_id for e in page.items] == [sc.p3.id, sc.p2.id]  # 칸 id 내림차순
    p2 = _by_slot(page)[sc.p2.id]
    assert p2.garage_id == sc.next_door.id and p2.building_name == "햇살빌라"
    assert p2.slot_label == "P2" and p2.title == "햇살빌라 · P2"
    assert _by_slot(page)[sc.p3.id].slot_label == "P3"
    assert p2.availability == "AVAILABLE" and p2.hourly_price == 2 and p2.max_hours == 4
    assert p2.info == "지금 이용 가능 · 06:00~22:00 · 최대 4시간"
    assert p2.weekdays_only is False


async def test_user_without_building_gets_empty_list(db, sc):
    lonely = await make_resident(db, "lonely@example.com")
    assert (await _list(db, lonely)).items == []


async def test_soon_exit_and_unavailable_from_resident_departure(db, sc):
    car1 = await make_vehicle(db, "11가1111", sc.neighbor)
    car2 = await make_vehicle(db, "22가2222", await make_resident(db, "n2@example.com", sc.next_door))
    await park(db, sc.p2, car1)
    await park(db, sc.p3, car2)
    await make_departure(db, car1, TODAY, time(15, 30), is_ai_estimated=True)  # 50분 뒤
    await make_departure(db, car2, TODAY, time(18))  # 3시간 넘게 남음

    items = _by_slot(await _list(db, sc.me))

    soon = items[sc.p2.id]
    assert soon.availability == "SOON_EXIT"
    assert soon.estimated_free_at == datetime(2026, 10, 7, 15, 30, tzinfo=KST)
    assert soon.estimate_source == "AI_ESTIMATED"
    assert items[sc.p3.id].availability == "UNAVAILABLE"
    assert items[sc.p3.id].estimated_free_at is None  # 출차 시간 원본은 노출하지 않는다


async def test_permanent_parking_is_unavailable(db, sc):
    car = await make_vehicle(db, "11가1111", sc.neighbor)
    await park(db, sc.p2, car, is_permanent=True)
    await make_departure(db, car, TODAY, time(15))

    assert _by_slot(await _list(db, sc.me))[sc.p2.id].availability == "UNAVAILABLE"


async def test_accepted_share_in_progress_makes_slot_busy(db, sc):
    other = await make_resident(db, "other@example.com", sc.mine)
    await make_request_on(db, sc.offer_p2, other.id, TODAY, 14, 15)  # 15:00 에 끝남

    item = _by_slot(await _list(db, sc.me))[sc.p2.id]

    assert item.availability == "SOON_EXIT"
    assert item.estimated_free_at == datetime(2026, 10, 7, 15, tzinfo=KST)
    assert item.estimate_source == "NONE"


async def test_reservable_when_offer_closed_now(db, sc):
    slot = await make_slot(db, sc.zone_b, 2)
    # 평일 09~12시만, 무료, 최대 2시간 → 수요일 14:40 에는 닫혀 있고 내일 09:00 부터
    await make_share_offer(
        db,
        slot,
        sc.host,
        hourly_price=0,
        available_weekdays=[0, 1, 2, 3, 4],
        start_hour=9,
        end_hour=12,
        max_hours=2,
        end_date=date(9999, 12, 31),
    )

    item = _by_slot(await _list(db, sc.me))[slot.id]

    assert item.availability == "RESERVABLE"
    assert item.available_from == datetime(2026, 10, 8, 9, tzinfo=KST)
    assert item.weekdays_only is True and item.hourly_price == 0
    assert item.info == "내일 09:00부터 이용 가능 · 무료 · 최대 2시간 · 평일만"


async def test_ended_offer_is_not_listed(db, sc):
    slot = await make_slot(db, sc.zone_b, 2)
    await make_share_offer(db, slot, sc.host, start_date=date(2026, 9, 1), end_date=date(2026, 9, 30))

    assert slot.id not in _by_slot(await _list(db, sc.me))


async def test_filters(db, sc):
    free_slot = await make_slot(db, sc.zone_b, 2)
    await make_share_offer(
        db, free_slot, sc.host, hourly_price=0, start_hour=20, end_hour=22, end_date=date(9999, 12, 31)
    )
    car = await make_vehicle(db, "11가1111", sc.neighbor)
    await park(db, sc.p3, car, is_permanent=True)

    ids = {f: [e.slot_id for e in (await _list(db, sc.me, filter_=f)).items] for f in ("now", "reservable", "free")}

    assert ids["now"] == [sc.p2.id]
    assert ids["reservable"] == [free_slot.id]
    assert ids["free"] == [free_slot.id]


async def test_search_by_building_name_or_address(db, sc):
    assert len((await _list(db, sc.me, q="햇살")).items) == 2
    assert len((await _list(db, sc.me, q="월계동")).items) == 2  # 주소 (factories 기본 주소)
    assert (await _list(db, sc.me, q="없는빌라")).items == []


async def test_distance_order_and_lat_lng_together(db, sc):
    near = await make_building(db, "NEAR01", "가까운빌라", sc.alley)
    near_slot = await make_slot(db, await make_garage(db, near))
    await make_share_offer(db, near_slot, sc.host, end_date=date(9999, 12, 31))
    await set_location(db, near, 37.6201, 127.0601)
    await set_location(db, sc.next_door, 37.63, 127.07)

    page = await _list(db, sc.me, lat=37.62, lng=127.06)

    assert [e.slot_id for e in page.items] == [near_slot.id, sc.p3.id, sc.p2.id]
    with pytest.raises(InvalidInputError):
        await _list(db, sc.me, lat=37.62)


async def test_pagination(db, sc):
    first = await _list(db, sc.me, limit=1)
    assert [e.slot_id for e in first.items] == [sc.p3.id] and first.next_cursor == str(sc.p3.id)

    second = await _list(db, sc.me, limit=1, cursor=first.next_cursor)
    assert [e.slot_id for e in second.items] == [sc.p2.id] and second.next_cursor is None


# ── 차고지 상세 ──


async def test_detail_slots_states_and_summary(db, sc):
    car = await make_vehicle(db, "11가1111", sc.neighbor)
    await park(db, sc.p3, car)
    await make_departure(db, car, TODAY, time(21))
    p1_offer = await make_share_offer(
        db, sc.p1, sc.host, hourly_price=1, start_hour=7, end_hour=23, max_hours=6, end_date=date(9999, 12, 31)
    )

    detail = await garages.get_garage(db, sc.me, sc.next_door.id, now=NOW)

    assert detail.building.id == sc.next_door.id and detail.alley.id == sc.alley.id
    assert [(s.label, s.state) for s in detail.slots] == [("P1", "AVAILABLE"), ("P2", "AVAILABLE"), ("P3", "IN_USE")]
    p3 = detail.slots[2]
    assert p3.in_use_until == datetime(2026, 10, 7, 21, tzinfo=KST) and p3.estimated_free_at is None
    assert p3.zone.id == sc.zone_b.id and p3.number == 1 and p3.offer.id == sc.offer_p3.id
    assert detail.slots[0].offer.id == p1_offer.id
    s = detail.summary
    assert (s.start_hour, s.end_hour, s.min_hourly_price, s.max_hours) == (6, 23, 1, 6)


async def test_detail_soon_exit_and_unlimited_max_hours(db, sc):
    car = await make_vehicle(db, "11가1111", sc.neighbor)
    await park(db, sc.p2, car)
    await make_departure(db, car, TODAY, time(15))
    await make_share_offer(db, sc.p1, sc.host, max_hours=None, end_date=date(9999, 12, 31))

    detail = await garages.get_garage(db, sc.me, sc.next_door.id, now=NOW)

    p2 = next(s for s in detail.slots if s.slot_id == sc.p2.id)
    assert p2.state == "SOON_EXIT" and p2.estimated_free_at == datetime(2026, 10, 7, 15, tzinfo=KST)
    assert detail.summary.max_hours is None  # 하나라도 제한 없음이면 null


async def test_detail_without_shared_slots(db, sc):
    empty = await make_building(db, "EMPTY1", "빈빌라", sc.alley)

    detail = await garages.get_garage(db, sc.me, empty.id, now=NOW)

    assert detail.slots == []
    assert detail.summary.start_hour is None and detail.summary.min_hourly_price is None


async def test_detail_not_found_outside_my_alley_or_my_building(db, sc):
    for garage_id in (sc.far.id, sc.mine.id, 999999):
        with pytest.raises(NotFoundError):
            await garages.get_garage(db, sc.me, garage_id, now=NOW)


async def test_pending_request_does_not_change_state(db, sc):
    other = await make_resident(db, "other@example.com", sc.mine)
    await make_request_on(db, sc.offer_p2, other.id, TODAY, 14, 15, status=ShareRequestStatus.PENDING)

    detail = await garages.get_garage(db, sc.me, sc.next_door.id, now=NOW)

    assert next(s for s in detail.slots if s.slot_id == sc.p2.id).state == "AVAILABLE"
