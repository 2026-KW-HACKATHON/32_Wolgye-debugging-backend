"""FE 연결·시연용 시드 데이터 (#36). 명세 Mock 시나리오(월계 한빛빌라·햇살빌라)를 DB 에 넣는다.

    python -m app.jobs.seed_demo

- 초대코드 `HANBIT01`·`SUNNY01` 빌라나 아래 이메일 계정이 이미 있으면 아무것도 하지 않는다. 다시 넣으려면 DB 를 비우고 마이그레이션부터 다시 한다
- 계정 비밀번호는 모두 `DEMO_PASSWORD`. 가입처럼 500,000 토큰을 시스템 지급한다 (결정 6)
- 출차 시각은 실행 시각(KST) 기준으로 잡는다 (40분 뒤 = 곧 출차, 5시간 뒤)

| 계정 | 역할 |
|---|---|
| jisu@chagok.dev | 김지수 · 한빛빌라 101동 202호 입주민 · 차량 12가 3456(흰색, 대표) · 주차 안 함 |
| admin@chagok.dev | 한빛빌라 관리인 · 공유 칸 P3·P7 |
| neighbor@chagok.dev | 한빛빌라 101동 302호 · 34나 5678 (P2, 5시간 뒤 출차) |
| neighbor2@chagok.dev | 한빛빌라 102동 101호 · 56라 7890 (P4, 40분 뒤 출차 → 곧 출차) |
| sunny-admin@chagok.dev | 햇살빌라 관리인 · 공유 칸 P1~P5 |
| sunny@chagok.dev | 햇살빌라 입주민 · 123가 4634 (한빛 P3 에 외부 차량으로 주차. 수락된 공유가 없어 출차 시간 없음) |

한빛빌라 칸 P1~P8 (P8 사용 중지), 미확인 차량 45다 6789 (P6). 앞 칸: P1 → P2, P4 → P5, P7 → P8.
"""

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from geoalchemy2.elements import WKTElement
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.alley import Alley
from app.models.building import Building
from app.models.departure_schedule import DepartureSchedule
from app.models.garage import Garage, GarageType
from app.models.parking_assignment import ParkingAssignment
from app.models.parking_slot import ParkingSlot
from app.models.resident import Resident, ResidentRole
from app.models.share_offer import ShareOffer
from app.models.vehicle import Vehicle
from app.schemas.common import KST
from app.services import tokens
from app.services.auth import SIGNUP_GRANT_MEMO

DEMO_PASSWORD = "chagok1234"
HANBIT_INVITE_CODE = "HANBIT01"
SUNNY_INVITE_CODE = "SUNNY01"
EMAILS = [
    f"{name}@chagok.dev" for name in ("jisu", "admin", "neighbor", "neighbor2", "sunny-admin", "sunny")
]

# (구역 이름, 종류, 칸 수). 칸 이름은 sort_order → number 순으로 P1, P2 …
HANBIT_ZONES = [
    ("필로티 안쪽", GarageType.PILOTI_IN, 2),
    ("필로티 외부", GarageType.PILOTI_OUT, 1),
    ("건물 앞", GarageType.PILOTI_OUT, 3),
    ("골목", GarageType.ROADSIDE, 2),
]
SUNNY_ZONES = [
    ("골목", GarageType.ROADSIDE, 2),
    ("필로티 외부", GarageType.PILOTI_OUT, 2),
    ("건물 앞", GarageType.PILOTI_OUT, 1),
]
# 명세 Mock 공유 조건: 07~23시, 시간당 2토큰, 최대 4시간
OFFER_TERMS = {"start_hour": 7, "end_hour": 23, "hourly_price": 2, "max_hours": 4}


@dataclass
class SeedResult:
    created: bool
    reason: str | None = None  # 건너뛴 이유
    hanbit_id: int | None = None
    sunny_id: int | None = None


async def _add[T](db: AsyncSession, obj: T) -> T:
    db.add(obj)
    await db.flush()
    return obj


async def _building(
    db: AsyncSession, alley: Alley, name: str, address: str, invite_code: str, lng: float, lat: float, zones: list
) -> tuple[Building, dict[str, ParkingSlot]]:
    building = await _add(
        db,
        Building(
            alley_id=alley.id,
            name=name,
            address=address,
            invite_code=invite_code,
            location=WKTElement(f"POINT({lng} {lat})", srid=4326),
        ),
    )
    slots: dict[str, ParkingSlot] = {}
    ordinal = 0
    for sort_order, (zone_name, garage_type, count) in enumerate(zones):
        garage = await _add(
            db, Garage(building_id=building.id, name=zone_name, garage_type=garage_type, sort_order=sort_order)
        )
        for number in range(1, count + 1):
            ordinal += 1
            x = 3.0 * sort_order
            y = 5.0 * (number - 1)
            slots[f"P{ordinal}"] = await _add(
                db,
                ParkingSlot(
                    garage_id=garage.id, number=number, render_x0=x, render_y0=y, render_x1=x + 2.5, render_y1=y + 5.0
                ),
            )
    return building, slots


async def _resident(
    db: AsyncSession,
    email: str,
    nickname: str,
    building: Building,
    name: str,
    unit_no: str | None = None,
    role: ResidentRole = ResidentRole.RESIDENT,
) -> Resident:
    resident = await _add(
        db,
        Resident(
            email=email,
            password_hash=hash_password(DEMO_PASSWORD),
            nickname=nickname,
            name=name,
            unit_no=unit_no,
            building_id=building.id,
            role=role,
        ),
    )
    await tokens.transfer(
        db, sender_id=None, receiver_id=resident.id, amount=get_settings().signup_token_grant, memo=SIGNUP_GRANT_MEMO
    )
    return resident


