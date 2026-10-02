"""요일 변환. 명세는 `MON`~`SUN`, DB 는 정수 0(월)~6(일) (Python date.weekday() 와 같음)."""

import enum
from collections.abc import Iterable


class Weekday(enum.StrEnum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


_ORDER = list(Weekday)


def weekday_to_db(day: Weekday | str) -> int:
    """`MON` → 0 ... `SUN` → 6."""
    return _ORDER.index(Weekday(day))


def weekday_from_db(value: int) -> Weekday:
    """0 → `MON` ... 6 → `SUN`. 범위 밖이면 ValueError."""
    if not 0 <= value <= 6:
        raise ValueError(f"weekday must be 0..6, got {value}")
    return _ORDER[value]


def weekdays_to_db(days: Iterable[Weekday | str]) -> list[int]:
    """요일 목록 → 정렬·중복 제거한 정수 목록 (DB 배열 컬럼용)."""
    return sorted({weekday_to_db(d) for d in days})


def weekdays_from_db(values: Iterable[int]) -> list[Weekday]:
    """DB 정수 목록 → 월요일부터 순서대로 요일 목록."""
    return [weekday_from_db(v) for v in sorted(set(values))]
