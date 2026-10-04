"""칸의 공유 예약 조회 (읽기 전용). 담당: 현서 (#8, #9).

입주민이 칸을 쓰려는 시간(지금 ~ 내 출차 시각)에 **수락된 공유**가 걸려 있으면 그 칸은 "예약된 칸"이다.
주차 배치(POST /parkings)와 배치 추천(slots/recommendations)이 같은 기준을 쓴다.
"""

from collections.abc import Iterable
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.share_request import ShareRequest, ShareRequestStatus
from app.schemas.common import KST, to_kst


def share_window(share: ShareRequest) -> tuple[datetime, datetime]:
    """공유 시간 [시작, 끝) (Asia/Seoul). end_hour = 24 는 다음 날 0시."""
    midnight = datetime.combine(share.request_date, time.min, tzinfo=KST)
    return midnight + timedelta(hours=share.start_hour), midnight + timedelta(hours=share.end_hour)


async def reserved_slot_ids(
    db: AsyncSession,
    slot_ids: Iterable[int],
    start: datetime,
    end: datetime | None,
    except_requester_id: int | None = None,
) -> set[int]:
    """slot_ids 중 [start, end) 사이에 수락된 공유가 있는 칸. end 가 None 이면 start 이후 전부 (상시 주차).

    except_requester_id 가 요청한 공유는 세지 않는다 (공유 이용자 본인의 예약).
    """
    ids = set(slot_ids)
    if not ids:
        return set()
    stmt = select(ShareRequest).where(
        ShareRequest.slot_id.in_(ids),
        ShareRequest.status == ShareRequestStatus.ACCEPTED,
        ShareRequest.request_date >= to_kst(start).date(),
    )
    if end is not None:
        stmt = stmt.where(ShareRequest.request_date <= to_kst(end).date())
    if except_requester_id is not None:
        stmt = stmt.where(ShareRequest.requester_id != except_requester_id)

    reserved = set()
    for share in (await db.scalars(stmt)).all():
        share_start, share_end = share_window(share)
        if share_end > start and (end is None or share_start < end):
            reserved.add(share.slot_id)
    return reserved
