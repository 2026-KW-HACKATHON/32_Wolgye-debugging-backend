import pytest

from app.core.error_codes import ErrorCode
from tests.factories import make_resident
from tests.helpers import assert_error

pytestmark = pytest.mark.anyio

URL = "/api/v1/vehicles"


async def test_create_and_get_vehicle(client, db):
    owner = await make_resident(db)
    res = await client.post(URL, json={"plate_no": "12가3456", "owner_id": owner.id, "is_primary": True})
    assert res.status_code == 201
    body = res.json()
    assert body == {
        "id": body["id"],
        "plate_no": "12가3456",
        "color": None,
        "nickname": None,
        "is_primary": True,
        "owner_id": owner.id,
    }

    res = await client.get(f"{URL}/{body['id']}")
    assert res.status_code == 200
    assert res.json() == body


async def test_create_unconfirmed_vehicle_without_owner(client):
    res = await client.post(URL, json={"plate_no": "99허9999"})
    assert res.status_code == 201
    assert res.json()["owner_id"] is None


async def test_list_vehicles(client):
    await client.post(URL, json={"plate_no": "11가1111"})
    await client.post(URL, json={"plate_no": "22나2222"})

    res = await client.get(URL)
    assert res.status_code == 200
    assert {v["plate_no"] for v in res.json()} == {"11가1111", "22나2222"}


async def test_get_vehicle_not_found(client):
    res = await client.get(f"{URL}/999")
    assert res.status_code == 404
    assert_error(res, ErrorCode.NOT_FOUND, "Vehicle not found")
