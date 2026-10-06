from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import ErrorCode
from app.core.weekdays import weekdays_from_db
from app.models.building import Building
from app.models.garage import Garage
from app.models.notification import NotificationType
from app.models.parking_slot import ParkingSlot
from app.models.resident import Resident
from app.models.share_offer import ShareOffer
from app.models.share_request import ShareRequest, ShareRequestStatus
from app.models.vehicle import Vehicle
from app.schemas.common import KST, to_kst
from app.services import notifications
from app.services.exceptions import ConflictError, InvalidInputError, NotFoundError
from app.services.pagination import DEFAULT_LIMIT, CursorPage, paginate
from app.services.slot_labels import slot_label, slot_labels


async def accepted_shares_at(db: AsyncSession, slot_ids: Iterable[int], at: datetime) -> dict[int, ShareRequest]:
    """at 시각(timezone-aware)에 칸별로 진행 중인 **수락된** 공유 요청 (slot_id → 요청). 없는 칸은 결과에 없다.

    규칙은 accepted_share_at 과 같다. 여러 칸을 한 번에 볼 때 (차고지 탐색·상세) 쓴다. commit 하지 않는다.
    """
    if at.tzinfo is None:
        raise ValueError("at 은 timezone-aware datetime 이어야 합니다.")
    ids = set(slot_ids)
    if not ids:
        return {}
    local = to_kst(at)
    # end_hour 는 정수 시라서 "at < request_date + end_hour" 는 "at 의 시 < end_hour" 와 같다
    result = await db.execute(
        select(ShareRequest).where(
            ShareRequest.slot_id.in_(ids),
            ShareRequest.status == ShareRequestStatus.ACCEPTED,
            ShareRequest.request_date == local.date(),
            ShareRequest.start_hour <= local.hour,
            ShareRequest.end_hour > local.hour,
        )
    )
    return {share.slot_id: share for share in result.scalars()}


async def accepted_share_at(db: AsyncSession, slot_id: int, at: datetime) -> ShareRequest | None:
    """at 시각(timezone-aware)에 slot_id 칸에서 진행 중인 **수락된** 공유 요청. 없으면 None.

    공유 시간은 Asia/Seoul 기준 `request_date + start_hour` 이상 ~ `request_date + end_hour` 미만으로 본다
    (end_hour = 24 는 다음 날 0시). 같은 칸에 수락된 요청끼리는 시간이 겹치지 않으므로(EXCLUDE 제약) 최대 하나다.

    현서 #8(주차 등록 시 공유 이용 칸 확인)이 호출한다. commit 하지 않는다.
    at 이 naive datetime 이면 ValueError (호출 코드 버그).
    """
    return (await accepted_shares_at(db, [slot_id], at)).get(slot_id)


# ── 새 API (명세 /share-requests, /me/share-requests) ─────────────────────────────


def validate_request_window(offer: ShareOffer, request_date: date, start_hour: int, end_hour: int) -> None:
    """요청 시간이 공유 조건(기간·요일·운영 시간·최대 이용 시간) 안인지. 밖이면 400 INVALID_INPUT.

    시작 < 종료, 0~24 범위는 요청 스키마가 확인한다. #13(수락 시 재확인)도 호출할 수 있다.
    """
    if not (offer.start_date <= request_date <= offer.end_date) or request_date.weekday() not in offer.available_weekdays:
        raise InvalidInputError(
            "이용할 수 없는 날짜입니다.",
            detail={"weekdays": [w.value for w in weekdays_from_db(offer.available_weekdays)]},
        )
    if start_hour < offer.start_hour or end_hour > offer.end_hour:
        raise InvalidInputError(
            "운영 시간 밖입니다.", detail={"start_hour": offer.start_hour, "end_hour": offer.end_hour}
        )
    if offer.max_hours is not None and end_hour - start_hour > offer.max_hours:
        raise InvalidInputError("최대 이용 시간을 초과했습니다.", detail={"max_hours": offer.max_hours})


