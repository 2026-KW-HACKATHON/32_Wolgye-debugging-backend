"""DB 제약 위반이 500 이 아니라 409 + 제약별 메시지로 나가는지."""

import pytest
from sqlalchemy import text

from app.core.db_errors import CONSTRAINT_MESSAGES, FOREIGN_KEY_MESSAGE
from app.models.share_request import ShareRequestStatus
from tests.factories import make_building, make_resident, make_share_request, make_slot, make_zone

pytestmark = pytest.mark.anyio


async def test_duplicate_invite_code(client):
    payload = {"name": "월계빌라", "address": "서울", "invite_code": "DUP"}
    assert (await client.post("/api/v1/buildings", json=payload)).status_code == 201

    res = await client.post("/api/v1/buildings", json=payload)
    assert res.status_code == 409
    assert res.json() == {"detail": CONSTRAINT_MESSAGES["buildings_invite_code_key"]}


async def test_duplicate_plate_no(client):
    assert (await client.post("/api/v1/vehicles", json={"plate_no": "12가3456"})).status_code == 201

    res = await client.post("/api/v1/vehicles", json={"plate_no": "12가3456"})
    assert res.status_code == 409
    assert res.json() == {"detail": CONSTRAINT_MESSAGES["vehicles_plate_no_key"]}


async def test_second_primary_vehicle_partial_unique_index(client, db):
    owner = await make_resident(db)
    await client.post("/api/v1/vehicles", json={"plate_no": "11가1111", "owner_id": owner.id, "is_primary": True})

    res = await client.post("/api/v1/vehicles", json={"plate_no": "22나2222", "owner_id": owner.id, "is_primary": True})
    assert res.status_code == 409
    assert res.json() == {"detail": CONSTRAINT_MESSAGES["uq_primary_vehicle_per_owner"]}


async def test_check_constraint_slot_number(client, db):
    zone = await make_zone(db, await make_building(db))

    res = await client.post("/api/v1/parking-slots", json={"zone_id": zone.id, "number": 0})
    assert res.status_code == 409
    assert res.json() == {"detail": CONSTRAINT_MESSAGES["ck_slot_number_positive"]}


async def test_foreign_key_violation(client):
    res = await client.post("/api/v1/vehicles", json={"plate_no": "12가3456", "owner_id": 999})
    assert res.status_code == 409
    assert res.json() == {"detail": FOREIGN_KEY_MESSAGE}


async def test_accept_overlapping_share_request_exclusion(client, db):
    slot = await make_slot(db, await make_zone(db, await make_building(db)), is_shareable=True)
    requester = await make_resident(db)
    await make_share_request(db, slot, requester, status=ShareRequestStatus.ACCEPTED)
    overlapping = await make_share_request(db, slot, requester)  # PENDING 은 겹쳐도 저장됨

    res = await client.post(f"/api/v1/share-requests/{overlapping.id}/decision", json={"status": "accepted"})
    assert res.status_code == 409
    assert res.json() == {"detail": CONSTRAINT_MESSAGES["ex_share_accepted_overlap"]}


async def test_constraint_message_keys_exist_in_db(db):
    """매핑 표의 이름에 오타가 있으면 메시지가 조용히 기본값으로 떨어진다 → 실제 DB 이름과 대조."""
    result = await db.execute(
        text(
            "SELECT conname FROM pg_constraint WHERE connamespace = 'public'::regnamespace "
            "UNION SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
        )
    )
    names = set(result.scalars().all())
    assert set(CONSTRAINT_MESSAGES) - names == set()
