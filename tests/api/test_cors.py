"""#36 CORS: FE 개발 서버 출처만 허용한다."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio

FE_ORIGIN = "http://localhost:5173"


async def test_preflight_allows_fe_origin(client: AsyncClient):
    res = await client.options(
        "/api/v1/users/me",
        headers={
            "Origin": FE_ORIGIN,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == FE_ORIGIN
    assert "PATCH" in res.headers["access-control-allow-methods"]
    assert "authorization" in res.headers["access-control-allow-headers"].lower()


async def test_response_has_allow_origin_for_fe(client: AsyncClient):
    res = await client.get("/health", headers={"Origin": FE_ORIGIN})
    assert res.headers["access-control-allow-origin"] == FE_ORIGIN


async def test_unknown_origin_not_allowed(client: AsyncClient):
    res = await client.options(
        "/api/v1/users/me",
        headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "GET"},
    )
    assert res.status_code == 400
    assert "access-control-allow-origin" not in res.headers
