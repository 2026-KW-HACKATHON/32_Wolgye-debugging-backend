from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.resident import Resident
from app.services import auth as auth_service
from app.services.pagination import MAX_LIMIT
from app.services.permissions import ensure_building_admin, ensure_building_exists, ensure_building_member


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


# 엔드포인트에서 `db: DbSession` 으로 주입 (FastAPI 권장 Annotated 방식, 기본값에 Depends() 를 두지 않는다)
DbSession = Annotated[AsyncSession, Depends(get_db)]


# ── 인증 ──────────────────────────────────────────────────────────────
# auto_error=False: 헤더가 없거나 Bearer 가 아니어도 FastAPI 기본 403 대신 아래에서 401 UNAUTHORIZED 로 통일한다
_bearer = HTTPBearer(auto_error=False, description="POST /auth/login 의 access_token")


async def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Resident:
    """`Authorization: Bearer <access_token>` 의 사용자 (JWT, type=access).

    토큰 없음·만료·위조·refresh 토큰·없는 사용자는 401 UNAUTHORIZED.
    """
    return await auth_service.authenticate(db, credentials.credentials if credentials else None)


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
