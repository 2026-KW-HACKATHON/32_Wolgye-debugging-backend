"""칸 이름(`label`, `slot_label`) = 빌라 안 순번 P1, P2 … (#24, 명세 열린 질문 2, FE 합의).

빌라의 칸 전체를 주차 구역 `sort_order` → 주차 구역 id → 칸 `number` 순으로 센다.
비활성 칸도 순번에 넣는다 (명세 예시: 비활성 칸 1005 = P5). 화면에는 주차 구역 이름을 쓰지 않는다.
"""

from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.garage import Garage
from app.models.parking_slot import ParkingSlot
from app.services.exceptions import NotFoundError


def format_label(ordinal: int) -> str:
    """1 → "P1"."""
    return f"P{ordinal}"


def _ordinal():
    return (
        func.row_number()
        .over(partition_by=Garage.building_id, order_by=(Garage.sort_order, Garage.id, ParkingSlot.number))
        .label("ordinal")
    )


async def building_slot_labels(db: AsyncSession, building_id: int) -> dict[int, str]:
    """빌라의 모든 칸 {slot_id: "P순번"}. 순번 순서로 들어 있다."""
    rows = await db.execute(
        select(ParkingSlot.id, _ordinal())
        .join(Garage, Garage.id == ParkingSlot.garage_id)
        .where(Garage.building_id == building_id)
        .order_by("ordinal")
    )
    return {slot_id: format_label(ordinal) for slot_id, ordinal in rows.all()}


async def slot_labels(db: AsyncSession, slot_ids: Iterable[int]) -> dict[int, str]:
    """여러 칸의 {slot_id: "P순번"}. 칸이 서로 다른 빌라에 있어도 된다. 없는 id 는 결과에 없다."""
    ids = set(slot_ids)
    if not ids:
        return {}
    buildings = (
        select(Garage.building_id).join(ParkingSlot, ParkingSlot.garage_id == Garage.id).where(ParkingSlot.id.in_(ids))
    )
    numbered = (
        select(ParkingSlot.id.label("slot_id"), _ordinal())
        .join(Garage, Garage.id == ParkingSlot.garage_id)
        .where(Garage.building_id.in_(buildings))
        .subquery()
    )
    rows = await db.execute(select(numbered.c.slot_id, numbered.c.ordinal).where(numbered.c.slot_id.in_(ids)))
    return {slot_id: format_label(ordinal) for slot_id, ordinal in rows.all()}


async def slot_label(db: AsyncSession, slot_id: int) -> str:
    """칸 하나의 이름. 없는 칸이면 404 NOT_FOUND."""
    label = (await slot_labels(db, [slot_id])).get(slot_id)
    if label is None:
        raise NotFoundError("칸을 찾을 수 없습니다.")
    return label
