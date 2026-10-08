"""차고지 탐색·상세 응답 (명세 GarageListItem, GarageDetail, ShareOfferSummary). 차고지 id = 빌라 id."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.core.weekdays import Weekday, weekdays_from_db
from app.models.share_offer import ShareOffer
from app.schemas.common import KstDatetime
from app.services.garages import GarageDetailData

GarageAvailability = Literal["AVAILABLE", "SOON_EXIT", "RESERVABLE", "UNAVAILABLE"]
GarageSlotState = Literal["AVAILABLE", "SOON_EXIT", "IN_USE"]
ExitSourceName = Literal["MANUAL", "RECURRING", "AI_ESTIMATED", "NONE"]


class GarageListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    garage_id: int
    building_name: str
    slot_id: int
    slot_label: str
    title: str
    availability: GarageAvailability
    hourly_price: int
    info: str | None = None
    estimated_free_at: KstDatetime | None = None
    estimate_source: ExitSourceName | None = None
    available_from: KstDatetime | None = None
    max_hours: int | None = None
    weekdays_only: bool


class ShareOfferSummary(BaseModel):
    id: int
    weekdays: list[Weekday]
    start_hour: int
    end_hour: int
    hourly_price: int
    max_hours: int | None
    memo: str | None

    @classmethod
    def from_model(cls, offer: ShareOffer) -> "ShareOfferSummary":
        return cls(
            id=offer.id,
            weekdays=weekdays_from_db(offer.available_weekdays),
            start_hour=offer.start_hour,
            end_hour=offer.end_hour,
            hourly_price=offer.hourly_price,
            max_hours=offer.max_hours,
            memo=offer.memo,
        )


class IdName(BaseModel):
    id: int
    name: str


class GarageSummaryOut(BaseModel):
    start_hour: int | None
    end_hour: int | None
    min_hourly_price: int | None
    max_hours: int | None


class GarageSlot(BaseModel):
    slot_id: int
    zone: IdName
    number: int
    label: str
    state: GarageSlotState
    estimated_free_at: KstDatetime | None = None
    in_use_until: KstDatetime | None = None
    offer: ShareOfferSummary


class GarageDetail(BaseModel):
    id: int
    name: str
    address: str
    site_key: str | None  # FE 배치도 사이트 파일 키 (BuildingLayout.site_key 와 같다)
    alley: IdName
    summary: GarageSummaryOut
    slots: list[GarageSlot]

    @classmethod
    def from_data(cls, data: GarageDetailData) -> "GarageDetail":
        s = data.summary
        return cls(
            id=data.building.id,
            name=data.building.name,
            address=data.building.address,
            site_key=data.building.site_key,
            alley=IdName(id=data.alley.id, name=data.alley.name),
            summary=GarageSummaryOut(
                start_hour=s.start_hour, end_hour=s.end_hour, min_hourly_price=s.min_hourly_price, max_hours=s.max_hours
            ),
            slots=[
                GarageSlot(
                    slot_id=slot.slot_id,
                    zone=IdName(id=slot.zone.id, name=slot.zone.name),
                    number=slot.number,
                    label=slot.label,
                    state=slot.state,
                    estimated_free_at=slot.estimated_free_at,
                    in_use_until=slot.in_use_until,
                    offer=ShareOfferSummary.from_model(slot.offer),
                )
                for slot in data.slots
            ],
        )