async def _park(
    db: AsyncSession, slot: ParkingSlot, vehicle: Vehicle, now: datetime, exit_at: datetime | None = None
) -> None:
    """주차 중인 배치. exit_at 이 있으면 그 시각에 출차 일정을 넣고, 없으면 상시 주차로 둔다."""
    db.add(
        ParkingAssignment(
            slot_id=slot.id, vehicle_id=vehicle.id, assigned_at=now - timedelta(hours=3), is_permanent=exit_at is None
        )
    )
    if exit_at is not None:
        local = exit_at.astimezone(KST)
        db.add(DepartureSchedule(vehicle_id=vehicle.id, scheduled_date=local.date(), scheduled_time=local.time()))
    await db.flush()


def _offer(slot: ParkingSlot, host: Resident, today: date) -> ShareOffer:
    return ShareOffer(
        slot_id=slot.id, host_id=host.id, start_date=today, end_date=today + timedelta(days=365), **OFFER_TERMS
    )


async def seed(db: AsyncSession, now: datetime | None = None) -> SeedResult:
    """시드 데이터를 넣고 커밋한다. 시드 빌라나 계정이 이미 있으면 아무것도 하지 않는다."""
    codes = (HANBIT_INVITE_CODE, SUNNY_INVITE_CODE)
    if await db.scalar(select(Building.id).where(Building.invite_code.in_(codes)).limit(1)) is not None:
        return SeedResult(created=False, reason=f"초대코드 {'/'.join(codes)} 빌라가 이미 있습니다.")
    taken = (await db.scalars(select(Resident.email).where(Resident.email.in_(EMAILS)))).all()
    if taken:
        return SeedResult(created=False, reason=f"이미 있는 계정: {', '.join(taken)}")

    now = (now or datetime.now(KST)).replace(second=0, microsecond=0)
    today = now.astimezone(KST).date()

    alley = await _add(db, Alley(name="광운로19가길"))
    hanbit, hp = await _building(
        db, alley, "월계 한빛빌라", "서울 노원구 광운로19가길 12", HANBIT_INVITE_CODE, 127.0590, 37.6195, HANBIT_ZONES
    )
    sunny, sp = await _building(
        db, alley, "햇살빌라", "서울 노원구 광운로19가길 20", SUNNY_INVITE_CODE, 127.0596, 37.6199, SUNNY_ZONES
    )
    for inner, outer in (("P1", "P2"), ("P4", "P5"), ("P7", "P8")):
        hp[inner].front_slot_id = hp[outer].id
    hp["P8"].is_active = False

    jisu = await _resident(db, "jisu@chagok.dev", "지수", hanbit, "김지수", "101동 202호")
    admin = await _resident(db, "admin@chagok.dev", "한빛관리인", hanbit, "박관리", role=ResidentRole.MANAGER)
    neighbor = await _resident(db, "neighbor@chagok.dev", "이웃302", hanbit, "이웃일", "101동 302호")
    neighbor2 = await _resident(db, "neighbor2@chagok.dev", "이웃101", hanbit, "이웃둘", "102동 101호")
    sunny_admin = await _resident(
        db, "sunny-admin@chagok.dev", "햇살관리인", sunny, "최햇살", role=ResidentRole.MANAGER
    )
    sunny_resident = await _resident(db, "sunny@chagok.dev", "햇살주민", sunny, "정햇살", "1동 201호")

    await _add(db, Vehicle(plate_no="12가 3456", owner_id=jisu.id, color="흰색", nickname="내 차", is_primary=True))
    neighbor_car = await _add(db, Vehicle(plate_no="34나 5678", owner_id=neighbor.id, color="검정", is_primary=True))
    neighbor2_car = await _add(db, Vehicle(plate_no="56라 7890", owner_id=neighbor2.id, color="은색", is_primary=True))
    external_car = await _add(
        db, Vehicle(plate_no="123가 4634", owner_id=sunny_resident.id, color="회색", is_primary=True)
    )
    unknown_car = await _add(db, Vehicle(plate_no="45다 6789"))  # 관리인이 등록한 미확인 차량

    await _park(db, hp["P2"], neighbor_car, now, exit_at=now + timedelta(hours=5))
    # 외부 차량의 출차 시간은 수락된 공유의 끝 시각이라 출차 일정을 넣지 않는다 (services/blocking.occupants)
    await _park(db, hp["P3"], external_car, now, exit_at=None)
    await _park(db, hp["P4"], neighbor2_car, now, exit_at=now + timedelta(minutes=40))
    await _park(db, hp["P6"], unknown_car, now, exit_at=None)

    db.add_all([_offer(hp[label], admin, today) for label in ("P3", "P7")])
    db.add_all([_offer(slot, sunny_admin, today) for slot in sp.values()])

    await db.commit()
    return SeedResult(created=True, hanbit_id=hanbit.id, sunny_id=sunny.id)


async def main() -> None:
    async with AsyncSessionLocal() as db:
        result = await seed(db)
    if not result.created:
        print(f"시드를 건너뜁니다. {result.reason}")
        return
    print(f"시드 완료: 월계 한빛빌라(id={result.hanbit_id}, {HANBIT_INVITE_CODE}), 햇살빌라(id={result.sunny_id})")
    print(f"계정 비밀번호는 모두 {DEMO_PASSWORD} 입니다. 계정 목록은 app/jobs/seed_demo.py 맨 위 설명을 보세요.")


if __name__ == "__main__":
    asyncio.run(main())
