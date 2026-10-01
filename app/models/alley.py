from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.building import Building


class Alley(Base):
    """골목. 서비스의 최상위 운영 단위로, 같은 골목의 빌라끼리 묶이고 차고지를 서로 공유한다.
    골목 > 빌라(buildings) > 차고지(garages) > 칸(parking_slots)."""

    __tablename__ = "alleys"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)  # 예: 광운로19가길
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    buildings: Mapped[list[Building]] = relationship(back_populates="alley", cascade="all, delete-orphan")
