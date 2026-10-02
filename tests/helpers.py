"""API 테스트 공용 검사 함수."""

from httpx import Response

from app.core.error_codes import ErrorCode


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

    #6 전까지는 임시 `X-User-Id` 헤더, #6 에서 `Authorization: Bearer <access_token>` 으로 바뀐다.
    이 함수만 바뀌므로 다른 테스트는 고칠 필요가 없다.
    """
    return {"X-User-Id": str(resident.id)}
