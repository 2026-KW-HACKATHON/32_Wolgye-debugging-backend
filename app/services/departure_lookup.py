"""출차 예정 조회 (읽기 전용). 담당: 건우 #12. 차고지 탐색·상세의 `estimated_free_at`·`SOON_EXIT`(결정 13)가 쓴다.

⚠️ 출차 예정 규칙은 현서 #7(PR #22)의 `app/services/departures.py` 와 **똑같이** 맞췄다. #22 가 머지되면
#15 에서 이 모듈의 `departure_on`·`next_departure(s)`·`ExitSource` 를 그쪽으로 합친다.

출차 예정 조회 규칙 (docs/db-design-issues.md 2-2, 결정 10):
- 날짜 하나에 적용되는 행 = 그 날짜의 일회성 행 + 반복 행(`scheduled_date` 이후, `repeat_weekdays` 요일)
- 여러 개면 사용자 등록 > AI 추정, 사용자 등록끼리는 그 날짜를 직접 지정한 일회성 > 반복, 그다음 최신 `created_at`, 그다음 큰 id
- exit_source: is_ai_estimated → AI_ESTIMATED, 반복 행 → RECURRING, 그 외 → MANUAL
- 시각은 Asia/Seoul 기준 (`scheduled_date + scheduled_time`)
- 다음 출차 예정: 오늘(KST) 것이 있으면 시각이 지났어도 오늘 것, 없으면 가장 가까운 이후 날짜의 것. 지난 날짜의 일회성 행은 보지 않는다

칸이 언제 비는지 (`slot_occupancy`):
- 주차 중인 차가 입주민 차(소유자가 그 칸 빌라 소속)면 그 차의 다음 출차 예정. 상시 주차면 없음
- 외부 차량(다른 빌라·공유 이용자)이거나 차는 없지만 수락된 공유가 진행 중이면 그 공유의 종료 시각 (출처 NONE)
- 미확인 차량(소유자 없음)은 없음
"""

import enum
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.departure_schedule import DepartureSchedule
from app.models.garage import Garage
from app.models.parking_assignment import ParkingAssignment
from app.models.parking_slot import ParkingSlot
from app.models.resident import Resident
from app.models.vehicle import Vehicle
from app.schemas.common import KST, to_kst
from app.services.share_requests import accepted_shares_at

SOON_EXIT_WINDOW = timedelta(hours=1)  # 결정 13
# 반복 일정은 일주일 안에 반드시 한 번 돌아온다
_RECURRING_LOOKAHEAD_DAYS = 7


class ExitSource(enum.StrEnum):
    """명세 ExitSource (결정 10)."""

    MANUAL = "MANUAL"
    RECURRING = "RECURRING"
    AI_ESTIMATED = "AI_ESTIMATED"
    NONE = "NONE"


@dataclass(frozen=True)
class Departure:
    """어느 날의 출차 예정 한 건."""

    at: datetime  # Asia/Seoul
    source: ExitSource


@dataclass(frozen=True)
class SlotOccupancy:
    """칸이 지금 쓰이고 있는지와 언제 비는지. free_at 이 None 이면 비는 시각을 모른다 (상시·미확인 등)."""

    occupied: bool
    free_at: datetime | None = None
    source: ExitSource | None = None

    def is_soon_exit(self, at: datetime) -> bool:
        """비는 시각이 at 부터 1시간 안 (이미 지났어도 아직 주차 중이면 곧 나갈 차로 본다)."""
        return self.occupied and self.free_at is not None and self.free_at - at <= SOON_EXIT_WINDOW


def _is_recurring(row: DepartureSchedule) -> bool:
    return bool(row.repeat_weekdays)


def _applies_on(row: DepartureSchedule, day: date) -> bool:
    if _is_recurring(row):
        return row.scheduled_date <= day and day.weekday() in row.repeat_weekdays
    return row.scheduled_date == day


def exit_source(row: DepartureSchedule) -> ExitSource:
    if row.is_ai_estimated:
        return ExitSource.AI_ESTIMATED
    return ExitSource.RECURRING if _is_recurring(row) else ExitSource.MANUAL


def departure_on(rows: Iterable[DepartureSchedule], day: date) -> Departure | None:
    """한 차량의 행들 중 day 에 적용되는 출차 예정. 없으면 None."""
    candidates = [row for row in rows if _applies_on(row, day)]
    if not candidates:
        return None
    best = max(candidates, key=lambda r: (not r.is_ai_estimated, not _is_recurring(r), r.created_at, r.id))
    return Departure(at=datetime.combine(day, best.scheduled_time, tzinfo=KST), source=exit_source(best))


