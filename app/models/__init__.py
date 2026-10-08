"""모든 ORM 모델을 한 곳에서 등록한다.

relationship("Garage") 같은 문자열 참조는 매퍼 설정 시점에 대상 클래스가 import 되어 있어야 해석된다.
`app.models` 를 import 하는 것만으로 전체 모델이 등록되도록 여기서 모두 import 한다.
"""

from app.models.alley import Alley
from app.models.building import Building
from app.models.departure_schedule import DepartureSchedule
from app.models.garage import Garage
from app.models.move_request import MoveRequest
from app.models.notification import Notification
from app.models.parking_assignment import ParkingAssignment
from app.models.parking_slot import ParkingSlot
from app.models.resident import Resident
from app.models.share_offer import ShareOffer
from app.models.share_request import ShareRequest
from app.models.token_transfer import TokenTransfer
from app.models.vehicle import Vehicle
from app.models.vehicle_report import VehicleReport

__all__ = [
    "Alley",
    "Building",
    "DepartureSchedule",
    "Garage",
    "MoveRequest",
    "Notification",
    "ParkingAssignment",
    "ParkingSlot",
    "Resident",
    "ShareOffer",
    "ShareRequest",
    "TokenTransfer",
    "Vehicle",
    "VehicleReport",
]
