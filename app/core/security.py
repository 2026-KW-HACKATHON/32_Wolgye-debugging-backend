"""비밀번호 해시와 JWT (결정 8).

- 비밀번호: argon2 (`pwdlib`)
- JWT: HS256, 키는 설정의 `SECRET_KEY`. payload = `sub`(resident id 문자열), `type`(access/refresh), `exp`
- access 30분, refresh 14일 (설정값). refresh 토큰은 DB 에 저장하지 않는다.

HTTP 와 무관하다. 토큰이 올바르지 않으면 `decode_token` 이 None 을 돌려주고, 401 변환은 호출한 쪽이 한다.
"""

import enum
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.core.config import get_settings

ALGORITHM = "HS256"

_password_hash = PasswordHash.recommended()
# 없는 이메일로 로그인할 때도 해시 검증 시간을 들여 가입 여부가 응답 시간으로 드러나지 않게 한다
_DUMMY_HASH = _password_hash.hash("dummy-password")


class TokenType(enum.StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """password_hash 가 None 이면 더미 해시로 검증해 시간만 쓰고 False."""
    try:
        ok = _password_hash.verify(password, password_hash or _DUMMY_HASH)
    except UnknownHashError:
        return False
    return ok and password_hash is not None


def create_token(resident_id: int, token_type: TokenType) -> str:
    settings = get_settings()
    if token_type is TokenType.ACCESS:
        lifetime = timedelta(minutes=settings.access_token_expire_minutes)
    else:
        lifetime = timedelta(days=settings.refresh_token_expire_days)
    payload = {"sub": str(resident_id), "type": token_type.value, "exp": datetime.now(UTC) + lifetime}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_access_token(resident_id: int) -> str:
    return create_token(resident_id, TokenType.ACCESS)


def create_refresh_token(resident_id: int) -> str:
    return create_token(resident_id, TokenType.REFRESH)


def decode_token(token: str, expected_type: TokenType) -> int | None:
    """서명·만료·type 이 맞으면 resident id, 아니면 None."""
    try:
        payload = jwt.decode(
            token, get_settings().secret_key, algorithms=[ALGORITHM], options={"require": ["sub", "type", "exp"]}
        )
    except jwt.PyJWTError:
        return None
    sub = payload["sub"]
    if payload["type"] != expected_type.value or not isinstance(sub, str) or not sub.isdigit():
        return None
    return int(sub)
