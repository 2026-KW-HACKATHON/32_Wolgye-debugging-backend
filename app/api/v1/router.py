from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin,
    admin_shares,
    auth,
    buildings,
    garages,
    home,
    move_requests,
    notifications,
    parkings,
    share_requests,
    users,
    vehicles,
)
from app.api.v1.endpoints.legacy import alleys as legacy_alleys
from app.api.v1.endpoints.legacy import buildings as legacy_buildings
from app.api.v1.endpoints.legacy import departures as legacy_departures
from app.api.v1.endpoints.legacy import parking_slots as legacy_parking_slots
from app.api.v1.endpoints.legacy import share_offers as legacy_share_offers
from app.api.v1.endpoints.legacy import share_requests as legacy_share_requests
from app.api.v1.endpoints.legacy import vehicles as legacy_vehicles

api_router = APIRouter()

# ── 명세(docs/openapi-mock.yaml) 기준 라우터. 등록은 #4에서 끝났다 → 각자 자기 endpoints 파일만 고친다 ──
api_router.include_router(auth.router)  # 건우 #6
api_router.include_router(users.router)  # 건우 #6
api_router.include_router(buildings.router)  # 건우 #6, 현서 #9
api_router.include_router(home.router)  # 현서 #9
api_router.include_router(vehicles.router)  # 현서 #7
api_router.include_router(parkings.router)  # 현서 #8
api_router.include_router(move_requests.router)  # 현서 #10
api_router.include_router(garages.router)  # 건우 #12
api_router.include_router(share_requests.router)  # 건우 #12
api_router.include_router(admin_shares.router)  # 건우 #13
api_router.include_router(admin.router)  # 건우 #14
api_router.include_router(notifications.router)  # 건우 #11

# ── 구 API. #15에서 legacy 폴더와 함께 지운다. 경로가 같으면 위(새 API)가 먼저 매칭된다 ──
api_router.include_router(legacy_alleys.router)
api_router.include_router(legacy_buildings.router)
api_router.include_router(legacy_parking_slots.router)
api_router.include_router(legacy_vehicles.router)
api_router.include_router(legacy_departures.router)
api_router.include_router(legacy_share_offers.router)
api_router.include_router(legacy_share_requests.router)
