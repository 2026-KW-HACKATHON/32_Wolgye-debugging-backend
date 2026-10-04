"""공유 요청 (명세 ShareRequestCreate, ShareRequestDetail). 상태는 명세 APPROVED ↔ DB ACCEPTED.

구 API 스키마(app/schemas/share_request.py)는 #15에서 지운다. 그때 이 파일 이름을 바꿔도 된다.
"""

from datetime import date
from typing import Self

from pydantic import BaseModel, Field, model_validator

from app.core.enum_maps import ApiShareRequestStatus, share_status_to_api
from app.models.share_request import ShareRequest
from app.services.share_requests import MyShareRequest


class ShareRequestCreate(BaseModel):
    offer_id: int
    vehicle_id: int | None = None
    request_date: date
    start_hour: int = Field(ge=0, le=24)
    end_hour: int = Field(ge=0, le=24)  # 24 = 자정

    @model_validator(mode="after")
    def check_hours(self) -> Self:
        if self.start_hour >= self.end_hour:
            raise ValueError("start_hour 는 end_hour 보다 앞서야 합니다.")
        return self


class ShareRequestCreated(BaseModel):
    id: int
    status: ApiShareRequestStatus
    total_price: int

    @classmethod
    def from_model(cls, r: ShareRequest) -> "ShareRequestCreated":
        return cls(id=r.id, status=share_status_to_api(r.status), total_price=r.total_price)


class GarageRef(BaseModel):
    id: int
    name: str


class ShareRequestDetail(BaseModel):
    id: int
    status: ApiShareRequestStatus
    reject_reason: str | None
    garage: GarageRef
    slot_id: int
    slot_label: str
    request_date: date
    start_hour: int
    end_hour: int
    total_price: int

    @classmethod
    def from_view(cls, view: MyShareRequest) -> "ShareRequestDetail":
        r = view.request
        return cls(
            id=r.id,
            status=share_status_to_api(r.status),
            reject_reason=r.reject_reason,
            garage=GarageRef(id=view.garage_id, name=view.garage_name),
            slot_id=r.slot_id,
            slot_label=view.slot_label,
            request_date=r.request_date,
            start_hour=r.start_hour,
            end_hour=r.end_hour,
            total_price=r.total_price,
        )
