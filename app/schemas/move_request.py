"""이동 요청 (#10) 요청·응답 스키마. 명세 MoveRequestDetail 과 /move-requests, /me/move-requests 응답.

명세 ↔ DB 이름: needed_at ↔ move_requests.needed_by, requested_at ↔ created_at.
상태(MoveRequestStatus)는 명세와 DB 이름이 같다 (PENDING / MOVED / DECLINED).
"""

import enum
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import KstDatetime, PlateOut
from app.schemas.parking import ExitAt

MoveRequestStatusName = Literal["PENDING", "MOVED", "DECLINED"]


class MoveRequestBox(enum.StrEnum):
    RECEIVED = "received"  # 받은 요청
    SENT = "sent"  # 보낸 요청


class MoveRequestCreate(BaseModel):
    target_parking_id: int  # 이동을 요청할 차량의 주차 건
    needed_at: ExitAt  # 출차가 필요한 시각
    reason: str | None = Field(default=None, max_length=500)


class MoveRequestCreated(BaseModel):
    id: int
    status: MoveRequestStatusName


class MoveRequester(BaseModel):
    label: str  # 동까지만 ("101동 입주민")


class RequestedVehicle(BaseModel):
    """이동을 요청받은 차량."""

    plate: PlateOut
    slot_label: str | None  # 지금 주차 중이 아니면 null
    parked_at: KstDatetime | None


class BlockedVehicle(BaseModel):
    """막힌 차량 (요청자의 차)."""

    plate: PlateOut
    slot_label: str | None
    needed_at: KstDatetime | None


class MoveRequestDetail(BaseModel):
    id: int
    status: MoveRequestStatusName
    requested_at: KstDatetime
    requester: MoveRequester
    my_vehicle: RequestedVehicle
    blocked_vehicle: BlockedVehicle | None  # 관리인이 외부 차량에 보낸 요청처럼 막힌 차가 없으면 null
    reason: str | None


class MoveRequestDone(BaseModel):
    id: int
    status: MoveRequestStatusName
    responded_at: KstDatetime


class MoveRequestListItem(BaseModel):
    id: int
    status: MoveRequestStatusName
    requested_at: KstDatetime
    counterpart_label: str  # 상대방 표기 (동까지만)
    needed_at: KstDatetime | None


class MoveRequestList(BaseModel):
    items: list[MoveRequestListItem]
