"""미등록 차량 제보 (#52) 응답 스키마. 명세 VehicleReportCreated / VehicleReportDetail.

요청은 multipart/form-data (photo, plate, slot_id) 라 스키마 대신 엔드포인트의 Form/File 로 받는다.
"""

from typing import Literal

from pydantic import BaseModel

from app.schemas.admin import OccupantType
from app.schemas.common import KstDatetime, PlateOut

VehicleReportStatusName = Literal["SUBMITTED", "DISMISSED"]


class VehicleReportCreated(BaseModel):
    report_id: int
    vehicle_id: int
    parking_id: int
    slot_label: str
    occupant_type: OccupantType  # 항상 UNKNOWN
    reward_tokens: int
    token_balance: int  # 보상 지급 후 내 잔액


class VehicleReportReporter(BaseModel):
    id: int
    name: str  # 이름이 없으면 닉네임


class VehicleReportDetail(BaseModel):
    id: int
    building_id: int
    plate: PlateOut
    slot_label: str
    photo_url: str  # API 기준 경로 (/vehicle-reports/{id}/photo). Bearer 인증으로 받는다
    reporter: VehicleReportReporter
    status: VehicleReportStatusName
    created_at: KstDatetime
