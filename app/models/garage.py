from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.building import Building
    from app.models.parking_slot import ParkingSlot


class GarageType(enum.StrEnum):
    PILOTI_IN = "piloti_in"    # 필로티 내부
    PILOTI_OUT = "piloti_out"  # 필로티 외부 / 건물 앞
    ROADSIDE = "roadside"      # 골목 노상


class Garage(Base):
    """차고지. 빌라에 속한 주차 공간이며, 칸은 차고지 안의 번호로 특정한다 (예: 필로티 안쪽 2번).
    공유 조건(기간·시간·토큰 가격)은 차고지가 아니라 칸별 share_offers 에 둔다."""

    __tablename__ = "garages"
    __table_args__ = (UniqueConstraint("building_id", "name", name="uq_garage_name_per_building"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)  # 예: 필로티 안쪽
    garage_type: Mapped[GarageType] = mapped_column(Enum(GarageType, name="garage_type"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    building: Mapped[Building] = relationship(back_populates="garages")
    slots: Mapped[list[ParkingSlot]] = relationship(back_populates="garage", cascade="all, delete-orphan")
