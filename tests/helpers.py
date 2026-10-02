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
