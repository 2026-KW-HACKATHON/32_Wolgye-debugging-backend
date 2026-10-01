import pytest
from sqlalchemy import select

from app.models.resident import Resident
from app.services import tokens
from app.services.exceptions import ConflictError, NotFoundError
from tests.factories import make_resident

pytestmark = pytest.mark.anyio


async def _balance(session_factory, resident: Resident) -> int:
    async with session_factory() as other:
        return await other.scalar(select(Resident.token_balance).where(Resident.id == resident.id))


async def test_grant_from_system(db, session_factory):
    alice = await make_resident(db)
    record = await tokens.transfer(db, sender_id=None, receiver_id=alice.id, amount=30, memo="가입 축하")
    await db.commit()

    assert record.sender_id is None
    assert await _balance(session_factory, alice) == 30


async def test_transfer_between_residents(db, session_factory):
    alice = await make_resident(db, "alice@example.com", token_balance=10)
    bob = await make_resident(db, "bob@example.com")
    await tokens.transfer(db, sender_id=alice.id, receiver_id=bob.id, amount=7)
    await db.commit()

    assert await _balance(session_factory, alice) == 3
    assert await _balance(session_factory, bob) == 7


async def test_transfer_not_enough_tokens(db):
    alice = await make_resident(db, "alice@example.com", token_balance=2)
    bob = await make_resident(db, "bob@example.com")
    with pytest.raises(ConflictError) as exc_info:
        await tokens.transfer(db, sender_id=alice.id, receiver_id=bob.id, amount=3)
    assert exc_info.value.detail == "Not enough tokens"


async def test_transfer_unknown_receiver(db):
    alice = await make_resident(db, "alice@example.com", token_balance=10)
    with pytest.raises(NotFoundError):
        await tokens.transfer(db, sender_id=alice.id, receiver_id=999, amount=1)


async def test_transfer_non_positive_amount(db):
    alice = await make_resident(db)
    with pytest.raises(ConflictError):
        await tokens.transfer(db, sender_id=None, receiver_id=alice.id, amount=0)
