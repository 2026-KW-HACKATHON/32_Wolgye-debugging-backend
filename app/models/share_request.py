from __future__ import annotations

import enum
from datetime import date, datetime, time
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, ForeignKey, String, Time, text
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.parking_slot import ParkingSlot
    from app.models.resident import Resident
    from app.models.vehicle import Vehicle


class ShareRequestStatus(enum.StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ShareRequest(Base):
    """옆 빌라 입주민이 공유 칸을 시간제로 요청 (n34 요청하기 → n41/n47 관리자 수락/거절)."""

    __tablename__ = "share_requests"
    __table_args__ = (
        CheckConstraint("start_time < end_time", name="ck_share_time_order"),
        # 같은 칸에 수락된 요청끼리 시간이 겹치지 않게 (btree_gist 필요)
        ExcludeConstraint(
            ("slot_id", "="),
            (text("tsrange(request_date + start_time, request_date + end_time)"), "&&"),
            name="ex_share_accepted_overlap",
            using="gist",
            where=text("status = 'ACCEPTED'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("parking_slots.id", ondelete="CASCADE"), nullable=False)
    requester_id: Mapped[int] = mapped_column(ForeignKey("residents.id", ondelete="CASCADE"), nullable=False)
    # 어떤 차가 들어오는지 (관리자 화면 외부 차량 번호판 표시)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True)

    request_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    status: Mapped[ShareRequestStatus] = mapped_column(
        Enum(ShareRequestStatus, name="share_request_status"),
        default=ShareRequestStatus.PENDING,
        server_default="PENDING",
    )
    reject_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)  # n40 거절 사유

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    slot: Mapped[ParkingSlot] = relationship(back_populates="share_requests")
    requester: Mapped[Resident] = relationship()
    vehicle: Mapped[Vehicle | None] = relationship()
