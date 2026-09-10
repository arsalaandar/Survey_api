import json
import logging
import os
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from .config import settings, validate_production_settings
from .database import SessionLocal
from .routers import auth, survey

validate_production_settings()
os.makedirs(settings.upload_dir, exist_ok=True)

class JsonFormatter(logging.Formatter):
    def format(self, record):
        try:
            payload = json.loads(record.getMessage())
        except json.JSONDecodeError:
            payload = {"message": record.getMessage()}
        payload.setdefault("timestamp", self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"))
        payload.setdefault("level", record.levelname.lower())
        return json.dumps(payload)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger = logging.getLogger("survey_api")
logger.handlers = [handler]
logger.setLevel(logging.INFO)
logger.propagate = False

app = FastAPI(title="SurveyApi", version="1.0.0")
app.state.limiter = auth.limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

if settings.sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment, enable_tracing=True)


@app.middleware("http")
async def request_tracing(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(json.dumps({"request_id": request_id, "path": request.url.path, "event": "request_failed"}))
        raise
    response.headers["X-Request-ID"] = request_id
    logger.info(json.dumps({"request_id": request_id, "path": request.url.path, "status_code": response.status_code, "duration_ms": round((time.perf_counter() - started) * 1000, 2)}))
    return response

if settings.allowed_origins == "*":
    origins = ["*"]
    allow_credentials = False  # can't combine "*" with credentials per CORS spec
else:
    origins = [o.strip() for o in settings.allowed_origins.split(",")]
    allow_credentials = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")

app.include_router(auth.router)
app.include_router(survey.router)
app.include_router(survey.v1_router)


@app.get("/health")
def health():
    try:
        from sqlalchemy import text
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
    except Exception:
        return JSONResponse(status_code=503, content={"status": "error", "db": "unavailable"})
    return {"status": "ok", "db": "ok"}
