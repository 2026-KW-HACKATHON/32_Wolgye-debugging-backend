"""차고지 탐색·상세. 담당: 건우 #12. 차고지(garage) = 빌라의 주차장이라 `garage_id` 는 빌라 id 다.

탐색 목록 (GET /garages):
- 내 빌라와 같은 골목의 **다른** 빌라에서, 공개(`is_public`)이고 아직 끝나지 않은 공유 조건이 있는 활성 칸을 하나씩
- 칸에 공유 조건이 여러 개면 가장 먼저 이용할 수 있는 조건 하나를 쓴다 (같으면 작은 id)
- availability:
    AVAILABLE   지금 공유 시간 안이고 칸이 비어 있음
    SOON_EXIT   지금 공유 시간 안이고 칸의 차가 1시간 안에 나갈 예정 (결정 13)
    RESERVABLE  지금은 공유 시간이 아니지만 앞으로 이용할 수 있는 시간이 있음 (`available_from`)
    UNAVAILABLE 그 밖 (지금 사용 중이고 1시간 안에 비지 않음, 앞으로 이용할 시간이 없음)
- filter: all / now = AVAILABLE / reservable = RESERVABLE / free = 시간당 0토큰
- 정렬: lat·lng 가 있으면 빌라 위치(`buildings.location`) 거리순(위치 없는 빌라는 뒤), 없으면 칸 id 내림차순.
  next_cursor 는 마지막 항목의 slot_id
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from geoalchemy2 import Geography
from sqlalchemy import cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alley import Alley
from app.models.building import Building
from app.models.garage import Garage
from app.models.parking_slot import ParkingSlot
from app.models.resident import Resident
from app.models.share_offer import ShareOffer
from app.schemas.common import KST, to_kst
from app.schemas.my_vehicle import ExitSource
from app.services.exceptions import InvalidInputError, NotFoundError
from app.services.pagination import DEFAULT_LIMIT, CursorPage, parse_cursor
from app.services.slot_labels import building_slot_labels, slot_labels
from app.services.slot_occupancy import SlotOccupancy, slot_occupancy

GarageFilter = Literal["all", "now", "reservable", "free"]
WEEKDAYS = {0, 1, 2, 3, 4}


# ── 공유 조건의 시간 계산 ──────────────────────────────────────────────


def _day_start(day: date, hour: int) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=KST) + timedelta(hours=hour)


def is_offer_open(offer: ShareOffer, at: datetime) -> bool:
    """at 시각이 공유 조건의 기간·요일·시간 안인지 (Asia/Seoul)."""
    local = to_kst(at)
    day = local.date()
    return (
        offer.start_date <= day <= offer.end_date
        and day.weekday() in offer.available_weekdays
        and offer.start_hour <= local.hour < offer.end_hour
    )


def next_open_at(offer: ShareOffer, at: datetime) -> datetime | None:
    """at 이후(포함) 공유 조건으로 이용할 수 있는 가장 이른 시각. 지금 열려 있으면 at, 앞으로 없으면 None."""
    local = to_kst(at)
    if is_offer_open(offer, local):
        return local
    day = max(local.date(), offer.start_date)
    for _ in range(8):  # 요일이 한 바퀴 돌면 충분하다
        if day > offer.end_date:
            return None
        if day.weekday() in offer.available_weekdays:
            start = _day_start(day, offer.start_hour)
            if start >= local:
                return start
        day += timedelta(days=1)
    return None


def _pick_offer(offers: Iterable[ShareOffer], at: datetime) -> ShareOffer:
    """칸 하나에 걸린 공유 조건 중 가장 먼저 이용할 수 있는 것 (같으면 작은 id)."""
    far = datetime.max.replace(tzinfo=KST)
    return min(offers, key=lambda o: (next_open_at(o, at) or far, o.id))


def _hhmm(hour: int) -> str:
    return f"{hour:02d}:00"


# ── 탐색 목록 ───────────────────────────────────────────────────────


@dataclass
class GarageListEntry:
    """명세 GarageListItem 과 같은 필드 (+ 정렬용 distance)."""

    garage_id: int
    building_name: str
    slot_id: int
    slot_label: str
    title: str
    availability: str
    hourly_price: int
    info: str | None
    estimated_free_at: datetime | None
    estimate_source: ExitSource | None
    available_from: datetime | None
    max_hours: int | None
    weekdays_only: bool
    distance: float | None = None


def _availability(
    offer: ShareOffer, occupancy: SlotOccupancy, at: datetime
) -> tuple[str, datetime | None, ExitSource | None, datetime | None]:
    """(availability, estimated_free_at, estimate_source, available_from)."""
    if is_offer_open(offer, at):
        if not occupancy.occupied:
            return "AVAILABLE", None, None, None
        if occupancy.is_soon_exit(at):
            return "SOON_EXIT", occupancy.free_at, occupancy.source, None
        return "UNAVAILABLE", None, None, None
    opens = next_open_at(offer, at)
    if opens is not None:
        return "RESERVABLE", None, None, opens
    return "UNAVAILABLE", None, None, None


def _info(offer: ShareOffer, availability: str, free_at: datetime | None, opens: datetime | None, at: datetime) -> str:
    """목록 보조 문구 (예: "지금 이용 가능 · 07:00~23:00", "내일 09:00부터 이용 가능 · 무료")."""
    match availability:
        case "AVAILABLE":
            head = f"지금 이용 가능 · {_hhmm(offer.start_hour)}~{_hhmm(offer.end_hour)}"
        case "SOON_EXIT":
            head = f"{to_kst(free_at):%H:%M} 출차 예정"
        case "RESERVABLE":
            days = (opens.date() - to_kst(at).date()).days
            when = {0: "오늘", 1: "내일"}.get(days, f"{opens.month}월 {opens.day}일")
            head = f"{when} {opens:%H:%M}부터 이용 가능"
        case _:
            head = "현재 이용 불가"
    parts = [head]
    if offer.hourly_price == 0:
        parts.append("무료")
    if offer.max_hours is not None:
        parts.append(f"최대 {offer.max_hours}시간")
    if _weekdays_only(offer):
        parts.append("평일만")
    return " · ".join(parts)


def _weekdays_only(offer: ShareOffer) -> bool:
    return bool(offer.available_weekdays) and set(offer.available_weekdays) <= WEEKDAYS


def _filter_matches(entry: GarageListEntry, filter_: GarageFilter) -> bool:
    match filter_:
        case "now":
            return entry.availability == "AVAILABLE"
        case "reservable":
            return entry.availability == "RESERVABLE"
        case "free":
            return entry.hourly_price == 0
        case _:
            return True


def _offer_rows_stmt(today: date):
    """공개되고 아직 끝나지 않은 공유 조건 + 활성 칸 + 주차 구역 + 빌라."""
    return (
        select(ShareOffer, ParkingSlot, Garage, Building)
        .join(ParkingSlot, ParkingSlot.id == ShareOffer.slot_id)
        .join(Garage, Garage.id == ParkingSlot.garage_id)
        .join(Building, Building.id == Garage.building_id)
        .where(ShareOffer.is_public.is_(True), ShareOffer.end_date >= today, ParkingSlot.is_active.is_(True))
    )


async def list_garages(
    db: AsyncSession,
    user: Resident,
    *,
    lat: float | None = None,
    lng: float | None = None,
    q: str | None = None,
    filter_: GarageFilter = "all",
    cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
    now: datetime | None = None,
) -> CursorPage[GarageListEntry]:
    """GET /garages. 빌라에 소속되지 않은 사용자는 같은 골목이 없으므로 빈 목록."""
    if (lat is None) != (lng is None):
        raise InvalidInputError("lat 과 lng 는 함께 보내야 합니다.", detail={"field": "lat" if lat is None else "lng"})
    after = parse_cursor(cursor)
    at = to_kst(now or datetime.now(KST))
    alley_id = await _my_alley_id(db, user)
    if alley_id is None:
        return CursorPage()

    stmt = _offer_rows_stmt(at.date()).where(Building.alley_id == alley_id, Building.id != user.building_id)
    if q:
        stmt = stmt.where(
            or_(Building.name.icontains(q, autoescape=True), Building.address.icontains(q, autoescape=True))
        )
    use_distance = lat is not None and lng is not None
    if use_distance:
        here = cast(func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326), Geography)
        stmt = stmt.add_columns(func.ST_Distance(cast(Building.location, Geography), here))
    rows = (await db.execute(stmt)).all()

    by_slot: dict[int, list] = {}
    for row in rows:
        by_slot.setdefault(row[1].id, []).append(row)
    occupancy = await slot_occupancy(db, by_slot, at)
    labels = await slot_labels(db, by_slot)

    entries: list[GarageListEntry] = []
    for slot_id, slot_rows in by_slot.items():
        offer = _pick_offer((r[0] for r in slot_rows), at)
        building, *rest = slot_rows[0][3:]
        availability, free_at, source, opens = _availability(offer, occupancy[slot_id], at)
        label = labels[slot_id]
        entry = GarageListEntry(
            garage_id=building.id,
            building_name=building.name,
            slot_id=slot_id,
            slot_label=label,
            title=f"{building.name} · {label}",
            availability=availability,
            hourly_price=offer.hourly_price,
            info=_info(offer, availability, free_at, opens, at),
            estimated_free_at=free_at,
            estimate_source=source,
            available_from=opens,
            max_hours=offer.max_hours,
            weekdays_only=_weekdays_only(offer),
            distance=rest[0] if rest else None,
        )
        if _filter_matches(entry, filter_):
            entries.append(entry)

    if use_distance:
        entries.sort(key=lambda e: (e.distance is None, e.distance or 0.0, -e.slot_id))
    else:
        entries.sort(key=lambda e: -e.slot_id)

    if after is not None:
        index = next((i for i, e in enumerate(entries) if e.slot_id == after), None)
        if index is not None:
            entries = entries[index + 1 :]
        elif use_distance:
            entries = []  # 기준 칸이 목록에서 사라짐 → 이어서 볼 위치를 알 수 없다
        else:
            entries = [e for e in entries if e.slot_id < after]
    if len(entries) > limit:
        return CursorPage(items=entries[:limit], next_cursor=str(entries[limit - 1].slot_id))
    return CursorPage(items=entries, next_cursor=None)


# ── 차고지 상세 ─────────────────────────────────────────────────────


@dataclass
class GarageSlotEntry:
    slot_id: int
    zone: Garage
    number: int
    label: str
    state: str  # AVAILABLE / SOON_EXIT / IN_USE
    estimated_free_at: datetime | None
    in_use_until: datetime | None
    offer: ShareOffer


@dataclass
class GarageSummary:
    start_hour: int | None
    end_hour: int | None
    min_hourly_price: int | None
    max_hours: int | None


@dataclass
class GarageDetailData:
    building: Building
    alley: Alley
    summary: GarageSummary
    slots: list[GarageSlotEntry]


def _slot_state(occupancy: SlotOccupancy, at: datetime) -> tuple[str, datetime | None, datetime | None]:
    """(state, estimated_free_at, in_use_until)."""
    if not occupancy.occupied:
        return "AVAILABLE", None, None
    if occupancy.is_soon_exit(at):
        return "SOON_EXIT", occupancy.free_at, None
    return "IN_USE", None, occupancy.free_at


def summarize(offers: list[ShareOffer]) -> GarageSummary:
    """가장 이른 시작 ~ 가장 늦은 종료, 가장 싼 요금, 가장 긴 최대 이용 (하나라도 제한 없음이면 null). 칸이 없으면 모두 null."""
    if not offers:
        return GarageSummary(None, None, None, None)
    limits = [o.max_hours for o in offers]
    return GarageSummary(
        start_hour=min(o.start_hour for o in offers),
        end_hour=max(o.end_hour for o in offers),
        min_hourly_price=min(o.hourly_price for o in offers),
        max_hours=None if None in limits else max(limits),
    )


async def _my_alley_id(db: AsyncSession, user: Resident) -> int | None:
    if user.building_id is None:
        return None
    return await db.scalar(select(Building.alley_id).where(Building.id == user.building_id))


async def get_garage(db: AsyncSession, user: Resident, garage_id: int, now: datetime | None = None) -> GarageDetailData:
    """GET /garages/{garage_id}. 공유 조건이 걸린 칸만 칸마다 조건 하나와 상태를 붙인다.

    탐색 목록과 같은 범위(내 빌라와 같은 골목의 **다른** 빌라)만 볼 수 있다. 빌라가 없거나 범위 밖이면 404 NOT_FOUND.
    """
    building = await db.get(Building, garage_id)
    alley_id = await _my_alley_id(db, user)
    if building is None or alley_id is None or building.alley_id != alley_id or building.id == user.building_id:
        raise NotFoundError("차고지를 찾을 수 없습니다.")
    alley = await db.get(Alley, building.alley_id)
    at = to_kst(now or datetime.now(KST))

    rows = (await db.execute(_offer_rows_stmt(at.date()).where(Building.id == building.id))).all()
    by_slot: dict[int, list] = {}
    for row in rows:
        by_slot.setdefault(row[1].id, []).append(row)
    occupancy = await slot_occupancy(db, by_slot, at)
    labels = await building_slot_labels(db, building.id)

    slots: list[GarageSlotEntry] = []
    for slot_id, slot_rows in by_slot.items():
        offer = _pick_offer((r[0] for r in slot_rows), at)
        _, slot, zone, _ = slot_rows[0]
        state, free_at, until = _slot_state(occupancy[slot_id], at)
        slots.append(
            GarageSlotEntry(
                slot_id=slot_id,
                zone=zone,
                number=slot.number,
                label=labels[slot_id],
                state=state,
                estimated_free_at=free_at,
                in_use_until=until,
                offer=offer,
            )
        )
    slots.sort(key=lambda s: (s.zone.sort_order, s.zone.id, s.number))
    return GarageDetailData(building=building, alley=alley, summary=summarize([s.offer for s in slots]), slots=slots)
