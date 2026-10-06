"""칸이 지금 쓰이고 있는지와 언제 비는지 (읽기 전용). 차고지 탐색·상세(#12)의 `estimated_free_at`·`SOON_EXIT`(결정 13)가 쓴다.

#15 에서 `departure_lookup.py`(#12)를 정리해 만든 모듈이다.
- 출차 예정 조회 규칙은 app/services/departures.py 한 곳에 있다
- 칸에 선 차와 그 차의 출차 시간은 app/services/blocking.occupants 를 그대로 쓴다

칸이 언제 비는지:
- 주차 중인 차가 입주민 차(소유자가 그 칸 빌라 소속)면 그 차의 다음 출차 예정. 상시 주차면 없음
- 외부 차량(다른 빌라·공유 이용자)이면 그 칸에서 진행 중인 수락된 공유의 종료 시각 (출처 NONE)
- 미확인 차량(소유자 없음)은 없음
- 차는 없지만 수락된 공유가 진행 중이면 그 공유의 종료 시각 (출처 NONE)
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.my_vehicle import ExitSource
from app.services import blocking
from app.services.share_requests import accepted_shares_at

SOON_EXIT_WINDOW = timedelta(hours=1)  # 결정 13


@dataclass(frozen=True)
class SlotOccupancy:
    """칸이 지금 쓰이고 있는지와 언제 비는지. free_at 이 None 이면 비는 시각을 모른다 (상시·미확인 등)."""

    occupied: bool
    free_at: datetime | None = None
    source: ExitSource | None = None

    def is_soon_exit(self, at: datetime) -> bool:
        """비는 시각이 at 부터 1시간 안 (이미 지났어도 아직 주차 중이면 곧 나갈 차로 본다)."""
        return self.occupied and self.free_at is not None and self.free_at - at <= SOON_EXIT_WINDOW


async def slot_occupancy(db: AsyncSession, slot_ids: Iterable[int], at: datetime) -> dict[int, SlotOccupancy]:
    """칸별 at 시각의 점유 상태. 모든 slot_id 가 결과에 들어간다. commit 하지 않는다."""
    ids = list(set(slot_ids))
    if not ids:
        return {}
    cars = await blocking.occupants(db, ids, at)
    occupancy = {
        slot_id: SlotOccupancy(occupied=True, free_at=car.exit_at, source=car.exit_source)
        for slot_id, car in cars.items()
    }
    empty = [slot_id for slot_id in ids if slot_id not in cars]
    shares = await accepted_shares_at(db, empty, at)
    for slot_id in empty:
        share = shares.get(slot_id)
        occupancy[slot_id] = (
            SlotOccupancy(occupied=True, free_at=blocking.share_end_at(share), source=ExitSource.NONE)
            if share
            else SlotOccupancy(occupied=False)
        )
    return occupancy
