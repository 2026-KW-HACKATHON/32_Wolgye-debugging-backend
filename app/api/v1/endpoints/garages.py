"""차고지 탐색 (명세 tag garages): GET /garages, GET /garages/{garage_id}

담당: 건우 #12. 엔드포인트는 이 파일에만 추가한다 (router.py 는 이미 등록됨)."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, CursorParam, DbSession, LimitParam
from app.schemas.common import Page
from app.schemas.garage import GarageDetail, GarageListItem
from app.services import garages as garage_service
from app.services.garages import GarageFilter
from app.services.pagination import DEFAULT_LIMIT

router = APIRouter(prefix="/garages", tags=["garages"])


@router.get("", response_model=Page[GarageListItem], summary="공유 주차 탐색")
async def list_garages(
    user: CurrentUser,
    db: DbSession,
    lat: float | None = None,
    lng: float | None = None,
    q: Annotated[str | None, Query(description="주소·빌라명 검색")] = None,
    filter_: Annotated[GarageFilter, Query(alias="filter")] = "all",
    cursor: CursorParam = None,
    limit: LimitParam = DEFAULT_LIMIT,
) -> Page[GarageListItem]:
    page = await garage_service.list_garages(
        db, user, lat=lat, lng=lng, q=q, filter_=filter_, cursor=cursor, limit=limit
    )
    return Page(items=[GarageListItem.model_validate(e) for e in page.items], next_cursor=page.next_cursor)


@router.get("/{garage_id}", response_model=GarageDetail, summary="차고지 상세")
async def get_garage(garage_id: int, user: CurrentUser, db: DbSession) -> GarageDetail:
    return GarageDetail.from_data(await garage_service.get_garage(db, user, garage_id))
