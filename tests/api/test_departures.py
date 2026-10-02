import pytest

from app.core.error_codes import ErrorCode
from tests.factories import make_vehicle
from tests.helpers import assert_error

pytestmark = pytest.mark.anyio

URL = "/api/v1/departures"


async def test_create_and_get_departure(client, db):
    vehicle = await make_vehicle(db)
    payload = {
        "vehicle_id": vehicle.id,
        "scheduled_date": "2026-10-02",
        "scheduled_time": "08:30:00",
        "repeat_weekdays": [0, 2],
        "memo": "출근",
    }
    res = await client.post(URL, json=payload)
    assert res.status_code == 201
    body = res.json()
    assert body == {**payload, "id": body["id"], "is_ai_estimated": False}

    res = await client.get(f"{URL}/{body['id']}")
    assert res.status_code == 200
    assert res.json() == body


async def test_list_departures_filtered_by_vehicle(client, db):
    car_a = await make_vehicle(db, plate_no="11가1111")
    car_b = await make_vehicle(db, plate_no="22나2222")
    for car in (car_a, car_a, car_b):
        await client.post(URL, json={"vehicle_id": car.id, "scheduled_date": "2026-10-02", "scheduled_time": "08:00"})

    res = await client.get(URL)
    assert res.status_code == 200
    assert len(res.json()) == 3

    res = await client.get(URL, params={"vehicle_id": car_a.id})
    assert res.status_code == 200
    assert [d["vehicle_id"] for d in res.json()] == [car_a.id, car_a.id]


async def test_get_departure_not_found(client):
    res = await client.get(f"{URL}/999")
    assert res.status_code == 404
    assert_error(res, ErrorCode.NOT_FOUND, "Departure schedule not found")
