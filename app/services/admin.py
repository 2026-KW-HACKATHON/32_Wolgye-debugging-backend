"""관리인 대시보드·칸 설정·미확인 차량 (#14). 권한(빌라 관리인)은 경로에 building_id 가 있으면 엔드포인트의
BuildingAdmin 의존성이, 없으면(칸 설정) 이 모듈이 ensure_building_admin 으로 확인한다.

- 막힘 판정(services/blocking)은 쓰지 않는다 (명세 대시보드·칸 목록 응답에 막힘 정보가 없음).
- 날짜·시각은 Asia/Seoul 기준.
"""

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import ErrorCode
from app.core.plates import format_plate
from app.models.building import Building
from app.models.garage import Garage
from app.models.parking_assignment import ParkingAssignment
from app.models.parking_slot import ParkingSlot
from app.models.resident import Resident
from app.models.share_offer import ShareOffer
from app.models.share_request import ShareRequest, ShareRequestStatus
from app.models.vehicle import Vehicle
from app.schemas.admin import (
    AdminDashboard,
    AdminSlot,
    AdminSlotUpdate,
    BuildingRef,
    Congestion,
    CongestionDay,
    MaskedRequester,
    OccupantType,
    PendingRequestItem,
    Realtime,
    RealtimeVehicle,
    UnknownVehicleCreate,
    UnknownVehicleCreated,
)
from app.services.exceptions import ConflictError, InvalidInputError, NotFoundError
from app.services.permissions import ensure_building_admin
from app.services.slot_labels import building_slot_labels, slot_labels

KST = ZoneInfo("Asia/Seoul")
MASK_CHAR = "○"


# ── 표시 규칙 ──────────────────────────────────────────────────────────
def mask_name(name: str) -> str:
    """첫 글자만 남기고 나머지를 ○ 로. "박민준" → "박○○", "홍" → "홍"."""
    name = name.strip()
    return name[:1] + MASK_CHAR * (len(name) - 1) if name else ""


def occupant_type(owner: Resident | None, building_id: int) -> OccupantType:
    """차 주인이 없으면 미확인, 이 빌라 소속이면 입주민, 아니면 외부(공유 이용자)."""
    if owner is None:
        return OccupantType.UNKNOWN
    return OccupantType.RESIDENT if owner.building_id == building_id else OccupantType.EXTERNAL


# ── 혼잡도 ────────────────────────────────────────────────────────────
def parse_month(month: str | None, now: datetime) -> tuple[int, int]:
    """"YYYY-MM" → (year, month). 없으면 now(KST)의 달. 월이 1~12 가 아니면 400 INVALID_INPUT."""
    if month is None:
        local = now.astimezone(KST)
        return local.year, local.month
    year_str, month_str = month.split("-")
    year, mon = int(year_str), int(month_str)
    if not 1 <= mon <= 12 or year < 1:
        raise InvalidInputError(detail={"field": "month", "reason": "YYYY-MM 형식의 올바른 월이어야 합니다."})
    return year, mon


def _month_days(year: int, month: int) -> list[date]:
    first = date(year, month, 1)
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return [first + timedelta(days=i) for i in range((nxt - first).days)]


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=KST)
    return start, datetime.combine(day + timedelta(days=1), time.min, tzinfo=KST)


def peak_overlap(intervals: Iterable[tuple[datetime, datetime]], start: datetime, end: datetime) -> int:
    """[start, end) 안에서 동시에 겹치는 구간 수의 최댓값. 구간은 [시작, 끝) — 한 차가 나간 순간 다른 차가 들어오면 겹치지 않는다."""
    events: list[tuple[datetime, int]] = []
    for s, e in intervals:
        s, e = max(s, start), min(e, end)
        if s < e:
            events.append((s, 1))
            events.append((e, -1))
    events.sort()  # 같은 시각이면 -1(나감)이 +1(들어옴)보다 먼저
    peak = current = 0
    for _, delta in events:
        current += delta
        peak = max(peak, current)
    return peak


