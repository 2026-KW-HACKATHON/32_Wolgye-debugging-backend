"""#14 관리인 대시보드 규칙: 혼잡도(날짜별 최대 동시 점유), 이름 마스킹, 입주민·외부·미확인 구분."""

from datetime import date, datetime

import pytest

from app.models.garage import Garage, GarageType
from app.models.parking_assignment import ParkingAssignment
from app.models.resident import ResidentRole
from app.models.share_request import ShareRequestStatus
from app.schemas.admin import OccupantType
from app.services import admin as admin_service
from app.services.admin import KST, daily_peaks, mask_name, peak_overlap
from app.services.exceptions import InvalidInputError
from tests.factories import (
    make_building,
    make_garage,
    make_resident,
    make_share_offer,
    make_share_request,
    make_slot,
    make_vehicle,
)

pytestmark = pytest.mark.anyio


def kst(*args: int) -> datetime:
    return datetime(*args, tzinfo=KST)


# ── 순수 함수 ──
def test_mask_name():
    assert mask_name("박민준") == "박○○"
    assert mask_name("홍길") == "홍○"
    assert mask_name("홍") == "홍"


def test_peak_overlap_counts_simultaneous_intervals():
    day = (kst(2026, 9, 1), kst(2026, 9, 2))
    intervals = [
        (kst(2026, 9, 1, 8), kst(2026, 9, 1, 12)),
        (kst(2026, 9, 1, 9), kst(2026, 9, 1, 10)),
        (kst(2026, 9, 1, 11), kst(2026, 9, 1, 13)),
    ]
    assert peak_overlap(intervals, *day) == 2


def test_peak_overlap_back_to_back_does_not_overlap():
    day = (kst(2026, 9, 1), kst(2026, 9, 2))
    intervals = [(kst(2026, 9, 1, 8), kst(2026, 9, 1, 10)), (kst(2026, 9, 1, 10), kst(2026, 9, 1, 12))]
    assert peak_overlap(intervals, *day) == 1


def test_daily_peaks_uses_kst_dates_and_spans_days():
    # KST 9/1 23:00 ~ 9/3 01:00 → 9/1·9/2·9/3 모두 점유. UTC 로 주어도 KST 날짜로 나뉜다
    long_stay = (datetime.fromisoformat("2026-09-01T14:00:00+00:00"), kst(2026, 9, 3, 1))
    short = (kst(2026, 9, 2, 9), kst(2026, 9, 2, 10))
    days = {d.date: d.peak_occupied for d in daily_peaks([long_stay, short], 2026, 9)}
    assert len(days) == 30
    assert days[date(2026, 9, 1)] == 1
    assert days[date(2026, 9, 2)] == 2
    assert days[date(2026, 9, 3)] == 1
    assert days[date(2026, 9, 4)] == 0


def test_parse_month_rejects_invalid_month():
    with pytest.raises(InvalidInputError):
        admin_service.parse_month("2026-13", kst(2026, 9, 30))
    assert admin_service.parse_month(None, kst(2026, 9, 30, 23)) == (2026, 9)


