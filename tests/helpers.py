"""API 테스트 공용 검사 함수."""

import io

from httpx import Response
from PIL import Image

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


def jpeg(size: tuple[int, int] = (64, 48), exif: bool = False, fmt: str = "JPEG") -> bytes:
    """테스트용 사진 바이트 (미등록 차량 제보 #52). exif=True 면 제조사·GPS 메타데이터를 넣는다."""
    image = Image.new("RGB", size, "red")
    out = io.BytesIO()
    if exif:
        data = Image.Exif()
        data[0x010F] = "PhoneMaker"  # Make
        data[0x8825] = {2: (37.0, 37.0, 0.0)}  # GPSInfo
        image.save(out, format=fmt, exif=data.tobytes())
    else:
        image.save(out, format=fmt)
    return out.getvalue()
