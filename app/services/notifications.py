"""알림. 담당: 건우 (#11). 다른 서비스(이동 요청·막힘·출차·공유)는 create() 로만 알림을 만든다."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationType
from app.models.resident import Resident
from app.services.exceptions import NotFoundError
from app.services.pagination import DEFAULT_LIMIT, CursorPage, paginate

# 종류별로 채워야 하는 FK (결정 11). 나머지 FK 는 None 이어야 한다.
_REQUIRED_FK: dict[NotificationType, str | None] = {
    NotificationType.MOVE_REQUEST: "move_request_id",
    NotificationType.SHARE_REQUEST: "share_request_id",
    NotificationType.SHARE_RESULT: "share_request_id",
    NotificationType.BLOCK_ALERT: None,
    NotificationType.EXIT_DONE: None,
    NotificationType.VEHICLE_REPORT: "vehicle_report_id",  # #52
}


async def create(
    db: AsyncSession,
    resident_id: int,
    type: NotificationType,
    title: str,
    body: str,
    *,
    share_request_id: int | None = None,
    move_request_id: int | None = None,
    vehicle_report_id: int | None = None,
) -> Notification:
    """resident_id 에게 알림 하나를 만들어 세션에 추가하고 돌려준다. **commit 하지 않는다** (호출한 쪽 트랜잭션에 포함).

    연결 FK 규칙 (결정 11의 알림 link 가 이 값으로 계산된다):
    - MOVE_REQUEST                  → move_request_id 필수
    - SHARE_REQUEST / SHARE_RESULT  → share_request_id 필수
    - VEHICLE_REPORT                → vehicle_report_id 필수 (#52)
    - BLOCK_ALERT / EXIT_DONE       → 둘 다 None
    규칙에 어긋나면 호출 코드의 버그이므로 ValueError 를 던진다 (HTTP 에러로 바꾸지 않음).

    flush 해서 id·created_at 이 채워진 상태로 돌려준다.

    호출 예 (현서 #10):
        await notifications.create(db, owner_id, NotificationType.MOVE_REQUEST, "주차 요청 도착", "101동 입주민",
                                   move_request_id=move_request.id)
    """
    fks = {
        "share_request_id": share_request_id,
        "move_request_id": move_request_id,
        "vehicle_report_id": vehicle_report_id,
    }
    required = _REQUIRED_FK[type]
    for name, value in fks.items():
        if name == required and value is None:
            raise ValueError(f"{type.name} 알림에는 {name} 가 필요합니다.")
        if name != required and value is not None:
            raise ValueError(f"{type.name} 알림에는 {name} 를 넣지 않습니다.")

    notification = Notification(
        resident_id=resident_id,
        type=type,
        title=title,
        body=body,
        share_request_id=share_request_id,
        move_request_id=move_request_id,
        vehicle_report_id=vehicle_report_id,
    )
    db.add(notification)
    await db.flush()
    await db.refresh(notification)
    return notification


async def list_for(
    db: AsyncSession, user: Resident, cursor: str | None = None, limit: int = DEFAULT_LIMIT
) -> CursorPage[Notification]:
    """내 알림 최신순 한 페이지 (결정 14)."""
    stmt = select(Notification).where(Notification.resident_id == user.id)
    return await paginate(db, stmt, Notification.id, cursor, limit)


async def mark_read(db: AsyncSession, user: Resident, notification_id: int) -> None:
    """알림 하나 읽음. 없거나 내 알림이 아니면 404 NOT_FOUND. 이미 읽었어도 성공."""
    notification = await db.get(Notification, notification_id)
    if notification is None or notification.resident_id != user.id:
        raise NotFoundError("알림을 찾을 수 없습니다.")
    notification.is_read = True
    await db.commit()


async def mark_all_read(db: AsyncSession, user: Resident) -> None:
    """내 안 읽은 알림 모두 읽음."""
    await db.execute(
        update(Notification)
        .where(Notification.resident_id == user.id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    await db.commit()
