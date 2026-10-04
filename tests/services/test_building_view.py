"""#9 배치도·실시간 현황·배치 추천·홈 서비스. 명세 예시의 빌라 3 (P1~P8) 로 확인한다."""

from datetime import date, datetime, time

import pytest

from app.core.error_codes import ErrorCode
from app.models.notification import NotificationType
from app.models.resident import ResidentRole
from app.models.share_request import ShareRequestStatus
from app.schemas.admin import OccupantType
from app.schemas.building_view import SlotState, SlotTag
from app.schemas.common import KST
from app.schemas.my_vehicle import ExitSource
from app.services import building_view, home, notifications, recommendations
from app.services.exceptions import ForbiddenError, InvalidInputError, NotFoundError
from tests.factories import make_resident, make_share_offer, make_share_request, make_vehicle
from tests.factories_parking import make_assignment, make_departure, make_spec_building

pytestmark = pytest.mark.anyio

# 2026-09-30 은 수요일
TODAY = date(2026, 9, 30)
NOW = datetime(2026, 9, 30, 14, 40, tzinfo=KST)


def _at(hour: int, minute: int = 0, day: int = 30, month: int = 9) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=KST)


@pytest.fixture
async def villa(db):
    """명세 예시 상태: P1(내 차 18:30)·P2(이웃 21:00)·P3(외부 17:00)·P4(15:10 반복)·P6(미확인) 주차, P5 사용 중지, P7·P8 빈칸."""
    v = await make_spec_building(db)
    building = v["building"]
    v["me"] = await make_resident(db, "me@example.com", building)
    v["neighbor"] = await make_resident(db, "neighbor@example.com", building)
    v["manager"] = await make_resident(db, "manager@example.com", building, role=ResidentRole.MANAGER)
    v["visitor"] = await make_resident(db, "visitor@example.com")
    v["my_car"] = await make_vehicle(db, "12가3456", owner=v["me"])
    neighbor_car = await make_vehicle(db, "34나5678", owner=v["neighbor"])
    soon_car = await make_vehicle(db, "27가4821", owner=v["neighbor"])
    visitor_car = await make_vehicle(db, "123가4634", owner=v["visitor"])
    unknown_car = await make_vehicle(db, "45다6789")

    v["my_parking"] = await make_assignment(db, v["P1"], v["my_car"], assigned_at=_at(8, 30))
    v["neighbor_parking"] = await make_assignment(db, v["P2"], neighbor_car)
    await make_assignment(db, v["P3"], visitor_car)
    await make_assignment(db, v["P4"], soon_car)
    await make_assignment(db, v["P6"], unknown_car)
    await make_departure(db, v["my_car"], TODAY, time(18, 30))
    await make_departure(db, neighbor_car, TODAY, time(21, 0))
    await make_departure(db, soon_car, date(2026, 9, 1), time(15, 10), repeat_weekdays=[0, 1, 2, 3, 4])

    offer = await make_share_offer(db, v["P3"], v["manager"])
    share = await make_share_request(db, offer, v["visitor"], ShareRequestStatus.ACCEPTED, start_hour=13, end_hour=17)
    share.request_date = TODAY
    await db.commit()
    return v


# ── 배치도 ──
async def test_layout(db, villa):
    layout = await building_view.get_layout(db, villa["building"].id)

    assert (layout.building_id, layout.name, layout.alley.name) == (villa["building"].id, "월계 한빛빌라", "광운로19가길")
    assert [(z.name, z.zone_type, z.sort_order) for z in layout.zones] == [
        ("필로티 안쪽", "PILOTI_IN", 0),
        ("필로티 외부", "PILOTI_OUT", 1),
        ("건물 앞", "PILOTI_OUT", 2),
        ("골목", "ROADSIDE", 3),
    ]
    slots = [slot for zone in layout.zones for slot in zone.slots]
    assert [s.label for s in slots] == [f"P{i}" for i in range(1, 9)]
    assert [s.number for s in slots] == [1, 2, 1, 1, 2, 3, 1, 2]
    p1, p5 = slots[0], slots[4]
    assert (p1.front_slot_id, p1.is_active) == (villa["P2"].id, True)
    assert (p1.rect.x0, p1.rect.y0, p1.rect.x1, p1.rect.y1) == (1.0, 0.0, 3.5, 5.0)
    assert (p5.front_slot_id, p5.is_active) == (None, False)


