import base64
import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import jwt

from .config import settings


def _legacy_sha256_hash(password: str) -> str:
    """Reproduces the old ASP.NET AuthController's HashPassword() exactly,
    so existing rows migrated from the Postgres DB still log in."""
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest).decode()


def hash_password(password: str) -> str:
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(password: str, stored_hash: str) -> bool:
    if stored_hash.startswith("$2"):  # bcrypt hash
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    # Fall back to the legacy scheme for rows created by the old .NET API.
    return _legacy_sha256_hash(password) == stored_hash


def create_access_token(user_id: int, username: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_expire_days)
    payload = {
        "sub": str(user_id),
        "unique_name": username,
        "role": role,
        "iss": settings.jwt_issuer,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
