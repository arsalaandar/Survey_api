"""add idempotency key for offline clients

Revision ID: 0003_client_id
Revises: 0002_postgis
"""
from alembic import op

revision = "0003_client_id"
down_revision = "0002_postgis"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE surveys ADD COLUMN IF NOT EXISTS client_id VARCHAR NULL")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_surveys_client_id ON surveys (client_id)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_surveys_client_id")
    op.execute("ALTER TABLE surveys DROP COLUMN IF EXISTS client_id")
