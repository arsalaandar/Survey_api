import base64
import binascii
import math
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..dependencies import CurrentUser, get_current_user, get_db, require_admin
from ..models import Survey, User
from ..schemas import NearbySurveyOut, SurveyDto, SurveyOut

router = APIRouter(prefix="/api/Survey", tags=["survey"])
v1_router = APIRouter(prefix="/api/v1/Survey", tags=["survey-v1"])

MAX_PHOTO_BYTES = 10 * 1024 * 1024


def _decode_image(photo: str) -> tuple[bytes, str]:
    """Decode a base64 JPEG or PNG without accepting arbitrary file bytes."""
    encoded = photo.split(",", 1)[-1] if photo.startswith("data:") else photo
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Photo must be valid base64 image data") from exc
    if len(payload) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Photo exceeds the 10 MB decoded limit")
    if payload.startswith(b"\xff\xd8\xff"):
        return payload, ".jpg"
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return payload, ".png"
    raise HTTPException(status_code=400, detail="Photo must be a JPEG or PNG image")


def _out(s: Survey, username: str | None, distance_km: float | None = None):
    values = dict(id=s.id, formId=s.form_id, pointId=s.point_id, latitude=s.latitude,
        longitude=s.longitude, name=s.name, headName=s.head_name, phone=s.phone,
        property=s.property, dataAccess=s.data_access, community=s.community,
        socialStatus=s.social_status, economicStatus=s.economic_status,
        photoUrl=s.photo_url, createdAt=s.created_at, userId=s.user_id, username=username)
    if distance_km is not None:
        return NearbySurveyOut(**values, distanceKm=round(distance_km, 3))
    return SurveyOut(**values)


def _save_survey(dto: SurveyDto, db: Session, current: CurrentUser) -> tuple[Survey, bool]:
    """Persist one DTO, returning (survey, created); client_id retries are safe."""
    if dto.client_id:
        existing = db.query(Survey).filter(Survey.client_id == dto.client_id).first()
        if existing:
            return existing, False

    photo_url = None
    if dto.photo:
        image_bytes, extension = _decode_image(dto.photo)
        os.makedirs(settings.upload_dir, exist_ok=True)
        file_name = f"{uuid.uuid4()}{extension}"
        with open(os.path.join(settings.upload_dir, file_name), "wb") as file:
            file.write(image_bytes)
        photo_url = f"/uploads/{file_name}"

    survey = Survey(
        form_id=dto.form_id, point_id=dto.point_id, latitude=dto.latitude,
        longitude=dto.longitude, name=dto.name, head_name=dto.head_name,
        phone=dto.phone, property=dto.property, data_access=dto.data_access,
        community=dto.community, social_status=dto.social_status,
        economic_status=dto.economic_status, photo_url=photo_url,
        client_id=dto.client_id, user_id=current.id,
    )
    db.add(survey)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # A concurrent retry won the unique-key race; return its successful row.
        if dto.client_id:
            existing = db.query(Survey).filter(Survey.client_id == dto.client_id).first()
            if existing:
                return existing, False
        raise
    db.refresh(survey)
    if db.bind.dialect.name == "postgresql":
        db.execute(text("UPDATE surveys SET location = ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography WHERE id = :id"), {"lng": dto.longitude, "lat": dto.latitude, "id": survey.id})
        db.commit()
    return survey, True


@router.post("")
def submit_survey(
    dto: SurveyDto,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    survey, _ = _save_survey(dto, db, current)
    return {"message": "Survey saved.", "photoUrl": survey.photo_url, "id": survey.id}


@router.post("/batch")
def submit_survey_batch(
    items: list[dict], db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    results = []
    for item in items:
        client_id = item.get("clientId") if isinstance(item, dict) else None
        try:
            dto = SurveyDto.model_validate(item)
            if not dto.client_id:
                raise ValueError("clientId is required for batch sync")
            survey, created = _save_survey(dto, db, current)
            results.append({"clientId": dto.client_id, "id": survey.id,
                            "photoUrl": survey.photo_url,
                            "status": "created" if created else "already_synced"})
        except Exception as exc:
            db.rollback()
            results.append({"clientId": client_id, "status": "error", "message": str(exc)})
    return results


@router.get("")
def get_all(
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
    page: int | None = Query(None, ge=1),
    limit: int | None = Query(None, ge=1, le=100),
    community: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    query = db.query(Survey)
    if current.role == "Surveyor":
        query = query.filter(Survey.user_id == current.id)

    if community:
        query = query.filter(Survey.community == community)
    if date_from:
        query = query.filter(Survey.created_at >= date_from)
    if date_to:
        query = query.filter(Survey.created_at <= date_to)
    total = query.count()
    is_paginated = any(value is not None for value in (page, limit, community, date_from, date_to))
    query = query.order_by(Survey.created_at.desc())
    if is_paginated:
        page = page or 1
        limit = limit or 20
        query = query.offset((page - 1) * limit).limit(limit)
    surveys = query.all()

    results = []
    for s in surveys:
        username = db.query(User.username).filter(User.id == s.user_id).scalar()
        results.append(_out(s, username))
    # No query parameters preserves the Flutter client's flat array contract.
    return results if not is_paginated else {"items": results, "page": page, "limit": limit, "total": total}


@v1_router.get("/nearby", response_model=list[NearbySurveyOut])
def nearby_surveys(
    lat: float = Query(..., ge=-90, le=90), lng: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(5, gt=0, le=100), db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    query = db.query(Survey)
    if current.role == "Surveyor":
        query = query.filter(Survey.user_id == current.id)
    rows = []
    if db.bind.dialect.name == "postgresql":
        # PostGIS geography returns metres and uses the GiST index for ST_DWithin.
        sql = """SELECT id, ST_Distance(location, ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography) / 1000 AS distance
                 FROM surveys WHERE location IS NOT NULL AND ST_DWithin(location, ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography, :radius)"""
        if current.role == "Surveyor":
            sql += " AND user_id = :user_id"
        sql += " ORDER BY distance"
        params = {"lat": lat, "lng": lng, "radius": radius_km * 1000, "user_id": current.id}
        distances = {row.id: row.distance for row in db.execute(text(sql), params)}
        rows = [(s, distances[s.id]) for s in query.filter(Survey.id.in_(distances)).all()]
        rows.sort(key=lambda item: item[1])
    else:
        # Test/dev fallback when PostGIS is unavailable.
        for s in query.all():
            a = math.sin(math.radians(s.latitude-lat)/2)**2 + math.cos(math.radians(lat))*math.cos(math.radians(s.latitude))*math.sin(math.radians(s.longitude-lng)/2)**2
            distance = 6371.0088 * 2 * math.asin(math.sqrt(a))
            if distance <= radius_km:
                rows.append((s, distance))
        rows.sort(key=lambda item: item[1])
    return [_out(s, db.query(User.username).filter(User.id == s.user_id).scalar(), distance) for s, distance in rows]


@router.delete("/{id}")
def delete_survey(
    id: int,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(require_admin),
):
    survey = db.query(Survey).filter(Survey.id == id).first()
    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found.")

    if survey.photo_url:
        try:
            file_path = os.path.join(settings.upload_dir, os.path.basename(survey.photo_url))
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass

    db.delete(survey)
    db.commit()

    return {"message": "Survey deleted."}
