from __future__ import annotations

from datetime import datetime, time
from typing import TYPE_CHECKING

from sqlalchemy import ARRAY, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, Time, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.building import Building
    from app.models.parking_slot import ParkingSlot


class Garage(Base):
    """관리자가 여는 시간제 공유 차고지 (차고지 등록 n45 / 탐색 n32 / 상세 n34). 칸은 parking_slots.garage_id 로 묶는다."""

    __tablename__ = "garages"
    __table_args__ = (
        CheckConstraint("available_start < available_end", name="ck_garage_available_time"),
        CheckConstraint("available_weekdays <@ ARRAY[0,1,2,3,4,5,6]", name="ck_garage_weekdays"),
        CheckConstraint("hourly_fee >= 0", name="ck_garage_fee"),
        CheckConstraint("max_hours IS NULL OR max_hours > 0", name="ck_garage_max_hours"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False)

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)  # 상세 위치 안내

    available_start: Mapped[time] = mapped_column(Time, nullable=False)
    available_end: Mapped[time] = mapped_column(Time, nullable=False)
    # 0=월 ... 6=일
    available_weekdays: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default=text("'{0,1,2,3,4,5,6}'")
    )

    hourly_fee: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # 원, 0 = 무료
    max_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)  # NULL = 제한 없음
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)  # 이용자에게 전달할 사항
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    building: Mapped[Building] = relationship(back_populates="garages")
    slots: Mapped[list[ParkingSlot]] = relationship(back_populates="garage")
