"""배치 추천 (#9, 명세 열린 질문 19 — 2026-10-03 확정).

빌라의 모든 칸을 칸 이름 순으로 내려주고 칸마다 태그를 하나 붙인다.
- UNAVAILABLE: 사용 중지 칸(`is_active=false`), 또는 지금부터 내 출차 시각까지(상시 주차면 그 이후 전부) 수락된 공유가 있는 칸
- OCCUPIED: 지금 차가 있는 칸
- RECOMMENDED: 막히지도 막지도 않는 빈 칸 중 가장 안쪽 한 칸 (같으면 칸 이름이 빠른 칸). 없으면 추천하지 않는다
- EMPTY: 나머지 빈 칸. `will_block` = 여기 두면 막게 되는 칸

막힘 규칙은 app/services/blocking.py (결정 1) 를 그대로 쓴다.
"""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.parking_slot import ParkingSlot
from app.models.resident import Resident
from app.schemas.building_view import SlotRecommendation, SlotRecommendations, SlotTag
from app.schemas.common import KST
from app.services.blocking import is_blocked
from app.services.building_view import BuildingSnapshot, snapshot
from app.services.exceptions import InvalidInputError
from app.services.slot_reservations import reserved_slot_ids
from app.services.vehicles import get_owned_vehicle

REASON_INACTIVE = "관리인이 사용 중지한 칸이에요"
REASON_RESERVED = "예약된 칸이에요"
REASON_FRONT_EMPTY = "앞 칸이 비어 있고 다른 차를 막지 않는 가장 안쪽 칸이에요"
REASON_FRONT_LEAVES_FIRST = "앞 차가 먼저 나가고 다른 차를 막지 않는 가장 안쪽 칸이에요"


def depth(slot: ParkingSlot, by_id: dict[int, ParkingSlot]) -> int:
    """안쪽 정도 = 앞 칸(front_slot_id)을 따라 출구까지 거치는 칸 수. 출구 쪽 칸은 0."""
    count, seen, current = 0, {slot.id}, slot
    while current.front_slot_id is not None and current.front_slot_id in by_id:
        if current.front_slot_id in seen:  # 잘못 등록된 순환 참조
            break
        current = by_id[current.front_slot_id]
        seen.add(current.id)
        count += 1
    return count


def tag_slots(snap: BuildingSnapshot, reserved: set[int], my_exit: datetime | None) -> list[SlotRecommendation]:
    """현재 상태(snap)에서 my_exit 에 나갈 차를 어디에 둘지. my_exit 가 None 이면 상시 주차."""
    by_id = {slot.id: slot for slot in snap.slots}
    behind: dict[int, list[int]] = {}  # 칸 id → 그 칸을 앞 칸으로 두는 뒤 칸들
    for slot in snap.slots:
        if slot.front_slot_id is not None:
            behind.setdefault(slot.front_slot_id, []).append(slot.id)

    result: list[SlotRecommendation] = []
    candidates: list[tuple[int, int]] = []  # (안쪽 정도, result 안의 위치)
    for slot in snap.slots:
        base = {"slot_id": slot.id, "label": snap.labels[slot.id]}
        if not slot.is_active:
            result.append(SlotRecommendation(**base, tag=SlotTag.UNAVAILABLE, unavailable_reason=REASON_INACTIVE))
            continue
        if slot.id in snap.occupants:
            result.append(SlotRecommendation(**base, tag=SlotTag.OCCUPIED))
            continue
        if slot.id in reserved:
            result.append(SlotRecommendation(**base, tag=SlotTag.UNAVAILABLE, unavailable_reason=REASON_RESERVED))
            continue

        front = snap.occupants.get(slot.front_slot_id) if slot.front_slot_id is not None else None
        blocked = front is not None and is_blocked(my_exit, front.exit_at)
        will_block = sorted(
            slot_id
            for slot_id in behind.get(slot.id, [])
            if slot_id in snap.occupants and is_blocked(snap.occupants[slot_id].exit_at, my_exit)
        )
        if not blocked and not will_block:
            candidates.append((depth(slot, by_id), len(result)))
        result.append(SlotRecommendation(**base, tag=SlotTag.EMPTY, will_block=will_block))

    if candidates:
        # 가장 안쪽, 같으면 칸 이름이 빠른(먼저 나온) 칸
        _, index = max(candidates, key=lambda c: (c[0], -c[1]))
        best = result[index]
        front_id = by_id[best.slot_id].front_slot_id
        reason = REASON_FRONT_LEAVES_FIRST if front_id in snap.occupants else REASON_FRONT_EMPTY
        result[index] = SlotRecommendation(
            slot_id=best.slot_id, label=best.label, tag=SlotTag.RECOMMENDED, reason=reason
        )
    return result


async def recommend(
    db: AsyncSession,
    user: Resident,
    building_id: int,
    vehicle_id: int,
    expected_exit_at: datetime | None,
    now: datetime | None = None,
) -> SlotRecommendations:
    """배치 등록 화면의 칸별 태그. 내 차량이 아니면 404, 지난 출차 시각이면 400 INVALID_INPUT."""
    now = now or datetime.now(KST)
    await get_owned_vehicle(db, user, vehicle_id)
    if expected_exit_at is not None and expected_exit_at <= now:
        raise InvalidInputError(detail={"field": "expected_exit_at", "reason": "출차 예정 시각은 지금 이후여야 합니다."})

    snap = await snapshot(db, building_id, now)
    reserved = await reserved_slot_ids(db, snap.labels.keys(), now, expected_exit_at, except_requester_id=user.id)
    return SlotRecommendations(slots=tag_slots(snap, reserved, expected_exit_at))
