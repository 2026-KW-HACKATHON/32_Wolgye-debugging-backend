"""막힘 판정. 담당: 현서 (#9). 막힘 규칙은 이 파일 한 곳에만 둔다 (건우 #14 등은 읽기 전용으로 호출).

막힘 규칙 (#4 결정 1):
- 칸 A 의 앞 칸(`parking_slots.front_slot_id`)을 B 라 할 때, B 에 차가 있고 그 차가 A 의 차보다 **늦게 나가면**
  A 는 B 에 의해 막혀 있다.
- B 차의 출차 시간이 없으면(상시 주차·미확인 차량) 늦게 나가는 것으로 본다 → 막힘.
- A 차의 출차 시간이 없으면(상시 주차 등) 막힘으로 보지 않는다.
- A 또는 B 에 주차 중인 차가 없으면 막힘이 아니다.
- 출차 시간은 Asia/Seoul 기준으로 해석한다 (출차 일정 = date + time).

차의 출차 시간:
- 상시 주차(`is_permanent`)·미확인 차량(주인 없음) → 없음
- 이 빌라 입주민 차 → 다음 출차 예정 (app/services/departures.next_departures)
- 외부 차량(공유 이용자) → 그 칸에서 진행 중인 수락된 공유의 종료 시각

`at` 은 판정 기준 시각(timezone-aware datetime). **지금 주차 중인 차**(활성 배치)와, at 기준 그 차의 출차 시간으로 판정한다.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.garage import Garage
from app.models.parking_assignment import ParkingAssignment
from app.models.parking_slot import ParkingSlot
from app.models.resident import Resident
from app.models.share_request import ShareRequest
from app.models.vehicle import Vehicle
from app.schemas.common import KST
from app.services import departures, share_requests


@dataclass
class SlotBlock:
    """칸 하나의 막힘 관계. 명세 SlotStatus 의 blocked_by / blocking 과 같은 뜻."""

    blocked_by: list[int] = field(default_factory=list)  # 이 칸의 차를 막고 있는 칸 id
    blocking: list[int] = field(default_factory=list)  # 이 칸의 차가 막고 있는 칸 id


def is_blocked(my_exit: datetime | None, front_exit: datetime | None) -> bool:
    """두 칸 모두 차가 있을 때의 판정. 내 출차 시간이 없으면 막힘이 아니고, 앞 차 출차 시간이 없으면 막힘."""
    if my_exit is None:
        return False
    return front_exit is None or front_exit > my_exit


def share_end_at(share: ShareRequest) -> datetime:
    """수락된 공유의 종료 시각 (Asia/Seoul). end_hour = 24 는 다음 날 0시."""
    return datetime.combine(share.request_date, time.min, tzinfo=KST) + timedelta(hours=share.end_hour)


async def accepted_share(db: AsyncSession, slot_id: int, at: datetime) -> ShareRequest | None:
    """at 시각에 slot_id 칸에서 진행 중인 수락된 공유 (건우 #12 의 share_requests.accepted_share_at). 없으면 None."""
    return await share_requests.accepted_share_at(db, slot_id, at)


async def occupant_exits(db: AsyncSession, slot_ids: Iterable[int], at: datetime) -> dict[int, datetime | None]:
    """주차 중인 칸마다 그 차의 출차 시간 (slot_id → 출차 시간 또는 None). 비어 있는 칸은 결과에 없다."""
    rows = (
        await db.execute(
            select(ParkingAssignment, Vehicle.owner_id, Resident.building_id, Garage.building_id)
            .join(Vehicle, Vehicle.id == ParkingAssignment.vehicle_id)
            .outerjoin(Resident, Resident.id == Vehicle.owner_id)
            .join(ParkingSlot, ParkingSlot.id == ParkingAssignment.slot_id)
            .join(Garage, Garage.id == ParkingSlot.garage_id)
            .where(ParkingAssignment.is_active, ParkingAssignment.slot_id.in_(list(slot_ids)))
        )
    ).all()

    exits: dict[int, datetime | None] = {}
    resident_cars: dict[int, int] = {}  # vehicle_id → slot_id
    for assignment, owner_id, owner_building_id, slot_building_id in rows:
        exits[assignment.slot_id] = None
        if assignment.is_permanent or owner_id is None:
            continue
        if owner_building_id == slot_building_id:
            resident_cars[assignment.vehicle_id] = assignment.slot_id
        else:
            share = await accepted_share(db, assignment.slot_id, at)
            exits[assignment.slot_id] = share_end_at(share) if share else None

    for vehicle_id, departure in (await departures.next_departures(db, resident_cars, at)).items():
        exits[resident_cars[vehicle_id]] = departure.at
    return exits


async def _block_map(db: AsyncSession, slots: list[ParkingSlot], at: datetime) -> dict[int, SlotBlock]:
    """slots 안에서의 막힘 관계. 앞 칸이 slots 에 없으면 그 관계는 보지 않는다."""
    blocks = {slot.id: SlotBlock() for slot in slots}
    exits = await occupant_exits(db, blocks.keys(), at)
    for slot in slots:
        front_id = slot.front_slot_id
        if front_id is None or slot.id not in exits or front_id not in exits:
            continue
        if is_blocked(exits[slot.id], exits[front_id]):
            blocks[slot.id].blocked_by.append(front_id)
            blocks[front_id].blocking.append(slot.id)
    return blocks


async def blocked_by(db: AsyncSession, slot_id: int, at: datetime) -> list[int]:
    """at 시각 기준으로 slot_id 칸의 차를 막고 있는 칸 id 목록. 막히지 않았거나 칸이 비어 있으면 []."""
    slot = await db.get(ParkingSlot, slot_id)
    if slot is None or slot.front_slot_id is None:
        return []
    front = await db.get(ParkingSlot, slot.front_slot_id)
    slots = [slot, front] if front is not None else [slot]
    return (await _block_map(db, slots, at))[slot_id].blocked_by


async def blocking_slots(db: AsyncSession, slot_id: int, at: datetime) -> list[int]:
    """at 시각 기준으로 slot_id 칸의 차가 막고 있는 칸 id 목록 (이 칸을 앞 칸으로 둔 칸들 중). 없으면 []."""
    slots = list(
        (
            await db.scalars(
                select(ParkingSlot).where((ParkingSlot.id == slot_id) | (ParkingSlot.front_slot_id == slot_id))
            )
        ).all()
    )
    block = (await _block_map(db, slots, at)).get(slot_id)
    return sorted(block.blocking) if block else []


async def building_block_map(db: AsyncSession, building_id: int, at: datetime) -> dict[int, SlotBlock]:
    """at 시각 기준으로 building_id 빌라의 모든 칸(slot_id → SlotBlock). 막힘이 없는 칸도 빈 SlotBlock 으로 포함한다.

    배치도 현황(#9), 홈 요약의 막힘 수, 전날 밤 막힘 알림(결정 15)이 이 결과를 쓴다.
    """
    slots = list(
        (
            await db.scalars(select(ParkingSlot).join(Garage, Garage.id == ParkingSlot.garage_id).where(
                Garage.building_id == building_id
            ))
        ).all()
    )
    return await _block_map(db, slots, at)
