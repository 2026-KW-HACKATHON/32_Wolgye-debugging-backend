"""notification types follow the Figma wireframe

Figma 와이어프레임 기준 2026-10-01: 알림은 화면에 나오는 5종만 둔다.
- DEPARTURE_REMINDER → BLOCK_ALERT (전날 밤 사전 알림도 막힘 알림에 포함)
- SHARE_RESPONSE → SHARE_RESULT
- EXIT_DONE 추가 (출차 완료 안내)
- MOVE_RESPONSE 제거 (요청자용 "옮겼어요" 결과 알림이 화면에 없음)

데이터 처리:
- MOVE_RESPONSE 알림은 옮길 값이 없어 삭제한다. downgrade 에서는 EXIT_DONE 알림을 삭제한다.
- PostgreSQL 은 enum 값을 지울 수 없어 타입을 새로 만들어 바꿔 끼운다.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-01 22:30:00

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_VALUES = ('BLOCK_ALERT', 'MOVE_REQUEST', 'EXIT_DONE', 'SHARE_REQUEST', 'SHARE_RESULT')
OLD_VALUES = ('DEPARTURE_REMINDER', 'SHARE_REQUEST', 'SHARE_RESPONSE', 'MOVE_REQUEST', 'MOVE_RESPONSE')


def _swap_type(values: tuple[str, ...], mapping: dict[str, str]) -> None:
    """notification_type 을 values 로 다시 만들고, 기존 값은 mapping 대로 옮긴다."""
    labels = ", ".join(f"'{v}'" for v in values)
    cases = " ".join(f"WHEN '{old}' THEN '{new}'" for old, new in mapping.items())
    op.execute("ALTER TYPE notification_type RENAME TO notification_type_old")
    op.execute(f"CREATE TYPE notification_type AS ENUM ({labels})")
    op.execute(
        "ALTER TABLE notifications ALTER COLUMN type TYPE notification_type "
        f"USING (CASE type::text {cases} ELSE type::text END)::notification_type"
    )
    op.execute("DROP TYPE notification_type_old")


def upgrade() -> None:
    op.execute("DELETE FROM notifications WHERE type = 'MOVE_RESPONSE'")
    _swap_type(NEW_VALUES, {'DEPARTURE_REMINDER': 'BLOCK_ALERT', 'SHARE_RESPONSE': 'SHARE_RESULT'})


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE type = 'EXIT_DONE'")
    _swap_type(OLD_VALUES, {'BLOCK_ALERT': 'DEPARTURE_REMINDER', 'SHARE_RESULT': 'SHARE_RESPONSE'})
