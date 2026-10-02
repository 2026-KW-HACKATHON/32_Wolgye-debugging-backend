"""DB 제약 위반이 500 이 아니라 409 + 제약별 메시지로 나가는지."""

import pytest
from sqlalchemy import text

from app.core.db_errors import CONSTRAINT_ERRORS, FOREIGN_KEY_ERROR
from app.models.share_request import ShareRequestStatus
from tests.factories import (
    make_alley,
    make_building,
    make_garage,
    make_resident,
    make_share_offer,
    make_share_request,
    make_slot,
)
from tests.helpers import assert_error

pytestmark = pytest.mark.anyio


async def test_duplicate_invite_code(client, db):
    alley = await make_alley(db)
    payload = {"alley_id": alley.id, "name": "월계빌라", "address": "서울", "invite_code": "DUP"}
    assert (await client.post("/api/v1/buildings", json=payload)).status_code == 201

    res = await client.post("/api/v1/buildings", json=payload)
    assert res.status_code == 409
    assert_error(res, *CONSTRAINT_ERRORS["buildings_invite_code_key"])


async def test_duplicate_plate_no(client):
    assert (await client.post("/api/v1/vehicles", json={"plate_no": "12가3456"})).status_code == 201

    res = await client.post("/api/v1/vehicles", json={"plate_no": "12가3456"})
    assert res.status_code == 409
    assert_error(res, *CONSTRAINT_ERRORS["vehicles_plate_no_key"])


async def test_second_primary_vehicle_partial_unique_index(client, db):
    owner = await make_resident(db)
    await client.post("/api/v1/vehicles", json={"plate_no": "11가1111", "owner_id": owner.id, "is_primary": True})

    res = await client.post("/api/v1/vehicles", json={"plate_no": "22나2222", "owner_id": owner.id, "is_primary": True})
    assert res.status_code == 409
    assert_error(res, *CONSTRAINT_ERRORS["uq_primary_vehicle_per_owner"])


async def test_check_constraint_slot_number(client, db):
    garage = await make_garage(db, await make_building(db))

    res = await client.post("/api/v1/parking-slots", json={"garage_id": garage.id, "number": 0})
    assert res.status_code == 409
    assert_error(res, *CONSTRAINT_ERRORS["ck_slot_number_positive"])


async def test_foreign_key_violation(client):
    res = await client.post("/api/v1/vehicles", json={"plate_no": "12가3456", "owner_id": 999})
    assert res.status_code == 409
    assert_error(res, *FOREIGN_KEY_ERROR)


async def test_accept_overlapping_share_request_exclusion(client, db):
    slot = await make_slot(db, await make_garage(db, await make_building(db)))
    offer = await make_share_offer(db, slot, await make_resident(db, "host@example.com"))
    requester = await make_resident(db)
    await make_share_request(db, offer, requester, status=ShareRequestStatus.ACCEPTED, start_hour=10, end_hour=12)
    # PENDING 은 겹쳐도 저장됨. 11~13시는 10~12시와 겹친다.
    overlapping = await make_share_request(db, offer, requester, start_hour=11, end_hour=13)

    res = await client.post(f"/api/v1/share-requests/{overlapping.id}/decision", json={"status": "accepted"})
    assert res.status_code == 409
    assert_error(res, *CONSTRAINT_ERRORS["ex_share_accepted_overlap"])


async def test_constraint_message_keys_exist_in_db(db):
    """매핑 표의 이름에 오타가 있으면 메시지가 조용히 기본값으로 떨어진다 → 실제 DB 이름과 대조."""
    result = await db.execute(
        text(
            "SELECT conname FROM pg_constraint WHERE connamespace = 'public'::regnamespace "
            "UNION SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
        )
    )
    names = set(result.scalars().all())
    assert set(CONSTRAINT_ERRORS) - names == set()