async def test_layout_rect_is_null_without_coordinates(db, villa):
    villa["P8"].render_x1 = None
    await db.commit()
    layout = await building_view.get_layout(db, villa["building"].id)
    assert layout.zones[-1].slots[-1].rect is None


async def test_layout_unknown_building(db):
    with pytest.raises(NotFoundError):
        await building_view.get_layout(db, 99999)


# ── 실시간 현황 ──
async def test_status_matches_spec_example(db, villa):
    status = await building_view.get_status(db, villa["me"], villa["building"].id, now=NOW)
    by_label = dict(zip([f"P{i}" for i in range(1, 9)], status.slots, strict=True))

    assert status.updated_at == NOW
    assert [s.slot_id for s in status.slots] == [villa[f"P{i}"].id for i in range(1, 9)]  # 칸 이름 순
    assert [s.state for s in status.slots] == [
        SlotState.OCCUPIED,
        SlotState.OCCUPIED,
        SlotState.OCCUPIED,
        SlotState.SOON_EXIT,  # 15:10 출차 → 1시간 이내
        SlotState.UNAVAILABLE,
        SlotState.OCCUPIED,
        SlotState.EMPTY,
        SlotState.EMPTY,
    ]

    p1 = by_label["P1"]
    assert (p1.parking.id, p1.parking.is_mine, p1.parking.occupant_type) == (
        villa["my_parking"].id,
        True,
        OccupantType.RESIDENT,
    )
    assert (p1.parking.expected_exit_at, p1.parking.exit_source) == (_at(18, 30), ExitSource.MANUAL)
    assert (p1.blocked_by, p1.blocking) == ([villa["P2"].id], [])  # 앞 칸 차(21:00)가 더 늦게 나간다

    p2 = by_label["P2"]
    assert (p2.parking.is_mine, p2.blocked_by, p2.blocking) == (False, [], [villa["P1"].id])

    p3 = by_label["P3"]  # 외부 차량: 수락된 공유의 종료 시각
    assert (p3.parking.occupant_type, p3.parking.expected_exit_at, p3.parking.exit_source) == (
        OccupantType.EXTERNAL,
        _at(17),
        ExitSource.NONE,
    )
    assert by_label["P4"].parking.exit_source == ExitSource.RECURRING
    p6 = by_label["P6"]  # 미확인 차량
    assert (p6.parking.occupant_type, p6.parking.expected_exit_at, p6.parking.exit_source) == (
        OccupantType.UNKNOWN,
        None,
        ExitSource.NONE,
    )
    assert by_label["P5"].parking is None and by_label["P7"].parking is None


async def test_status_overdue_car_is_soon_exit(db, villa):
    """예정 시각이 지났는데 아직 서 있는 차는 곧 나갈 차로 본다."""
    status = await building_view.get_status(db, villa["me"], villa["building"].id, now=_at(19))
    assert status.slots[0].state == SlotState.SOON_EXIT  # P1 은 18:30 출차 예정이었다


# ── 배치 추천 ──
async def _tags(db, villa, exit_at, now=NOW):
    if "second_car" not in villa:  # 아직 세우지 않은 내 두 번째 차
        villa["second_car"] = await make_vehicle(db, "78나9012", owner=villa["me"])
    car = villa["second_car"]
    result = await recommendations.recommend(db, villa["me"], villa["building"].id, car.id, exit_at, now=now)
    return {s.label: s for s in result.slots}


