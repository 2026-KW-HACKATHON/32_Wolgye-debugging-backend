"""HTTP 없이 서비스 함수를 직접 호출."""

from datetime import date

import pytest
from sqlalchemy import select

from app.core.error_codes import ErrorCode
from app.models.resident import Resident
from app.models.share_request import ShareRequestStatus
from app.models.token_transfer import TokenTransfer
from app.schemas.share_request import ShareRequestCreate, ShareRequestDecision
from app.services import share_requests as share_request_service
from app.services.exceptions import ConflictError, NotFoundError
from tests.factories import make_building, make_garage, make_resident, make_share_offer, make_share_request, make_slot

pytestmark = pytest.mark.anyio

ACCEPT = ShareRequestDecision(status=ShareRequestStatus.ACCEPTED)


@pytest.fixture
async def slot(db):
    return await make_slot(db, await make_garage(db, await make_building(db)))


@pytest.fixture
async def host(db):
    return await make_resident(db, "host@example.com", token_balance=5)


@pytest.fixture
async def requester(db):
    return await make_resident(db, "req@example.com", token_balance=10)


@pytest.fixture
async def offer(db, slot, host):
    # 2026-10-05(월) ~ 10-18, 월·수요일만, 06~17시, 최대 4시간, 시간당 2 토큰
    return await make_share_offer(
        db,
        slot,
        host,
        hourly_price=2,
        start_date=date(2026, 10, 5),
        end_date=date(2026, 10, 18),
        available_weekdays=[0, 2],
        start_hour=6,
        end_hour=17,
        max_hours=4,
    )


@pytest.fixture
async def pending_request(db, offer, requester):
    return await make_share_request(db, offer, requester)  # 10~12시, 4 토큰


async def _balances(session_factory, *residents: Resident) -> list[int]:
    async with session_factory() as other:
        result = await other.execute(
            select(Resident.id, Resident.token_balance).where(Resident.id.in_([r.id for r in residents]))
        )
        balances = dict(result.all())
    return [balances[r.id] for r in residents]


def _create(offer, requester, day=date(2026, 10, 7), start_hour=9, end_hour=12) -> ShareRequestCreate:
    return ShareRequestCreate(
        offer_id=offer.id, requester_id=requester.id, request_date=day, start_hour=start_hour, end_hour=end_hour
    )


# --- 생성: 공유 조건 검사 ------------------------------------------------------


async def test_create_computes_total_price_and_slot(db, offer, requester):
    created = await share_request_service.create_share_request(db, _create(offer, requester))
    assert created.slot_id == offer.slot_id
    assert created.total_price == 6  # 3시간 × 2


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"day": date(2026, 10, 19)}, "Requested date is outside the share offer"),  # 기간 밖 (월)
        ({"day": date(2026, 10, 6)}, "Requested date is outside the share offer"),  # 화요일
        ({"start_hour": 5, "end_hour": 7}, "Requested hours are outside the share offer"),
        ({"start_hour": 15, "end_hour": 18}, "Requested hours are outside the share offer"),
        ({"start_hour": 6, "end_hour": 11}, "Requested hours exceed max_hours"),
    ],
)
async def test_create_outside_offer(db, offer, requester, kwargs, message):
    with pytest.raises(ConflictError) as exc_info:
        await share_request_service.create_share_request(db, _create(offer, requester, **kwargs))
    assert exc_info.value.message == message


async def test_create_on_stopped_offer(db, slot, host, requester):
    stopped = await make_share_offer(db, slot, host, is_public=False)
    with pytest.raises(ConflictError) as exc_info:
        await share_request_service.create_share_request(db, _create(stopped, requester, day=date(2026, 10, 2)))
    assert exc_info.value.message == "Share offer is not public"


async def test_create_own_offer(db, offer, host):
    with pytest.raises(ConflictError) as exc_info:
        await share_request_service.create_share_request(db, _create(offer, host))
    assert exc_info.value.message == "Cannot request own share offer"


