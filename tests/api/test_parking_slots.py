import pytest

from tests.factories import make_building, make_zone

pytestmark = pytest.mark.anyio

URL = "/api/v1/parking-slots"


async def test_create_and_get_parking_slot(client, db):
    zone = await make_zone(db, await make_building(db))
    res = await client.post(URL, json={"zone_id": zone.id, "number": 1, "is_shareable": True})
    assert res.status_code == 201
    body = res.json()
    assert body["zone_id"] == zone.id
    assert body["number"] == 1
    assert body["is_shareable"] is True
    assert body["is_active"] is True  # server_default
    assert body["garage_id"] is None

    res = await client.get(f"{URL}/{body['id']}")
    assert res.status_code == 200
    assert res.json() == body


async def test_list_parking_slots_filtered_by_building(client, db):
    zone_a = await make_zone(db, await make_building(db, invite_code="A"))
    zone_b = await make_zone(db, await make_building(db, invite_code="B"))
    await client.post(URL, json={"zone_id": zone_a.id, "number": 1})
    await client.post(URL, json={"zone_id": zone_a.id, "number": 2})
    await client.post(URL, json={"zone_id": zone_b.id, "number": 1})

    res = await client.get(URL)
    assert res.status_code == 200
    assert len(res.json()) == 3

    res = await client.get(URL, params={"building_id": zone_a.building_id})
    assert res.status_code == 200
    assert sorted(s["number"] for s in res.json()) == [1, 2]
    assert {s["zone_id"] for s in res.json()} == {zone_a.id}


async def test_get_parking_slot_not_found(client):
    res = await client.get(f"{URL}/999")
    assert res.status_code == 404
    assert res.json() == {"detail": "Parking slot not found"}
