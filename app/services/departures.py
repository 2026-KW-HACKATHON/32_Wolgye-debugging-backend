"""출차 예정. 구 API(/departures)용 함수와, 명세 API(#7~#9)가 쓰는 출차 예정 조회·반복 일정.

출차 예정 조회 규칙 (docs/db-design-issues.md 2-2, 결정 10):
- 날짜 하나에 적용되는 행 = 그 날짜의 일회성 행 + 반복 행(`scheduled_date` 이후, `repeat_weekdays` 요일)
- 여러 개면 사용자 등록 > AI 추정, 사용자 등록끼리는 그 날짜를 직접 지정한 일회성 > 반복, 그다음 최신 `created_at`
- exit_source: 반복 행 → RECURRING, is_ai_estimated → AI_ESTIMATED, 그 외 → MANUAL
- 시각은 Asia/Seoul 기준 (`scheduled_date + scheduled_time`)
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.weekdays import weekdays_from_db, weekdays_to_db
from app.models.departure_schedule import DepartureSchedule
from app.models.resident import Resident
from app.schemas.common import KST
from app.schemas.departure_schedule import DepartureScheduleCreate
from app.schemas.my_vehicle import ExitSource, RecurringSchedule
from app.services.exceptions import NotFoundError


# ── 구 API (#15에서 삭제) ──────────────────────────────────────────────
async def list_departures(db: AsyncSession, vehicle_id: int | None = None) -> list[DepartureSchedule]:
    stmt = select(DepartureSchedule)
    if vehicle_id is not None:
        stmt = stmt.where(DepartureSchedule.vehicle_id == vehicle_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_departure(db: AsyncSession, payload: DepartureScheduleCreate) -> DepartureSchedule:
    schedule = DepartureSchedule(**payload.model_dump())
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)
    return schedule


async def get_departure(db: AsyncSession, schedule_id: int) -> DepartureSchedule:
    schedule = await db.get(DepartureSchedule, schedule_id)
    if not schedule:
        raise NotFoundError("Departure schedule not found")
    return schedule


# ── 출차 예정 조회 ─────────────────────────────────────────────────────
@dataclass(frozen=True)
class Departure:
    """어느 날의 출차 예정 한 건."""

    at: datetime  # Asia/Seoul
    source: ExitSource


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


# 반복 일정은 일주일 안에 반드시 한 번 돌아온다
_RECURRING_LOOKAHEAD_DAYS = 7


def _next_from_rows(rows: list[DepartureSchedule], today: date) -> Departure | None:
    days = {row.scheduled_date for row in rows if not _is_recurring(row)}
    if any(_is_recurring(row) for row in rows):
        days.update(today + timedelta(days=i) for i in range(_RECURRING_LOOKAHEAD_DAYS))
    for day in sorted(days):
        departure = departure_on(rows, day)
        if departure is not None:
            return departure
    return None


async def next_departures(db: AsyncSession, vehicle_ids: Iterable[int], now: datetime) -> dict[int, Departure]:
    """차량별 다음 출차 예정 (vehicle_id → Departure). 예정이 없는 차량은 결과에 없다.

    다음 출차 예정 = 오늘(KST) 것이 있으면 시각이 지났어도 오늘 것, 없으면 가장 가까운 이후 날짜의 것.
    지난 날짜의 일회성 행은 보지 않는다.
    """
    ids = list(vehicle_ids)
    if not ids:
        return {}
    today = now.astimezone(KST).date()
    rows = await db.scalars(
        select(DepartureSchedule).where(
            DepartureSchedule.vehicle_id.in_(ids),
            or_(
                DepartureSchedule.scheduled_date >= today,
                func.cardinality(DepartureSchedule.repeat_weekdays) > 0,
            ),
        )
    )
    by_vehicle: dict[int, list[DepartureSchedule]] = {}
    for row in rows.all():
        by_vehicle.setdefault(row.vehicle_id, []).append(row)
    result = {}
    for vehicle_id, vehicle_rows in by_vehicle.items():
        departure = _next_from_rows(vehicle_rows, today)
        if departure is not None:
            result[vehicle_id] = departure
    return result


async def next_departure(db: AsyncSession, vehicle_id: int, now: datetime) -> Departure | None:
    """vehicle_id 차량의 다음 출차 예정 (규칙은 next_departures). 없으면 None."""
    return (await next_departures(db, [vehicle_id], now)).get(vehicle_id)


# ── 반복 출차 일정 (차량당 하나: repeat_weekdays 가 비어 있지 않은 행) ─────────
def _recurring_rows(vehicle_id: int):
    return (
        select(DepartureSchedule)
        .where(DepartureSchedule.vehicle_id == vehicle_id, func.cardinality(DepartureSchedule.repeat_weekdays) > 0)
        .order_by(DepartureSchedule.id.desc())
    )


def _to_recurring(row: DepartureSchedule) -> RecurringSchedule:
    return RecurringSchedule(days=weekdays_from_db(row.repeat_weekdays), time=row.scheduled_time, memo=row.memo)


async def _owned_vehicle_id(db: AsyncSession, user: Resident, vehicle_id: int) -> int:
    # vehicles 서비스가 이 모듈을 import 하므로 여기서 가져온다 (순환 import 방지)
    from app.services.vehicles import get_owned_vehicle

    return (await get_owned_vehicle(db, user, vehicle_id)).id


async def get_recurring(db: AsyncSession, user: Resident, vehicle_id: int) -> RecurringSchedule:
    """내 차량의 반복 출차 일정. 내 차량이 아니거나 반복 일정이 없으면 404 NOT_FOUND."""
    vehicle_id = await _owned_vehicle_id(db, user, vehicle_id)
    row = (await db.scalars(_recurring_rows(vehicle_id).limit(1))).first()
    if row is None:
        raise NotFoundError("반복 출차 일정이 없습니다.")
    return _to_recurring(row)


async def put_recurring(
    db: AsyncSession, user: Resident, vehicle_id: int, payload: RecurringSchedule, now: datetime | None = None
) -> RecurringSchedule:
    """반복 출차 일정을 설정한다. 이미 있으면 그 행을 바꾼다. `scheduled_date` = 설정한 날(KST)."""
    vehicle_id = await _owned_vehicle_id(db, user, vehicle_id)
    today = (now or datetime.now(KST)).astimezone(KST).date()
    rows = list((await db.scalars(_recurring_rows(vehicle_id))).all())
    if rows:
        row, extras = rows[0], rows[1:]
        for extra in extras:  # 구 API 로 여러 개 만들어 둔 경우 하나만 남긴다
            await db.delete(extra)
    else:
        row = DepartureSchedule(vehicle_id=vehicle_id)
        db.add(row)
    row.scheduled_date = today
    row.scheduled_time = payload.time
    row.repeat_weekdays = weekdays_to_db(payload.days)
    row.is_ai_estimated = False
    row.memo = payload.memo
    await db.commit()
    await db.refresh(row)
    return _to_recurring(row)


async def delete_recurring(db: AsyncSession, user: Resident, vehicle_id: int) -> None:
    """반복 출차 일정 해제. 일정이 없어도 성공한다."""
    vehicle_id = await _owned_vehicle_id(db, user, vehicle_id)
    await db.execute(
        delete(DepartureSchedule).where(
            DepartureSchedule.vehicle_id == vehicle_id, func.cardinality(DepartureSchedule.repeat_weekdays) > 0
        )
    )
    await db.commit()
