"""add notes table and show_menu_notes preference

Revision ID: c2d3e4f5a6b7
Revises: c1d2e3f4a5b6
Create Date: 2026-06-04 19:01:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = 'c2d3e4f5a6b7'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if 'notes' not in inspector.get_table_names():
        op.create_table(
            'notes',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('vehicle_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('date', sa.Date(), nullable=False),
            sa.Column('title', sa.String(length=200), nullable=True),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('odometer', sa.Float(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id']),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    if 'users' in inspector.get_table_names():
        user_cols = [col['name'] for col in inspector.get_columns('users')]
        if 'show_menu_notes' not in user_cols:
            with op.batch_alter_table('users', schema=None) as batch_op:
                batch_op.add_column(sa.Column('show_menu_notes', sa.Boolean(), nullable=True, server_default=sa.true()))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('show_menu_notes')
    op.drop_table('notes')
