"""토큰 이동. 잔액 변경과 기록(token_transfers)을 같은 트랜잭션에서 하며, commit 은 호출한 쪽이 한다."""

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import ErrorCode
from app.models.resident import Resident
from app.models.token_transfer import TokenTransfer
from app.services.exceptions import ConflictError, InvalidInputError, NotFoundError


async def transfer(
    db: AsyncSession,
    sender_id: int | None,
    receiver_id: int,
    amount: int,
    share_request_id: int | None = None,
    memo: str | None = None,
) -> TokenTransfer:
    """sender 에서 receiver 로 amount 를 넘긴다. sender 가 None 이면 시스템 지급."""
    if amount <= 0:
        raise InvalidInputError("토큰은 1 이상 보낼 수 있습니다.")

    # 동시에 반대 방향 이동이 일어나도 교착되지 않도록 id 순서로 행을 잠근다
    deltas = {receiver_id: amount} if sender_id is None else {sender_id: -amount, receiver_id: amount}
    for resident_id in sorted(deltas):
        delta = deltas[resident_id]
        stmt = update(Resident).where(Resident.id == resident_id)
        if delta < 0:
            # 잔액 확인과 차감을 한 문장으로 → 동시 요청에도 음수가 되지 않는다
            stmt = stmt.where(Resident.token_balance >= -delta)
        result = await db.execute(
            stmt.values(token_balance=Resident.token_balance + delta).returning(Resident.id)
        )
        if result.scalar_one_or_none() is None:
            if delta < 0 and await db.get(Resident, resident_id) is not None:
                raise ConflictError("토큰이 부족합니다.", code=ErrorCode.INSUFFICIENT_TOKENS)
            raise NotFoundError("사용자를 찾을 수 없습니다.")

    record = TokenTransfer(
        sender_id=sender_id, receiver_id=receiver_id, amount=amount, share_request_id=share_request_id, memo=memo
    )
    db.add(record)
    return record
