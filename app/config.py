import logging

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # PostgreSQL connection string (SQLAlchemy format)
    database_url: str = "postgresql+psycopg2://postgres:12345@localhost:5433/survey_db"

    # JWT
    jwt_secret: str = "CHANGE_ME_IN_PRODUCTION"
    jwt_issuer: str = "SurveyApi"
    jwt_expire_days: int = 1

    # CORS - comma separated list of origins, or "*" for all (dev only)
    allowed_origins: str = "*"

    # File uploads
    upload_dir: str = "uploads"
    max_upload_mb: int = 50
    environment: str = "development"
    sentry_dsn: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_prefix="SURVEY_", extra="ignore")


settings = Settings()


def validate_production_settings() -> None:
    """Fail closed for the two unsafe defaults when deployed to production."""
    unsafe = []
    if settings.jwt_secret == "CHANGE_ME_IN_PRODUCTION":
        unsafe.append("SURVEY_JWT_SECRET is the default placeholder")
    if settings.allowed_origins == "*":
        unsafe.append("SURVEY_ALLOWED_ORIGINS must not be '*'")
    if not unsafe:
        return
    message = "; ".join(unsafe)
    if settings.environment.lower() == "production":
        raise RuntimeError(message)
    logging.getLogger(__name__).warning("Unsafe development configuration: %s", message)