def daily_peaks(
    intervals: list[tuple[datetime, datetime]], year: int, month: int, until: date | None = None
) -> list[CongestionDay]:
    """year-month 의 날짜(KST)마다 peak_occupied. until 이 있으면 그 날짜까지만 (지난달 = 전체, 이번 달 = 오늘까지, 미래 달 = [])."""
    days = [day for day in _month_days(year, month) if until is None or day <= until]
    return [CongestionDay(date=day, peak_occupied=peak_overlap(intervals, *_day_bounds(day))) for day in days]


async def _congestion(db: AsyncSession, building_id: int, year: int, month: int, now: datetime) -> Congestion:
    total_slots = await db.scalar(
        select(func.count(ParkingSlot.id)).join(Garage).where(Garage.building_id == building_id)
    )
    today = now.astimezone(KST).date()
    label = f"{year:04d}-{month:02d}"
    days = [day for day in _month_days(year, month) if day <= today]
    if not days:  # 미래 달
        return Congestion(month=label, total_slots=total_slots or 0, days=[])
    month_start, _ = _day_bounds(days[0])
    _, month_end = _day_bounds(days[-1])
    rows = await db.execute(
        select(ParkingAssignment.assigned_at, ParkingAssignment.released_at)
        .join(ParkingSlot, ParkingSlot.id == ParkingAssignment.slot_id)
        .join(Garage, Garage.id == ParkingSlot.garage_id)
        .where(
            Garage.building_id == building_id,
            ParkingAssignment.assigned_at < month_end,
            (ParkingAssignment.released_at.is_(None)) | (ParkingAssignment.released_at > month_start),
        )
    )
    # 아직 주차 중인 차는 지금까지만 점유한 것으로 본다
    intervals = [(assigned, released or now) for assigned, released in rows.all()]
    return Congestion(month=label, total_slots=total_slots or 0, days=daily_peaks(intervals, year, month, until=today))


# ── 대시보드 ──────────────────────────────────────────────────────────
async def _pending_requests(db: AsyncSession, building_id: int) -> list[PendingRequestItem]:
    rows = await db.execute(
        select(ShareRequest, Resident)
        .join(Resident, Resident.id == ShareRequest.requester_id)
        .join(ParkingSlot, ParkingSlot.id == ShareRequest.slot_id)
        .join(Garage, Garage.id == ParkingSlot.garage_id)
        .where(Garage.building_id == building_id, ShareRequest.status == ShareRequestStatus.PENDING)
        .order_by(ShareRequest.created_at.desc(), ShareRequest.id.desc())
    )
    rows = rows.all()
    labels = await slot_labels(db, {req.slot_id for req, _ in rows})
    return [
        PendingRequestItem(
            id=req.id,
            requester=MaskedRequester(
                name=mask_name(requester.name or requester.nickname), temperature=requester.manner_temperature
            ),
            slot_label=labels[req.slot_id],
            request_date=req.request_date,
            start_hour=req.start_hour,
            end_hour=req.end_hour,
            total_price=req.total_price,
            created_at=req.created_at.astimezone(KST),
        )
        for req, requester in rows
    ]


