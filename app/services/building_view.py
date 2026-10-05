"""배치도·실시간 현황 (#9). 빌라 소속 확인은 엔드포인트의 BuildingMember 의존성이 한다.

- 칸 이름은 app/services/slot_labels.py (빌라 안 순번 P1, P2 …), 응답 순서도 그 순서
- 막힘은 app/services/blocking.py, 시각은 Asia/Seoul 기준
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enum_maps import api_name
from app.models.alley import Alley
from app.models.building import Building
from app.models.garage import Garage
from app.models.parking_slot import ParkingSlot
from app.models.resident import Resident
from app.schemas.building_view import (
    BuildingLayout,
    BuildingStatus,
    LayoutSlot,
    LayoutZone,
    SlotParking,
    SlotRect,
    SlotState,
    SlotStatus,
)
from app.schemas.common import KST
from app.schemas.user import AlleyRef
from app.services import blocking
from app.services.blocking import Occupant, SlotBlock
from app.services.exceptions import NotFoundError
from app.services.slot_labels import building_slot_labels

SOON_EXIT_WINDOW = timedelta(hours=1)  # 결정 13


@dataclass
class BuildingSnapshot:
    """빌라의 칸 전체와 지금 상태. 현황·추천·홈·전날 밤 알림이 같이 쓴다."""

    slots: list[ParkingSlot]  # 칸 이름 순 (P1, P2 …)
    labels: dict[int, str]
    occupants: dict[int, Occupant]  # 주차 중인 칸만
    blocks: dict[int, SlotBlock]

    def state(self, slot: ParkingSlot, now: datetime) -> SlotState:
        if not slot.is_active:
            return SlotState.UNAVAILABLE
        occupant = self.occupants.get(slot.id)
        if occupant is None:
            return SlotState.EMPTY
        # 예정 시각이 지났어도 아직 주차 중이면 곧 나갈 차로 본다
        if occupant.exit_at is not None and occupant.exit_at - now <= SOON_EXIT_WINDOW:
            return SlotState.SOON_EXIT
        return SlotState.OCCUPIED


async def snapshot(db: AsyncSession, building_id: int, at: datetime) -> BuildingSnapshot:
    labels = await building_slot_labels(db, building_id)  # 칸 순번 순서
    by_id = {
        slot.id: slot
        for slot in (
            await db.scalars(
                select(ParkingSlot).join(Garage, Garage.id == ParkingSlot.garage_id).where(
                    Garage.building_id == building_id
                )
            )
        ).all()
    }
    slots = [by_id[slot_id] for slot_id in labels]
    occupants = await blocking.occupants(db, labels.keys(), at)
    exits = {slot_id: occupant.exit_at for slot_id, occupant in occupants.items()}
    return BuildingSnapshot(slots=slots, labels=labels, occupants=occupants, blocks=blocking.block_map(slots, exits))


def _rect(slot: ParkingSlot) -> SlotRect | None:
    coords = (slot.render_x0, slot.render_y0, slot.render_x1, slot.render_y1)
    if any(c is None for c in coords):
        return None
    return SlotRect(x0=coords[0], y0=coords[1], x1=coords[2], y1=coords[3])


async def get_layout(db: AsyncSession, building_id: int) -> BuildingLayout:
    """배치도: 골목 > 빌라 > 주차 구역(sort_order 순) > 칸(번호 순)."""
    row = (
        await db.execute(
            select(Building, Alley).join(Alley, Alley.id == Building.alley_id).where(Building.id == building_id)
        )
    ).first()
    if row is None:
        raise NotFoundError("빌라를 찾을 수 없습니다.")
    building, alley = row
    labels = await building_slot_labels(db, building_id)
    garages = (
        await db.scalars(
            select(Garage).where(Garage.building_id == building_id).order_by(Garage.sort_order, Garage.id)
        )
    ).all()
    slots = (
        await db.scalars(
            select(ParkingSlot)
            .join(Garage, Garage.id == ParkingSlot.garage_id)
            .where(Garage.building_id == building_id)
            .order_by(ParkingSlot.number)
        )
    ).all()
    by_garage: dict[int, list[ParkingSlot]] = {}
    for slot in slots:
        by_garage.setdefault(slot.garage_id, []).append(slot)

    return BuildingLayout(
        building_id=building.id,
        name=building.name,
        alley=AlleyRef.model_validate(alley),
        zones=[
            LayoutZone(
                id=garage.id,
                name=garage.name,
                zone_type=api_name(garage.garage_type),
                sort_order=garage.sort_order,
                slots=[
                    LayoutSlot(
                        id=slot.id,
                        number=slot.number,
                        label=labels[slot.id],
                        front_slot_id=slot.front_slot_id,
                        is_active=slot.is_active,
                        rect=_rect(slot),
                    )
                    for slot in by_garage.get(garage.id, [])
                ],
            )
            for garage in garages
        ],
    )


async def get_status(
    db: AsyncSession, user: Resident, building_id: int, now: datetime | None = None
) -> BuildingStatus:
    """실시간 현황: 칸마다 상태·주차 정보·막힘 관계. 칸 이름 순."""
    now = now or datetime.now(KST)
    snap = await snapshot(db, building_id, now)

    def parking(slot_id: int) -> SlotParking | None:
        occupant = snap.occupants.get(slot_id)
        if occupant is None:
            return None
        return SlotParking(
            id=occupant.assignment.id,
            is_mine=occupant.vehicle.owner_id == user.id,
            plate=occupant.vehicle.plate_no,
            occupant_type=occupant.kind,
            expected_exit_at=occupant.exit_at,
            exit_source=occupant.exit_source,
        )

    return BuildingStatus(
        updated_at=now,
        slots=[
            SlotStatus(
                slot_id=slot.id,
                state=snap.state(slot, now),
                parking=parking(slot.id),
                blocked_by=snap.blocks[slot.id].blocked_by,
                blocking=snap.blocks[slot.id].blocking,
            )
            for slot in snap.slots
        ],
    )
