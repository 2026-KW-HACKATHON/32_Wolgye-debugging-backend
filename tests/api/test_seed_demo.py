"""#36 시드 데이터: FE 시연 흐름에 필요한 계정·빌라·칸·주차가 API 로 보이는지 확인한다."""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.seed_demo import DEMO_PASSWORD, seed
from app.models.building import Building
from tests.factories import make_resident

pytestmark = pytest.mark.anyio


async def _login(client: AsyncClient, email: str) -> dict[str, str]:
    res = await client.post("/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def test_seed_runs_once(db: AsyncSession):
    assert (await seed(db)).created
    assert not (await seed(db)).created
    assert await db.scalar(select(func.count()).select_from(Building)) == 2


async def test_seed_skips_when_email_taken(db: AsyncSession):
    await make_resident(db, email="admin@chagok.dev")
    result = await seed(db)
    assert not result.created
    assert "admin@chagok.dev" in result.reason
    assert await db.scalar(select(func.count()).select_from(Building)) == 0


async def test_resident_jisu(db: AsyncSession, client: AsyncClient):
    result = await seed(db)
    headers = await _login(client, "jisu@chagok.dev")

    me = (await client.get("/api/v1/users/me", headers=headers)).json()
    assert me["onboarding_step"] == "DONE"
    assert me["token_balance"] == 500_000

    vehicles = (await client.get("/api/v1/me/vehicles", headers=headers)).json()["items"]
    assert [(v["plate"], v["color"], v["is_default"]) for v in vehicles] == [("12가 3456", "흰색", True)]

    status = (await client.get(f"/api/v1/buildings/{result.hanbit_id}/status", headers=headers)).json()
    assert not any(s["parking"] and s["parking"]["is_mine"] for s in status["slots"])  # 처음엔 주차 안 함


async def test_hanbit_layout_and_status(db: AsyncSession, client: AsyncClient):
    result = await seed(db)
    headers = await _login(client, "jisu@chagok.dev")

    layout = (await client.get(f"/api/v1/buildings/{result.hanbit_id}/layout", headers=headers)).json()
    slots = {s["label"]: s for zone in layout["zones"] for s in zone["slots"]}
    assert list(slots) == [f"P{i}" for i in range(1, 9)]
    assert [label for label, s in slots.items() if not s["is_active"]] == ["P8"]

    status = (await client.get(f"/api/v1/buildings/{result.hanbit_id}/status", headers=headers)).json()
    label_of = {s["id"]: label for label, s in slots.items()}
    occupants = {label_of[s["slot_id"]]: s["parking"]["occupant_type"] for s in status["slots"] if s["parking"]}
    assert occupants == {"P2": "RESIDENT", "P3": "EXTERNAL", "P4": "RESIDENT", "P6": "UNKNOWN"}
    states = {label_of[s["slot_id"]]: s["state"] for s in status["slots"]}
    assert states["P4"] == "SOON_EXIT"
    assert states["P8"] == "UNAVAILABLE"


async def test_admin_and_share_flow_accounts(db: AsyncSession, client: AsyncClient):
    result = await seed(db)

    admin = await _login(client, "admin@chagok.dev")
    res = await client.get(f"/api/v1/admin/buildings/{result.hanbit_id}/share-offers", headers=admin)
    assert sorted(o["slot_label"] for o in res.json()["items"]) == ["P3", "P7"]

    jisu = await _login(client, "jisu@chagok.dev")
    garages = (await client.get("/api/v1/garages", headers=jisu)).json()["items"]
    assert {g["garage_id"] for g in garages} == {result.sunny_id}
    assert len(garages) == 5

    sunny_admin = await _login(client, "sunny-admin@chagok.dev")
    res = await client.get(f"/api/v1/admin/buildings/{result.sunny_id}/share-offers", headers=sunny_admin)
    assert len(res.json()["items"]) == 5
