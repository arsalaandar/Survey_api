from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.sql import func

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="Surveyor")


class Survey(Base):
    __tablename__ = "surveys"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    form_id = Column(String, nullable=True)
    point_id = Column(String, nullable=True)
    latitude = Column(Float, nullable=False, default=0.0)
    longitude = Column(Float, nullable=False, default=0.0)
    # Caller-generated UUID used to make offline retries idempotent.
    client_id = Column(String, unique=True, index=True, nullable=True)
    # Created as PostGIS geography by migration 0002. Kept opaque to the ORM
    # so SQLite-based tests do not need PostGIS extensions.
    location = Column(String, nullable=True)
    name = Column(String, nullable=True)
    head_name = Column(String, nullable=True)
    phone = Column(String, nullable=False)
    property = Column(String, nullable=True)
    data_access = Column(String, nullable=False)
    community = Column(String, nullable=False)
    social_status = Column(String, nullable=False)
    economic_status = Column(String, nullable=False)
    photo_url = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
