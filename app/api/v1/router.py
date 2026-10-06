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
