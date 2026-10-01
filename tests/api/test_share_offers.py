import pytest

from app.core.db_errors import CONSTRAINT_MESSAGES
from tests.factories import make_building, make_garage, make_resident, make_share_offer, make_slot

pytestmark = pytest.mark.anyio

URL = "/api/v1/share-offers"


@pytest.fixture
async def slot(db):
    return await make_slot(db, await make_garage(db, await make_building(db)))


@pytest.fixture
async def host(db):
    return await make_resident(db, "host@example.com")


async def test_create_and_get_share_offer(client, slot, host):
    payload = {
        "slot_id": slot.id,
        "host_id": host.id,
        "start_date": "2026-10-05",
        "end_date": "2026-10-30",
        "available_weekdays": [0, 2],
        "start_hour": 6,
        "end_hour": 17,
        "hourly_price": 2,
        "max_hours": 8,
    }
    res = await client.post(URL, json=payload)
    assert res.status_code == 201
    body = res.json()
    assert {k: body[k] for k in payload} == payload
    assert body["is_public"] is True
    assert body["memo"] is None

    res = await client.get(f"{URL}/{body['id']}")
    assert res.status_code == 200
    assert res.json() == body


async def test_list_share_offers_public_only(client, db, slot, host):
    public = await make_share_offer(db, slot, host)
    await make_share_offer(db, slot, host, is_public=False)

    res = await client.get(URL, params={"slot_id": slot.id})
    assert len(res.json()) == 2

    res = await client.get(URL, params={"public_only": True})
    assert [o["id"] for o in res.json()] == [public.id]


async def test_share_offer_end_date_before_start_date(client, slot, host):
    payload = {
        "slot_id": slot.id,
        "host_id": host.id,
        "start_date": "2026-10-30",
        "end_date": "2026-10-05",
        "start_hour": 6,
        "end_hour": 17,
    }
    res = await client.post(URL, json=payload)
    assert res.status_code == 409
    assert res.json() == {"detail": CONSTRAINT_MESSAGES["ck_share_offer_dates"]}


async def test_share_offer_hours_reversed(client, slot, host):
    payload = {
        "slot_id": slot.id,
        "host_id": host.id,
        "start_date": "2026-10-05",
        "end_date": "2026-10-30",
        "start_hour": 17,
        "end_hour": 6,
    }
    res = await client.post(URL, json=payload)
    assert res.status_code == 409
    assert res.json() == {"detail": CONSTRAINT_MESSAGES["ck_share_offer_hours"]}


async def test_get_share_offer_not_found(client):
    res = await client.get(f"{URL}/999")
    assert res.status_code == 404
    assert res.json() == {"detail": "Share offer not found"}
