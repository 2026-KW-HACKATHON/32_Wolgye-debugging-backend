"""#4 공통 기반: 에러 응답 형식, 임시 인증(X-User-Id), 빌라 입주민·관리인 의존성, 페이지네이션 쿼리.

엔드포인트가 아직 없으므로 테스트 전용 앱에 공용 핸들러·의존성을 붙여 확인한다.
"""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import (
    BuildingAdmin,
    BuildingMember,
    CurrentUser,
    CursorParam,
    DbSession,
    LimitParam,
    get_db,
)
from app.api.errors import register_exception_handlers
from app.core.error_codes import ErrorCode
from app.models.alley import Alley
from app.models.resident import ResidentRole
from app.schemas.common import Page
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError, UnauthorizedError
from app.services.pagination import DEFAULT_LIMIT, paginate
from tests.factories import make_alley, make_building, make_resident
from tests.helpers import assert_error

pytestmark = pytest.mark.anyio


class _AlleyItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class _Body(BaseModel):
    name: str
    count: int


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/raise/not-found")
    async def raise_not_found():
        raise NotFoundError()

    @app.get("/raise/conflict")
    async def raise_conflict():
        raise ConflictError("토큰이 부족합니다.", code=ErrorCode.INSUFFICIENT_TOKENS, detail={"required": 6})

    @app.get("/raise/forbidden")
    async def raise_forbidden():
        raise ForbiddenError()

    @app.get("/raise/unauthorized")
    async def raise_unauthorized():
        raise UnauthorizedError("이메일 또는 비밀번호가 올바르지 않습니다.", code=ErrorCode.INVALID_CREDENTIALS)

    @app.post("/validate")
    async def validate(body: _Body):
        return body

    @app.get("/me")
    async def me(user: CurrentUser):
        return {"id": user.id}

    @app.get("/buildings/{building_id}/member")
    async def member(building_id: int, user: BuildingMember):
        return {"id": user.id}

    @app.get("/buildings/{building_id}/admin")
    async def admin(building_id: int, user: BuildingAdmin):
        return {"id": user.id}

    @app.get("/page")
    async def page(cursor: CursorParam = None, limit: LimitParam = DEFAULT_LIMIT):
        return {"cursor": cursor, "limit": limit}

    @app.get("/alleys", response_model=Page[_AlleyItem])
    async def alleys(db: DbSession, cursor: CursorParam = None, limit: LimitParam = DEFAULT_LIMIT):
        return await paginate(db, select(Alley), Alley.id, cursor, limit)

    return app


@pytest.fixture
async def test_client(session_factory) -> AsyncIterator[AsyncClient]:
    app = _build_app()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── 에러 응답 형식 ──
@pytest.mark.parametrize(
    ("path", "status", "code", "message"),
    [
        ("/raise/not-found", 404, ErrorCode.NOT_FOUND, "대상을 찾을 수 없습니다."),
        ("/raise/forbidden", 403, ErrorCode.NOT_BUILDING_MEMBER, "이 빌라의 입주민만 이용할 수 있습니다."),
        ("/raise/unauthorized", 401, ErrorCode.INVALID_CREDENTIALS, "이메일 또는 비밀번호가 올바르지 않습니다."),
        ("/raise/conflict", 409, ErrorCode.INSUFFICIENT_TOKENS, "토큰이 부족합니다."),
    ],
)
async def test_domain_error_format(test_client, path, status, code, message):
    res = await test_client.get(path)
    assert res.status_code == status
    assert_error(res, code, message)


async def test_domain_error_detail(test_client):
    error = assert_error(await test_client.get("/raise/conflict"), ErrorCode.INSUFFICIENT_TOKENS)
    assert error["detail"] == {"required": 6}
    assert assert_error(await test_client.get("/raise/not-found"), ErrorCode.NOT_FOUND)["detail"] is None


async def test_validation_error_is_400_invalid_input(test_client):
    res = await test_client.post("/validate", json={"name": "a", "count": "many"})
    assert res.status_code == 400
    error = assert_error(res, ErrorCode.INVALID_INPUT)
    assert error["detail"]["field"] == "count"
    assert error["detail"]["reason"]
    assert [e["field"] for e in error["detail"]["errors"]] == ["count"]