async def has_accepted_overlap(
    db: AsyncSession, slot_id: int, request_date: date, start_hour: int, end_hour: int, exclude_id: int | None = None
) -> bool:
    """같은 칸·같은 날짜에 수락된 요청 중 [start_hour, end_hour) 와 겹치는 것이 있는지 (끝 시각 미포함)."""
    conditions = [
        ShareRequest.slot_id == slot_id,
        ShareRequest.status == ShareRequestStatus.ACCEPTED,
        ShareRequest.request_date == request_date,
        ShareRequest.start_hour < end_hour,
        ShareRequest.end_hour > start_hour,
    ]
    if exclude_id is not None:
        conditions.append(ShareRequest.id != exclude_id)
    return bool(await db.scalar(select(exists().where(*conditions))))


def ensure_enough_tokens(balance: int, required: int, message: str = "토큰이 부족합니다.") -> None:
    """잔액이 required 보다 적으면 409 INSUFFICIENT_TOKENS (detail: required, balance). 결정 18."""
    if balance < required:
        raise ConflictError(
            message, code=ErrorCode.INSUFFICIENT_TOKENS, detail={"required": required, "balance": balance}
        )


async def visible_offer(db: AsyncSession, user: Resident, offer_id: int) -> tuple[ShareOffer, Building]:
    """user 가 요청할 수 있는(= GET /garages 에 보이는) 공유 조건과 그 칸의 빌라.

    공개(`is_public`)이고 칸이 사용 중(`is_active`)이며, 칸의 빌라가 **내 빌라와 같은 골목**이어야 한다. 아니면 404 NOT_FOUND.
    내가 연 공유 조건이거나 내 빌라의 칸이면 400 INVALID_INPUT (명세 "내가 연 공유 조건에는 요청할 수 없습니다",
    docs/db-design-issues.md 2-1 "요청자는 다른 건물 주민").
    """
    row = (
        await db.execute(
            select(ShareOffer, ParkingSlot, Building)
            .join(ParkingSlot, ParkingSlot.id == ShareOffer.slot_id)
            .join(Garage, Garage.id == ParkingSlot.garage_id)
            .join(Building, Building.id == Garage.building_id)
            .where(ShareOffer.id == offer_id)
        )
    ).first()
    my_alley = (
        await db.scalar(select(Building.alley_id).where(Building.id == user.building_id))
        if user.building_id is not None
        else None
    )
    if row is None:
        raise NotFoundError("공유 조건을 찾을 수 없습니다.")
    offer, slot, building = row
    if offer.host_id == user.id:
        raise InvalidInputError("내가 연 공유 조건에는 요청할 수 없습니다.")
    if not offer.is_public or not slot.is_active or my_alley is None or building.alley_id != my_alley:
        raise NotFoundError("공유 조건을 찾을 수 없습니다.")
    if building.id == user.building_id:
        raise InvalidInputError("우리 빌라의 칸에는 공유 요청을 할 수 없습니다.")
    return offer, building


def _request_end(request_date: date, end_hour: int) -> datetime:
    return datetime.combine(request_date, time(0), tzinfo=KST) + timedelta(hours=end_hour)


