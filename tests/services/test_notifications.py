"""알림 생성 서비스 create() — 종류별 FK 규칙, commit 하지 않음, link 계산 (결정 11)."""

import pytest
from sqlalchemy import select

from app.models.move_request import MoveRequest
from app.models.notification import Notification, NotificationType
from app.schemas.notification import notification_link
from app.services import notifications
from tests.factories import (
    make_building,
    make_garage,
    make_resident,
    make_share_offer,
    make_share_request,
    make_slot,
    make_vehicle,
)

pytestmark = pytest.mark.anyio


async def _move_request(db, requester, owner) -> MoveRequest:
    vehicle = await make_vehicle(db, "12가3456", owner=owner)
    mr = MoveRequest(requester_id=requester.id, target_vehicle_id=vehicle.id)
    db.add(mr)
    await db.commit()
    await db.refresh(mr)
    return mr


async def _share_request(db, requester):
    building = await make_building(db)
    host = await make_resident(db, "host@example.com", building=building)
    slot = await make_slot(db, await make_garage(db, building))
    offer = await make_share_offer(db, slot, host)
    return await make_share_request(db, offer, requester)


async def test_create_move_request_links_move_request(db):
    owner = await make_resident(db, "owner@example.com")
    requester = await make_resident(db, "req@example.com")
    mr = await _move_request(db, requester, owner)

    n = await notifications.create(
        db, owner.id, NotificationType.MOVE_REQUEST, "주차 요청 도착", "101동 입주민", move_request_id=mr.id
    )

    assert n.id is not None and n.created_at is not None and n.is_read is False
    assert n.move_request_id == mr.id and n.share_request_id is None
    link = notification_link(n)
    assert (link.screen, link.id) == ("MOVE_REQUEST", mr.id)


@pytest.mark.parametrize("type_", [NotificationType.SHARE_REQUEST, NotificationType.SHARE_RESULT])
async def test_create_share_types_link_share_request(db, type_):
    requester = await make_resident(db, "req@example.com")
    sr = await _share_request(db, requester)

    n = await notifications.create(db, requester.id, type_, "공유", "본문", share_request_id=sr.id)

    link = notification_link(n)
    assert (link.screen, link.id) == ("SHARE_REQUEST", sr.id)


async def test_create_block_alert_links_home(db):
    r = await make_resident(db)
    n = await notifications.create(db, r.id, NotificationType.BLOCK_ALERT, "막힘 알림", "막혀 있습니다.")
    link = notification_link(n)
    assert (link.screen, link.id) == ("HOME", None)


async def test_create_exit_done_has_no_link(db):
    r = await make_resident(db)
    n = await notifications.create(db, r.id, NotificationType.EXIT_DONE, "출차 완료 안내", "건물 앞 1번 비어 있음")
    assert notification_link(n) is None


@pytest.mark.parametrize(
    ("type_", "kwargs"),
    [
        (NotificationType.MOVE_REQUEST, {}),
        (NotificationType.MOVE_REQUEST, {"move_request_id": 1, "share_request_id": 1}),
        (NotificationType.SHARE_REQUEST, {}),
        (NotificationType.SHARE_RESULT, {"move_request_id": 1}),
        (NotificationType.BLOCK_ALERT, {"move_request_id": 1}),
        (NotificationType.EXIT_DONE, {"share_request_id": 1}),
    ],
)
async def test_create_rejects_wrong_fk(db, type_, kwargs):
    r = await make_resident(db)
    with pytest.raises(ValueError):
        await notifications.create(db, r.id, type_, "t", "b", **kwargs)


async def test_create_does_not_commit(db, session_factory):
    r = await make_resident(db)
    await notifications.create(db, r.id, NotificationType.EXIT_DONE, "t", "b")

    async with session_factory() as other:
        assert (await other.execute(select(Notification))).scalars().all() == []

    await db.rollback()
    assert (await db.execute(select(Notification))).scalars().all() == []
