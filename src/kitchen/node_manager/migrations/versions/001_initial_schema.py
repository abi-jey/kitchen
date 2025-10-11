"""Initial schema for node manager

Revision ID: 001
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create node_snapshots table
    op.create_table('node_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('internal_ip', sa.String(length=45), nullable=True),
        sa.Column('external_ip', sa.String(length=45), nullable=True),
        sa.Column('tailscale_ip', sa.String(length=45), nullable=True),
        sa.Column('hostname', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('ready', sa.Boolean(), nullable=True, default=False),
        sa.Column('schedulable', sa.Boolean(), nullable=True, default=True),
        sa.Column('kubelet_version', sa.String(length=50), nullable=True),
        sa.Column('container_runtime', sa.String(length=100), nullable=True),
        sa.Column('os_image', sa.String(length=255), nullable=True),
        sa.Column('kernel_version', sa.String(length=100), nullable=True),
        sa.Column('cpu_capacity', sa.String(length=20), nullable=True),
        sa.Column('memory_capacity', sa.String(length=20), nullable=True),
        sa.Column('pods_capacity', sa.Integer(), nullable=True),
        sa.Column('conditions', sa.Text(), nullable=True),
        sa.Column('labels', sa.Text(), nullable=True),
        sa.Column('annotations', sa.Text(), nullable=True),
        sa.Column('node_created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('unavailable_since', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for node_snapshots
    op.create_index(op.f('ix_node_snapshots_name'), 'node_snapshots', ['name'], unique=False)
    
    # Create node_connectivity table
    op.create_table('node_connectivity',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('node_name', sa.String(length=255), nullable=False),
        sa.Column('target_ip', sa.String(length=45), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('latency_ms', sa.Float(), nullable=True),
        sa.Column('packet_loss', sa.Float(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('error_code', sa.Integer(), nullable=True),
        sa.Column('ping_count', sa.Integer(), nullable=True, default=4),
        sa.Column('timeout_seconds', sa.Integer(), nullable=True, default=5),
        sa.Column('measured_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for node_connectivity
    op.create_index(op.f('ix_node_connectivity_node_name'), 'node_connectivity', ['node_name'], unique=False)
    op.create_index(op.f('ix_node_connectivity_measured_at'), 'node_connectivity', ['measured_at'], unique=False)


def downgrade() -> None:
    # Drop tables and indexes
    op.drop_index(op.f('ix_node_connectivity_measured_at'), table_name='node_connectivity')
    op.drop_index(op.f('ix_node_connectivity_node_name'), table_name='node_connectivity')
    op.drop_table('node_connectivity')
    
    op.drop_index(op.f('ix_node_snapshots_name'), table_name='node_snapshots')
    op.drop_table('node_snapshots')