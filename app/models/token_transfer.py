from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.resident import Resident


class TokenTransfer(Base):
    """토큰 이동 기록. 잔액은 residents.token_balance 에 두고, 이 표는 누가 누구에게 얼마를 넘겼는지 남긴다.
    sender 가 NULL 이면 시스템 지급. 공유 이용료면 share_request_id 로 원인 요청을 연결한다."""

    __tablename__ = "token_transfers"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_token_transfer_amount"),
        CheckConstraint("sender_id IS NULL OR sender_id <> receiver_id", name="ck_token_transfer_distinct"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # 이력은 남기기 위해 사람이 지워져도 SET NULL
    sender_id: Mapped[int | None] = mapped_column(ForeignKey("residents.id", ondelete="SET NULL"), nullable=True)
    receiver_id: Mapped[int | None] = mapped_column(ForeignKey("residents.id", ondelete="SET NULL"), nullable=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    share_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("share_requests.id", ondelete="SET NULL"), nullable=True
    )
    memo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sender: Mapped[Resident | None] = relationship(foreign_keys=[sender_id])
    receiver: Mapped[Resident | None] = relationship(foreign_keys=[receiver_id])