# ── DB ──
async def test_dashboard_congestion_realtime_and_pending(db):
    building = await make_building(db)
    other_building = await make_building(db, invite_code="INV002", name="햇살빌라")
    garage = await make_garage(db, building, name="필로티 안쪽")
    road = Garage(building_id=building.id, name="골목", garage_type=GarageType.ROADSIDE, sort_order=1)
    db.add(road)
    await db.commit()
    s1, s2 = await make_slot(db, garage, 1), await make_slot(db, garage, 2)
    s3, s4 = await make_slot(db, road, 1), await make_slot(db, road, 2)

    admin = await make_resident(db, "admin@example.com", building, role=ResidentRole.MANAGER)
    neighbor = await make_resident(db, "nb@example.com", building)
    outsider = await make_resident(db, "out@example.com", other_building)
    outsider.name = "박민준"
    outsider.manner_temperature = 38.5
    await db.commit()

    v_res = await make_vehicle(db, "12가3456", neighbor)
    v_ext = await make_vehicle(db, "123가4634", outsider)
    v_unknown = await make_vehicle(db, "45다6789", None)

    now = kst(2026, 10, 2, 14, 40)
    db.add_all(
        [
            # 지금 주차 중: 입주민(s1), 미확인(s2)
            ParkingAssignment(slot_id=s1.id, vehicle_id=v_res.id, assigned_at=kst(2026, 10, 2, 8)),
            ParkingAssignment(slot_id=s2.id, vehicle_id=v_unknown.id, assigned_at=kst(2026, 10, 1, 20)),
            # 지난 기록: 10/1 10~12 시에 외부 차
            ParkingAssignment(
                slot_id=s3.id,
                vehicle_id=v_ext.id,
                assigned_at=kst(2026, 10, 1, 10),
                released_at=kst(2026, 10, 1, 12),
                is_active=False,
            ),
        ]
    )
    await db.commit()

    # 공유: s3 에 수락된 오늘 13~17 시(지금 이용 중) → 외부 차로 보임, s4 에 대기 요청
    offer3 = await make_share_offer(db, s3, admin)
    accepted = await make_share_request(db, offer3, outsider, ShareRequestStatus.ACCEPTED, start_hour=13, end_hour=17)
    accepted.vehicle_id = v_ext.id
    await db.commit()
    offer4 = await make_share_offer(db, s4, admin, hourly_price=2)
    pending = await make_share_request(db, offer4, outsider, start_hour=7, end_hour=11)

    dash = await admin_service.get_dashboard(db, building.id, "2026-10", now=now)

    assert dash.building.name == "월계빌라"
    assert dash.ai_insight is None
    assert [p.id for p in dash.pending_requests] == [pending.id]
    item = dash.pending_requests[0]
    assert item.requester.name == "박○○"
    assert item.requester.temperature == 38.5
    assert item.slot_label == "P4"  # 필로티 안쪽 1·2 → P1·P2, 골목 1·2 → P3·P4
    assert item.total_price == 8

    vehicles = {v.slot_id: v for v in dash.realtime.vehicles}
    # 입주민 차(s1)는 빼고 외부·미확인만
    assert [v.slot_id for v in dash.realtime.vehicles] == [s2.id, s3.id]
    assert vehicles[s2.id].occupant_type == OccupantType.UNKNOWN
    assert vehicles[s2.id].can_request_move is False
    assert vehicles[s2.id].plate == "45다 6789"
    assert vehicles[s3.id].occupant_type == OccupantType.EXTERNAL
    assert vehicles[s3.id].slot_label == "P3"
    # 주차 중인 미확인 차(s2) vs 공유 예약만 있고 아직 주차 안 한 외부 차(s3) (#53)
    assert (vehicles[s2.id].parked, vehicles[s2.id].share) == (True, None)
    assert vehicles[s3.id].parked is False
    assert (vehicles[s3.id].share.start_hour, vehicles[s3.id].share.end_hour) == (13, 17)
    assert vehicles[s3.id].can_request_move is False  # 옮길 차가 아직 없다
    assert vehicles[s3.id].plate == "123가 4634"
    assert dash.realtime.available_count == 1  # s4

    peaks = {d.date: d.peak_occupied for d in dash.congestion.days}
    assert dash.congestion.month == "2026-10"
    assert dash.congestion.total_slots == 4
    assert list(peaks) == [date(2026, 10, 1), date(2026, 10, 2)]  # 이번 달은 오늘(KST)까지
    assert peaks[date(2026, 10, 1)] == 1  # 10~12 시 외부 차, 20 시부터 미확인 차 → 겹치지 않음
    assert peaks[date(2026, 10, 2)] == 2  # 미확인 + 입주민

    past = await admin_service.get_dashboard(db, building.id, "2026-09", now=now)
    assert past.congestion.month == "2026-09"
    assert len(past.congestion.days) == 30  # 지난달은 전체
    current = await admin_service.get_dashboard(db, building.id, None, now=now)
    assert current.congestion.month == "2026-10"  # month 생략 → 이번 달(KST)
    future = await admin_service.get_dashboard(db, building.id, "2026-11", now=now)
    assert future.congestion.month == "2026-11"
    assert future.congestion.days == []  # 미래 달
