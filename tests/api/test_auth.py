"""#6 인증·내 정보·빌라 합류 API."""

import pytest

from app.core.error_codes import ErrorCode
from app.core.security import create_access_token, create_refresh_token
from app.models.resident import ResidentRole
from tests.factories import make_building, make_resident, make_vehicle
from tests.helpers import assert_error, auth_headers

pytestmark = pytest.mark.anyio

API = "/api/v1"
SIGNUP = {"email": "kim@kw.ac.kr", "password": "secret-pw", "nickname": "지수", "agree_terms": True}


async def _signup(client, **overrides):
    return await client.post(f"{API}/auth/signup", json={**SIGNUP, **overrides})


# ── POST /auth/signup ──
async def test_signup(client):
    res = await _signup(client)
    assert res.status_code == 201
    body = res.json()
    assert set(body) == {"access_token", "refresh_token", "user"}
    assert body["user"]["nickname"] == "지수"
    assert body["user"]["onboarding_step"] == "JOIN_BUILDING"

    me = await client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["token_balance"] == 500_000


async def test_signup_without_agree_terms(client):
    res = await _signup(client, agree_terms=False)
    assert res.status_code == 400
    assert assert_error(res, ErrorCode.INVALID_INPUT)["detail"]["field"] == "agree_terms"


@pytest.mark.parametrize("field", ["email", "password", "nickname", "agree_terms"])
async def test_signup_missing_field(client, field):
    body = {k: v for k, v in SIGNUP.items() if k != field}
    res = await client.post(f"{API}/auth/signup", json=body)
    assert res.status_code == 400
    assert assert_error(res, ErrorCode.INVALID_INPUT)["detail"]["field"] == field


@pytest.mark.parametrize("password", ["1234567", "x" * 129])
async def test_signup_password_length(client, password):
    res = await _signup(client, password=password)
    assert res.status_code == 400
    assert assert_error(res, ErrorCode.INVALID_INPUT)["detail"]["field"] == "password"


@pytest.mark.parametrize("password", ["12345678", "x" * 128])
async def test_signup_password_length_ok(client, password):
    assert (await _signup(client, password=password)).status_code == 201


@pytest.mark.parametrize("nickname", ["", "x" * 51])
async def test_signup_nickname_length(client, nickname):
    res = await _signup(client, nickname=nickname)
    assert res.status_code == 400
    assert assert_error(res, ErrorCode.INVALID_INPUT)["detail"]["field"] == "nickname"


async def test_signup_invalid_email(client):
    res = await _signup(client, email="not-an-email")
    assert res.status_code == 400
    assert_error(res, ErrorCode.INVALID_INPUT)


async def test_signup_duplicate_email(client):
    await _signup(client)
    res = await _signup(client)
    assert res.status_code == 409
    assert_error(res, ErrorCode.EMAIL_EXISTS, "이미 가입된 이메일입니다.")


# ── POST /auth/login ──
async def test_login(client):
    user_id = (await _signup(client)).json()["user"]["id"]
    res = await client.post(f"{API}/auth/login", json={"email": "kim@kw.ac.kr", "password": "secret-pw"})
    assert res.status_code == 200
    body = res.json()
    assert body["user"] == {"id": user_id, "nickname": "지수", "onboarding_step": "JOIN_BUILDING"}
    assert body["access_token"] and body["refresh_token"]


@pytest.mark.parametrize(("email", "password"), [("kim@kw.ac.kr", "wrong"), ("nobody@kw.ac.kr", "secret-pw")])
async def test_login_invalid_credentials(client, email, password):
    await _signup(client)
    res = await client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert res.status_code == 401
    assert_error(res, ErrorCode.INVALID_CREDENTIALS, "이메일 또는 비밀번호가 올바르지 않습니다.")


# ── POST /auth/refresh ──
async def test_refresh(client):
    tokens = (await _signup(client)).json()
    res = await client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"access_token", "refresh_token"}
    me = await client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200


@pytest.mark.parametrize("kind", ["access", "garbage", "no-user"])
async def test_refresh_unauthorized(client, db, kind):
    user = await make_resident(db)
    token = {"access": create_access_token(user.id), "garbage": "x.y.z", "no-user": create_refresh_token(999)}[kind]
    res = await client.post(f"{API}/auth/refresh", json={"refresh_token": token})
    assert res.status_code == 401
    assert_error(res, ErrorCode.UNAUTHORIZED)


# ── POST /auth/password-reset ──
@pytest.mark.parametrize("email", ["kim@kw.ac.kr", "nobody@kw.ac.kr"])
async def test_password_reset_always_202(client, email):
    await _signup(client)
    res = await client.post(f"{API}/auth/password-reset", json={"email": email})
    assert res.status_code == 202
    assert res.content == b""


