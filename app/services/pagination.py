"""커서 페이지네이션 (결정 14). 최신순(id 내림차순), next_cursor = 마지막 항목 id 문자열, 더 없으면 None.

사용 예 (서비스):
    stmt = select(Notification).where(Notification.resident_id == user.id)
    return await paginate(db, stmt, Notification.id, cursor, limit)

엔드포인트는 `response_model=Page[NotificationRead]` (app/schemas/common.py) 로 그대로 돌려준다.
쿼리 파라미터는 app/api/deps.py 의 CursorParam / LimitParam 을 쓴다.
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.services.exceptions import InvalidInputError

DEFAULT_LIMIT = 20
MAX_LIMIT = 50


@dataclass
class CursorPage[T]:
    """서비스가 돌려주는 한 페이지. Page[T] 스키마와 같은 모양."""

    items: list[T] = field(default_factory=list)
    next_cursor: str | None = None


def parse_cursor(cursor: str | None) -> int | None:
    """next_cursor 문자열 → id. 비어 있으면 None, 숫자가 아니면 400 INVALID_INPUT."""
    if cursor is None or cursor == "":
        return None
    if not cursor.isdigit():
        raise InvalidInputError("cursor 값이 올바르지 않습니다.", detail={"field": "cursor", "reason": "숫자 문자열이어야 합니다."})
    return int(cursor)


def apply_cursor[S: Select[Any]](stmt: S, id_column: InstrumentedAttribute[int], cursor: str | None, limit: int) -> S:
    """stmt 에 `id < cursor`, `ORDER BY id DESC`, `LIMIT limit + 1` 을 붙인다 (다음 페이지 유무 확인용 1개 더)."""
    after = parse_cursor(cursor)
    if after is not None:
        stmt = stmt.where(id_column < after)
    return stmt.order_by(id_column.desc()).limit(limit + 1)


def make_page[T](rows: list[T], limit: int, id_of: Any = None) -> CursorPage[T]:
    """apply_cursor 로 limit + 1 개까지 가져온 rows 를 한 페이지로 자른다. id_of 기본은 `row.id`."""
    get_id = id_of or (lambda row: row.id)
    if len(rows) > limit:
        items = rows[:limit]
        return CursorPage(items=items, next_cursor=str(get_id(items[-1])))
    return CursorPage(items=rows, next_cursor=None)


async def paginate[T](
    db: AsyncSession,
    stmt: Select[tuple[T]],
    id_column: InstrumentedAttribute[int],
    cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> CursorPage[T]:
    """ORM 엔티티 하나를 고르는 select 에 커서를 적용해 실행하고 한 페이지를 돌려준다."""
    result = await db.execute(apply_cursor(stmt, id_column, cursor, limit))
    return make_page(list(result.scalars().all()), limit)
