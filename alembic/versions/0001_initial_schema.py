"""initial legacy-compatible schema

Revision ID: 0001_initial
Revises:
"""
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # IF NOT EXISTS makes the baseline safe for the existing PostgreSQL dev DB.
    op.execute("CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username VARCHAR NOT NULL UNIQUE, password_hash VARCHAR NOT NULL, role VARCHAR NOT NULL)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_id ON users (id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_username ON users (username)")
    op.execute("""CREATE TABLE IF NOT EXISTS surveys (
        id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), form_id VARCHAR,
        point_id VARCHAR, latitude DOUBLE PRECISION NOT NULL, longitude DOUBLE PRECISION NOT NULL,
        name VARCHAR, head_name VARCHAR, phone VARCHAR NOT NULL, property VARCHAR,
        data_access VARCHAR NOT NULL, community VARCHAR NOT NULL, social_status VARCHAR NOT NULL,
        economic_status VARCHAR NOT NULL, photo_url VARCHAR, created_at TIMESTAMP WITH TIME ZONE DEFAULT now())""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_surveys_id ON surveys (id)")

def downgrade():
    op.drop_table("surveys")
    op.drop_table("users")
