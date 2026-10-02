"""커서 페이지네이션 (결정 14): id 내림차순, next_cursor = 마지막 id, 더 없으면 None."""

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.core.error_codes import ErrorCode
from app.models.alley import Alley
from app.schemas.common import Page
from app.services.exceptions import InvalidInputError
from app.services.pagination import CursorPage, make_page, paginate, parse_cursor
from tests.factories import make_alley

pytestmark = pytest.mark.anyio


class _AlleyItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


async def test_paginate_walks_all_pages_newest_first(db):
    for i in range(5):
        await make_alley(db, f"골목{i}")
    stmt = select(Alley)

    first = await paginate(db, stmt, Alley.id, None, 2)
    assert [a.id for a in first.items] == [5, 4]
    assert first.next_cursor == "4"

    second = await paginate(db, stmt, Alley.id, first.next_cursor, 2)
    assert [a.id for a in second.items] == [3, 2]

    last = await paginate(db, stmt, Alley.id, second.next_cursor, 2)
    assert [a.id for a in last.items] == [1]
    assert last.next_cursor is None


async def test_paginate_exact_limit_has_no_next(db):
    for i in range(2):
        await make_alley(db, f"골목{i}")
    page = await paginate(db, select(Alley), Alley.id, None, 2)
    assert len(page.items) == 2
    assert page.next_cursor is None


async def test_page_schema_from_orm_page(db):
    await make_alley(db, "광운로")
    page = await paginate(db, select(Alley), Alley.id)
    body = Page[_AlleyItem].model_validate(page).model_dump()
    assert body == {"items": [{"id": 1, "name": "광운로"}], "next_cursor": None}


def test_make_page_trims_extra_row():
    page = make_page([10, 9, 8], 2, id_of=lambda x: x)
    assert page == CursorPage(items=[10, 9], next_cursor="9")


@pytest.mark.parametrize("cursor", [None, ""])
def test_parse_empty_cursor(cursor):
    assert parse_cursor(cursor) is None


@pytest.mark.parametrize("cursor", ["abc", "-1", "1.5"])
def test_parse_invalid_cursor(cursor):
    with pytest.raises(InvalidInputError) as exc_info:
        parse_cursor(cursor)
    assert exc_info.value.code == ErrorCode.INVALID_INPUT
