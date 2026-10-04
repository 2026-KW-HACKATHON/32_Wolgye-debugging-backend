"""#24 칸 이름 = 빌라 안 순번 P1, P2 … (주차 구역 sort_order → 구역 id → 칸 number)."""

import pytest

from app.services.exceptions import NotFoundError
from app.services.slot_labels import building_slot_labels, slot_label, slot_labels
from tests.factories import make_alley, make_building, make_garage, make_slot

pytestmark = pytest.mark.anyio


async def test_numbers_slots_by_zone_sort_order_then_number(db):
    building = await make_building(db)
    back = await make_garage(db, building, name="골목")
    front = await make_garage(db, building, name="필로티 안쪽")
    back.sort_order, front.sort_order = 2, 1
    await db.commit()
    b2 = await make_slot(db, back, number=2)
    b1 = await make_slot(db, back, number=1)
    f1 = await make_slot(db, front, number=1)
    f2 = await make_slot(db, front, number=2)
    f2.is_active = False  # 비활성 칸도 순번에 들어간다
    await db.commit()

    labels = await building_slot_labels(db, building.id)

    assert labels == {f1.id: "P1", f2.id: "P2", b1.id: "P3", b2.id: "P4"}
    assert list(labels) == [f1.id, f2.id, b1.id, b2.id]


async def test_same_sort_order_falls_back_to_zone_id(db):
    building = await make_building(db)
    first = await make_garage(db, building, name="A")
    second = await make_garage(db, building, name="B")
    s2 = await make_slot(db, second, number=1)
    s1 = await make_slot(db, first, number=1)

    assert await building_slot_labels(db, building.id) == {s1.id: "P1", s2.id: "P2"}


async def test_slot_labels_counts_each_building_separately(db):
    alley = await make_alley(db)
    a = await make_building(db, invite_code="A00001", name="가빌라", alley=alley)
    b = await make_building(db, invite_code="B00001", name="나빌라", alley=alley)
    a1 = await make_slot(db, await make_garage(db, a), number=1)
    a2 = await make_slot(db, await make_garage(db, a, name="골목"), number=1)
    b1 = await make_slot(db, await make_garage(db, b), number=1)

    assert await slot_labels(db, [a2.id, b1.id]) == {a2.id: "P2", b1.id: "P1"}
    assert await slot_labels(db, []) == {}
    assert await slot_label(db, a1.id) == "P1"


async def test_slot_label_unknown_slot_is_not_found(db):
    with pytest.raises(NotFoundError):
        await slot_label(db, 999_999)
