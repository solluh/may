"""add discount_per_unit to fuel_logs

Revision ID: c1d2e3f4a5b6
Revises: 42b26bf6d488
Create Date: 2026-06-04 19:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = 'c1d2e3f4a5b6'
down_revision = '42b26bf6d488'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'fuel_logs' not in inspector.get_table_names():
        return
    existing_cols = [col['name'] for col in inspector.get_columns('fuel_logs')]
    if 'discount_per_unit' in existing_cols:
        return

    with op.batch_alter_table('fuel_logs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('discount_per_unit', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('fuel_logs', schema=None) as batch_op:
        batch_op.drop_column('discount_per_unit')
