from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.parking_slot import ParkingSlot
    from app.models.resident import Resident


class ShareOffer(Base):
    """칸 공유 조건 (차고지 등록 n45 / 탐색 n32 / 상세 n34). 칸 하나에 기간별로 여러 개를 둘 수 있다.
    start_date~end_date 사이, available_weekdays 요일마다 start_hour~end_hour 시에 시간 단위로 빌려준다.
    요청이 수락되면 요청자의 토큰이 host 에게 넘어간다."""

    __tablename__ = "share_offers"
    __table_args__ = (
        CheckConstraint("start_date <= end_date", name="ck_share_offer_dates"),
        CheckConstraint("0 <= start_hour AND start_hour < end_hour AND end_hour <= 24", name="ck_share_offer_hours"),
        CheckConstraint("available_weekdays <@ ARRAY[0,1,2,3,4,5,6]", name="ck_share_offer_weekdays"),
        CheckConstraint("hourly_price >= 0", name="ck_share_offer_price"),
        CheckConstraint("max_hours IS NULL OR max_hours > 0", name="ck_share_offer_max_hours"),
        # share_requests 가 (offer_id, slot_id) 복합 FK 로 칸을 일치시키기 위한 키
        UniqueConstraint("id", "slot_id", name="uq_share_offer_id_slot"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("parking_slots.id", ondelete="CASCADE"), nullable=False)
    # 공유를 연 관리인. 수락된 요청의 토큰을 받는다.
    host_id: Mapped[int] = mapped_column(ForeignKey("residents.id", ondelete="CASCADE"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)  # 포함
    # 0=월 ... 6=일
    available_weekdays: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default=text("'{0,1,2,3,4,5,6}'")
    )
    start_hour: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0~23
    end_hour: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 1~24 (24 = 자정)
    hourly_price: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # 시간당 토큰, 0 = 무료
    max_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 요청 1건 최대 시간, NULL = 제한 없음
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)  # 이용자에게 전달할 사항
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")  # False = 공유 중단
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    slot: Mapped[ParkingSlot] = relationship(back_populates="share_offers")
    host: Mapped[Resident] = relationship()
