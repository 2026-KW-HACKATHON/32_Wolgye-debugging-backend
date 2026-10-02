"""공통 도구 단위 테스트: 에러 코드, 번호판, 요일, 명세 ↔ DB enum."""

import re
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from app.core.enum_maps import (
    ApiShareRequestStatus,
    BuildingRole,
    api_name,
    from_api_name,
    role_from_api,
    role_to_api,
    share_status_from_api,
    share_status_to_api,
)
from app.core.error_codes import ErrorCode
from app.core.plates import format_plate, is_valid_plate, normalize_plate
from app.core.weekdays import Weekday, weekday_from_db, weekday_to_db, weekdays_from_db, weekdays_to_db
from app.models.move_request import MoveRequestStatus
from app.models.notification import NotificationType
from app.models.resident import ResidentRole
from app.models.share_request import ShareRequestStatus
from app.schemas.common import PlateIn, PlateOut

SPEC = Path(__file__).resolve().parents[2] / "docs" / "openapi-mock.yaml"


def test_error_codes_match_spec_enum():
    text = SPEC.read_text(encoding="utf-8")
    block = text.split("    ErrorCode:", 1)[1].split("enum:", 1)[1].split("\n    Weekday:", 1)[0]
    spec_codes = re.findall(r"^\s+- (\w+)$", block, flags=re.MULTILINE)
    assert len(spec_codes) == 17
    assert [c.value for c in ErrorCode] == spec_codes


# ── 번호판 ──
@pytest.mark.parametrize(
    ("raw", "normalized", "formatted"),
    [
        ("12가3456", "12가3456", "12가 3456"),
        ("12가 3456", "12가3456", "12가 3456"),
        (" 123 가  4567 ", "123가4567", "123가 4567"),
    ],
)
def test_plate_normalize_and_format(raw, normalized, formatted):
    assert normalize_plate(raw) == normalized
    assert format_plate(raw) == formatted
    assert is_valid_plate(raw)


@pytest.mark.parametrize("raw", ["", "1가3456", "12가345", "12a3456", "서울12가3456"])
def test_plate_invalid(raw):
    assert not is_valid_plate(raw)


def test_format_unknown_plate_keeps_value_without_spaces():
    assert format_plate("서울 12가3456") == "서울12가3456"


class _PlateModel(BaseModel):
    plate_in: PlateIn | None = None
    plate_out: PlateOut | None = None


def test_plate_schema_types():
    assert _PlateModel(plate_in="12가 3456").plate_in == "12가3456"
    assert _PlateModel(plate_out="12가3456").plate_out == "12가 3456"
    with pytest.raises(ValidationError):
        _PlateModel(plate_in="12가")


# ── 요일 ──
def test_weekday_round_trip():
    for i, day in enumerate(["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]):
        assert weekday_to_db(day) == i
        assert weekday_from_db(i) == Weekday(day)


def test_weekday_lists():
    assert weekdays_to_db([Weekday.FRI, "MON", Weekday.MON]) == [0, 4]
    assert weekdays_from_db([6, 0, 2]) == [Weekday.MON, Weekday.WED, Weekday.SUN]


@pytest.mark.parametrize("bad", [-1, 7])
def test_weekday_out_of_range(bad):
    with pytest.raises(ValueError):
        weekday_from_db(bad)


def test_weekday_unknown_name():
    with pytest.raises(ValueError):
        weekday_to_db("MONDAY")


# ── 명세 ↔ DB enum ──
def test_role_mapping():
    assert role_to_api(ResidentRole.MANAGER) == BuildingRole.ADMIN
    assert role_to_api(ResidentRole.RESIDENT) == BuildingRole.RESIDENT
    assert role_from_api("ADMIN") == ResidentRole.MANAGER
    assert role_from_api(BuildingRole.RESIDENT) == ResidentRole.RESIDENT


def test_share_status_mapping():
    assert share_status_to_api(ShareRequestStatus.ACCEPTED) == ApiShareRequestStatus.APPROVED
    assert share_status_to_api(ShareRequestStatus.PENDING) == "PENDING"
    assert share_status_from_api("APPROVED") == ShareRequestStatus.ACCEPTED
    assert share_status_from_api("REJECTED") == ShareRequestStatus.REJECTED
    with pytest.raises(ValueError):
        share_status_from_api("ACCEPTED")  # 명세 이름이 아님


def test_same_name_enums():
    assert api_name(MoveRequestStatus.MOVED) == "MOVED"
    assert api_name(NotificationType.BLOCK_ALERT) == "BLOCK_ALERT"
    assert from_api_name(MoveRequestStatus, "PENDING") is MoveRequestStatus.PENDING
    with pytest.raises(ValueError):
        from_api_name(MoveRequestStatus, "moved")
