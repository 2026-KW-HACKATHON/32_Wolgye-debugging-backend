"""알림. 담당: 건우 (#11). 다른 서비스(이동 요청·막힘·출차·공유)는 create() 로만 알림을 만든다."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationType


async def create(
    db: AsyncSession,
    resident_id: int,
    type: NotificationType,
    title: str,
    body: str,
    *,
    share_request_id: int | None = None,
    move_request_id: int | None = None,
) -> Notification:
    """resident_id 에게 알림 하나를 만들어 세션에 추가하고 돌려준다. **commit 하지 않는다** (호출한 쪽 트랜잭션에 포함).

    연결 FK 규칙 (결정 11의 알림 link 가 이 값으로 계산된다):
    - MOVE_REQUEST                  → move_request_id 필수
    - SHARE_REQUEST / SHARE_RESULT  → share_request_id 필수
    - BLOCK_ALERT / EXIT_DONE       → 둘 다 None

    호출 예 (현서 #10):
        await notifications.create(db, owner_id, NotificationType.MOVE_REQUEST, "주차 요청 도착", "101동 입주민",
                                   move_request_id=move_request.id)

    TODO(#11): 건우가 구현한다.
    """
    raise NotImplementedError("#11 에서 구현")
