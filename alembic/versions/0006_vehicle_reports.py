"""vehicle reports

미등록 차량 사진 제보 (#52).
- vehicle_reports 테이블 (사진은 파일로 두고 photo_key 만 저장)
- 알림 종류 VEHICLE_REPORT + notifications.vehicle_report_id (알림 탭 → 제보 상세)

PostgreSQL 은 enum 값을 지울 수 없어 downgrade 는 0004 처럼 타입을 새로 만들어 바꿔 끼운다.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-08 23:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_NOTIFICATION_TYPES = ('BLOCK_ALERT', 'MOVE_REQUEST', 'EXIT_DONE', 'SHARE_REQUEST', 'SHARE_RESULT')


def upgrade() -> None:
    op.create_table(
        'vehicle_reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('building_id', sa.Integer(), nullable=False),
        sa.Column('reporter_id', sa.Integer(), nullable=False),
        sa.Column('slot_id', sa.Integer(), nullable=False),
        sa.Column('vehicle_id', sa.Integer(), nullable=True),
        sa.Column('parking_assignment_id', sa.Integer(), nullable=True),
        sa.Column('plate_no', sa.String(length=20), nullable=False),
        sa.Column('photo_key', sa.String(length=64), nullable=False),
        sa.Column(
            'status',
            sa.Enum('SUBMITTED', 'DISMISSED', name='vehicle_report_status'),
            server_default='SUBMITTED',
            nullable=False,
        ),
        sa.Column('reward_amount', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('reward_amount >= 0', name='ck_vehicle_report_reward'),
        sa.ForeignKeyConstraint(['building_id'], ['buildings.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parking_assignment_id'], ['parking_assignments.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reporter_id'], ['residents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['slot_id'], ['parking_slots.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_vehicle_reports_building', 'vehicle_reports', ['building_id', 'id'], unique=False)
    op.create_index(
        'ix_vehicle_reports_reporter_created', 'vehicle_reports', ['reporter_id', 'created_at'], unique=False
    )

    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'VEHICLE_REPORT'")
    op.add_column('notifications', sa.Column('vehicle_report_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'notifications_vehicle_report_id_fkey',
        'notifications',
        'vehicle_reports',
        ['vehicle_report_id'],
        ['id'],
        ondelete='CASCADE',
    )


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE type = 'VEHICLE_REPORT'")
    op.drop_constraint('notifications_vehicle_report_id_fkey', 'notifications', type_='foreignkey')
    op.drop_column('notifications', 'vehicle_report_id')

    labels = ", ".join(f"'{v}'" for v in OLD_NOTIFICATION_TYPES)
    op.execute("ALTER TYPE notification_type RENAME TO notification_type_old")
    op.execute(f"CREATE TYPE notification_type AS ENUM ({labels})")
    op.execute(
        "ALTER TABLE notifications ALTER COLUMN type TYPE notification_type USING type::text::notification_type"
    )
    op.execute("DROP TYPE notification_type_old")

    op.drop_index('ix_vehicle_reports_reporter_created', table_name='vehicle_reports')
    op.drop_index('ix_vehicle_reports_building', table_name='vehicle_reports')
    op.drop_table('vehicle_reports')
    op.execute("DROP TYPE vehicle_report_status")
