import pytest

from app.core.error_codes import ErrorCode
from tests.helpers import assert_error

pytestmark = pytest.mark.anyio

URL = "/api/v1/alleys"


async def test_create_and_get_alley(client):
    res = await client.post(URL, json={"name": "광운로19가길"})
    assert res.status_code == 201
    body = res.json()
    assert body == {"id": body["id"], "name": "광운로19가길", "description": None}

    res = await client.get(f"{URL}/{body['id']}")
    assert res.status_code == 200
    assert res.json() == body

    res = await client.get(URL)
    assert [a["id"] for a in res.json()] == [body["id"]]


async def test_get_alley_not_found(client):
    res = await client.get(f"{URL}/999")
    assert res.status_code == 404
    assert_error(res, ErrorCode.NOT_FOUND, "Alley not found")
