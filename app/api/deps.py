from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.resident import Resident
from app.services.exceptions import UnauthorizedError
from app.services.pagination import MAX_LIMIT
from app.services.permissions import ensure_building_admin, ensure_building_exists, ensure_building_member


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


# 엔드포인트에서 `db: DbSession` 으로 주입 (FastAPI 권장 Annotated 방식, 기본값에 Depends() 를 두지 않는다)
DbSession = Annotated[AsyncSession, Depends(get_db)]


# ── 인증 ──────────────────────────────────────────────────────────────
async def get_current_user(
    db: DbSession,
    x_user_id: Annotated[str | None, Header(alias="X-User-Id", description="임시 인증(#6 전까지): 로그인한 resident id")] = None,
) -> Resident:
    """로그인한 사용자. 없거나 확인할 수 없으면 401 UNAUTHORIZED.

    TODO(#6): 임시 구현이다. `X-User-Id` 헤더의 resident id 를 그대로 믿는다.
    #6에서 `Authorization: Bearer <access_token>` 검증(JWT, type=access)으로 교체한다.
    교체해도 이 함수 이름과 반환 타입(Resident)은 유지한다 → 엔드포인트는 고칠 필요 없음.
    """
    if x_user_id is None or not x_user_id.isdigit():
        raise UnauthorizedError()
    user = await db.get(Resident, int(x_user_id))
    if user is None:
        raise UnauthorizedError()
    return user


# 엔드포인트에서 `user: CurrentUser`
CurrentUser = Annotated[Resident, Depends(get_current_user)]


# ── 빌라 권한 (경로에 {building_id} 가 있는 엔드포인트용) ───────────────────
async def require_building_member(building_id: int, user: CurrentUser, db: DbSession) -> Resident:
    """빌라가 없으면 404 NOT_FOUND, 소속(입주민·관리인)이 아니면 403 NOT_BUILDING_MEMBER. 통과하면 user 를 돌려준다."""
    await ensure_building_exists(db, building_id)
    ensure_building_member(user, building_id)
    return user


async def require_building_admin(building_id: int, user: CurrentUser, db: DbSession) -> Resident:
    """빌라가 없으면 404 NOT_FOUND, 관리인(role = MANAGER)이 아니면 403 NOT_BUILDING_ADMIN. 통과하면 user 를 돌려준다."""
    await ensure_building_exists(db, building_id)
    ensure_building_admin(user, building_id)
    return user


# 엔드포인트에서 `user: BuildingMember` / `user: BuildingAdmin` (경로에 {building_id} 필요)
BuildingMember = Annotated[Resident, Depends(require_building_member)]
BuildingAdmin = Annotated[Resident, Depends(require_building_admin)]


# ── 페이지네이션 쿼리 (결정 14) ──────────────────────────────────────────
# 엔드포인트에서 `cursor: CursorParam = None, limit: LimitParam = DEFAULT_LIMIT` (DEFAULT_LIMIT 는 app.services.pagination)
CursorParam = Annotated[str | None, Query(description="이전 응답의 next_cursor")]
LimitParam = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
