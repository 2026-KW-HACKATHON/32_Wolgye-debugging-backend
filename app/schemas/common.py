"""여러 응답에서 함께 쓰는 스키마와 타입.

- Page[T]: 페이지네이션 응답 `{items, next_cursor}` (결정 14, 만드는 쪽은 app/services/pagination.py)
- PlateIn / PlateOut: 번호판 (요청은 공백 제거 저장, 응답은 `12가 3456`)
- Weekday: 요일 `MON`~`SUN` (DB 는 0~6, 변환은 app/core/weekdays.py)
- KstDatetime: 응답 datetime 을 Asia/Seoul(+09:00) 로 내보내는 타입
- 명세 ↔ DB 이름이 다른 enum 은 app/core/enum_maps.py
"""

from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, PlainSerializer

from app.core.plates import format_plate, is_valid_plate, normalize_plate
from app.core.weekdays import Weekday

__all__ = ["KstDatetime", "Page", "PlateIn", "PlateOut", "Weekday"]


class Page[T](BaseModel):
    """`?cursor=&limit=` 목록 응답. next_cursor 가 null 이면 마지막 페이지."""

    model_config = ConfigDict(from_attributes=True)

    items: list[T]
    next_cursor: str | None = None


def _plate_in(value: object) -> object:
    return normalize_plate(value) if isinstance(value, str) else value


def _require_plate(value: str) -> str:
    if not is_valid_plate(value):
        raise ValueError("번호판 형식이 올바르지 않습니다 (예: 12가 3456).")
    return value


# 요청 필드: "12가 3456" / "12가3456" → "12가3456" (DB 저장 형식). 형식(PLATE_PATTERN)이 틀리면 400 INVALID_INPUT
PlateIn = Annotated[str, BeforeValidator(_plate_in), AfterValidator(_require_plate)]
# 응답 필드: DB 값 "12가3456" → "12가 3456"
PlateOut = Annotated[str, AfterValidator(format_plate)]


KST = ZoneInfo("Asia/Seoul")


def to_kst(value: datetime) -> datetime:
    """datetime → Asia/Seoul. naive 면 UTC 로 간주한다."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(KST)


# 응답 필드: 직렬화할 때 Asia/Seoul 로 바꿔 "2026-09-30T14:20:00+09:00" 형식으로 내보낸다
KstDatetime = Annotated[
    datetime, PlainSerializer(lambda v: to_kst(v).isoformat(), return_type=str, when_used="json")
]
