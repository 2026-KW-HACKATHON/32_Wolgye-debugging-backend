from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.resident import Resident


class NotificationType(enum.StrEnum):
    """Figma 와이어프레임에 나오는 알림 5종."""

    BLOCK_ALERT = "block_alert"      # 막힘 알림 (전날 밤 사전 알림 포함, 홈 막힘 카드)
    MOVE_REQUEST = "move_request"    # 이동 요청 도착
    EXIT_DONE = "exit_done"          # 출차 완료 안내 ("건물 앞 2번 비어 있음")
    SHARE_REQUEST = "share_request"  # 공유 사용 요청 도착 (관리인용)
    SHARE_RESULT = "share_result"    # 공유 요청 수락/거절 결과
    VEHICLE_REPORT = "vehicle_report"  # 미등록 차량 제보 도착 (관리인용, #52)


class Notification(Base):
    """막힘·이동 요청·출차 완료·공유 요청 알림. 원인 요청을 FK로 연결해 알림 탭 → 해당 화면 이동.
    막힘·출차 완료 알림은 연결할 요청이 없어 FK 가 모두 NULL 이다 (막힘은 홈으로 이동)."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    resident_id: Mapped[int] = mapped_column(ForeignKey("residents.id", ondelete="CASCADE"), nullable=False)

    type: Mapped[NotificationType] = mapped_column(Enum(NotificationType, name="notification_type"), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    share_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("share_requests.id", ondelete="CASCADE"), nullable=True
    )
    move_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("move_requests.id", ondelete="CASCADE"), nullable=True
    )
    vehicle_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("vehicle_reports.id", ondelete="CASCADE"), nullable=True
    )

    is_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    resident: Mapped[Resident] = relationship(back_populates="notifications")
