import pytest

from app.models.share_request import ShareRequestStatus
from tests.factories import make_building, make_garage, make_resident, make_share_offer, make_share_request, make_slot

pytestmark = pytest.mark.anyio

URL = "/api/v1/share-requests"


@pytest.fixture
async def slot(db):
    return await make_slot(db, await make_garage(db, await make_building(db)))


@pytest.fixture
async def host(db):
    return await make_resident(db, "host@example.com")


@pytest.fixture
async def offer(db, slot, host):
    # 10월 한 달, 매일 06~22시, 시간당 3 토큰
    return await make_share_offer(db, slot, host, hourly_price=3)


@pytest.fixture
async def requester(db):
    return await make_resident(db, token_balance=100)


async def test_create_share_request(client, offer, requester):
    payload = {
        "offer_id": offer.id,
        "requester_id": requester.id,
        "request_date": "2026-10-02",
        "start_hour": 10,
        "end_hour": 12,
    }
    res = await client.post(URL, json=payload)
    assert res.status_code == 201
    body = res.json()
    assert {k: body[k] for k in payload} == payload
    assert body["slot_id"] == offer.slot_id
    assert body["total_price"] == 6  # 2시간 × 3 토큰
    assert body["vehicle_id"] is None
    assert body["status"] == "pending"
    assert body["reject_reason"] is None
    assert body["responded_at"] is None
    assert body["created_at"]


@pytest.mark.parametrize(
    ("start_hour", "end_hour"),
    [(12, 10), (10, 10), (-1, 3), (23, 25)],
)
async def test_create_share_request_invalid_hours(client, offer, requester, start_hour, end_hour):
    payload = {
        "offer_id": offer.id,
        "requester_id": requester.id,
        "request_date": "2026-10-02",
        "start_hour": start_hour,
        "end_hour": end_hour,
    }
    res = await client.post(URL, json=payload)
    assert res.status_code == 422


async def test_list_share_requests_filtered_by_status(client, db, offer, requester):
    await make_share_request(db, offer, requester)
    await make_share_request(db, offer, requester, status=ShareRequestStatus.REJECTED)

    res = await client.get(URL)
    assert res.status_code == 200
    assert len(res.json()) == 2

    res = await client.get(URL, params={"status": "pending"})
    assert res.status_code == 200
    assert [r["status"] for r in res.json()] == ["pending"]


async def test_accept_share_request(client, db, offer, requester):
    req = await make_share_request(db, offer, requester)

    res = await client.post(f"{URL}/{req.id}/decision", json={"status": "accepted"})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "accepted"
    assert body["reject_reason"] is None
    assert body["responded_at"] is not None


async def test_reject_share_request_with_reason(client, db, offer, requester):
    req = await make_share_request(db, offer, requester)

    res = await client.post(f"{URL}/{req.id}/decision", json={"status": "rejected", "reject_reason": "공사 중"})
    assert res.status_code == 200
    assert res.json()["status"] == "rejected"
    assert res.json()["reject_reason"] == "공사 중"


async def test_decide_share_request_not_found(client):
    res = await client.post(f"{URL}/999/decision", json={"status": "accepted"})
    assert res.status_code == 404
    assert res.json() == {"detail": "Share request not found"}


async def test_decide_share_request_already_decided(client, db, offer, requester):
    req = await make_share_request(db, offer, requester, status=ShareRequestStatus.ACCEPTED)

    res = await client.post(f"{URL}/{req.id}/decision", json={"status": "rejected"})
    assert res.status_code == 409
    assert res.json() == {"detail": "Already decided"}
