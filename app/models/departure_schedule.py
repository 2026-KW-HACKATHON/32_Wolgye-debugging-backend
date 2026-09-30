from __future__ import annotations

from datetime import date, datetime, time
from typing import TYPE_CHECKING

from sqlalchemy import ARRAY, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Text, Time, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.vehicle import Vehicle


class DepartureSchedule(Base):
    """출차 예정 시간 (n15 차 배치 · n18 수정 · n20 반복). 모든 알림/추천 기능의 기반 데이터.
    반복 행은 scheduled_date 를 반복 시작일로 보고 repeat_weekdays 요일마다 scheduled_time 에 출차.
    같은 (차량, 날짜)에 여러 행이 있으면 사용자 등록 > AI 추정, 같은 종류면 최신 created_at 을 쓴다."""

    __tablename__ = "departure_schedules"
    __table_args__ = (
        CheckConstraint("repeat_weekdays <@ ARRAY[0,1,2,3,4,5,6]", name="ck_departure_weekdays"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False)

    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    scheduled_time: Mapped[time] = mapped_column(Time, nullable=False)

    # 반복 요일: 0=월 ... 6=일. 반복이 아니면 빈 배열.
    repeat_weekdays: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), default=list, nullable=False, server_default=text("'{}'")
    )

    # True면 차주가 등록하지 않아 과거 기록으로 추정한 값 (AI 추정 말풍선)
    is_ai_estimated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    vehicle: Mapped[Vehicle] = relationship(back_populates="departure_schedules")
