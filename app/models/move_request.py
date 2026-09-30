from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.resident import Resident
    from app.models.vehicle import Vehicle


class MoveRequestStatus(enum.StrEnum):
    PENDING = "pending"
    MOVED = "moved"        # "옮겼어요"
    DECLINED = "declined"


class MoveRequest(Base):
    """이동 요청 (입주민 → 입주민, 관리자 → 외부 차량). 수신자는 target_vehicle.owner_id 로 정해진다.
    owner 가 없는 미확인 차량에는 생성하지 않는다 (앱으로 연락 불가)."""

    __tablename__ = "move_requests"
    __table_args__ = (
        CheckConstraint(
            "blocked_vehicle_id IS NULL OR blocked_vehicle_id <> target_vehicle_id",
            name="ck_move_request_distinct_vehicles",
        ),
        # 같은 차에 대기 중인 요청은 하나
        Index(
            "uq_pending_move_request_target",
            "target_vehicle_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("residents.id", ondelete="CASCADE"), nullable=False)
    target_vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False)
    # 막힌 차. 관리자가 외부 차량에 보내는 요청이면 NULL.
    blocked_vehicle_id: Mapped[int | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True
    )

    needed_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 출차 필요 시각
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[MoveRequestStatus] = mapped_column(
        Enum(MoveRequestStatus, name="move_request_status"),
        default=MoveRequestStatus.PENDING,
        server_default="PENDING",
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    requester: Mapped[Resident] = relationship()
    target_vehicle: Mapped[Vehicle] = relationship(foreign_keys=[target_vehicle_id])
    blocked_vehicle: Mapped[Vehicle | None] = relationship(foreign_keys=[blocked_vehicle_id])
