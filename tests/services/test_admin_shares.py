"""관리인 공유 조건·공유 요청 결정 비즈니스 규칙 (#13)."""

from datetime import date

import pytest
from sqlalchemy import func, select

from app.core.error_codes import ErrorCode
from app.models.notification import Notification, NotificationType
from app.models.resident import Resident, ResidentRole
from app.models.share_offer import ShareOffer
from app.models.share_request import ShareRequest, ShareRequestStatus
from app.models.token_transfer import TokenTransfer
from app.schemas.admin_shares import ShareOfferCreate
from app.services import admin_shares
from app.services.exceptions import ConflictError, ForbiddenError, InvalidInputError
from tests.factories import (
    make_building,
    make_garage,
    make_resident,
    make_share_offer,
    make_share_request,
    make_slot,
)

pytestmark = pytest.mark.anyio


async def _setup(db, *, price: int = 2, balance: int = 100):
    building = await make_building(db)
    garage = await make_garage(db, building, name="골목")
    slot = await make_slot(db, garage, 1)
    admin = await make_resident(db, "admin@example.com", building=building, role=ResidentRole.MANAGER)
    other = await make_building(db, invite_code="INV002", name="옆빌라")
    requester = await make_resident(db, "req@example.com", building=other, token_balance=balance)
    offer = await make_share_offer(db, slot, admin, hourly_price=price)
    return building, slot, admin, requester, offer


async def _reload(db, model, id_):
    return await db.scalar(select(model).where(model.id == id_).execution_options(populate_existing=True))


async def test_create_offers_sets_open_period_and_host(db):
    building, slot, admin, _, _ = await _setup(db)
    garage = await make_garage(db, building, name="필로티 외부")
    slot2 = await make_slot(db, garage, 1)
    payload = ShareOfferCreate(slot_ids=[slot.id, slot2.id], weekdays=["MON", "FRI"], start_hour=7, end_hour=23)

    views = await admin_shares.create_offers(db, building.id, admin, payload)

    assert [v.slot_label for v in views] == ["P1", "P2"]
    for v in views:
        assert v.offer.host_id == admin.id
        assert v.offer.start_date == admin_shares.today_kst()
        assert v.offer.end_date == date(9999, 12, 31)
        assert v.offer.available_weekdays == [0, 4]
        assert v.offer.max_hours is None


async def test_create_offers_all_or_nothing(db):
    building, slot, admin, _, _ = await _setup(db)
    other_garage = await make_garage(db, await make_building(db, invite_code="INV003", name="남의빌라"))
    foreign_slot = await make_slot(db, other_garage, 1)
    before = await db.scalar(select(func.count()).select_from(ShareOffer))

    with pytest.raises(InvalidInputError) as exc:
        await admin_shares.create_offers(
            db, building.id, admin, ShareOfferCreate(slot_ids=[slot.id, foreign_slot.id], start_hour=7, end_hour=9)
        )
    assert exc.value.detail == {"slot_id": foreign_slot.id}
    assert await db.scalar(select(func.count()).select_from(ShareOffer)) == before


async def test_create_offers_rejects_inactive_slot(db):
    building, slot, admin, _, _ = await _setup(db)
    slot.is_active = False
    await db.commit()
    with pytest.raises(InvalidInputError):
        await admin_shares.create_offers(db, building.id, admin, ShareOfferCreate(slot_ids=[slot.id], start_hour=7, end_hour=9))


async def test_accept_moves_tokens_and_notifies(db):
    _, _, admin, requester, offer = await _setup(db, price=2, balance=100)
    req = await make_share_request(db, offer, requester, start_hour=10, end_hour=14)  # 8 토큰

    result = await admin_shares.decide(db, admin, req.id, "APPROVED")

    assert result.status == ShareRequestStatus.ACCEPTED
    assert result.responded_at is not None
    assert (await _reload(db, Resident, requester.id)).token_balance == 92
    assert (await _reload(db, Resident, admin.id)).token_balance == 8
    transfer = await db.scalar(select(TokenTransfer))
    assert (transfer.sender_id, transfer.receiver_id, transfer.amount, transfer.share_request_id) == (
        requester.id, admin.id, 8, req.id,
    )
    note = await db.scalar(select(Notification))
    assert (note.resident_id, note.type, note.share_request_id) == (requester.id, NotificationType.SHARE_RESULT, req.id)


async def test_accept_free_offer_moves_no_tokens(db):
    _, _, admin, requester, offer = await _setup(db, price=0, balance=0)
    req = await make_share_request(db, offer, requester)

    await admin_shares.decide(db, admin, req.id, "APPROVED")

    assert await db.scalar(select(func.count()).select_from(TokenTransfer)) == 0