# ── GET /users/me ──
async def test_me_before_join(client, db):
    user = await make_resident(db, token_balance=500_000)
    res = await client.get(f"{API}/users/me", headers=auth_headers(user))
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == user.id
    assert body["email"] == user.email
    assert body["onboarding_step"] == "JOIN_BUILDING"
    assert body["building"] is None
    assert body["phone"] is None
    assert body["temperature"] == 36.5
    assert body["token_balance"] == 500_000


async def test_me_with_building_and_vehicle(client, db):
    building = await make_building(db)
    user = await make_resident(db, building=building, role=ResidentRole.MANAGER)
    await make_vehicle(db, owner=user)
    body = (await client.get(f"{API}/users/me", headers=auth_headers(user))).json()
    assert body["onboarding_step"] == "DONE"
    assert body["building"]["building_id"] == building.id
    assert body["building"]["name"] == building.name
    assert body["building"]["alley"]["name"] == "광운로19가길"
    assert body["building"]["role"] == "ADMIN"
    assert body["building"]["unit"] is None


async def test_me_requires_login(client):
    res = await client.get(f"{API}/users/me")
    assert res.status_code == 401
    assert_error(res, ErrorCode.UNAUTHORIZED)


# ── PATCH /users/me ──
async def test_update_me(client, db):
    building = await make_building(db)
    user = await make_resident(db, building=building)
    res = await client.patch(
        f"{API}/users/me",
        headers=auth_headers(user),
        json={"name": "김지수", "unit": "101동 202호", "phone": "010-1234-5678"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "김지수"
    assert body["phone"] == "010-****-5678"
    assert body["building"]["unit"] == "101동 202호"

    # 보내지 않은 필드는 그대로
    res = await client.patch(f"{API}/users/me", headers=auth_headers(user), json={"name": "지수"})
    assert res.json()["building"]["unit"] == "101동 202호"
    assert res.json()["phone"] == "010-****-5678"


async def test_update_me_too_long(client, db):
    user = await make_resident(db)
    res = await client.patch(f"{API}/users/me", headers=auth_headers(user), json={"unit": "x" * 21})
    assert res.status_code == 400
    assert assert_error(res, ErrorCode.INVALID_INPUT)["detail"]["field"] == "unit"


async def test_update_me_requires_login(client):
    res = await client.patch(f"{API}/users/me", json={"name": "지수"})
    assert res.status_code == 401
    assert_error(res, ErrorCode.UNAUTHORIZED)


# ── POST /buildings/join ──
async def test_join_building(client, db):
    building = await make_building(db, invite_code="HANBIT01")
    user = await make_resident(db)
    res = await client.post(f"{API}/buildings/join", headers=auth_headers(user), json={"invite_code": "HANBIT01"})
    assert res.status_code == 200
    body = res.json()
    assert body["building_id"] == building.id
    assert body["name"] == building.name
    assert body["address"] == building.address
    assert body["alley"] == {"id": building.alley_id, "name": "광운로19가길"}
    assert body["role"] == "RESIDENT"
    assert body["onboarding_step"] == "REGISTER_VEHICLE"

    me = (await client.get(f"{API}/users/me", headers=auth_headers(user))).json()
    assert me["building"]["building_id"] == building.id


async def test_join_building_code_ignores_case_and_spaces(client, db):
    building = await make_building(db, invite_code="HANBIT01")
    user = await make_resident(db)
    res = await client.post(f"{API}/buildings/join", headers=auth_headers(user), json={"invite_code": " hanbit01 "})
    assert res.status_code == 200
    assert res.json()["building_id"] == building.id


async def test_join_building_invalid_code(client, db):
    await make_building(db, invite_code="HANBIT01")
    user = await make_resident(db)
    res = await client.post(f"{API}/buildings/join", headers=auth_headers(user), json={"invite_code": "WRONG"})
    assert res.status_code == 404
    assert_error(res, ErrorCode.INVALID_INVITE_CODE, "초대코드가 올바르지 않습니다.")


@pytest.mark.parametrize("same_building", [True, False])
async def test_join_building_already_in_building(client, db, same_building):
    mine = await make_building(db, invite_code="MINE01")
    other = mine if same_building else await make_building(db, invite_code="OTHER1", name="다른빌라")
    user = await make_resident(db, building=mine)
    res = await client.post(
        f"{API}/buildings/join", headers=auth_headers(user), json={"invite_code": other.invite_code}
    )
    assert res.status_code == 409
    assert assert_error(res, ErrorCode.ALREADY_IN_BUILDING)["detail"] == {"building_id": mine.id}


async def test_join_building_requires_login(client):
    res = await client.post(f"{API}/buildings/join", json={"invite_code": "HANBIT01"})
    assert res.status_code == 401
    assert_error(res, ErrorCode.UNAUTHORIZED)
