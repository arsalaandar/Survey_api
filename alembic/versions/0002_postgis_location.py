"""add indexed PostGIS survey geography

Revision ID: 0002_postgis
Revises: 0001_initial
"""
from alembic import op

revision = "0002_postgis"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("ALTER TABLE surveys ADD COLUMN IF NOT EXISTS location geography(Point,4326)")
    op.execute("UPDATE surveys SET location = ST_SetSRID(ST_MakePoint(longitude, latitude),4326)::geography WHERE location IS NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_surveys_location_gist ON surveys USING GIST (location)")

def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_surveys_location_gist")
    op.execute("ALTER TABLE surveys DROP COLUMN IF EXISTS location")
