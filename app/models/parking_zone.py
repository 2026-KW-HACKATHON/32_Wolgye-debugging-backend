from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.building import Building
    from app.models.parking_slot import ParkingSlot


class ZoneType(enum.StrEnum):
    PILOTI_IN = "piloti_in"    # 필로티 내부
    PILOTI_OUT = "piloti_out"  # 필로티 외부 / 건물 앞
    ALLEY = "alley"            # 골목


class ParkingZone(Base):
    """운영팀이 미리 등록하는 주차 구역. 칸은 구역 안의 번호로 특정한다 (예: 필로티 안쪽 2번)."""

    __tablename__ = "parking_zones"
    __table_args__ = (UniqueConstraint("building_id", "name", name="uq_zone_name_per_building"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False)

    name: Mapped[str] = mapped_column(String(50), nullable=False)  # 예: 필로티 안쪽
    zone_type: Mapped[ZoneType] = mapped_column(Enum(ZoneType, name="zone_type"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    building: Mapped[Building] = relationship(back_populates="zones")
    slots: Mapped[list[ParkingSlot]] = relationship(back_populates="zone", cascade="all, delete-orphan")
