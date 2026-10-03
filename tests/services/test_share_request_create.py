"""새 공유 요청 API 의 서비스 (services/share_requests.create_for_user · get_mine · list_mine). 기준 시각: 2026-10-07(수) 14:40 KST."""

from datetime import date, datetime

import pytest
from sqlalchemy import select

from app.core.error_codes import ErrorCode
from app.models.notification import Notification, NotificationType
from app.models.resident import Resident
from app.models.share_request import ShareRequestStatus
from app.schemas.common import KST
from app.services import share_requests as service
from app.services.exceptions import ConflictError, InvalidInputError, NotFoundError
from tests.factories import make_garage, make_resident, make_share_offer, make_slot, make_vehicle
from tests.factories_share import make_request_on, make_scenario

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 7, 14, 40, tzinfo=KST)
DAY = date(2026, 10, 8)  # 목요일


@pytest.fixture
async def sc(db):
    return await make_scenario(db, my_tokens=10)


async def _create(db, sc, user=None, offer=None, day=DAY, start=10, end=13, **kwargs):
    return await service.create_for_user(
        db,
        user or sc.me,
        offer_id=(offer or sc.offer_p2).id,
        request_date=day,
        start_hour=start,
        end_hour=end,
        now=NOW,
        **kwargs,
    )


async def test_create_pending_with_fixed_price_and_notifies_host(db, sc, session_factory):
    created = await _create(db, sc, vehicle_id=sc.my_vehicle.id)

    assert created.status == ShareRequestStatus.PENDING
    assert created.total_price == 6 and created.slot_id == sc.p2.id and created.vehicle_id == sc.my_vehicle.id
    async with session_factory() as other:
        assert (await other.get(Resident, sc.me.id)).token_balance == 10  # 요청만으로는 차감 없음
        notes = (await other.scalars(select(Notification))).all()
    assert len(notes) == 1
    note = notes[0]
    assert note.resident_id == sc.host.id and note.type == NotificationType.SHARE_REQUEST
    assert note.share_request_id == created.id
    assert note.body == "P2 · 10월 8일 10:00~13:00"


async def test_price_is_fixed_at_request_time(db, sc):
    created = await _create(db, sc)
    sc.offer_p2.hourly_price = 3
    await db.commit()

    assert (await service.get_mine(db, sc.me, created.id)).request.total_price == 6


async def test_vehicle_optional(db, sc):
    assert (await _create(db, sc)).vehicle_id is None


async def test_ongoing_hour_today_is_allowed(db, sc):
    assert (await _create(db, sc, day=NOW.date(), start=14, end=16)).total_price == 4


@pytest.mark.parametrize(
    ("day", "start", "end", "message", "detail"),
    [
        (DAY, 5, 8, "운영 시간 밖입니다.", {"start_hour": 6, "end_hour": 22}),
        (DAY, 20, 23, "운영 시간 밖입니다.", {"start_hour": 6, "end_hour": 22}),
        (DAY, 10, 15, "최대 이용 시간을 초과했습니다.", {"max_hours": 4}),
        (date(2026, 10, 7), 10, 12, "이미 지난 시간에는 요청할 수 없습니다.", None),
    ],
)
async def test_invalid_window(db, sc, day, start, end, message, detail):
    with pytest.raises(InvalidInputError) as exc:
        await _create(db, sc, day=day, start=start, end=end)
    assert exc.value.message == message and exc.value.detail == detail


async def test_invalid_weekday_and_period(db, sc):
    weekday_only = await make_share_offer(
        db, sc.p1, sc.host, available_weekdays=[0, 1, 2, 3, 4], end_date=date(2026, 10, 31)
    )
    with pytest.raises(InvalidInputError) as exc:
        await _create(db, sc, offer=weekday_only, day=date(2026, 10, 10))  # 토요일
    assert exc.value.detail == {"weekdays": ["MON", "TUE", "WED", "THU", "FRI"]}
    with pytest.raises(InvalidInputError):
        await _create(db, sc, offer=weekday_only, day=date(2026, 11, 2))  # 기간 밖


async def test_own_offer_is_rejected(db, sc):
    with pytest.raises(InvalidInputError, match="내가 연 공유 조건"):
        await _create(db, sc, user=sc.host)


