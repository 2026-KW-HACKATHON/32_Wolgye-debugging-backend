"""알림 API: 목록(최신순·페이지네이션·link), 읽음, 전체 읽음."""

import pytest
from sqlalchemy import select

from app.core.error_codes import ErrorCode
from app.models.notification import Notification, NotificationType
from app.services import notifications
from tests.factories import make_resident
from tests.helpers import assert_error, auth_headers

pytestmark = pytest.mark.anyio


async def _notify(db, resident, type_=NotificationType.BLOCK_ALERT, title="막힘 알림") -> Notification:
    n = await notifications.create(db, resident.id, type_, title, "본문")
    await db.commit()
    return n


async def _is_read(session_factory, notification_id: int) -> bool:
    async with session_factory() as s:
        return (await s.get(Notification, notification_id)).is_read


async def test_list_newest_first_only_mine(client, db):
    me = await make_resident(db, "me@example.com")
    other = await make_resident(db, "other@example.com")
    first = await _notify(db, me)
    await _notify(db, other)
    second = await _notify(db, me, NotificationType.EXIT_DONE, "출차 완료 안내")

    res = await client.get("/api/v1/notifications", headers=auth_headers(me))

    assert res.status_code == 200
    body = res.json()
    assert [item["id"] for item in body["items"]] == [second.id, first.id]
    assert body["next_cursor"] is None
    newest, oldest = body["items"]
    assert newest["type"] == "EXIT_DONE" and newest["link"] is None
    assert newest["title"] == "출차 완료 안내" and newest["body"] == "본문" and newest["is_read"] is False
    assert newest["created_at"]
    assert oldest["type"] == "BLOCK_ALERT" and oldest["link"] == {"screen": "HOME", "id": None}


async def test_list_pagination(client, db):
    me = await make_resident(db)
    ids = [(await _notify(db, me)).id for _ in range(5)]

    res = await client.get("/api/v1/notifications", params={"limit": 2}, headers=auth_headers(me))
    page1 = res.json()
    assert [i["id"] for i in page1["items"]] == [ids[4], ids[3]]
    assert page1["next_cursor"] == str(ids[3])

    res = await client.get(
        "/api/v1/notifications", params={"limit": 2, "cursor": page1["next_cursor"]}, headers=auth_headers(me)
    )
    page2 = res.json()
    assert [i["id"] for i in page2["items"]] == [ids[2], ids[1]]

    res = await client.get(
        "/api/v1/notifications", params={"limit": 2, "cursor": page2["next_cursor"]}, headers=auth_headers(me)
    )
    page3 = res.json()
    assert [i["id"] for i in page3["items"]] == [ids[0]]
    assert page3["next_cursor"] is None


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 51}, {"cursor": "abc"}])
async def test_list_invalid_paging_400(client, db, params):
    me = await make_resident(db)
    res = await client.get("/api/v1/notifications", params=params, headers=auth_headers(me))
    assert res.status_code == 400
    assert_error(res, ErrorCode.INVALID_INPUT)


async def test_list_requires_login(client):
    res = await client.get("/api/v1/notifications")
    assert res.status_code == 401
    assert_error(res, ErrorCode.UNAUTHORIZED)


async def test_read_one(client, db, session_factory):
    me = await make_resident(db)
    n = await _notify(db, me)
    untouched = await _notify(db, me)

    res = await client.post(f"/api/v1/notifications/{n.id}/read", headers=auth_headers(me))
    assert res.status_code == 204
    assert res.content == b""
    assert await _is_read(session_factory, n.id) is True
    assert await _is_read(session_factory, untouched.id) is False

    # 이미 읽은 알림도 204
    res = await client.post(f"/api/v1/notifications/{n.id}/read", headers=auth_headers(me))
    assert res.status_code == 204


async def test_read_others_notification_404(client, db, session_factory):
    me = await make_resident(db, "me@example.com")
    other = await make_resident(db, "other@example.com")
    n = await _notify(db, other)

    res = await client.post(f"/api/v1/notifications/{n.id}/read", headers=auth_headers(me))
    assert res.status_code == 404
    assert_error(res, ErrorCode.NOT_FOUND)
    assert await _is_read(session_factory, n.id) is False


async def test_read_missing_404(client, db):
    me = await make_resident(db)
    res = await client.post("/api/v1/notifications/999999/read", headers=auth_headers(me))
    assert res.status_code == 404
    assert_error(res, ErrorCode.NOT_FOUND)


async def test_read_requires_login(client, db):
    me = await make_resident(db)
    n = await _notify(db, me)
    res = await client.post(f"/api/v1/notifications/{n.id}/read")
    assert res.status_code == 401
    assert_error(res, ErrorCode.UNAUTHORIZED)


async def test_read_all_only_mine(client, db, session_factory):
    me = await make_resident(db, "me@example.com")
    other = await make_resident(db, "other@example.com")
    mine = [await _notify(db, me) for _ in range(3)]
    theirs = await _notify(db, other)

    res = await client.post("/api/v1/notifications/read-all", headers=auth_headers(me))
    assert res.status_code == 204

    async with session_factory() as s:
        rows = (await s.execute(select(Notification).order_by(Notification.id))).scalars().all()
    read = {r.id: r.is_read for r in rows}
    assert all(read[n.id] for n in mine)
    assert read[theirs.id] is False


async def test_read_all_requires_login(client):
    res = await client.post("/api/v1/notifications/read-all")
    assert res.status_code == 401
    assert_error(res, ErrorCode.UNAUTHORIZED)


async def test_list_created_at_is_kst(client, db):
    me = await make_resident(db)
    await _notify(db, me)
    res = await client.get("/api/v1/notifications", headers=auth_headers(me))
    assert res.json()["items"][0]["created_at"].endswith("+09:00")
