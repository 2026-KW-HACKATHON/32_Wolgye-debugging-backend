from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.garage import Garage
    from app.models.parking_assignment import ParkingAssignment
    from app.models.share_offer import ShareOffer
    from app.models.share_request import ShareRequest


class ParkingSlot(Base):
    """차고지 안의 번호로 특정되는 주차 칸. 2.5D 배치도에서 탭하면 이 칸에 차가 배치된다."""

    __tablename__ = "parking_slots"
    __table_args__ = (
        UniqueConstraint("garage_id", "number", name="uq_slot_number_per_garage"),
        CheckConstraint("number > 0", name="ck_slot_number_positive"),
        CheckConstraint("front_slot_id IS NULL OR front_slot_id <> id", name="ck_slot_front_not_self"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    garage_id: Mapped[int] = mapped_column(ForeignKey("garages.id", ondelete="CASCADE"), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)  # 차고지 안 번호

    # 이 칸 바로 앞(출구 쪽) 칸. 앞 칸 차가 더 늦게 나가면 이 칸 차가 막힌다 (막힘·추천 계산용).
    front_slot_id: Mapped[int | None] = mapped_column(
        ForeignKey("parking_slots.id", ondelete="SET NULL"), nullable=True
    )

    # 2.5D 배치도 로컬 좌표 (건물 기준 미터, 목업 slotRect 의 x0,y0,x1,y1). 탭 판정·렌더링용.
    render_x0: Mapped[float | None] = mapped_column(Float, nullable=True)
    render_y0: Mapped[float | None] = mapped_column(Float, nullable=True)
    render_x1: Mapped[float | None] = mapped_column(Float, nullable=True)
    render_y1: Mapped[float | None] = mapped_column(Float, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")  # 삭제 대신 비활성화


    garage: Mapped[Garage] = relationship(back_populates="slots")
    front_slot: Mapped[ParkingSlot | None] = relationship(remote_side="ParkingSlot.id")
    assignments: Mapped[list[ParkingAssignment]] = relationship(back_populates="slot", cascade="all, delete-orphan")
    share_offers: Mapped[list[ShareOffer]] = relationship(back_populates="slot", cascade="all, delete-orphan")
    share_requests: Mapped[list[ShareRequest]] = relationship(back_populates="slot", cascade="all, delete-orphan")
