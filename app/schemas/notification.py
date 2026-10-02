"""알림 응답 (명세 NotificationItem). link 는 컬럼 없이 종류와 FK 로 계산한다 (결정 11)."""

from typing import Literal

from pydantic import BaseModel

from app.models.notification import Notification, NotificationType
from app.schemas.common import KstDatetime

NotificationTypeName = Literal["BLOCK_ALERT", "MOVE_REQUEST", "EXIT_DONE", "SHARE_REQUEST", "SHARE_RESULT"]


class NotificationLink(BaseModel):
    screen: str
    id: int | None = None


class NotificationItem(BaseModel):
    id: int
    type: NotificationTypeName
    title: str
    body: str
    link: NotificationLink | None
    is_read: bool
    created_at: KstDatetime

    @classmethod
    def from_model(cls, n: Notification) -> "NotificationItem":
        return cls(
            id=n.id,
            type=n.type.name,
            title=n.title,
            body=n.body,
            link=notification_link(n),
            is_read=n.is_read,
            created_at=n.created_at,
        )


def notification_link(n: Notification) -> NotificationLink | None:
    """결정 11: 알림을 눌렀을 때 이동할 화면."""
    match n.type:
        case NotificationType.MOVE_REQUEST:
            return NotificationLink(screen="MOVE_REQUEST", id=n.move_request_id)
        case NotificationType.SHARE_REQUEST | NotificationType.SHARE_RESULT:
            return NotificationLink(screen="SHARE_REQUEST", id=n.share_request_id)
        case NotificationType.BLOCK_ALERT:
            return NotificationLink(screen="HOME", id=None)
        case _:
            return None
