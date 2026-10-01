"""HTTP 없이 서비스 함수를 직접 호출."""

import pytest

from app.models.share_request import ShareRequestStatus
from app.schemas.share_request import ShareRequestDecision
from app.services import share_requests as share_request_service
from app.services.exceptions import ConflictError, NotFoundError
from tests.factories import make_building, make_resident, make_share_request, make_slot, make_zone

pytestmark = pytest.mark.anyio


@pytest.fixture
async def pending_request(db):
    slot = await make_slot(db, await make_zone(db, await make_building(db)), is_shareable=True)
    return await make_share_request(db, slot, await make_resident(db))


async def test_decide_accepts_pending_request(db, session_factory, pending_request):
    decided = await share_request_service.decide(
        db, pending_request.id, ShareRequestDecision(status=ShareRequestStatus.ACCEPTED)
    )
    assert decided.status == ShareRequestStatus.ACCEPTED
    assert decided.responded_at is not None

    # 서비스가 commit 했으므로 새 세션에서도 보인다
    async with session_factory() as other:
        stored = await share_request_service.get_share_request(other, pending_request.id)
        assert stored.status == ShareRequestStatus.ACCEPTED


async def test_decide_not_found(db):
    with pytest.raises(NotFoundError) as exc_info:
        await share_request_service.decide(db, 999, ShareRequestDecision(status=ShareRequestStatus.ACCEPTED))
    assert exc_info.value.detail == "Share request not found"


async def test_decide_already_decided(db, pending_request):
    await share_request_service.decide(db, pending_request.id, ShareRequestDecision(status=ShareRequestStatus.REJECTED))

    with pytest.raises(ConflictError) as exc_info:
        await share_request_service.decide(
            db, pending_request.id, ShareRequestDecision(status=ShareRequestStatus.ACCEPTED)
        )
    assert exc_info.value.detail == "Already decided"
