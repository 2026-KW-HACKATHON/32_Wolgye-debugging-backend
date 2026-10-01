from fastapi import APIRouter

from app.api.v1.endpoints import (
    alleys,
    buildings,
    departures,
    parking_slots,
    share_offers,
    share_requests,
    vehicles,
)

api_router = APIRouter()
api_router.include_router(alleys.router)
api_router.include_router(buildings.router)
api_router.include_router(parking_slots.router)
api_router.include_router(vehicles.router)
api_router.include_router(departures.router)
api_router.include_router(share_offers.router)
api_router.include_router(share_requests.router)
