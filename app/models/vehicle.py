from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.departure_schedule import DepartureSchedule
    from app.models.parking_assignment import ParkingAssignment
    from app.models.resident import Resident


class Vehicle(Base):
    """차량. owner 가 있으면 앱 사용자 차량(입주민 또는 공유 이용자), owner 가 NULL 이면 관리자가 등록한 미확인 차량.
    입주민/외부 구분은 저장하지 않고 조회하는 건물 기준으로 owner.building_id 를 비교해 계산한다."""

    __tablename__ = "vehicles"
    __table_args__ = (
        # 사용자당 대표 차량은 하나
        Index("uq_primary_vehicle_per_owner", "owner_id", unique=True, postgresql_where=text("is_primary")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plate_no: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)  # 예: 12가 3456
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("residents.id", ondelete="SET NULL"), nullable=True)

    color: Mapped[str | None] = mapped_column(String(20), nullable=True)     # 차량 등록 n10
    nickname: Mapped[str | None] = mapped_column(String(30), nullable=True)  # 차량 관리 n52 (내 차, 가족 차)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    owner: Mapped[Resident | None] = relationship(back_populates="vehicles")
    assignments: Mapped[list[ParkingAssignment]] = relationship(back_populates="vehicle", cascade="all, delete-orphan")
    departure_schedules: Mapped[list[DepartureSchedule]] = relationship(back_populates="vehicle", cascade="all, delete-orphan")
