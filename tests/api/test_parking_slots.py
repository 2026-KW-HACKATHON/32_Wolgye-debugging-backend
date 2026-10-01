import pytest

from tests.factories import make_building, make_garage

pytestmark = pytest.mark.anyio

URL = "/api/v1/parking-slots"


async def test_create_and_get_parking_slot(client, db):
    garage = await make_garage(db, await make_building(db))
    res = await client.post(URL, json={"garage_id": garage.id, "number": 1})
    assert res.status_code == 201
    body = res.json()
    assert body["garage_id"] == garage.id
    assert body["number"] == 1
    assert body["is_active"] is True  # server_default

    res = await client.get(f"{URL}/{body['id']}")
    assert res.status_code == 200
    assert res.json() == body


async def test_list_parking_slots_filtered_by_building(client, db):
    garage_a = await make_garage(db, await make_building(db, invite_code="A"))
    garage_b = await make_garage(db, await make_building(db, invite_code="B"))
    await client.post(URL, json={"garage_id": garage_a.id, "number": 1})
    await client.post(URL, json={"garage_id": garage_a.id, "number": 2})
    await client.post(URL, json={"garage_id": garage_b.id, "number": 1})

    res = await client.get(URL)
    assert res.status_code == 200
    assert len(res.json()) == 3

    res = await client.get(URL, params={"building_id": garage_a.building_id})
    assert res.status_code == 200
    assert sorted(s["number"] for s in res.json()) == [1, 2]
    assert {s["garage_id"] for s in res.json()} == {garage_a.id}


async def test_get_parking_slot_not_found(client):
    res = await client.get(f"{URL}/999")
    assert res.status_code == 404
    assert res.json() == {"detail": "Parking slot not found"}