async def test_my_building_slot_is_rejected(db, sc):
    my_slot = await make_slot(db, await make_garage(db, sc.mine))
    my_manager = await make_resident(db, "mgr@example.com", sc.mine)
    offer = await make_share_offer(db, my_slot, my_manager)

    with pytest.raises(InvalidInputError, match="우리 빌라"):
        await _create(db, sc, offer=offer)


async def test_not_visible_offers_are_not_found(db, sc):
    far_slot = await make_slot(db, await make_garage(db, sc.far))
    far_offer = await make_share_offer(db, far_slot, sc.host)
    private = await make_share_offer(db, sc.p1, sc.host, is_public=False)
    inactive_slot = await make_slot(db, sc.zone_b, 2)
    inactive = await make_share_offer(db, inactive_slot, sc.host)
    inactive_slot.is_active = False
    await db.commit()

    for offer in (far_offer, private, inactive):
        with pytest.raises(NotFoundError):
            await _create(db, sc, offer=offer)
    with pytest.raises(NotFoundError):
        await service.create_for_user(db, sc.me, offer_id=999999, request_date=DAY, start_hour=10, end_hour=12, now=NOW)
    lonely = await make_resident(db, "lonely@example.com", token_balance=100)
    with pytest.raises(NotFoundError):
        await _create(db, sc, user=lonely)


async def test_vehicle_must_be_mine(db, sc):
    others = await make_vehicle(db, "99가9999", sc.neighbor)
    with pytest.raises(NotFoundError, match="차량"):
        await _create(db, sc, vehicle_id=others.id)


async def test_overlap_with_accepted_request_conflicts(db, sc):
    await make_request_on(db, sc.offer_p2, sc.neighbor.id, DAY, 12, 14)
    await make_request_on(db, sc.offer_p2, sc.neighbor.id, DAY, 9, 11, status=ShareRequestStatus.PENDING)

    with pytest.raises(ConflictError) as exc:
        await _create(db, sc, start=10, end=13)
    assert exc.value.code == ErrorCode.GARAGE_TIME_CONFLICT
    # 끝 시각은 포함하지 않는다, 대기 중인 요청과는 겹쳐도 된다
    assert (await _create(db, sc, start=9, end=12)).status == ShareRequestStatus.PENDING


async def test_insufficient_tokens(db, sc):
    poor = await make_resident(db, "poor@example.com", sc.mine, token_balance=4)

    with pytest.raises(ConflictError) as exc:
        await _create(db, sc, user=poor)  # 3시간 × 2토큰 = 6
    assert exc.value.code == ErrorCode.INSUFFICIENT_TOKENS
    assert exc.value.detail == {"required": 6, "balance": 4}


async def test_free_offer_needs_no_tokens(db, sc):
    broke = await make_resident(db, "broke@example.com", sc.mine, token_balance=0)
    free = await make_share_offer(db, sc.p1, sc.host, hourly_price=0, end_date=date(9999, 12, 31))

    assert (await _create(db, sc, user=broke, offer=free)).total_price == 0


async def test_get_mine_and_list_mine(db, sc):
    first = await _create(db, sc, start=10, end=11)
    second = await _create(db, sc, offer=sc.offer_p3, start=11, end=12)
    stranger = await make_resident(db, "stranger@example.com", sc.mine, token_balance=100)
    await _create(db, sc, user=stranger, start=15, end=16)

    view = await service.get_mine(db, sc.me, first.id)
    assert (view.garage_id, view.garage_name, view.slot_label) == (sc.next_door.id, "햇살빌라", "P2")

    page = await service.list_mine(db, sc.me)
    assert [(v.request.id, v.slot_label) for v in page.items] == [(second.id, "P3"), (first.id, "P2")]
    assert page.next_cursor is None
    page = await service.list_mine(db, sc.me, limit=1)
    assert [v.request.id for v in page.items] == [second.id] and page.next_cursor == str(second.id)

    with pytest.raises(NotFoundError):
        await service.get_mine(db, stranger, first.id)
    with pytest.raises(NotFoundError):
        await service.get_mine(db, sc.me, 999999)
