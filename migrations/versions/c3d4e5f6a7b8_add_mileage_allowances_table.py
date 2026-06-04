"""add mileage_allowances table and show_menu_allowance preference

Revision ID: c3d4e5f6a7b8
Revises: c2d3e4f5a6b7
Create Date: 2026-06-04 19:02:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = 'c3d4e5f6a7b8'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if 'mileage_allowances' not in inspector.get_table_names():
        op.create_table(
            'mileage_allowances',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('vehicle_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('date', sa.Date(), nullable=False),
            sa.Column('description', sa.String(length=200), nullable=True),
            sa.Column('distance', sa.Float(), nullable=True),
            sa.Column('rate_per_unit', sa.Float(), nullable=True),
            sa.Column('amount', sa.Float(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id']),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    if 'users' in inspector.get_table_names():
        user_cols = [col['name'] for col in inspector.get_columns('users')]
        if 'show_menu_allowance' not in user_cols:
            with op.batch_alter_table('users', schema=None) as batch_op:
                batch_op.add_column(sa.Column('show_menu_allowance', sa.Boolean(), nullable=True, server_default=sa.true()))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('show_menu_allowance')
    op.drop_table('mileage_allowances')
