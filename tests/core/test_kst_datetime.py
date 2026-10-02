"""KstDatetime: 응답 datetime 을 Asia/Seoul(+09:00) 로 직렬화."""

from datetime import UTC, datetime, timedelta, timezone

from pydantic import BaseModel

from app.schemas.common import KstDatetime


class _M(BaseModel):
    at: KstDatetime


def test_utc_to_kst():
    m = _M(at=datetime(2026, 9, 30, 5, 20, tzinfo=UTC))
    assert m.model_dump(mode="json") == {"at": "2026-09-30T14:20:00+09:00"}
    assert m.model_dump_json() == '{"at":"2026-09-30T14:20:00+09:00"}'


def test_naive_is_treated_as_utc():
    assert _M(at=datetime(2026, 9, 30, 20, 0)).model_dump(mode="json") == {"at": "2026-10-01T05:00:00+09:00"}


def test_other_offset_converted():
    at = datetime(2026, 9, 30, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
    assert _M(at=at).model_dump(mode="json") == {"at": "2026-09-30T14:00:00+09:00"}


def test_python_mode_keeps_datetime():
    at = datetime(2026, 9, 30, 5, 20, tzinfo=UTC)
    assert _M(at=at).model_dump()["at"] == at
