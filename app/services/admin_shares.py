"""관리인 공유 조건 관리·공유 요청 수락/거절. 담당: 건우 #13.

- 공유 조건 (결정 12): start_date = 등록일(KST), end_date = 9999-12-31(무기한), host = 호출한 관리인
- 칸 이름: 빌라 안 순번 P1, P2 … (app/services/slot_labels.py, #24)
- 수락 (결정 18): PENDING 에서만, 같은 칸 수락 요청과 시간이 겹치면 409, 수락 시점에 잔액을 다시 확인.
  토큰 이동은 tokens.transfer, 결과 알림은 notifications.create (모두 같은 트랜잭션)
경로에 building_id 가 없는 대상(공유 조건·공유 요청)은 대상의 빌라를 찾아 ensure_building_admin 으로 확인한다.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enum_maps import share_status_from_api, share_status_to_api
from app.core.error_codes import ErrorCode
from app.core.weekdays import weekdays_to_db
from app.models.garage import Garage
from app.models.notification import NotificationType
from app.models.parking_slot import ParkingSlot
from app.models.resident import Resident
from app.models.share_offer import ShareOffer
from app.models.share_request import ShareRequest, ShareRequestStatus
from app.models.vehicle import Vehicle
from app.schemas.admin_shares import ShareOfferCreate, ShareOfferUpdate
from app.schemas.common import KST
from app.services import notifications, tokens
from app.services.exceptions import ConflictError, InvalidInputError, NotFoundError
from app.services.pagination import DEFAULT_LIMIT, CursorPage, apply_cursor, make_page
from app.services.permissions import ensure_building_admin
from app.services.slot_labels import building_slot_labels, slot_label

OPEN_END_DATE = date(9999, 12, 31)


def today_kst() -> date:
    return datetime.now(KST).date()


# ── 공유 조건 ─────────────────────────────────────────────────────────
@dataclass
class OfferView:
    offer: ShareOffer
    slot_label: str


def _offers_with_building() -> Select:
    """(공유 조건, 빌라 id)"""
    return (
        select(ShareOffer, Garage.building_id)
        .join(ParkingSlot, ShareOffer.slot_id == ParkingSlot.id)
        .join(Garage, ParkingSlot.garage_id == Garage.id)
    )


async def list_offers(db: AsyncSession, building_id: int) -> list[OfferView]:
    """이 빌라 칸에 걸린 공유 조건 전부 (id 순)."""
    rows = await db.execute(_offers_with_building().where(Garage.building_id == building_id).order_by(ShareOffer.id))
    labels = await building_slot_labels(db, building_id)
    return [OfferView(offer, labels[offer.slot_id]) for offer, _ in rows.all()]


async def create_offers(
    db: AsyncSession, building_id: int, host: Resident, payload: ShareOfferCreate
) -> list[OfferView]:
    """slot_ids 칸마다 공유 조건을 하나씩 만든다. 칸 하나라도 잘못되면 아무것도 만들지 않는다 (한 트랜잭션)."""
    slot_ids = list(dict.fromkeys(payload.slot_ids))  # 같은 칸을 두 번 보내도 하나만
    rows = await db.execute(
        select(ParkingSlot.id, ParkingSlot.is_active, Garage.building_id)
        .join(Garage, ParkingSlot.garage_id == Garage.id)
        .where(ParkingSlot.id.in_(slot_ids))
    )
    slots = {slot_id: (is_active, slot_building) for slot_id, is_active, slot_building in rows.all()}
    for slot_id in slot_ids:
        found = slots.get(slot_id)
        if found is None or found[1] != building_id:
            raise InvalidInputError("이 빌라의 칸만 공유할 수 있습니다.", detail={"slot_id": slot_id})
        if not found[0]:
            raise InvalidInputError("사용 중지된 칸은 공유할 수 없습니다.", detail={"slot_id": slot_id})

    fields = payload.model_dump(exclude={"slot_ids", "weekdays"})
    start = today_kst()
    labels = await building_slot_labels(db, building_id)
    views: list[OfferView] = []
    for slot_id in slot_ids:
        offer = ShareOffer(
            **fields,
            slot_id=slot_id,
            host_id=host.id,
            start_date=start,
            end_date=OPEN_END_DATE,
            available_weekdays=weekdays_to_db(payload.weekdays),
        )
        db.add(offer)
        views.append(OfferView(offer, labels[slot_id]))
    await db.commit()
    return views


async def _get_offer_for_admin(db: AsyncSession, user: Resident, offer_id: int) -> OfferView:
    row = (await db.execute(_offers_with_building().where(ShareOffer.id == offer_id))).first()
    if row is None:
        raise NotFoundError("공유 조건을 찾을 수 없습니다.")
    offer, building_id = row
    ensure_building_admin(user, building_id)
    return OfferView(offer, await slot_label(db, offer.slot_id))


async def update_offer(db: AsyncSession, user: Resident, offer_id: int, payload: ShareOfferUpdate) -> OfferView:
    """보낸 필드만 바꾼다. 가격을 바꿔도 이미 들어온 요청의 total_price 는 그대로다 (요청에 저장된 값)."""
    view = await _get_offer_for_admin(db, user, offer_id)
    offer = view.offer
    changes = payload.model_dump(exclude_unset=True)
    if "weekdays" in changes:
        offer.available_weekdays = weekdays_to_db(changes.pop("weekdays"))
    for name, value in changes.items():
        setattr(offer, name, value)
    if offer.start_hour >= offer.end_hour:
        raise InvalidInputError(
            "start_hour 는 end_hour 보다 앞서야 합니다.",
            detail={"start_hour": offer.start_hour, "end_hour": offer.end_hour},
        )
    await db.commit()
    return view


async def delete_offer(db: AsyncSession, user: Resident, offer_id: int) -> None:
    """공유 조건 삭제. 딸린 공유 요청(과 그 알림)은 DB ON DELETE CASCADE 로 함께 지워진다."""
    await _get_offer_for_admin(db, user, offer_id)
    await db.execute(delete(ShareOffer).where(ShareOffer.id == offer_id))
    await db.commit()


# ── 공유 요청 목록 ─────────────────────────────────────────────────────
@dataclass
class RequestView:
    request: ShareRequest
    slot_label: str


@dataclass
class AdminShareRequestPage:
    counts: dict[str, int]
    page: CursorPage[RequestView]


def _requests_in_building(building_id: int) -> Select:
    return (
        select(ShareRequest)
        .join(ParkingSlot, ShareRequest.slot_id == ParkingSlot.id)
        .join(Garage, ParkingSlot.garage_id == Garage.id)
        .where(Garage.building_id == building_id)
    )


async def list_requests(
    db: AsyncSession,
    building_id: int,
    status: str = "all",
    q: str | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> AdminShareRequestPage:
    """이 빌라 칸에 들어온 공유 요청 최신순 한 페이지 + 상태별 개수(필터와 무관한 빌라 전체 기준).

    q: 요청자 이름·닉네임 또는 차량 번호(공백 무시) 부분 일치.
    """
    count_rows = await db.execute(
        _requests_in_building(building_id)
        .with_only_columns(ShareRequest.status, func.count())
        .group_by(ShareRequest.status)
    )
    counts = {"PENDING": 0, "APPROVED": 0, "REJECTED": 0}
    for db_status, n in count_rows.all():
        counts[share_status_to_api(db_status).value] = n

    stmt = (
        _requests_in_building(building_id)
        .join(Resident, ShareRequest.requester_id == Resident.id)
        .outerjoin(Vehicle, ShareRequest.vehicle_id == Vehicle.id)
        .options(
            selectinload(ShareRequest.requester),
            selectinload(ShareRequest.vehicle),
        )
    )
    if status != "all":
        stmt = stmt.where(ShareRequest.status == share_status_from_api(status))
    if q is not None and q.strip():
        text_q = f"%{q.strip()}%"
        plate_q = f"%{''.join(q.split())}%"
        stmt = stmt.where(
            or_(Resident.name.ilike(text_q), Resident.nickname.ilike(text_q), Vehicle.plate_no.ilike(plate_q))
        )
    result = await db.execute(apply_cursor(stmt, ShareRequest.id, cursor, limit))
    page = make_page(list(result.scalars().all()), limit)
    labels = await building_slot_labels(db, building_id)
    return AdminShareRequestPage(
        counts=counts,
        page=CursorPage(items=[RequestView(r, labels[r.slot_id]) for r in page.items], next_cursor=page.next_cursor),
    )


# ── 공유 요청 수락 / 거절 ───────────────────────────────────────────────
async def decide(
    db: AsyncSession, user: Resident, share_request_id: int, status: str, reject_reason: str | None = None
) -> ShareRequest:
    """status: 명세 값 APPROVED / REJECTED.

    - 없으면 404, 그 빌라 관리인이 아니면 403 NOT_BUILDING_ADMIN, PENDING 이 아니면 409 ALREADY_DECIDED
    - 수락: 같은 칸의 수락된 요청과 겹치면 409 GARAGE_TIME_CONFLICT, 요청자 잔액이 모자라면 409 INSUFFICIENT_TOKENS
      (요청은 PENDING 그대로). total_price > 0 이면 요청자 → host 로 토큰 이동
    - 수락·거절 모두 요청자에게 SHARE_RESULT 알림
    """
    # 같은 요청을 동시에 처리해 토큰이 두 번 빠지지 않도록 행을 잠근다
    share_request = await db.scalar(
        select(ShareRequest)
        .where(ShareRequest.id == share_request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if share_request is None:
        raise NotFoundError("공유 요청을 찾을 수 없습니다.")
    building_id, host_id = (
        await db.execute(
            select(Garage.building_id, ShareOffer.host_id)
            .select_from(ShareOffer)
            .join(ParkingSlot, ShareOffer.slot_id == ParkingSlot.id)
            .join(Garage, ParkingSlot.garage_id == Garage.id)
            .where(ShareOffer.id == share_request.offer_id)
        )
    ).one()
    ensure_building_admin(user, building_id)
    if share_request.status != ShareRequestStatus.PENDING:
        raise ConflictError(
            "이미 처리된 요청입니다.",
            code=ErrorCode.ALREADY_DECIDED,
            detail={"status": share_status_to_api(share_request.status).value},
        )

    new_status = share_status_from_api(status)
    try:
        if new_status == ShareRequestStatus.ACCEPTED:
            await _ensure_no_overlap(db, share_request)
            await _ensure_balance(db, share_request)
        share_request.status = new_status
        share_request.reject_reason = reject_reason if new_status == ShareRequestStatus.REJECTED else None
        share_request.responded_at = datetime.now(UTC)
        await db.flush()  # 동시 수락으로 겹치면 EXCLUDE 제약(ex_share_accepted_overlap)이 막는다

        if new_status == ShareRequestStatus.ACCEPTED and share_request.total_price > 0:
            await tokens.transfer(
                db,
                sender_id=share_request.requester_id,
                receiver_id=host_id,
                amount=share_request.total_price,
                share_request_id=share_request.id,
                memo="공유 주차 이용료",
            )

        await notifications.create(
            db,
            share_request.requester_id,
            NotificationType.SHARE_RESULT,
            *_result_message(share_request, await slot_label(db, share_request.slot_id)),
            share_request_id=share_request.id,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return share_request


async def _ensure_no_overlap(db: AsyncSession, share_request: ShareRequest) -> None:
    """같은 칸·같은 날 수락된 요청과 [start_hour, end_hour) 가 겹치면 409 GARAGE_TIME_CONFLICT."""
    overlap = await db.scalar(
        select(ShareRequest.id).where(
            ShareRequest.slot_id == share_request.slot_id,
            ShareRequest.request_date == share_request.request_date,
            ShareRequest.status == ShareRequestStatus.ACCEPTED,
            ShareRequest.id != share_request.id,
            ShareRequest.start_hour < share_request.end_hour,
            ShareRequest.end_hour > share_request.start_hour,
        ).limit(1)
    )
    if overlap is not None:
        raise ConflictError("이미 수락된 다른 예약과 시간이 겹칩니다.", code=ErrorCode.GARAGE_TIME_CONFLICT)


async def _ensure_balance(db: AsyncSession, share_request: ShareRequest) -> None:
    """수락 시점 잔액 재확인 (결정 18). 실제 차감은 tokens.transfer 가 원자적으로 다시 확인한다."""
    if share_request.total_price <= 0:
        return
    balance = await db.scalar(select(Resident.token_balance).where(Resident.id == share_request.requester_id))
    if balance is None or balance < share_request.total_price:
        raise ConflictError(
            "요청자의 토큰이 부족합니다.",
            code=ErrorCode.INSUFFICIENT_TOKENS,
            detail={"required": share_request.total_price, "balance": balance or 0},
        )


def _result_message(share_request: ShareRequest, label: str) -> tuple[str, str]:
    """SHARE_RESULT 알림 (title, body). 거절이면 body 는 사유 (명세 알림 예시)."""
    when = (
        f"{label} · {share_request.request_date.month}월 {share_request.request_date.day}일 "
        f"{share_request.start_hour}~{share_request.end_hour}시"
    )
    if share_request.status == ShareRequestStatus.ACCEPTED:
        return "공유 요청이 수락되었어요", when
    return "공유 요청이 거절되었어요", share_request.reject_reason or when