async def test_reject_notifies_with_reason(db):
    _, _, admin, requester, offer = await _setup(db)
    req = await make_share_request(db, offer, requester)

    result = await admin_shares.decide(db, admin, req.id, "REJECTED", "시간 불가")

    assert result.status == ShareRequestStatus.REJECTED
    assert result.reject_reason == "시간 불가"
    note = await db.scalar(select(Notification))
    assert note.type == NotificationType.SHARE_RESULT
    assert note.body == "시간 불가"
    assert await db.scalar(select(func.count()).select_from(TokenTransfer)) == 0


async def test_accept_with_insufficient_tokens_keeps_pending(db):
    _, _, admin, requester, offer = await _setup(db, price=2, balance=3)
    req = await make_share_request(db, offer, requester, start_hour=10, end_hour=12)  # 4 토큰
    req_id = req.id  # 실패하면 서비스가 rollback 해서 세션 객체가 만료된다

    with pytest.raises(ConflictError) as exc:
        await admin_shares.decide(db, admin, req_id, "APPROVED")

    assert exc.value.code == ErrorCode.INSUFFICIENT_TOKENS
    assert exc.value.detail == {"required": 4, "balance": 3}
    reloaded = await _reload(db, ShareRequest, req_id)
    assert reloaded.status == ShareRequestStatus.PENDING
    assert reloaded.responded_at is None
    assert await db.scalar(select(func.count()).select_from(Notification)) == 0


async def test_accept_overlapping_request_conflicts(db):
    _, _, admin, requester, offer = await _setup(db)
    await make_share_request(db, offer, requester, status=ShareRequestStatus.ACCEPTED, start_hour=10, end_hour=12)
    req = await make_share_request(db, offer, requester, start_hour=11, end_hour=13)

    with pytest.raises(ConflictError) as exc:
        await admin_shares.decide(db, admin, req.id, "APPROVED")
    assert exc.value.code == ErrorCode.GARAGE_TIME_CONFLICT


async def test_accept_adjacent_request_ok(db):
    _, _, admin, requester, offer = await _setup(db)
    await make_share_request(db, offer, requester, status=ShareRequestStatus.ACCEPTED, start_hour=10, end_hour=12)
    req = await make_share_request(db, offer, requester, start_hour=12, end_hour=13)

    result = await admin_shares.decide(db, admin, req.id, "APPROVED")
    assert result.status == ShareRequestStatus.ACCEPTED


async def test_decide_twice_already_decided(db):
    _, _, admin, requester, offer = await _setup(db)
    req = await make_share_request(db, offer, requester, status=ShareRequestStatus.REJECTED)

    with pytest.raises(ConflictError) as exc:
        await admin_shares.decide(db, admin, req.id, "APPROVED")
    assert exc.value.code == ErrorCode.ALREADY_DECIDED
    assert exc.value.detail == {"status": "REJECTED"}


async def test_decide_by_other_building_admin_forbidden(db):
    _, _, _, requester, offer = await _setup(db)
    req = await make_share_request(db, offer, requester)
    stranger = await make_resident(
        db, "other-admin@example.com", building=await make_building(db, invite_code="INV9"), role=ResidentRole.MANAGER
    )

    with pytest.raises(ForbiddenError) as exc:
        await admin_shares.decide(db, stranger, req.id, "APPROVED")
    assert exc.value.code == ErrorCode.NOT_BUILDING_ADMIN


async def test_labels_are_building_ordinals_across_zones(db):
    building, _slot, admin, requester, _ = await _setup(db)
    later_zone = await make_garage(db, building, name="건물 앞")
    zone_slot = await make_slot(db, later_zone, 1)
    offer2 = await make_share_offer(db, zone_slot, admin)
    req = await make_share_request(db, offer2, requester)

    labels = [v.slot_label for v in await admin_shares.list_offers(db, building.id)]
    assert labels == ["P1", "P2"]
    page = await admin_shares.list_requests(db, building.id)
    assert [(v.request.id, v.slot_label) for v in page.page.items] == [(req.id, "P2")]


async def test_accept_notification_names_slot_by_ordinal(db):
    _, _, admin, requester, offer = await _setup(db)
    req = await make_share_request(db, offer, requester, start_hour=10, end_hour=12)

    await admin_shares.decide(db, admin, req.id, "APPROVED")

    note = await db.scalar(select(Notification))
    assert note.title == "공유 요청이 수락되었어요"
    assert note.body.startswith("P1 · ")
