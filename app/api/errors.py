"""에러 응답 본문 `{"error": {"code", "message", "detail"}}` 과 전역 예외 핸들러.

- DomainError         → exc.status_code, exc.code
- RequestValidationError → 400 INVALID_INPUT, detail = {field, reason, errors}
- IntegrityError      → 409, app/core/db_errors.py 의 제약별 (code, message)
- HTTPException(경로 없음 404, 메서드 405 등) → 같은 상태 코드, 형식만 맞춘다
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.db_errors import integrity_error_info
from app.core.error_codes import ErrorCode
from app.services.exceptions import DomainError

INVALID_INPUT_MESSAGE = "입력값이 올바르지 않습니다."

# 요청 위치 표시는 필드 이름에서 뺀다 ("body.plate" → "plate")
_LOCATION_PREFIXES = {"body", "query", "path", "header", "cookie"}

_HTTP_STATUS_CODES: dict[int, tuple[ErrorCode, str]] = {
    401: (ErrorCode.UNAUTHORIZED, "로그인이 필요합니다."),
    404: (ErrorCode.NOT_FOUND, "대상을 찾을 수 없습니다."),
}


def error_body(code: ErrorCode | str, message: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": str(code), "message": message, "detail": detail}}


def _field_name(loc: tuple[Any, ...] | list[Any]) -> str:
    parts = list(loc)
    if parts and parts[0] in _LOCATION_PREFIXES:
        parts = parts[1:]
    return ".".join(str(p) for p in parts)


def validation_detail(exc: RequestValidationError) -> dict[str, Any]:
    """첫 번째 오류를 field/reason 으로 (명세 예시 형식), 전체 목록은 errors 로."""
    errors = [{"field": _field_name(e.get("loc", ())), "reason": e.get("msg", "")} for e in exc.errors()]
    first = errors[0] if errors else {"field": "", "reason": ""}
    return {**first, "errors": errors}


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message, exc.detail))


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=400, content=error_body(ErrorCode.INVALID_INPUT, INVALID_INPUT_MESSAGE, validation_detail(exc))
    )


async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """DB 제약 위반이 500 으로 나가지 않도록 409 로 변환 (docs/db-design-issues.md 1장)."""
    code, message = integrity_error_info(exc)
    return JSONResponse(status_code=409, content=error_body(code, message))


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code, message = _HTTP_STATUS_CODES.get(exc.status_code, (ErrorCode.INVALID_INPUT, INVALID_INPUT_MESSAGE))
    if isinstance(exc.detail, str) and exc.status_code not in _HTTP_STATUS_CODES:
        message = exc.detail
    return JSONResponse(status_code=exc.status_code, content=error_body(code, message), headers=exc.headers)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
