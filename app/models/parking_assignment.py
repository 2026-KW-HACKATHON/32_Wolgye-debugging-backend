from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.parking_slot import ParkingSlot
    from app.models.vehicle import Vehicle


class ParkingAssignment(Base):
    """차량이 특정 칸에 배치된 기록 (n15 차 배치). released_at 이 NULL 이면 주차 중."""

    __tablename__ = "parking_assignments"
    __table_args__ = (
        # 한 칸에 주차 중인 차는 하나, 한 차는 한 칸에만
        Index("uq_active_assignment_slot", "slot_id", unique=True, postgresql_where=text("is_active")),
        Index("uq_active_assignment_vehicle", "vehicle_id", unique=True, postgresql_where=text("is_active")),
        CheckConstraint("is_active = (released_at IS NULL)", name="ck_assignment_active_released"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("parking_slots.id", ondelete="CASCADE"), nullable=False)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False)

    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")  # 출차 시 False
    is_permanent: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")  # 상시 주차

    slot: Mapped[ParkingSlot] = relationship(back_populates="assignments")
    vehicle: Mapped[Vehicle] = relationship(back_populates="assignments")
