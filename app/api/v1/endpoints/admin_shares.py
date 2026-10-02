"""관리인 공유 조건·공유 요청 (명세 tag admin): /admin/buildings/{building_id}/share-offers, /admin/share-offers/{offer_id}, /admin/buildings/{building_id}/share-requests, PATCH /admin/share-requests/{share_request_id}

담당: 건우 #13. 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import BuildingAdmin, CurrentUser, CursorParam, DbSession, LimitParam
from app.core.enum_maps import share_status_to_api
from app.core.plates import format_plate
from app.core.weekdays import weekdays_from_db
from app.schemas.admin_shares import (
    AdminShareRequestCounts,
    AdminShareRequestItem,
    AdminShareRequestPage,
    AdminShareRequestRequester,
    ShareOfferCreate,
    ShareOfferList,
    ShareOfferRead,
    ShareOfferUpdate,
    ShareRequestDecision,
    ShareRequestDecisionResult,
    ShareRequestStatusFilter,
)
from app.services import admin_shares as service
from app.services.pagination import DEFAULT_LIMIT

router = APIRouter(prefix="/admin", tags=["admin"])


def _offer_read(view: service.OfferView) -> ShareOfferRead:
    o = view.offer
    return ShareOfferRead(
        id=o.id,
        slot_id=o.slot_id,
        slot_label=view.slot_label,
        host_id=o.host_id,
        weekdays=weekdays_from_db(o.available_weekdays),
        start_hour=o.start_hour,
        end_hour=o.end_hour,
        hourly_price=o.hourly_price,
        max_hours=o.max_hours,
        memo=o.memo,
        is_public=o.is_public,
    )


def _request_item(view: service.RequestView) -> AdminShareRequestItem:
    r = view.request
    return AdminShareRequestItem(
        id=r.id,
        requester=AdminShareRequestRequester(name=r.requester.name or r.requester.nickname, unit=r.requester.unit_no),
        plate=format_plate(r.vehicle.plate_no) if r.vehicle else None,
        slot_label=view.slot_label,
        request_date=r.request_date,
        start_hour=r.start_hour,
        end_hour=r.end_hour,
        total_price=r.total_price,
        status=share_status_to_api(r.status),
    )


@router.get("/buildings/{building_id}/share-offers", response_model=ShareOfferList, summary="등록한 공유 조건 목록")
async def list_share_offers(building_id: int, user: BuildingAdmin, db: DbSession) -> ShareOfferList:
    views = await service.list_offers(db, building_id)
    return ShareOfferList(items=[_offer_read(v) for v in views])


@router.post(
    "/buildings/{building_id}/share-offers",
    response_model=ShareOfferList,
    status_code=status.HTTP_201_CREATED,
    summary="고른 칸들에 공유 조건 등록",
)
async def create_share_offers(
    building_id: int, payload: ShareOfferCreate, user: BuildingAdmin, db: DbSession
) -> ShareOfferList:
    views = await service.create_offers(db, building_id, user, payload)
    return ShareOfferList(items=[_offer_read(v) for v in views])


@router.patch("/share-offers/{offer_id}", response_model=ShareOfferRead, summary="공유 조건 수정")
async def update_share_offer(
    offer_id: int, payload: ShareOfferUpdate, user: CurrentUser, db: DbSession
) -> ShareOfferRead:
    return _offer_read(await service.update_offer(db, user, offer_id, payload))


@router.delete("/share-offers/{offer_id}", status_code=status.HTTP_204_NO_CONTENT, summary="공유 조건 삭제")
async def delete_share_offer(offer_id: int, user: CurrentUser, db: DbSession) -> Response:
    await service.delete_offer(db, user, offer_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/buildings/{building_id}/share-requests", response_model=AdminShareRequestPage, summary="공유 요청 관리"
)
async def list_share_requests(
    building_id: int,
    user: BuildingAdmin,
    db: DbSession,
    status_filter: Annotated[ShareRequestStatusFilter, Query(alias="status")] = "all",
    q: Annotated[str | None, Query(description="요청자 또는 차량번호 검색")] = None,
    cursor: CursorParam = None,
    limit: LimitParam = DEFAULT_LIMIT,
) -> AdminShareRequestPage:
    result = await service.list_requests(db, building_id, status_filter, q, cursor, limit)
    return AdminShareRequestPage(
        counts=AdminShareRequestCounts(**result.counts),
        items=[_request_item(v) for v in result.page.items],
        next_cursor=result.page.next_cursor,
    )


@router.patch(
    "/share-requests/{share_request_id}", response_model=ShareRequestDecisionResult, summary="공유 요청 수락 / 거절"
)
async def decide_share_request(
    share_request_id: int, payload: ShareRequestDecision, user: CurrentUser, db: DbSession
) -> ShareRequestDecisionResult:
    r = await service.decide(db, user, share_request_id, payload.status, payload.reject_reason)
    return ShareRequestDecisionResult(
        id=r.id, status=share_status_to_api(r.status), reject_reason=r.reject_reason, responded_at=r.responded_at
    )
