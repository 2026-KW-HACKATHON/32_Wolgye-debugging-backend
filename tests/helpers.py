"""API 테스트 공용 검사 함수."""

from httpx import Response

from app.core.error_codes import ErrorCode
from app.core.security import create_access_token


def assert_error(res: Response, code: ErrorCode | str, message: str | None = None) -> dict:
    """에러 응답이 {"error": {"code", "message", "detail"}} 형식이고 code(·message)가 맞는지. error 본문을 돌려준다."""
    body = res.json()
    assert set(body) == {"error"}, body
    error = body["error"]
    assert set(error) == {"code", "message", "detail"}, error
    assert error["code"] == code
    if message is not None:
        assert error["message"] == message
    return error


def auth_headers(resident) -> dict[str, str]:
    """로그인한 resident 의 인증 헤더. API 테스트는 인증 헤더를 **항상 이 함수로** 만든다.

    resident id 로 access 토큰(JWT, 30분)을 바로 만들어 `Authorization: Bearer <access_token>` 을 돌려준다 (#6).
    로그인 API 를 거치지 않으므로 password_hash 가 없는 factories 의 resident 에도 쓸 수 있다.
    """
    return {"Authorization": f"Bearer {create_access_token(resident.id)}"}
