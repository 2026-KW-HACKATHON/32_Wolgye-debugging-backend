import pytest

from app.models.share_request import ShareRequestStatus
from tests.factories import make_building, make_resident, make_share_request, make_slot, make_zone

pytestmark = pytest.mark.anyio

URL = "/api/v1/share-requests"


@pytest.fixture
async def slot(db):
    return await make_slot(db, await make_zone(db, await make_building(db)), is_shareable=True)


@pytest.fixture
async def requester(db):
    return await make_resident(db)


async def test_create_share_request(client, slot, requester):
    payload = {
        "slot_id": slot.id,
        "requester_id": requester.id,
        "request_date": "2026-10-02",
        "start_time": "10:00:00",
        "end_time": "12:00:00",
    }
    res = await client.post(URL, json=payload)
    assert res.status_code == 201
    body = res.json()
    assert {k: body[k] for k in payload} == payload
    assert body["vehicle_id"] is None
    assert body["status"] == "pending"
    assert body["reject_reason"] is None
    assert body["responded_at"] is None
    assert body["created_at"]


async def test_list_share_requests_filtered_by_status(client, db, slot, requester):
    await make_share_request(db, slot, requester)
    await make_share_request(db, slot, requester, status=ShareRequestStatus.REJECTED)

    res = await client.get(URL)
    assert res.status_code == 200
    assert len(res.json()) == 2

    res = await client.get(URL, params={"status": "pending"})
    assert res.status_code == 200
    assert [r["status"] for r in res.json()] == ["pending"]


async def test_accept_share_request(client, db, slot, requester):
    req = await make_share_request(db, slot, requester)

    res = await client.post(f"{URL}/{req.id}/decision", json={"status": "accepted"})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "accepted"
    assert body["reject_reason"] is None
    assert body["responded_at"] is not None


async def test_reject_share_request_with_reason(client, db, slot, requester):
    req = await make_share_request(db, slot, requester)

    res = await client.post(f"{URL}/{req.id}/decision", json={"status": "rejected", "reject_reason": "공사 중"})
    assert res.status_code == 200
    assert res.json()["status"] == "rejected"
    assert res.json()["reject_reason"] == "공사 중"


async def test_decide_share_request_not_found(client):
    res = await client.post(f"{URL}/999/decision", json={"status": "accepted"})
    assert res.status_code == 404
    assert res.json() == {"detail": "Share request not found"}


async def test_decide_share_request_already_decided(client, db, slot, requester):
    req = await make_share_request(db, slot, requester, status=ShareRequestStatus.ACCEPTED)

    res = await client.post(f"{URL}/{req.id}/decision", json={"status": "rejected"})
    assert res.status_code == 409
    assert res.json() == {"detail": "Already decided"}
