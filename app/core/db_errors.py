"""DB 제약 위반(IntegrityError)을 에러 코드와 사용자에게 보여줄 메시지로 바꾼다. 응답 상태는 항상 409.

제약 이름은 asyncpg 원본 예외(`exc.orig.__cause__`)의 `constraint_name` 에 들어 있다.
부분 UNIQUE 인덱스는 인덱스 이름이, 이름을 지정하지 않은 UNIQUE/FK 는 PostgreSQL 기본 이름
(`<table>_<column>_key`, `<table>_<column>_fkey`)이 들어온다. NOT NULL 위반은 이름이 없다.

새 제약을 추가하면 CONSTRAINT_ERRORS 에 (에러 코드, 메시지)를 등록한다.
명세에 맞는 코드가 없으면 INVALID_INPUT 을 쓴다.
"""

from typing import NamedTuple

from sqlalchemy.exc import IntegrityError

from app.core.error_codes import ErrorCode


class ConstraintError(NamedTuple):
    code: ErrorCode
    message: str


_INVALID = ErrorCode.INVALID_INPUT

# 제약 이름 → (코드, 메시지). 이름은 alembic/versions/0002·0003 기준.
CONSTRAINT_ERRORS: dict[str, ConstraintError] = {
    # UNIQUE (이름 미지정 → PostgreSQL 기본 이름)
    "buildings_invite_code_key": ConstraintError(_INVALID, "이미 사용 중인 초대코드입니다."),
    "residents_email_key": ConstraintError(ErrorCode.EMAIL_EXISTS, "이미 가입된 이메일입니다."),
    "vehicles_plate_no_key": ConstraintError(ErrorCode.PLATE_EXISTS, "이미 등록된 차량 번호입니다."),
    # UNIQUE / 부분 UNIQUE 인덱스
    "uq_garage_name_per_building": ConstraintError(_INVALID, "같은 빌라에 같은 이름의 차고지가 있습니다."),
    "uq_slot_number_per_garage": ConstraintError(_INVALID, "같은 차고지에 같은 번호의 칸이 있습니다."),
    "uq_primary_vehicle_per_owner": ConstraintError(_INVALID, "대표 차량은 한 대만 지정할 수 있습니다."),
    "uq_active_assignment_slot": ConstraintError(ErrorCode.SLOT_OCCUPIED, "이 칸에는 이미 주차 중인 차가 있습니다."),
    "uq_active_assignment_vehicle": ConstraintError(
        ErrorCode.VEHICLE_ALREADY_PARKED, "이 차는 이미 다른 칸에 주차 중입니다."
    ),
    "uq_pending_move_request_target": ConstraintError(
        ErrorCode.MOVE_REQUEST_ALREADY_PENDING, "이 차에 대기 중인 이동 요청이 이미 있습니다."
    ),
    # EXCLUDE
    "ex_share_accepted_overlap": ConstraintError(
        ErrorCode.GARAGE_TIME_CONFLICT, "같은 칸에 이미 수락된 공유 시간과 겹칩니다."
    ),
    # CHECK
    "ck_share_request_hours": ConstraintError(_INVALID, "공유 시간은 0~24시 사이, 시작 시가 종료 시보다 앞서야 합니다."),
    "ck_share_request_price": ConstraintError(_INVALID, "공유 이용 토큰은 0 이상이어야 합니다."),
    "ck_slot_number_positive": ConstraintError(_INVALID, "칸 번호는 1 이상이어야 합니다."),
    "ck_slot_front_not_self": ConstraintError(_INVALID, "자기 자신을 앞 칸으로 지정할 수 없습니다."),
    "ck_departure_weekdays": ConstraintError(_INVALID, "반복 요일은 0(월)~6(일) 사이여야 합니다."),
    "ck_share_offer_dates": ConstraintError(_INVALID, "공유 시작일은 종료일보다 늦을 수 없습니다."),
    "ck_share_offer_hours": ConstraintError(_INVALID, "공유 시간은 0~24시 사이, 시작 시가 종료 시보다 앞서야 합니다."),
    "ck_share_offer_weekdays": ConstraintError(_INVALID, "공유 요일은 0(월)~6(일) 사이여야 합니다."),
    "ck_share_offer_price": ConstraintError(_INVALID, "시간당 토큰은 0 이상이어야 합니다."),
    "ck_share_offer_max_hours": ConstraintError(_INVALID, "최대 이용 시간은 0보다 커야 합니다."),
    "ck_move_request_distinct_vehicles": ConstraintError(_INVALID, "이동 요청 대상 차와 막힌 차가 같을 수 없습니다."),
    "ck_resident_manner_temperature": ConstraintError(_INVALID, "매너 온도는 0~99.9 사이여야 합니다."),
    "ck_assignment_active_released": ConstraintError(_INVALID, "배치 상태와 출차 시각이 맞지 않습니다."),
    "ck_resident_token_balance": ConstraintError(ErrorCode.INSUFFICIENT_TOKENS, "토큰 잔액이 부족합니다."),
    "ck_token_transfer_amount": ConstraintError(_INVALID, "토큰은 1 이상 보낼 수 있습니다."),
    "ck_token_transfer_distinct": ConstraintError(_INVALID, "자기 자신에게 토큰을 보낼 수 없습니다."),
}

FOREIGN_KEY_VIOLATION = "23503"
FOREIGN_KEY_ERROR = ConstraintError(_INVALID, "참조한 데이터가 존재하지 않습니다.")
DEFAULT_ERROR = ConstraintError(_INVALID, "데이터 제약 조건 위반")


def integrity_error_info(exc: IntegrityError) -> ConstraintError:
    """제약 이름으로 (code, message)를 찾는다. 등록되지 않은 FK 위반·기타 위반은 기본값."""
    cause = getattr(exc.orig, "__cause__", None)
    name = getattr(cause, "constraint_name", None)
    if name in CONSTRAINT_ERRORS:
        return CONSTRAINT_ERRORS[name]
    if getattr(cause, "sqlstate", None) == FOREIGN_KEY_VIOLATION:
        return FOREIGN_KEY_ERROR
    return DEFAULT_ERROR
