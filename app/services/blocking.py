"""막힘 판정. 담당: 현서 (#9). 막힘 규칙은 이 파일 한 곳에만 둔다 (건우 #14 등은 읽기 전용으로 호출).

막힘 규칙 (#4 결정 1):
- 칸 A 의 앞 칸(`parking_slots.front_slot_id`)을 B 라 할 때, B 에 차가 있고 그 차가 A 의 차보다 **늦게 나가면**
  A 는 B 에 의해 막혀 있다.
- B 차의 출차 시간이 없으면(상시 주차·미확인 차량) 늦게 나가는 것으로 본다 → 막힘.
- A 차가 상시 주차(출차 시간 없음)면 막힘으로 보지 않는다.
- A 또는 B 에 주차 중인 차가 없으면 막힘이 아니다.
- 출차 시간은 Asia/Seoul 기준으로 해석한다 (출차 일정 = date + time).

`at` 은 판정 기준 시각(timezone-aware datetime). 그 시각에 주차 중인 차와 그 차의 다음 출차 예정 시각으로 판정한다.
"""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class SlotBlock:
    """칸 하나의 막힘 관계. 명세 SlotStatus 의 blocked_by / blocking 과 같은 뜻."""

    blocked_by: list[int] = field(default_factory=list)  # 이 칸의 차를 막고 있는 칸 id
    blocking: list[int] = field(default_factory=list)  # 이 칸의 차가 막고 있는 칸 id


async def blocked_by(db: AsyncSession, slot_id: int, at: datetime) -> list[int]:
    """at 시각에 slot_id 칸의 차를 막고 있는 칸 id 목록. 막히지 않았거나 칸이 비어 있으면 [].

    TODO(#9): 현서가 구현한다.
    """
    raise NotImplementedError("#9 에서 구현")


async def building_block_map(db: AsyncSession, building_id: int, at: datetime) -> dict[int, SlotBlock]:
    """at 시각에 building_id 빌라의 모든 칸(slot_id → SlotBlock). 막힘이 없는 칸도 빈 SlotBlock 으로 포함한다.

    배치도 현황(#9), 홈 요약의 막힘 수, 관리인 칸 현황(#14), 전날 밤 막힘 알림(결정 15)이 이 결과를 쓴다.

    TODO(#9): 현서가 구현한다.
    """
    raise NotImplementedError("#9 에서 구현")