async def test_recommend_matches_spec_example(db, villa):
    """내일 07:30 출차: P7(안쪽, 앞 칸 P8 비어 있음)이 추천, P8 은 EMPTY."""
    tags = await _tags(db, villa, _at(7, 30, day=1, month=10))

    assert list(tags) == [f"P{i}" for i in range(1, 9)]
    assert [t.tag for t in tags.values()] == [
        SlotTag.OCCUPIED,
        SlotTag.OCCUPIED,
        SlotTag.OCCUPIED,
        SlotTag.OCCUPIED,
        SlotTag.UNAVAILABLE,
        SlotTag.OCCUPIED,
        SlotTag.RECOMMENDED,
        SlotTag.EMPTY,
    ]
    assert tags["P5"].unavailable_reason == "관리인이 사용 중지한 칸이에요"
    assert tags["P7"].reason == "앞 칸이 비어 있고 다른 차를 막지 않는 가장 안쪽 칸이에요"
    assert (tags["P7"].will_block, tags["P8"].will_block, tags["P8"].reason) == (None, [], None)
    assert tags["P1"].will_block is None and tags["P1"].unavailable_reason is None  # 태그에 해당하는 필드만


async def test_recommend_avoids_blocking_and_being_blocked(db, villa):
    """P7 에 20:00 출차 차가 있을 때: 앞 칸 P8 에 21:00 출차로 서면 P7 을 막는다 → 추천 없음, will_block=[P7]."""
    parked = await make_vehicle(db, "11가1111", owner=villa["neighbor"])
    await make_assignment(db, villa["P7"], parked)
    await make_departure(db, parked, TODAY, time(20, 0))

    late = await _tags(db, villa, _at(21))
    assert (late["P7"].tag, late["P8"].tag, late["P8"].will_block) == (SlotTag.OCCUPIED, SlotTag.EMPTY, [villa["P7"].id])
    assert SlotTag.RECOMMENDED not in {t.tag for t in late.values()}  # 조건에 맞는 칸이 없으면 추천하지 않는다

    # 상시 주차(출차 시각 없음)는 가장 늦게 나가는 것으로 본다 → 역시 P7 을 막는다
    car = await make_vehicle(db, "22나2222", owner=villa["me"])
    long_term = await recommendations.recommend(db, villa["me"], villa["building"].id, car.id, None, now=NOW)
    p8 = next(s for s in long_term.slots if s.label == "P8")
    assert (p8.tag, p8.will_block) == (SlotTag.EMPTY, [villa["P7"].id])


async def test_recommend_outer_slot_when_leaving_first(db, villa):
    """P7 차(20:00)보다 먼저(19:00) 나가면 P8 에 서도 아무도 막지 않는다 → P8 추천."""
    parked = await make_vehicle(db, "11가1111", owner=villa["neighbor"])
    await make_assignment(db, villa["P7"], parked)
    await make_departure(db, parked, TODAY, time(20, 0))

    early = await _tags(db, villa, _at(19))
    assert (early["P8"].tag, early["P8"].reason) == (
        SlotTag.RECOMMENDED,
        "앞 칸이 비어 있고 다른 차를 막지 않는 가장 안쪽 칸이에요",
    )


async def test_recommend_inner_slot_blocked_by_front_car(db, villa):
    """P8 에 21:00 출차 차가 있을 때 P7 에 18:00 출차로 서면 내가 막힌다 → 추천하지 않는다. 22:00 출차면 추천."""
    parked = await make_vehicle(db, "11가1111", owner=villa["neighbor"])
    await make_assignment(db, villa["P8"], parked)
    await make_departure(db, parked, TODAY, time(21, 0))

    blocked = await _tags(db, villa, _at(18))
    assert (blocked["P7"].tag, blocked["P7"].will_block) == (SlotTag.EMPTY, [])

    free = await _tags(db, villa, _at(22))
    assert (free["P7"].tag, free["P7"].reason) == (
        SlotTag.RECOMMENDED,
        "앞 차가 먼저 나가고 다른 차를 막지 않는 가장 안쪽 칸이에요",
    )


