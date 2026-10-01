import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import get_db
from app.core.config import get_settings
from app.db.base import Base
from app.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _ensure_disposable_db(url: str) -> None:
    """테스트는 매번 전체 테이블을 TRUNCATE 한다 → 개발 DB 를 지우지 않도록 막는다.
    DB 이름이 `_test` 로 끝나거나 CI 환경(GitHub Actions 는 CI=true)일 때만 허용."""
    name = make_url(url).database or ""
    if not (name.endswith("_test") or os.environ.get("CI")):
        pytest.exit(f"DB '{name}' 는 테스트용이 아닙니다. DATABASE_URL 을 *_test DB 로 지정하세요.", returncode=2)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    url = get_settings().database_url
    _ensure_disposable_db(url)
    # 테스트마다 이벤트 루프가 바뀌므로 커넥션을 재사용하지 않는다 (NullPool)
    engine = create_async_engine(url, poolclass=NullPool)
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # app/db/session.py 와 같은 설정
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)


@pytest.fixture
async def db(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """테스트 데이터 준비·서비스 직접 호출용 세션."""
    async with session_factory() as session:
        yield session


@pytest.fixture
async def client(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncClient]:
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
