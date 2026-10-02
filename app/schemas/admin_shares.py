"""관리인 공유 조건·공유 요청 (명세 ShareOffer*, AdminShareRequest*, decideShareRequest). 담당: 건우 #13.

- 요일: 명세 `MON`~`SUN` ↔ DB 0~6 (app/core/weekdays.py)
- 공유 요청 상태: 명세 `APPROVED` ↔ DB `ACCEPTED` (app/core/enum_maps.py)
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from app.core.enum_maps import ApiShareRequestStatus
from app.schemas.common import KstDatetime, Weekday

Hour = Annotated[int, Field(ge=0, le=24, description="정시 단위 시각. 24 = 자정")]
ALL_WEEKDAYS = list(Weekday)


def _check_hours(start_hour: int | None, end_hour: int | None) -> None:
    if start_hour is not None and end_hour is not None and start_hour >= end_hour:
        raise ValueError("start_hour 는 end_hour 보다 앞서야 합니다.")


# ── 공유 조건 ──
class ShareOfferFields(BaseModel):
    """명세 ShareOfferFields. 시작일·종료일은 받지 않는다 (서버가 등록일 ~ 9999-12-31 로 저장, 결정 12)."""

    weekdays: list[Weekday] = Field(default_factory=lambda: list(ALL_WEEKDAYS), min_length=1)
    start_hour: Hour
    end_hour: Hour
    hourly_price: int = Field(default=0, ge=0, description="시간당 토큰. 0 이면 무료")
    max_hours: int | None = Field(default=None, ge=1, description="요청 1건 최대 시간. null = 제한 없음")
    memo: str | None = None
    is_public: bool = True

    @model_validator(mode="after")
    def _hours_in_order(self):
        _check_hours(self.start_hour, self.end_hour)
        return self


class ShareOfferCreate(ShareOfferFields):
    slot_ids: list[int] = Field(min_length=1, description="공유할 칸 (이 빌라의 활성 칸)")


class ShareOfferUpdate(BaseModel):
    """부분 수정. 보낸 필드만 바꾼다. null 을 허용하는 필드는 max_hours·memo 뿐이다 (나머지에 null 이면 400)."""

    weekdays: list[Weekday] | None = Field(default=None, min_length=1)
    start_hour: Hour | None = None
    end_hour: Hour | None = None
    hourly_price: int | None = Field(default=None, ge=0)
    max_hours: int | None = Field(default=None, ge=1)
    memo: str | None = None
    is_public: bool | None = None

    @model_validator(mode="after")
    def _check(self):
        for name in _NOT_NULL_FIELDS:
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} 에는 null 을 보낼 수 없습니다.")
        _check_hours(self.start_hour, self.end_hour)
        return self


_NOT_NULL_FIELDS = ("weekdays", "start_hour", "end_hour", "hourly_price", "is_public")


class ShareOfferRead(BaseModel):
    id: int
    slot_id: int
    slot_label: str
    host_id: int
    weekdays: list[Weekday]
    start_hour: int
    end_hour: int
    hourly_price: int
    max_hours: int | None
    memo: str | None
    is_public: bool


class ShareOfferList(BaseModel):
    items: list[ShareOfferRead]


# ── 공유 요청 ──
class AdminShareRequestRequester(BaseModel):
    name: str
    unit: str | None


class AdminShareRequestItem(BaseModel):
    id: int
    requester: AdminShareRequestRequester
    plate: str | None
    slot_label: str
    request_date: date
    start_hour: int
    end_hour: int
    total_price: int
    status: ApiShareRequestStatus


class AdminShareRequestCounts(BaseModel):
    PENDING: int = 0
    APPROVED: int = 0
    REJECTED: int = 0


class AdminShareRequestPage(BaseModel):
    counts: AdminShareRequestCounts
    items: list[AdminShareRequestItem]
    next_cursor: str | None = None


ShareRequestStatusFilter = Literal["all", "PENDING", "APPROVED", "REJECTED"]


class ShareRequestDecision(BaseModel):
    status: Literal["APPROVED", "REJECTED"]
    # 프리셋: 주차 구역 용량 초과 · 시간 불가 · 기타 (Figma 문구). 자유 문자열로 받는다
    reject_reason: str | None = Field(default=None, max_length=200)


class ShareRequestDecisionResult(BaseModel):
    id: int
    status: ApiShareRequestStatus
    reject_reason: str | None
    responded_at: KstDatetime
