"""전날 밤 막힘 알림 (#9, 결정 15). 외부 cron 으로 매일 22:00 KST 에 실행한다.

    python -m app.jobs.block_alert

내일 출차할 차가 앞 칸 차에 막혀 있으면, 막고 있는 차의 주인에게 BLOCK_ALERT 를 보낸다
("내 차량이 내일 07:30 출차하는 차량을 막고 있어요"). 막힘 판정은 app/services/blocking.py (결정 1) 그대로다.
주인 없는 미확인 차량에는 보낼 수 없어 건너뛴다.
"""

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.building import Building
from app.models.notification import NotificationType
from app.schemas.common import KST
from app.services import notifications
from app.services.building_view import snapshot

TITLE = "내일 출차 안내"


def alert_body(exit_at: datetime) -> str:
    return f"내 차량이 내일 {exit_at.astimezone(KST).strftime('%H:%M')} 출차하는 차량을 막고 있어요"


async def send_block_alerts(db: AsyncSession, now: datetime | None = None) -> int:
    """모든 빌라에서 내일(KST) 출차 예정인 막힌 차를 찾아 막는 차 주인에게 알린다. 보낸 알림 수를 돌려준다."""
    now = now or datetime.now(KST)
    tomorrow = now.astimezone(KST).date() + timedelta(days=1)
    sent = 0
    for building_id in (await db.scalars(select(Building.id).order_by(Building.id))).all():
        snap = await snapshot(db, building_id, now)
        for slot_id, block in snap.blocks.items():
            exit_at = snap.occupants[slot_id].exit_at if block.blocked_by else None
            if exit_at is None or exit_at.astimezone(KST).date() != tomorrow:
                continue
            for blocker_slot_id in block.blocked_by:
                owner_id = snap.occupants[blocker_slot_id].vehicle.owner_id
                if owner_id is None:
                    continue
                await notifications.create(db, owner_id, NotificationType.BLOCK_ALERT, TITLE, alert_body(exit_at))
                sent += 1
    await db.commit()
    return sent


async def main() -> None:
    async with AsyncSessionLocal() as db:
        sent = await send_block_alerts(db)
    print(f"막힘 알림 {sent}건을 보냈습니다.")


if __name__ == "__main__":
    asyncio.run(main())
