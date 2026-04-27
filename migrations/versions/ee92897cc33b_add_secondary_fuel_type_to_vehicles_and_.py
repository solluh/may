"""add secondary_fuel_type to vehicles and fuel_type to fuel_logs

Revision ID: ee92897cc33b
Revises: b2c3d4e5f6a7
Create Date: 2026-04-22 21:28:46.208340

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ee92897cc33b'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    fuel_log_cols = [c['name'] for c in inspector.get_columns('fuel_logs')]
    if 'fuel_type' not in fuel_log_cols:
        with op.batch_alter_table('fuel_logs', schema=None) as batch_op:
            batch_op.add_column(sa.Column('fuel_type', sa.String(length=20), nullable=True))

    vehicle_cols = [c['name'] for c in inspector.get_columns('vehicles')]
    if 'secondary_fuel_type' not in vehicle_cols:
        with op.batch_alter_table('vehicles', schema=None) as batch_op:
            batch_op.add_column(sa.Column('secondary_fuel_type', sa.String(length=20), nullable=True))


def downgrade():
    with op.batch_alter_table('vehicles', schema=None) as batch_op:
        batch_op.drop_column('secondary_fuel_type')

    with op.batch_alter_table('fuel_logs', schema=None) as batch_op:
        batch_op.drop_column('fuel_type')
