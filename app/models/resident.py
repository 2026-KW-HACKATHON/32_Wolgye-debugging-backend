from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.building import Building
    from app.models.notification import Notification
    from app.models.vehicle import Vehicle


class ResidentRole(enum.StrEnum):
    RESIDENT = "resident"  # 입주민
    MANAGER = "manager"    # 건물주 · 관리인


class Resident(Base):
    """사용자 계정 (입주민/관리자). 이메일로 가입하고 초대코드로 건물에 합류하기 전까지 building_id 는 NULL."""

    __tablename__ = "residents"
    __table_args__ = (
        CheckConstraint("manner_temperature BETWEEN 0 AND 99.9", name="ck_resident_manner_temperature"),
        CheckConstraint("token_balance >= 0", name="ck_resident_token_balance"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    building_id: Mapped[int | None] = mapped_column(ForeignKey("buildings.id", ondelete="SET NULL"), nullable=True)

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str] = mapped_column(String(50), nullable=False)

    name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 비노출 대상 아님 (기획 결정)
    unit_no: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 동/호수
    role: Mapped[ResidentRole] = mapped_column(
        Enum(ResidentRole, name="resident_role"), default=ResidentRole.RESIDENT, server_default="RESIDENT"
    )

    # 매너 온도 (관리자 화면의 38.5℃ 표시). 기본 36.5.
    manner_temperature: Mapped[float] = mapped_column(Float, default=36.5, server_default="36.5")

    # 보유 토큰. 공유 이용료는 토큰으로만 주고받는다 (이동 기록은 token_transfers).
    token_balance: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    building: Mapped[Building | None] = relationship(back_populates="residents")
    vehicles: Mapped[list[Vehicle]] = relationship(back_populates="owner")
    notifications: Mapped[list[Notification]] = relationship(back_populates="resident", cascade="all, delete-orphan")