async def _realtime(db: AsyncSession, building_id: int, now: datetime) -> Realtime:
    """주차 중인 차(활성 배치) + 지금 이용 시간인 수락된 공유(그 칸에 배치가 없을 때) 중 외부·미확인 차량."""
    labels = await building_slot_labels(db, building_id)  # 칸 순번 순서
    slots = {
        slot.id: slot for slot in (await db.scalars(select(ParkingSlot).where(ParkingSlot.id.in_(labels)))).all()
    }
    order = {slot_id: i for i, slot_id in enumerate(labels)}

    # (slot_id → (vehicle, owner))
    occupants: dict[int, tuple[Vehicle, Resident | None]] = {}
    assigned = await db.execute(
        select(ParkingAssignment.slot_id, Vehicle, Resident)
        .join(Vehicle, Vehicle.id == ParkingAssignment.vehicle_id)
        .outerjoin(Resident, Resident.id == Vehicle.owner_id)
        .where(ParkingAssignment.is_active, ParkingAssignment.slot_id.in_(labels.keys()))
    )
    for slot_id, vehicle, owner in assigned.all():
        occupants[slot_id] = (vehicle, owner)

    local = now.astimezone(KST)
    shared = await db.execute(
        select(ShareRequest.slot_id, Vehicle, Resident)
        .join(Vehicle, Vehicle.id == ShareRequest.vehicle_id)
        .outerjoin(Resident, Resident.id == Vehicle.owner_id)
        .where(
            ShareRequest.status == ShareRequestStatus.ACCEPTED,
            ShareRequest.slot_id.in_(labels.keys()),
            ShareRequest.request_date == local.date(),
            ShareRequest.start_hour <= local.hour,
            ShareRequest.end_hour > local.hour,
        )
    )
    for slot_id, vehicle, owner in shared.all():
        occupants.setdefault(slot_id, (vehicle, owner))

    vehicles = []
    for slot_id in sorted(occupants, key=order.__getitem__):
        vehicle, owner = occupants[slot_id]
        kind = occupant_type(owner, building_id)
        if kind == OccupantType.RESIDENT:  # 관리 구역 실시간은 외부·미확인 차량만 (입주민 차는 빈 칸 계산에만 반영)
            continue
        vehicles.append(
            RealtimeVehicle(
                slot_id=slot_id,
                slot_label=labels[slot_id],
                plate=format_plate(vehicle.plate_no),
                occupant_type=kind,
                can_request_move=kind != OccupantType.UNKNOWN,  # 미확인 차량은 앱으로 연락 불가
            )
        )
    available = sum(1 for slot in slots.values() if slot.is_active and slot.id not in occupants)
    return Realtime(available_count=available, vehicles=vehicles)


async def get_dashboard(
    db: AsyncSession, building_id: int, month: str | None = None, now: datetime | None = None
) -> AdminDashboard:
    now = now or datetime.now(KST)
    year, mon = parse_month(month, now)
    building = await db.get(Building, building_id)
    if building is None:
        raise NotFoundError("빌라를 찾을 수 없습니다.")
    return AdminDashboard(
        building=BuildingRef(id=building.id, name=building.name),
        pending_requests=await _pending_requests(db, building_id),
        realtime=await _realtime(db, building_id, now),
        congestion=await _congestion(db, building_id, year, mon, now),
        ai_insight=None,
    )


# ── 칸 목록·설정 ───────────────────────────────────────────────────────
async def _to_admin_slots(db: AsyncSession, slots: list[ParkingSlot], today: date) -> list[AdminSlot]:
    ids = [slot.id for slot in slots]
    labels = await slot_labels(db, ids)
    occupied = set(
        (await db.scalars(select(ParkingAssignment.slot_id).where(ParkingAssignment.is_active, ParkingAssignment.slot_id.in_(ids)))).all()
    )
    # 지금 적용되는 공유 조건: 공개 중이고 오늘이 기간 안. 여러 개면 가장 최근(id 큰) 것
    offers: dict[int, int] = {}
    offer_rows = await db.execute(
        select(ShareOffer.slot_id, ShareOffer.id)
        .where(
            ShareOffer.slot_id.in_(ids),
            ShareOffer.is_public,
            ShareOffer.start_date <= today,
            ShareOffer.end_date >= today,
        )
        .order_by(ShareOffer.id)
    )
    for slot_id, offer_id in offer_rows.all():
        offers[slot_id] = offer_id
    return [
        AdminSlot(
            slot_id=slot.id,
            zone_id=slot.garage_id,
            number=slot.number,
            label=labels[slot.id],
            is_active=slot.is_active,
            occupied=slot.id in occupied,
            share_offer_id=offers.get(slot.id),
        )
        for slot in slots
    ]


async def list_slots(db: AsyncSession, building_id: int, now: datetime | None = None) -> list[AdminSlot]:
    today = (now or datetime.now(KST)).astimezone(KST).date()
    slots = (
        await db.scalars(
            select(ParkingSlot)
            .join(Garage, Garage.id == ParkingSlot.garage_id)
            .where(Garage.building_id == building_id)
            .order_by(Garage.sort_order, Garage.id, ParkingSlot.number)
        )
    ).all()
    return await _to_admin_slots(db, list(slots), today)


