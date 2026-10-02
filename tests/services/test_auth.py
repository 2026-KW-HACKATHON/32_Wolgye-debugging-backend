from datetime import timedelta

import jwt
import pytest
from sqlalchemy import select

from app.core import security
from app.core.config import get_settings
from app.core.error_codes import ErrorCode
from app.core.security import TokenType, create_access_token, create_refresh_token, decode_token
from app.models.resident import Resident
from app.models.token_transfer import TokenTransfer
from app.schemas.auth import LoginRequest, SignupRequest
from app.services import auth
from app.services.exceptions import ConflictError, InvalidInputError, UnauthorizedError
from tests.factories import make_resident

pytestmark = pytest.mark.anyio


def _signup(email: str = "kim@kw.ac.kr", agree_terms: bool = True) -> SignupRequest:
    return SignupRequest(email=email, password="secret-pw", nickname="지수", agree_terms=agree_terms)


# ── 비밀번호·JWT ──
def test_password_hash_roundtrip():
    hashed = security.hash_password("secret-pw")
    assert hashed != "secret-pw"
    assert security.verify_password("secret-pw", hashed)
    assert not security.verify_password("wrong", hashed)
    assert not security.verify_password("secret-pw", None)
    assert not security.verify_password("x", "x")  # 알 수 없는 해시 형식


def test_token_type_is_checked():
    assert decode_token(create_access_token(7), TokenType.ACCESS) == 7
    assert decode_token(create_refresh_token(7), TokenType.REFRESH) == 7
    assert decode_token(create_access_token(7), TokenType.REFRESH) is None
    assert decode_token(create_refresh_token(7), TokenType.ACCESS) is None
    assert decode_token("garbage", TokenType.ACCESS) is None


def test_token_lifetimes():
    settings = get_settings()
    access = jwt.decode(create_access_token(1), settings.secret_key, algorithms=[security.ALGORITHM])
    refresh = jwt.decode(create_refresh_token(1), settings.secret_key, algorithms=[security.ALGORITHM])
    assert set(access) == {"sub", "type", "exp"}
    assert access["sub"] == "1"
    assert refresh["exp"] - access["exp"] == pytest.approx(
        (timedelta(days=14) - timedelta(minutes=30)).total_seconds(), abs=5
    )


# ── 가입 ──
async def test_signup_grants_tokens(db, session_factory):
    result = await auth.signup(db, _signup())

    async with session_factory() as other:
        user = await other.scalar(select(Resident).where(Resident.email == "kim@kw.ac.kr"))
        grants = (await other.scalars(select(TokenTransfer).where(TokenTransfer.receiver_id == user.id))).all()
    assert user.token_balance == get_settings().signup_token_grant == 500_000
    assert [(g.sender_id, g.amount) for g in grants] == [(None, 500_000)]
    assert user.password_hash != "secret-pw"
    assert result.user.id == user.id
    assert result.user.onboarding_step == "JOIN_BUILDING"
    assert decode_token(result.access_token, TokenType.ACCESS) == user.id
    assert decode_token(result.refresh_token, TokenType.REFRESH) == user.id


async def test_signup_requires_agree_terms(db):
    with pytest.raises(InvalidInputError) as exc:
        await auth.signup(db, _signup(agree_terms=False))
    assert exc.value.detail["field"] == "agree_terms"
    assert await db.scalar(select(Resident.id)) is None


async def test_signup_duplicate_email_ignores_case(db):
    await auth.signup(db, _signup("kim@kw.ac.kr"))
    with pytest.raises(ConflictError) as exc:
        await auth.signup(db, _signup("KIM@kw.ac.kr"))
    assert exc.value.code == ErrorCode.EMAIL_EXISTS


# ── 로그인 ──
async def test_login(db):
    signed = await auth.signup(db, _signup())
    result = await auth.login(db, LoginRequest(email="Kim@KW.ac.kr", password="secret-pw"))
    assert result.user.id == signed.user.id


@pytest.mark.parametrize(("email", "password"), [("kim@kw.ac.kr", "wrong"), ("nobody@kw.ac.kr", "secret-pw")])
async def test_login_invalid_credentials(db, email, password):
    await auth.signup(db, _signup())
    with pytest.raises(UnauthorizedError) as exc:
        await auth.login(db, LoginRequest(email=email, password=password))
    assert exc.value.code == ErrorCode.INVALID_CREDENTIALS


# ── 재발급·인증 ──
async def test_refresh(db):
    user = await make_resident(db)
    pair = await auth.refresh(db, create_refresh_token(user.id))
    assert decode_token(pair.access_token, TokenType.ACCESS) == user.id
    assert decode_token(pair.refresh_token, TokenType.REFRESH) == user.id


@pytest.mark.parametrize("kind", ["access", "garbage", "no-user"])
async def test_refresh_rejects(db, kind):
    user = await make_resident(db)
    token = {"access": create_access_token(user.id), "garbage": "x.y.z", "no-user": create_refresh_token(999)}[kind]
    with pytest.raises(UnauthorizedError) as exc:
        await auth.refresh(db, token)
    assert exc.value.code == ErrorCode.UNAUTHORIZED


async def test_authenticate(db):
    user = await make_resident(db)
    assert (await auth.authenticate(db, create_access_token(user.id))).id == user.id
    for token in (None, create_refresh_token(user.id)):
        with pytest.raises(UnauthorizedError):
            await auth.authenticate(db, token)
