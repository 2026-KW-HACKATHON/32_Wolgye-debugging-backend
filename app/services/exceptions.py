"""HTTP 와 무관한 도메인 예외. HTTP 상태 코드 변환은 app/main.py 의 전역 핸들러가 한다."""


class DomainError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFoundError(DomainError):
    """대상이 없음 → 404"""


class ConflictError(DomainError):
    """현재 상태와 충돌 → 409"""


class ForbiddenError(DomainError):
    """권한 없음 → 403"""