async def test_recommend_reserved_slot_is_unavailable(db, villa):
    offer = await make_share_offer(db, villa["P7"], villa["manager"])
    share = await make_share_request(db, offer, villa["visitor"], ShareRequestStatus.ACCEPTED, start_hour=17, end_hour=19)
    share.request_date = TODAY
    await db.commit()

    reserved = await _tags(db, villa, _at(18))  # 18:00 출차 → 17~19시 공유와 겹친다
    assert (reserved["P7"].tag, reserved["P7"].unavailable_reason) == (SlotTag.UNAVAILABLE, "예약된 칸이에요")
    assert reserved["P8"].tag == SlotTag.RECOMMENDED

    before = await _tags(db, villa, _at(16))  # 공유 시작 전에 나간다
    assert before["P7"].tag == SlotTag.RECOMMENDED


async def test_recommend_errors(db, villa):
    with pytest.raises(NotFoundError):  # 남의 차량
        other_car = await make_vehicle(db, "33다3333", owner=villa["neighbor"])
        await recommendations.recommend(db, villa["me"], villa["building"].id, other_car.id, _at(18), now=NOW)
    with pytest.raises(InvalidInputError):  # 지난 시각
        await recommendations.recommend(db, villa["me"], villa["building"].id, villa["my_car"].id, _at(9), now=NOW)


# ── 홈 ──
async def test_home_matches_spec_example(db, villa):
    await notifications.create(db, villa["me"].id, NotificationType.EXIT_DONE, "출차 완료 안내", "P4 비어 있음")
    for i in range(3):
        await notifications.create(db, villa["me"].id, NotificationType.BLOCK_ALERT, "막힘 알림", f"알림 {i}")
    await db.commit()

    result = await home.get_home(db, villa["me"], now=NOW)

    assert (result.building.id, result.building.name, result.building.role) == (
        villa["building"].id,
        "월계 한빛빌라",
        "RESIDENT",
    )
    # 빈칸 2(P7·P8), 곧 출차 1(P4), 가능 3, 막힌 입주민 차량 1(P1)
    assert result.summary.model_dump() == {"available": 3, "soon_exit": 1, "blocked": 1, "empty": 2}
    assert (result.my_parking.parking_id, result.my_parking.slot_label, result.my_parking.expected_exit_at) == (
        villa["my_parking"].id,
        "P1",
        _at(18, 30),
    )
    assert (result.my_parking.vehicle.id, result.my_parking.vehicle.plate) == (villa["my_car"].id, "12가 3456")
    assert (result.block_alert.blocking_parking_id, result.block_alert.message) == (
        villa["neighbor_parking"].id,
        "내 차량이 P2 차량에 의해 막혀 있습니다.",
    )
    assert result.admin is None
    assert result.unread_notification_count == 4
    assert [n.body for n in result.recent_notifications] == ["알림 2", "알림 1"]  # 최신 2개


async def test_home_without_parking_and_for_manager(db, villa):
    offer = await make_share_offer(db, villa["P7"], villa["manager"])
    await make_share_request(db, offer, villa["visitor"])  # 대기 중인 공유 요청 1건

    neighbor = await home.get_home(db, villa["neighbor"], now=NOW)
    assert neighbor.block_alert is None  # 이웃 차(P2·P4)는 막혀 있지 않다
    assert neighbor.admin is None

    manager = await home.get_home(db, villa["manager"], now=NOW)
    assert (manager.my_parking, manager.block_alert) == (None, None)
    assert (manager.building.role, manager.admin.pending_share_requests) == ("ADMIN", 1)
    assert manager.recent_notifications == [] and manager.unread_notification_count == 0


async def test_home_requires_building(db):
    loner = await make_resident(db, "loner@example.com")
    with pytest.raises(ForbiddenError) as exc:
        await home.get_home(db, loner, now=NOW)
    assert exc.value.code == ErrorCode.NOT_BUILDING_MEMBER
