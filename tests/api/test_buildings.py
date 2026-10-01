import pytest

from tests.factories import make_alley

pytestmark = pytest.mark.anyio

URL = "/api/v1/buildings"
PAYLOAD = {"name": "월계빌라", "address": "서울 노원구 월계동 1", "invite_code": "INV001"}


@pytest.fixture
async def alley(db):
    return await make_alley(db)


async def test_create_and_get_building(client, alley):
    res = await client.post(URL, json={**PAYLOAD, "alley_id": alley.id})
    assert res.status_code == 201
    body = res.json()
    assert body == {
        "id": body["id"],
        "alley_id": alley.id,
        "name": "월계빌라",
        "address": "서울 노원구 월계동 1",
        "detail_address": None,
    }

    res = await client.get(f"{URL}/{body['id']}")
    assert res.status_code == 200
    assert res.json() == body


async def test_list_buildings(client, alley):
    await client.post(URL, json={**PAYLOAD, "alley_id": alley.id})
    await client.post(URL, json={**PAYLOAD, "alley_id": alley.id, "name": "옆빌라", "invite_code": "INV002"})

    res = await client.get(URL)
    assert res.status_code == 200
    assert {b["name"] for b in res.json()} == {"월계빌라", "옆빌라"}


async def test_get_building_not_found(client):
    res = await client.get(f"{URL}/999")
    assert res.status_code == 404
    assert res.json() == {"detail": "Building not found"}