async def test_validation_error_missing_body(test_client):
    res = await test_client.post("/validate", json={})
    assert res.status_code == 400
    error = assert_error(res, ErrorCode.INVALID_INPUT)
    assert {e["field"] for e in error["detail"]["errors"]} == {"name", "count"}


async def test_unknown_route_uses_error_format(client):
    res = await client.get("/api/v1/does-not-exist")
    assert res.status_code == 404
    assert_error(res, ErrorCode.NOT_FOUND)


# ── CurrentUser (임시: X-User-Id) ──
@pytest.mark.parametrize("headers", [{}, {"X-User-Id": "abc"}, {"X-User-Id": "999"}])
async def test_current_user_unauthorized(test_client, headers):
    res = await test_client.get("/me", headers=headers)
    assert res.status_code == 401
    assert_error(res, ErrorCode.UNAUTHORIZED, "로그인이 필요합니다.")


async def test_current_user_ok(test_client, db):
    user = await make_resident(db)
    res = await test_client.get("/me", headers={"X-User-Id": str(user.id)})
    assert res.status_code == 200
    assert res.json() == {"id": user.id}


# ── 빌라 입주민·관리인 ──
@pytest.fixture
async def building(db):
    return await make_building(db)


async def test_member_ok(test_client, db, building):
    user = await make_resident(db, building=building)
    res = await test_client.get(f"/buildings/{building.id}/member", headers={"X-User-Id": str(user.id)})
    assert res.status_code == 200


async def test_member_requires_login(test_client, building):
    res = await test_client.get(f"/buildings/{building.id}/member")
    assert res.status_code == 401
    assert_error(res, ErrorCode.UNAUTHORIZED)


@pytest.mark.parametrize("other_building", [True, False])
async def test_member_forbidden(test_client, db, building, other_building):
    other = await make_building(db, invite_code="OTHER1", alley=None) if other_building else None
    user = await make_resident(db, building=other)
    res = await test_client.get(f"/buildings/{building.id}/member", headers={"X-User-Id": str(user.id)})
    assert res.status_code == 403
    assert_error(res, ErrorCode.NOT_BUILDING_MEMBER)


async def test_admin_ok_and_admin_is_member(test_client, db, building):
    manager = await make_resident(db, building=building, role=ResidentRole.MANAGER)
    headers = {"X-User-Id": str(manager.id)}
    assert (await test_client.get(f"/buildings/{building.id}/admin", headers=headers)).status_code == 200
    assert (await test_client.get(f"/buildings/{building.id}/member", headers=headers)).status_code == 200


async def test_admin_forbidden_for_resident(test_client, db, building):
    resident = await make_resident(db, building=building)
    res = await test_client.get(f"/buildings/{building.id}/admin", headers={"X-User-Id": str(resident.id)})
    assert res.status_code == 403
    assert_error(res, ErrorCode.NOT_BUILDING_ADMIN)


async def test_admin_forbidden_for_other_building_manager(test_client, db, building):
    other = await make_building(db, invite_code="OTHER1")
    manager = await make_resident(db, building=other, role=ResidentRole.MANAGER)
    res = await test_client.get(f"/buildings/{building.id}/admin", headers={"X-User-Id": str(manager.id)})
    assert res.status_code == 403
    assert_error(res, ErrorCode.NOT_BUILDING_ADMIN)


# ── 페이지네이션 쿼리 ──
async def test_page_params_default(test_client):
    assert (await test_client.get("/page")).json() == {"cursor": None, "limit": 20}


@pytest.mark.parametrize("limit", [0, 51])
async def test_page_limit_out_of_range(test_client, limit):
    res = await test_client.get("/page", params={"limit": limit})
    assert res.status_code == 400
    assert assert_error(res, ErrorCode.INVALID_INPUT)["detail"]["field"] == "limit"


async def test_paginated_endpoint_response(test_client, db):
    for i in range(3):
        await make_alley(db, f"골목{i}")
    first = (await test_client.get("/alleys", params={"limit": 2})).json()
    assert [a["id"] for a in first["items"]] == [3, 2]
    assert first["next_cursor"] == "2"
    second = (await test_client.get("/alleys", params={"limit": 2, "cursor": first["next_cursor"]})).json()
    assert second == {"items": [{"id": 1, "name": "골목0"}], "next_cursor": None}
