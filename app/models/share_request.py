from __future__ import annotations

import enum
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.parking_slot import ParkingSlot
    from app.models.resident import Resident
    from app.models.share_offer import ShareOffer
    from app.models.vehicle import Vehicle


class ShareRequestStatus(enum.StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ShareRequest(Base):
    """옆 빌라 입주민이 공유 칸을 시간 단위로 요청 (n34 요청하기 → n41/n47 관리자 수락/거절).
    시간은 request_date 의 start_hour~end_hour 시 (정시 단위). 수락되면 total_price 토큰이 offer.host 에게 넘어간다."""

    __tablename__ = "share_requests"
    __table_args__ = (
        CheckConstraint("0 <= start_hour AND start_hour < end_hour AND end_hour <= 24", name="ck_share_request_hours"),
        CheckConstraint("total_price >= 0", name="ck_share_request_price"),
        # slot_id 는 EXCLUDE 제약용 사본 → offer 의 칸과 항상 같도록 복합 FK 로 묶는다
        ForeignKeyConstraint(
            ["offer_id", "slot_id"],
            ["share_offers.id", "share_offers.slot_id"],
            name="fk_share_request_offer_slot",
            ondelete="CASCADE",
        ),
        # 같은 칸에 수락된 요청끼리 시간이 겹치지 않게 (btree_gist 필요)
        ExcludeConstraint(
            ("slot_id", "="),
            (
                text(
                    "tsrange(request_date + make_interval(hours => start_hour), "
                    "request_date + make_interval(hours => end_hour))"
                ),
                "&&",
            ),
            name="ex_share_accepted_overlap",
            using="gist",
            where=text("status = 'ACCEPTED'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(nullable=False)
    slot_id: Mapped[int] = mapped_column(ForeignKey("parking_slots.id", ondelete="CASCADE"), nullable=False)
    requester_id: Mapped[int] = mapped_column(ForeignKey("residents.id", ondelete="CASCADE"), nullable=False)
    # 어떤 차가 들어오는지 (관리자 화면 외부 차량 번호판 표시)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True)
    request_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_hour: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0~23
    end_hour: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 1~24 (24 = 자정)
    # 요청 시점 가격으로 계산한 토큰 (시간 수 × offer.hourly_price). 이후 가격이 바뀌어도 유지.
    total_price: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ShareRequestStatus] = mapped_column(
        Enum(ShareRequestStatus, name="share_request_status"),
        default=ShareRequestStatus.PENDING,
        server_default="PENDING",
    )
    reject_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)  # n40 거절 사유
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # slot_id 는 slot 관계가 쓰므로 offer 는 읽기 전용 (offer_id·slot_id 는 서비스가 직접 채운다)
    offer: Mapped[ShareOffer] = relationship(foreign_keys=[offer_id, slot_id], viewonly=True)
    slot: Mapped[ParkingSlot] = relationship(back_populates="share_requests", foreign_keys=[slot_id])
    requester: Mapped[Resident] = relationship()
    vehicle: Mapped[Vehicle | None] = relationship()
