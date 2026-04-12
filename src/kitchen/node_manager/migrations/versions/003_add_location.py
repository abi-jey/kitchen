"""add location to node_snapshots

Revision ID: 003_add_location
Revises: 002_add_source_node
Create Date: 2026-04-12 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision = '003_add_location'
down_revision = '002_add_source_node'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('node_snapshots', sa.Column('location', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True))

def downgrade() -> None:
    op.drop_column('node_snapshots', 'location')
