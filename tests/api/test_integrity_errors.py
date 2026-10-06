"""DB 제약 위반이 500 이 아니라 409 + 제약별 메시지로 나가는지 (전역 IntegrityError 핸들러, app/core/db_errors.py).

새 API 는 대부분 제약에 걸리기 전에 서비스에서 먼저 막기 때문에, 핸들러는 테스트 전용 앱에서 제약을 직접 어겨서 확인한다.
(구 API 로 확인하던 것을 #15 에서 옮김)
"""

from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbSession, get_db
from app.api.errors import register_exception_handlers
from app.core.db_errors import CONSTRAINT_ERRORS, FOREIGN_KEY_ERROR
from app.models.building import Building
from app.models.parking_slot import ParkingSlot
from app.models.share_request import ShareRequestStatus
from app.models.vehicle import Vehicle
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

Action = Callable[[AsyncSession], Awaitable[None]]


@pytest.fixture
async def violate(session_factory) -> AsyncIterator[Callable[[Action], Awaitable]]:
    """action(db) 을 실행하고 commit 하는 엔드포인트를 가진 테스트 앱으로 요청을 보낸다. 응답을 돌려준다."""
    app = FastAPI()
    register_exception_handlers(app)
    current: dict[str, Action] = {}

    @app.post("/violate")
    async def run(db: DbSession):
        await current["action"](db)
        await db.commit()
        return {"ok": True}

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:

        async def send(action: Action):
            current["action"] = action
            return await client.post("/violate")

        yield send


async def test_duplicate_invite_code(violate, db):
    alley = await make_alley(db)
    await make_building(db, invite_code="DUP", alley=alley)

    async def action(session):
        session.add(Building(alley_id=alley.id, name="옆 빌라", address="서울", invite_code="DUP"))

    res = await violate(action)
    assert res.status_code == 409
    assert_error(res, *CONSTRAINT_ERRORS["buildings_invite_code_key"])


async def test_duplicate_plate_no(violate, db):
    async def action(session):
        session.add(Vehicle(plate_no="12가3456"))

    assert (await violate(action)).status_code == 200
    res = await violate(action)
    assert res.status_code == 409
    assert_error(res, *CONSTRAINT_ERRORS["vehicles_plate_no_key"])


async def test_second_primary_vehicle_partial_unique_index(violate, db):
    owner = await make_resident(db)

    async def action(session):
        session.add_all(
            [
                Vehicle(plate_no="11가1111", owner_id=owner.id, is_primary=True),
                Vehicle(plate_no="22나2222", owner_id=owner.id, is_primary=True),
            ]
        )

    res = await violate(action)
    assert res.status_code == 409
    assert_error(res, *CONSTRAINT_ERRORS["uq_primary_vehicle_per_owner"])


async def test_check_constraint_slot_number(violate, db):
    garage = await make_garage(db, await make_building(db))

    async def action(session):
        session.add(ParkingSlot(garage_id=garage.id, number=0))

    res = await violate(action)
    assert res.status_code == 409
    assert_error(res, *CONSTRAINT_ERRORS["ck_slot_number_positive"])


async def test_foreign_key_violation(violate):
    async def action(session):
        session.add(Vehicle(plate_no="12가3456", owner_id=999))

    res = await violate(action)
    assert res.status_code == 409
    assert_error(res, *FOREIGN_KEY_ERROR)


async def test_accept_overlapping_share_request_exclusion(violate, db):
    slot = await make_slot(db, await make_garage(db, await make_building(db)))
    offer = await make_share_offer(db, slot, await make_resident(db, "host@example.com"))
    requester = await make_resident(db)
    await make_share_request(db, offer, requester, status=ShareRequestStatus.ACCEPTED, start_hour=10, end_hour=12)
    # PENDING 은 겹쳐도 저장됨. 11~13시는 10~12시와 겹친다.
    overlapping = await make_share_request(db, offer, requester, start_hour=11, end_hour=13)

    async def action(session):
        await session.execute(
            text("UPDATE share_requests SET status = 'ACCEPTED' WHERE id = :id"), {"id": overlapping.id}
        )

    res = await violate(action)
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
