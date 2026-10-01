from __future__ import annotations

from typing import TYPE_CHECKING

from geoalchemy2 import Geometry
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.alley import Alley
    from app.models.garage import Garage
    from app.models.resident import Resident


class Building(Base):
    """빌라/건물. 골목에 속하며, 운영팀이 미리 등록하고 입주민은 초대코드로 합류한다."""

    __tablename__ = "buildings"

    id: Mapped[int] = mapped_column(primary_key=True)
    alley_id: Mapped[int] = mapped_column(ForeignKey("alleys.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)  # 예: 월계 한빛빌라
    address: Mapped[str] = mapped_column(String(255), nullable=False)  # 예: 노원구 광운로19가길
    detail_address: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # 관리자가 입주민에게 전달하는 초대코드
    invite_code: Mapped[str] = mapped_column(String(12), nullable=False, unique=True)

    # 건물 대표 위치 (공유 주차 탐색 지도, 거리 계산용). SRID 4326 = WGS84 위경도.
    location: Mapped[str] = mapped_column(Geometry(geometry_type="POINT", srid=4326), nullable=True)

    alley: Mapped[Alley] = relationship(back_populates="buildings")
    garages: Mapped[list[Garage]] = relationship(back_populates="building", cascade="all, delete-orphan")
    residents: Mapped[list[Resident]] = relationship(back_populates="building")
