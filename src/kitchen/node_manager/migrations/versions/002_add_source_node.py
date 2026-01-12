"""Add source_node to node_connectivity table.

Revision ID: 002
Revises: 001
Create Date: 2026-01-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add source_node column with default value
    op.add_column(
        'node_connectivity',
        sa.Column('source_node', sa.String(255), nullable=False, server_default='node-manager')
    )
    # Create index on source_node for faster queries
    op.create_index('ix_node_connectivity_source_node', 'node_connectivity', ['source_node'])


def downgrade() -> None:
    op.drop_index('ix_node_connectivity_source_node', 'node_connectivity')
    op.drop_column('node_connectivity', 'source_node')