async def create_for_user(
    db: AsyncSession,
    user: Resident,
    *,
    offer_id: int,
    request_date: date,
    start_hour: int,
    end_hour: int,
    vehicle_id: int | None = None,
    now: datetime | None = None,
) -> ShareRequest:
    """POST /share-requests. 요청을 PENDING 으로 만들고 공유를 연 관리인에게 SHARE_REQUEST 알림 (같은 트랜잭션), commit.

    검사 순서:
    - 공유 조건이 없거나 볼 수 없으면 404 NOT_FOUND, 내가 연 조건·내 빌라 칸이면 400 INVALID_INPUT (visible_offer)
    - 이미 끝난 시간(KST `request_date + end_hour` <= 지금)이면 400 INVALID_INPUT
    - 기간·요일·운영 시간·max_hours 밖이면 400 INVALID_INPUT (validate_request_window)
    - 차량은 내 차여야 한다 (없거나 남의 차면 404 NOT_FOUND)
    - 같은 칸의 수락된 요청과 시간이 겹치면 409 GARAGE_TIME_CONFLICT
    - 잔액 < total_price 이면 409 INSUFFICIENT_TOKENS (차감은 수락할 때, 결정 18)
    """
    offer, _ = await visible_offer(db, user, offer_id)
    if _request_end(request_date, end_hour) <= (now or datetime.now(KST)):
        raise InvalidInputError("이미 지난 시간에는 요청할 수 없습니다.")
    validate_request_window(offer, request_date, start_hour, end_hour)
    if vehicle_id is not None:
        vehicle = await db.get(Vehicle, vehicle_id)
        if vehicle is None or vehicle.owner_id != user.id:
            raise NotFoundError("차량을 찾을 수 없습니다.")
    if await has_accepted_overlap(db, offer.slot_id, request_date, start_hour, end_hour):
        raise ConflictError("요청한 시간에 이미 다른 예약이 있습니다.", code=ErrorCode.GARAGE_TIME_CONFLICT)

    total_price = (end_hour - start_hour) * offer.hourly_price  # 요청 시점 가격으로 고정
    ensure_enough_tokens(user.token_balance, total_price)

    share_request = ShareRequest(
        offer_id=offer.id,
        slot_id=offer.slot_id,
        requester_id=user.id,
        vehicle_id=vehicle_id,
        request_date=request_date,
        start_hour=start_hour,
        end_hour=end_hour,
        total_price=total_price,
    )
    db.add(share_request)
    await db.flush()

    await notifications.create(
        db,
        offer.host_id,
        NotificationType.SHARE_REQUEST,
        "공유 사용 요청이 도착했어요",
        share_request_body(await slot_label(db, offer.slot_id), request_date, start_hour, end_hour),
        share_request_id=share_request.id,
    )
    await db.commit()
    await db.refresh(share_request)
    return share_request


def share_request_body(label: str, request_date: date, start_hour: int, end_hour: int) -> str:
    """SHARE_REQUEST 알림 본문. 예: "P3 · 10월 2일 13:00~17:00"."""
    return f"{label} · {request_date.month}월 {request_date.day}일 {start_hour:02d}:00~{end_hour:02d}:00"


@dataclass
class MyShareRequest:
    """명세 ShareRequestDetail 한 건 (요청 + 차고지(빌라) + 칸 이름)."""

    request: ShareRequest
    garage_id: int
    garage_name: str
    slot_label: str


async def _with_place(db: AsyncSession, requests: list[ShareRequest]) -> list[MyShareRequest]:
    if not requests:
        return []
    slot_ids = {r.slot_id for r in requests}
    buildings = dict(
        (
            await db.execute(
                select(ParkingSlot.id, Building)
                .join(Garage, Garage.id == ParkingSlot.garage_id)
                .join(Building, Building.id == Garage.building_id)
                .where(ParkingSlot.id.in_(slot_ids))
            )
        ).all()
    )
    labels = await slot_labels(db, slot_ids)
    return [
        MyShareRequest(r, buildings[r.slot_id].id, buildings[r.slot_id].name, labels[r.slot_id]) for r in requests
    ]


async def get_mine(db: AsyncSession, user: Resident, share_request_id: int) -> MyShareRequest:
    """GET /share-requests/{id}. 내 요청이 아니거나 없으면 404 NOT_FOUND."""
    share_request = await db.get(ShareRequest, share_request_id)
    if share_request is None or share_request.requester_id != user.id:
        raise NotFoundError("공유 요청을 찾을 수 없습니다.")
    return (await _with_place(db, [share_request]))[0]


async def list_mine(
    db: AsyncSession, user: Resident, cursor: str | None = None, limit: int = DEFAULT_LIMIT
) -> CursorPage[MyShareRequest]:
    """GET /me/share-requests. 내가 보낸 요청 최신순 한 페이지 (결정 14)."""
    page = await paginate(db, select(ShareRequest).where(ShareRequest.requester_id == user.id), ShareRequest.id, cursor, limit)
    return CursorPage(items=await _with_place(db, page.items), next_cursor=page.next_cursor)