async def update_slot(db: AsyncSession, user: Resident, slot_id: int, payload: AdminSlotUpdate) -> AdminSlot:
    """칸 설정 (is_active 만). 칸이 없으면 404, 그 칸 빌라의 관리인이 아니면 403."""
    row = (
        await db.execute(
            select(ParkingSlot, Garage).join(Garage, Garage.id == ParkingSlot.garage_id).where(ParkingSlot.id == slot_id)
        )
    ).first()
    if row is None:
        raise NotFoundError("칸을 찾을 수 없습니다.")
    slot, garage = row
    ensure_building_admin(user, garage.building_id)

    if payload.is_active is not None:
        slot.is_active = payload.is_active
        await db.commit()
        await db.refresh(slot)
    today = datetime.now(KST).date()
    return (await _to_admin_slots(db, [slot], today))[0]


# ── 미확인 차량 ───────────────────────────────────────────────────────
async def register_unknown_vehicle(
    db: AsyncSession, building_id: int, payload: UnknownVehicleCreate
) -> UnknownVehicleCreated:
    """번호판만으로 주인 없는 차(owner_id NULL)를 만들고 칸에 배치한다. 규칙은 place_unknown_vehicle."""
    assignment = await place_unknown_vehicle(db, building_id, payload.slot_id, payload.plate)
    await db.commit()
    return UnknownVehicleCreated(
        parking_id=assignment.id, vehicle_id=assignment.vehicle_id, occupant_type=OccupantType.UNKNOWN
    )


async def place_unknown_vehicle(db: AsyncSession, building_id: int, slot_id: int, plate: str) -> ParkingAssignment:
    """주인 없는 차(owner_id NULL)를 칸에 배치하고 flush 한다. **commit 하지 않는다** (관리인 등록·미등록 차량 제보 #52 공용).

    - 칸이 이 빌라에 없으면 404, 비활성 칸이면 409 SLOT_UNAVAILABLE, 이미 차가 있으면 409 SLOT_OCCUPIED
    - 같은 번호판의 미확인 차량이 이미 있으면 그 차를 다시 쓴다 (주인 있는 차면 409 PLATE_EXISTS)
    - 그 미확인 차량이 다른 칸에 주차 중이면 409 VEHICLE_ALREADY_PARKED
    plate 는 공백 없는 값 (PlateIn·normalize_plate).
    """
    slot = await db.scalar(
        select(ParkingSlot)
        .join(Garage, Garage.id == ParkingSlot.garage_id)
        .where(ParkingSlot.id == slot_id, Garage.building_id == building_id)
        .with_for_update(of=ParkingSlot)
    )
    if slot is None:
        raise NotFoundError("칸을 찾을 수 없습니다.")
    if not slot.is_active:
        raise ConflictError("사용할 수 없는 칸입니다.", code=ErrorCode.SLOT_UNAVAILABLE)
    occupied = await db.scalar(
        select(ParkingAssignment.id).where(ParkingAssignment.slot_id == slot.id, ParkingAssignment.is_active)
    )
    if occupied is not None:
        raise ConflictError("이미 다른 차량이 주차 중인 칸입니다.", code=ErrorCode.SLOT_OCCUPIED)

    vehicle = await db.scalar(select(Vehicle).where(Vehicle.plate_no == plate))
    if vehicle is None:
        vehicle = Vehicle(plate_no=plate, owner_id=None)
        db.add(vehicle)
        await db.flush()
    elif vehicle.owner_id is not None:
        raise ConflictError("이미 등록된 차량 번호입니다.", code=ErrorCode.PLATE_EXISTS)
    else:
        parked = await db.scalar(
            select(ParkingAssignment.id).where(ParkingAssignment.vehicle_id == vehicle.id, ParkingAssignment.is_active)
        )
        if parked is not None:
            raise ConflictError(
                "이미 다른 칸에 주차 중인 차량입니다.", code=ErrorCode.VEHICLE_ALREADY_PARKED, detail={"parking_id": parked}
            )

    # 동시에 같은 차를 배치하면 uq_active_assignment_vehicle → 409 VEHICLE_ALREADY_PARKED (전역 핸들러)
    assignment = ParkingAssignment(slot_id=slot.id, vehicle_id=vehicle.id)
    db.add(assignment)
    await db.flush()
    return assignment
