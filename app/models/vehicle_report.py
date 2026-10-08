from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base_class import Base


class VehicleReportStatus(enum.StrEnum):
    SUBMITTED = "submitted"  # 제보됨 (미확인 차량 등록 + 보상 지급 완료)
    DISMISSED = "dismissed"  # 관리인이 허위 제보로 기각 (기각 API 는 아직 없음)


class VehicleReport(Base):
    """미등록 차량 사진 제보 (#52). 제보 한 번에 미확인 차량 배치·관리인 알림·제보 보상이 함께 생긴다.

    사진 파일은 DB 가 아니라 REPORT_PHOTO_DIR 에 두고 photo_key(파일 이름)만 저장한다.
    번호판은 제보 시점 값을 plate_no 에 따로 남긴다 (차량·배치가 지워져도 제보 내용은 남게 SET NULL).
    """

    __tablename__ = "vehicle_reports"
    __table_args__ = (
        CheckConstraint("reward_amount >= 0", name="ck_vehicle_report_reward"),
        Index("ix_vehicle_reports_reporter_created", "reporter_id", "created_at"),  # 하루 제보 횟수
        Index("ix_vehicle_reports_building", "building_id", "id"),  # 관리인 목록
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("residents.id", ondelete="CASCADE"), nullable=False)
    slot_id: Mapped[int] = mapped_column(ForeignKey("parking_slots.id", ondelete="CASCADE"), nullable=False)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True)
    parking_assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("parking_assignments.id", ondelete="SET NULL"), nullable=True
    )
    plate_no: Mapped[str] = mapped_column(String(20), nullable=False)  # 공백 없는 값 (vehicles.plate_no 와 같은 규칙)
    photo_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[VehicleReportStatus] = mapped_column(
        Enum(VehicleReportStatus, name="vehicle_report_status"),
        default=VehicleReportStatus.SUBMITTED,
        server_default="SUBMITTED",
        nullable=False,
    )
    reward_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