async def test_create_without_enough_tokens(db, offer):
    poor = await make_resident(db, "poor@example.com", token_balance=3)
    with pytest.raises(ConflictError) as exc_info:
        await share_request_service.create_share_request(db, _create(offer, poor))  # 6 토큰 필요
    assert exc_info.value.message == "Not enough tokens"


async def test_create_offer_not_found(db, requester):
    payload = ShareRequestCreate(
        offer_id=999, requester_id=requester.id, request_date=date(2026, 10, 7), start_hour=9, end_hour=10
    )
    with pytest.raises(NotFoundError):
        await share_request_service.create_share_request(db, payload)


# --- 결정: 토큰 이동 ------------------------------------------------------------


async def test_accept_transfers_tokens_to_host(db, session_factory, pending_request, requester, host):
    decided = await share_request_service.decide(db, pending_request.id, ACCEPT)
    assert decided.status == ShareRequestStatus.ACCEPTED
    assert decided.responded_at is not None

    # 서비스가 commit 했으므로 새 세션에서도 보인다
    assert await _balances(session_factory, requester, host) == [10 - 4, 5 + 4]
    async with session_factory() as other:
        transfer = (await other.execute(select(TokenTransfer))).scalar_one()
    assert (transfer.sender_id, transfer.receiver_id, transfer.amount, transfer.share_request_id) == (
        requester.id,
        host.id,
        4,
        pending_request.id,
    )


async def test_reject_does_not_move_tokens(db, session_factory, pending_request, requester, host):
    await share_request_service.decide(
        db, pending_request.id, ShareRequestDecision(status=ShareRequestStatus.REJECTED)
    )
    assert await _balances(session_factory, requester, host) == [10, 5]


async def test_accept_fails_when_balance_dropped(db, session_factory, offer, host):
    """요청 뒤 잔액이 줄었으면 수락이 실패하고, 상태도 PENDING 으로 남는다."""
    requester = await make_resident(db, "spent@example.com", token_balance=1)
    req = await make_share_request(db, offer, requester)  # 4 토큰
    req_id = req.id

    with pytest.raises(ConflictError) as exc_info:
        await share_request_service.decide(db, req_id, ACCEPT)
    assert exc_info.value.code == ErrorCode.INSUFFICIENT_TOKENS

    # 서비스는 commit 하지 않았다 → 다른 세션에서는 바뀐 것이 없다
    assert await _balances(session_factory, requester, host) == [1, 5]
    async with session_factory() as other:
        assert (await share_request_service.get_share_request(other, req_id)).status == ShareRequestStatus.PENDING


async def test_free_offer_accept_records_no_transfer(db, session_factory, slot, host, requester):
    free = await make_share_offer(db, slot, host, hourly_price=0)
    req = await make_share_request(db, free, requester)

    await share_request_service.decide(db, req.id, ACCEPT)
    async with session_factory() as other:
        assert (await other.execute(select(TokenTransfer))).first() is None


async def test_adjacent_hours_can_both_be_accepted(db, offer, requester):
    """10~12시와 12~14시는 겹치지 않는다 (정시 단위, 끝 시각 미포함)."""
    first = await make_share_request(db, offer, requester, start_hour=10, end_hour=12)
    second = await make_share_request(db, offer, requester, start_hour=12, end_hour=14)
    await share_request_service.decide(db, first.id, ACCEPT)
    decided = await share_request_service.decide(db, second.id, ACCEPT)
    assert decided.status == ShareRequestStatus.ACCEPTED


async def test_decide_not_found(db):
    with pytest.raises(NotFoundError) as exc_info:
        await share_request_service.decide(db, 999, ACCEPT)
    assert exc_info.value.message == "Share request not found"


async def test_decide_already_decided(db, pending_request):
    await share_request_service.decide(
        db, pending_request.id, ShareRequestDecision(status=ShareRequestStatus.REJECTED)
    )

    with pytest.raises(ConflictError) as exc_info:
        await share_request_service.decide(db, pending_request.id, ACCEPT)
    assert exc_info.value.message == "Already decided"
