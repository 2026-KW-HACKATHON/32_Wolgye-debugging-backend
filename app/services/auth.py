"""가입·로그인·토큰 재발급 (#6, 결정 3·4·6·8)."""

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.error_codes import ErrorCode
from app.core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.resident import Resident
from app.schemas.auth import AuthTokens, AuthUser, LoginRequest, SignupRequest, TokenPair
from app.services import tokens
from app.services.exceptions import ConflictError, InvalidInputError, UnauthorizedError
from app.services.users import onboarding_step

SIGNUP_GRANT_MEMO = "가입 지급"
INVALID_CREDENTIALS_MESSAGE = "이메일 또는 비밀번호가 올바르지 않습니다."


def _normalize_email(email: str) -> str:
    """이메일은 대소문자를 구분하지 않는다 (소문자로 저장·비교)."""
    return email.strip().lower()


def _token_pair(resident_id: int) -> TokenPair:
    return TokenPair(access_token=create_access_token(resident_id), refresh_token=create_refresh_token(resident_id))


async def _auth_tokens(db: AsyncSession, resident: Resident) -> AuthTokens:
    pair = _token_pair(resident.id)
    user = AuthUser(id=resident.id, nickname=resident.nickname, onboarding_step=await onboarding_step(db, resident))
    return AuthTokens(access_token=pair.access_token, refresh_token=pair.refresh_token, user=user)


async def signup(db: AsyncSession, payload: SignupRequest) -> AuthTokens:
    """가입하고 같은 트랜잭션에서 SIGNUP_TOKEN_GRANT 토큰을 시스템 지급한다."""
    if not payload.agree_terms:
        raise InvalidInputError(detail={"field": "agree_terms", "reason": "이용약관에 동의해야 합니다."})
    email = _normalize_email(payload.email)
    if await db.scalar(select(exists().where(Resident.email == email))):
        raise ConflictError("이미 가입된 이메일입니다.", code=ErrorCode.EMAIL_EXISTS)

    resident = Resident(email=email, password_hash=hash_password(payload.password), nickname=payload.nickname)
    db.add(resident)
    await db.flush()  # id 확보 (동시 가입으로 이메일이 겹치면 IntegrityError → 409 EMAIL_EXISTS)
    await tokens.transfer(
        db, sender_id=None, receiver_id=resident.id, amount=get_settings().signup_token_grant, memo=SIGNUP_GRANT_MEMO
    )
    await db.commit()
    await db.refresh(resident)
    return await _auth_tokens(db, resident)


async def login(db: AsyncSession, payload: LoginRequest) -> AuthTokens:
    resident = await db.scalar(select(Resident).where(Resident.email == _normalize_email(payload.email)))
    # 없는 이메일도 해시 검증을 거친다 (응답 시간으로 가입 여부가 드러나지 않게)
    password_ok = verify_password(payload.password, resident.password_hash if resident else None)
    if resident is None or not password_ok:
        raise UnauthorizedError(INVALID_CREDENTIALS_MESSAGE, code=ErrorCode.INVALID_CREDENTIALS)
    return await _auth_tokens(db, resident)


async def refresh(db: AsyncSession, refresh_token: str) -> TokenPair:
    """refresh 토큰으로 새 access + 새 refresh. 만료·위조·access 토큰·없는 사용자는 401 UNAUTHORIZED."""
    resident_id = decode_token(refresh_token, TokenType.REFRESH)
    if resident_id is None or await db.get(Resident, resident_id) is None:
        raise UnauthorizedError()
    return _token_pair(resident_id)


async def authenticate(db: AsyncSession, access_token: str | None) -> Resident:
    """access 토큰의 사용자. 없음·만료·위조·refresh 토큰·없는 사용자는 401 UNAUTHORIZED."""
    resident_id = decode_token(access_token, TokenType.ACCESS) if access_token else None
    user = await db.get(Resident, resident_id) if resident_id is not None else None
    if user is None:
        raise UnauthorizedError()
    return user
