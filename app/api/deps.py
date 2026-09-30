from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


# 엔드포인트에서 `db: DbSession` 으로 주입 (FastAPI 권장 Annotated 방식, 기본값에 Depends() 를 두지 않는다)
DbSession = Annotated[AsyncSession, Depends(get_db)]
