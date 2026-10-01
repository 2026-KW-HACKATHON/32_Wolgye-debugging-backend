"""alley > building > garage > slot, share offers, tokens

기획(Manyfast) 충돌 정리 2026-10-01:
- 골목(alleys)을 최상위로: 골목 > 빌라(buildings) > 차고지(garages) > 칸(parking_slots)
- 구역(parking_zones)을 차고지(garages)로 바꾼다. 기존 시간제 공유 garages 표는 없앤다.
- 공유 설정을 칸별 share_offers 하나로 (기간 start_date~end_date, 요일, 정시 단위 시간, 시간당 토큰, 공개 여부).
  parking_slots.is_shareable / garage_id(공유 묶음) 제거.
- 공유 요청은 정시 단위(start_hour/end_hour)로, offer 를 참조하고 total_price(토큰)를 기록.
- 결제는 토큰만: residents.token_balance + token_transfers.

데이터 처리:
- 빌라가 있으면 '기본 골목'을 하나 만들어 모두 연결한다.
- 기존 garages(공유 설정)와 share_requests 는 새 구조(offer 필수)로 옮길 수 없어 삭제한다.
  share_requests 를 원인으로 둔 알림도 FK CASCADE 로 함께 삭제된다.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-01 20:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SHARE_OVERLAP = (
    "tsrange(request_date + make_interval(hours => start_hour), "
    "request_date + make_interval(hours => end_hour))"
)


def _exclude_overlap(time_range: str) -> str:
    """같은 칸에 수락된 요청끼리 시간이 겹치지 않게 (op.create_exclude_constraint 는 식(text)을 받지 못한다)."""
    return (
        "ALTER TABLE share_requests ADD CONSTRAINT ex_share_accepted_overlap "
        f"EXCLUDE USING gist (slot_id WITH =, ({time_range}) WITH &&) WHERE (status = 'ACCEPTED')"
    )


def upgrade() -> None:
    # --- 골목 ---------------------------------------------------------------
    op.create_table('alleys',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.add_column('buildings', sa.Column('alley_id', sa.Integer(), nullable=True))
    op.execute(
        "INSERT INTO alleys (name) SELECT '기본 골목' WHERE EXISTS (SELECT 1 FROM buildings)"
    )
    op.execute("UPDATE buildings SET alley_id = (SELECT min(id) FROM alleys)")
    op.alter_column('buildings', 'alley_id', nullable=False)
    op.create_foreign_key('buildings_alley_id_fkey', 'buildings', 'alleys', ['alley_id'], ['id'], ondelete='CASCADE')

    # --- 기존 공유 설정(garages) 제거 ----------------------------------------
    op.drop_constraint('parking_slots_garage_id_fkey', 'parking_slots', type_='foreignkey')
    op.drop_column('parking_slots', 'garage_id')
    op.drop_column('parking_slots', 'is_shareable')
    op.drop_table('garages')

    # --- 구역(parking_zones) → 차고지(garages) --------------------------------
    op.rename_table('parking_zones', 'garages')
    op.execute("ALTER SEQUENCE parking_zones_id_seq RENAME TO garages_id_seq")
    op.execute("ALTER INDEX parking_zones_pkey RENAME TO garages_pkey")
    op.execute("ALTER TABLE garages RENAME CONSTRAINT parking_zones_building_id_fkey TO garages_building_id_fkey")
    op.execute("ALTER TABLE garages RENAME CONSTRAINT uq_zone_name_per_building TO uq_garage_name_per_building")
    op.alter_column('garages', 'zone_type', new_column_name='garage_type')
    op.execute("ALTER TYPE zone_type RENAME TO garage_type")
    # '골목'이 최상위 엔티티 이름이 되어 칸 종류의 ALLEY 는 ROADSIDE(골목 노상)로 바꾼다
    op.execute("ALTER TYPE garage_type RENAME VALUE 'ALLEY' TO 'ROADSIDE'")

    op.alter_column('parking_slots', 'zone_id', new_column_name='garage_id')
    op.execute("ALTER TABLE parking_slots RENAME CONSTRAINT parking_slots_zone_id_fkey TO parking_slots_garage_id_fkey")
    op.execute("ALTER TABLE parking_slots RENAME CONSTRAINT uq_slot_number_per_zone TO uq_slot_number_per_garage")

    # --- 토큰 -----------------------------------------------------------------
    op.add_column('residents', sa.Column('token_balance', sa.Integer(), server_default='0', nullable=False))
    op.create_check_constraint('ck_resident_token_balance', 'residents', 'token_balance >= 0')

    # --- 공유 조건(share_offers) ----------------------------------------------
    op.create_table('share_offers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('slot_id', sa.Integer(), nullable=False),
    sa.Column('host_id', sa.Integer(), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=False),
    sa.Column('available_weekdays', sa.ARRAY(sa.Integer()), server_default=sa.text("'{0,1,2,3,4,5,6}'"), nullable=False),
    sa.Column('start_hour', sa.SmallInteger(), nullable=False),
    sa.Column('end_hour', sa.SmallInteger(), nullable=False),
    sa.Column('hourly_price', sa.Integer(), server_default='0', nullable=False),
    sa.Column('max_hours', sa.Integer(), nullable=True),
    sa.Column('memo', sa.Text(), nullable=True),
    sa.Column('is_public', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('start_date <= end_date', name='ck_share_offer_dates'),
    sa.CheckConstraint('0 <= start_hour AND start_hour < end_hour AND end_hour <= 24', name='ck_share_offer_hours'),
    sa.CheckConstraint('available_weekdays <@ ARRAY[0,1,2,3,4,5,6]', name='ck_share_offer_weekdays'),
    sa.CheckConstraint('hourly_price >= 0', name='ck_share_offer_price'),
    sa.CheckConstraint('max_hours IS NULL OR max_hours > 0', name='ck_share_offer_max_hours'),
    sa.ForeignKeyConstraint(['host_id'], ['residents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['slot_id'], ['parking_slots.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'slot_id', name='uq_share_offer_id_slot')
    )

    # --- 공유 요청: 정시 단위 + offer 참조 + 토큰 가격 ----------------------------
    op.execute("DELETE FROM share_requests")
    op.drop_constraint('ex_share_accepted_overlap', 'share_requests')
    op.drop_constraint('ck_share_time_order', 'share_requests', type_='check')
    op.drop_column('share_requests', 'start_time')
    op.drop_column('share_requests', 'end_time')
    op.add_column('share_requests', sa.Column('offer_id', sa.Integer(), nullable=False))
    op.add_column('share_requests', sa.Column('start_hour', sa.SmallInteger(), nullable=False))
    op.add_column('share_requests', sa.Column('end_hour', sa.SmallInteger(), nullable=False))
    op.add_column('share_requests', sa.Column('total_price', sa.Integer(), nullable=False))
    op.create_check_constraint(
        'ck_share_request_hours', 'share_requests', '0 <= start_hour AND start_hour < end_hour AND end_hour <= 24'
    )
    op.create_check_constraint('ck_share_request_price', 'share_requests', 'total_price >= 0')
    op.create_foreign_key(
        'fk_share_request_offer_slot', 'share_requests', 'share_offers',
        ['offer_id', 'slot_id'], ['id', 'slot_id'], ondelete='CASCADE',
    )
    op.execute(_exclude_overlap(SHARE_OVERLAP))

    # --- 토큰 이동 기록 ---------------------------------------------------------
    op.create_table('token_transfers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('sender_id', sa.Integer(), nullable=True),
    sa.Column('receiver_id', sa.Integer(), nullable=True),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('share_request_id', sa.Integer(), nullable=True),
    sa.Column('memo', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('amount > 0', name='ck_token_transfer_amount'),
    sa.CheckConstraint('sender_id IS NULL OR sender_id <> receiver_id', name='ck_token_transfer_distinct'),
    sa.ForeignKeyConstraint(['receiver_id'], ['residents.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['sender_id'], ['residents.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['share_request_id'], ['share_requests.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    # 공유 요청·공유 조건·토큰 기록은 0002 구조로 옮길 수 없어 삭제한다.
    op.drop_table('token_transfers')

    op.execute("DELETE FROM share_requests")
    op.drop_constraint('ex_share_accepted_overlap', 'share_requests')
    op.drop_constraint('fk_share_request_offer_slot', 'share_requests', type_='foreignkey')
    op.drop_constraint('ck_share_request_price', 'share_requests', type_='check')
    op.drop_constraint('ck_share_request_hours', 'share_requests', type_='check')
    op.drop_column('share_requests', 'total_price')
    op.drop_column('share_requests', 'end_hour')
    op.drop_column('share_requests', 'start_hour')
    op.drop_column('share_requests', 'offer_id')
    op.add_column('share_requests', sa.Column('start_time', sa.Time(), nullable=False))
    op.add_column('share_requests', sa.Column('end_time', sa.Time(), nullable=False))
    op.create_check_constraint('ck_share_time_order', 'share_requests', 'start_time < end_time')
    op.execute(_exclude_overlap('tsrange(request_date + start_time, request_date + end_time)'))

    op.drop_table('share_offers')

    op.drop_constraint('ck_resident_token_balance', 'residents', type_='check')
    op.drop_column('residents', 'token_balance')

    op.execute("ALTER TABLE parking_slots RENAME CONSTRAINT uq_slot_number_per_garage TO uq_slot_number_per_zone")
    op.execute("ALTER TABLE parking_slots RENAME CONSTRAINT parking_slots_garage_id_fkey TO parking_slots_zone_id_fkey")
    op.alter_column('parking_slots', 'garage_id', new_column_name='zone_id')

    op.execute("ALTER TYPE garage_type RENAME VALUE 'ROADSIDE' TO 'ALLEY'")
    op.execute("ALTER TYPE garage_type RENAME TO zone_type")
    op.alter_column('garages', 'garage_type', new_column_name='zone_type')
    op.execute("ALTER TABLE garages RENAME CONSTRAINT uq_garage_name_per_building TO uq_zone_name_per_building")
    op.execute("ALTER TABLE garages RENAME CONSTRAINT garages_building_id_fkey TO parking_zones_building_id_fkey")
    op.execute("ALTER INDEX garages_pkey RENAME TO parking_zones_pkey")
    op.execute("ALTER SEQUENCE garages_id_seq RENAME TO parking_zones_id_seq")
    op.rename_table('garages', 'parking_zones')

    op.create_table('garages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('building_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('available_start', sa.Time(), nullable=False),
    sa.Column('available_end', sa.Time(), nullable=False),
    sa.Column('available_weekdays', sa.ARRAY(sa.Integer()), server_default=sa.text("'{0,1,2,3,4,5,6}'"), nullable=False),
    sa.Column('hourly_fee', sa.Integer(), server_default='0', nullable=False),
    sa.Column('max_hours', sa.Integer(), nullable=True),
    sa.Column('memo', sa.Text(), nullable=True),
    sa.Column('is_public', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('available_start < available_end', name='ck_garage_available_time'),
    sa.CheckConstraint('available_weekdays <@ ARRAY[0,1,2,3,4,5,6]', name='ck_garage_weekdays'),
    sa.CheckConstraint('hourly_fee >= 0', name='ck_garage_fee'),
    sa.CheckConstraint('max_hours IS NULL OR max_hours > 0', name='ck_garage_max_hours'),
    sa.ForeignKeyConstraint(['building_id'], ['buildings.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.add_column('parking_slots', sa.Column('is_shareable', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('parking_slots', sa.Column('garage_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'parking_slots_garage_id_fkey', 'parking_slots', 'garages', ['garage_id'], ['id'], ondelete='SET NULL'
    )

    op.drop_constraint('buildings_alley_id_fkey', 'buildings', type_='foreignkey')
    op.drop_column('buildings', 'alley_id')
    op.drop_table('alleys')