def next_departure_from_rows(rows: Iterable[DepartureSchedule], now: datetime) -> Departure | None:
    """한 차량의 행들 중 다음 출차 예정 (PR #22 `next_departure` 와 같은 규칙). 없으면 None."""
    today = to_kst(now).date()
    rows = [row for row in rows if _is_recurring(row) or row.scheduled_date >= today]
    days = {row.scheduled_date for row in rows if not _is_recurring(row)}
    if any(_is_recurring(row) for row in rows):
        days.update(today + timedelta(days=i) for i in range(_RECURRING_LOOKAHEAD_DAYS))
    for day in sorted(days):
        departure = departure_on(rows, day)
        if departure is not None:
            return departure
    return None


async def next_departures(db: AsyncSession, vehicle_ids: Iterable[int], now: datetime) -> dict[int, Departure]:
    """차량별 다음 출차 예정. 출차 예정이 없는 차량은 결과에 없다. commit 하지 않는다."""
    ids = set(vehicle_ids)
    if not ids:
        return {}
    today = to_kst(now).date()
    result = await db.execute(
        select(DepartureSchedule).where(
            DepartureSchedule.vehicle_id.in_(ids),
            or_(DepartureSchedule.scheduled_date >= today, func.cardinality(DepartureSchedule.repeat_weekdays) > 0),
        )
    )
    by_vehicle: dict[int, list[DepartureSchedule]] = {}
    for row in result.scalars():
        by_vehicle.setdefault(row.vehicle_id, []).append(row)
    departures = {vid: next_departure_from_rows(rows, now) for vid, rows in by_vehicle.items()}
    return {vid: dep for vid, dep in departures.items() if dep is not None}


async def next_departure(db: AsyncSession, vehicle_id: int, now: datetime) -> Departure | None:
    """차량 하나의 다음 출차 예정. 없으면 None."""
    return (await next_departures(db, [vehicle_id], now)).get(vehicle_id)


async def slot_occupancy(db: AsyncSession, slot_ids: Iterable[int], at: datetime) -> dict[int, SlotOccupancy]:
    """칸별 at 시각의 점유 상태. 모든 slot_id 가 결과에 들어간다. commit 하지 않는다."""
    ids = list(set(slot_ids))
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(ParkingAssignment, Vehicle, Resident.building_id, Garage.building_id)
            .join(Vehicle, Vehicle.id == ParkingAssignment.vehicle_id)
            .outerjoin(Resident, Resident.id == Vehicle.owner_id)
            .join(ParkingSlot, ParkingSlot.id == ParkingAssignment.slot_id)
            .join(Garage, Garage.id == ParkingSlot.garage_id)
            .where(ParkingAssignment.slot_id.in_(ids), ParkingAssignment.is_active.is_(True))
        )
    ).all()
    shares = await accepted_shares_at(db, ids, at)

    resident_vehicle_ids = [
        vehicle.id
        for assignment, vehicle, owner_building, slot_building in rows
        if vehicle.owner_id is not None and owner_building == slot_building and not assignment.is_permanent
    ]
    departures = await next_departures(db, resident_vehicle_ids, at)

    def share_end(slot_id: int) -> datetime | None:
        share = shares.get(slot_id)
        if share is None:
            return None
        return datetime.combine(share.request_date, time(0), tzinfo=KST) + timedelta(hours=share.end_hour)

    occupancy: dict[int, SlotOccupancy] = {}
    for assignment, vehicle, owner_building, slot_building in rows:
        slot_id = assignment.slot_id
        if vehicle.owner_id is None:  # 미확인 차량
            occupancy[slot_id] = SlotOccupancy(occupied=True, source=ExitSource.NONE)
        elif owner_building == slot_building:  # 입주민 차량
            dep = None if assignment.is_permanent else departures.get(vehicle.id)
            occupancy[slot_id] = SlotOccupancy(
                occupied=True, free_at=dep.at if dep else None, source=dep.source if dep else ExitSource.NONE
            )
        else:  # 외부 차량: 수락된 공유의 종료 시각
            occupancy[slot_id] = SlotOccupancy(occupied=True, free_at=share_end(slot_id), source=ExitSource.NONE)
    for slot_id in ids:
        if slot_id in occupancy:
            continue
        end = share_end(slot_id)
        occupancy[slot_id] = (
            SlotOccupancy(occupied=True, free_at=end, source=ExitSource.NONE) if end else SlotOccupancy(occupied=False)
        )
    return occupancy
