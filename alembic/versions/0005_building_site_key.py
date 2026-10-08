"""buildings.site_key for FE site layout files

FE 가 빌라별 배치도(건물·벽·입구·칸 좌표)를 public/sites/{site_key}.json 으로 가지고,
백엔드는 키만 내려준다 (#47). 이미 들어간 시연 시드 빌라는 초대코드로 찾아 키를 채운다.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-08 12:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('buildings', sa.Column('site_key', sa.String(length=40), nullable=True))
    op.execute("UPDATE buildings SET site_key = 'hanbit' WHERE invite_code = 'HANBIT01'")
    op.execute("UPDATE buildings SET site_key = 'sunny' WHERE invite_code = 'SUNNY01'")


def downgrade() -> None:
    op.drop_column('buildings', 'site_key')
