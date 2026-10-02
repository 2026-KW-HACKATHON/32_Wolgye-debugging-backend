"""HTTP 와 무관한 도메인 예외. HTTP 상태 코드 변환은 app/main.py 의 전역 핸들러가 한다.

응답 본문: {"error": {"code": exc.code, "message": exc.message, "detail": exc.detail}}

사용 예:
    raise NotFoundError("차량을 찾을 수 없습니다.")                       # 404 NOT_FOUND
    raise NotFoundError("초대코드가 올바르지 않습니다.", code=ErrorCode.INVALID_INVITE_CODE)
    raise ConflictError("토큰이 부족합니다.", code=ErrorCode.INSUFFICIENT_TOKENS, detail={"required": 6})

서브클래스마다 상태 코드(`status_code`)와 기본 코드(`default_code`)가 정해져 있고, 호출할 때 `code` 로 바꿀 수 있다.
새 서브클래스를 추가하면 `status_code` 만 정하면 된다 (main.py 는 고칠 필요 없음).
"""

from typing import Any, ClassVar

from app.core.error_codes import ErrorCode


class DomainError(Exception):
    status_code: ClassVar[int] = 400
    default_code: ClassVar[ErrorCode] = ErrorCode.INVALID_INPUT
    default_message: ClassVar[str] = "입력값이 올바르지 않습니다."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: ErrorCode | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.code = code or self.default_code
        self.detail = detail
        super().__init__(self.message)


class InvalidInputError(DomainError):
    """규칙상 잘못된 입력 → 400"""


class UnauthorizedError(DomainError):
    """인증 실패 → 401 (토큰 없음·만료 = UNAUTHORIZED, 로그인 실패 = INVALID_CREDENTIALS)"""

    status_code = 401
    default_code = ErrorCode.UNAUTHORIZED
    default_message = "로그인이 필요합니다."


class ForbiddenError(DomainError):
    """권한 없음 → 403 (기본 NOT_BUILDING_MEMBER, 관리인 전용은 NOT_BUILDING_ADMIN)"""

    status_code = 403
    default_code = ErrorCode.NOT_BUILDING_MEMBER
    default_message = "이 빌라의 입주민만 이용할 수 있습니다."


class NotFoundError(DomainError):
    """대상이 없음 → 404"""

    status_code = 404
    default_code = ErrorCode.NOT_FOUND
    default_message = "대상을 찾을 수 없습니다."


class ConflictError(DomainError):
    """현재 상태와 충돌 → 409. 기본 CONFLICT, 명세에 더 구체적인 코드가 있으면 code 로 지정한다."""

    status_code = 409
    default_code = ErrorCode.CONFLICT
    default_message = "현재 상태에서 처리할 수 없습니다."
