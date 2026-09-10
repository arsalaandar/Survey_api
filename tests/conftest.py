import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["SURVEY_DATABASE_URL"] = "sqlite://"
os.environ["SURVEY_JWT_SECRET"] = "test-secret"
from app.database import Base
from app.main import app
from app.models import User
from app.routers import auth
from app.security import hash_password


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """TestClient wired to an isolated in-memory SQLite DB per test, with the
    slowapi rate limiter disabled by default (see `rate_limited_client` for
    the rate-limit tests, which need it enabled). Photo uploads are
    redirected to a per-test tmp dir so tests never write into the real
    project `uploads/` folder."""
    from app import config
    monkeypatch.setattr(config.settings, "upload_dir", str(tmp_path))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(engine)
    import app.dependencies as dependencies
    monkeypatch.setattr(dependencies, "SessionLocal", factory)
    monkeypatch.setattr(auth.limiter, "enabled", False)
    with TestClient(app) as test_client:
        test_client.db_factory = factory
        test_client.upload_dir = tmp_path
        yield test_client
    Base.metadata.drop_all(engine)


@pytest.fixture()
def rate_limited_client(monkeypatch):
    """Same as `client`, but leaves the real slowapi limiter active so
    rate-limit behavior itself can be exercised. The limiter's hit counters
    live in a module-level singleton (`auth.limiter`), so they're reset
    before and after each test to keep tests independent of each other and
    of execution order."""
    auth.limiter.reset()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(engine)
    import app.dependencies as dependencies
    monkeypatch.setattr(dependencies, "SessionLocal", factory)
    with TestClient(app) as test_client:
        test_client.db_factory = factory
        yield test_client
    Base.metadata.drop_all(engine)
    auth.limiter.reset()


def seed_user(client, username="admin", password="adminpass", role="Admin"):
    """Insert a user directly at the DB layer, bypassing the HTTP API —
    mirrors what your production `scripts_create_admin.py` bootstrap does,
    since the API itself has no way to create the first admin. Idempotent:
    reuses the row if this username was already seeded in this test."""
    db = client.db_factory()
    try:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            return existing
        user = User(username=username, password_hash=hash_password(password), role=role)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def token(client, username="surveyor", password="secret"):
    response = client.post("/api/Auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {response.json()['token']}"}


def admin_headers(client, username="admin", password="adminpass"):
    seed_user(client, username, password, role="Admin")
    return token(client, username, password)


def register(client, headers, username="surveyor", password="secret", role=None):
    """Register via the real HTTP endpoint. Requires an admin's headers,
    since /api/Auth/register is admin-gated."""
    body = {"username": username, "password": password}
    if role:
        body["role"] = role
    return client.post("/api/Auth/register", json=body, headers=headers)


def surveyor_headers(client, username="surveyor", password="secret", admin=None):
    """Convenience: seed an admin (or reuse one), register a Surveyor through
    the real endpoint, then log them in."""
    admin = admin or admin_headers(client)
    register(client, admin, username=username, password=password)
    return token(client, username, password)


def payload(**changes):
    value = {"latitude": 28.6139, "longitude": 77.2090, "phone": "123", "dataAccess": "yes", "community": "A", "socialStatus": "x", "economicStatus": "y"}
    value.update(changes)
    return value