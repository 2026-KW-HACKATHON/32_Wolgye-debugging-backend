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
    DEPARTURE_REMINDER = "departure_reminder"  # 전날 밤 출차 예정 알림
    SHARE_REQUEST = "share_request"            # 공유 요청 도착 (관리자용)
    SHARE_RESPONSE = "share_response"          # 공유 요청 수락/거절 결과
    MOVE_REQUEST = "move_request"              # 이동 요청 도착
    MOVE_RESPONSE = "move_response"            # 이동 요청 응답 ("옮겼어요")


class Notification(Base):
    """전날 밤 알림, 공유 요청·이동 요청 알림. 원인 요청을 FK로 연결해 알림 탭 → 해당 화면 이동."""

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

    is_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    resident: Mapped[Resident] = relationship(back_populates="notifications")
