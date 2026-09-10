from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class UserRole(str, Enum):
    admin = "admin"
    surveyor = "surveyor"


class RegisterDto(BaseModel):
    username: str
    password: str
    role: Optional[UserRole] = None


class LoginDto(BaseModel):
    username: str
    password: str


class SurveyDto(BaseModel):
    """Mirrors the Flutter app's existing JSON payload (camelCase keys)."""

    model_config = ConfigDict(populate_by_name=True)

    form_id: Optional[str] = Field(None, alias="formId")
    point_id: Optional[str] = Field(None, alias="pointId")
    latitude: float
    longitude: float
    client_id: Optional[str] = Field(None, alias="clientId")
    name: Optional[str] = None
    head_name: Optional[str] = Field(None, alias="headName")
    phone: str
    property: Optional[str] = None
    data_access: str = Field(..., alias="dataAccess")
    community: str
    social_status: str = Field(..., alias="socialStatus")
    economic_status: str = Field(..., alias="economicStatus")
    photo: Optional[str] = None  # base64-encoded image, optional


class SurveyOut(BaseModel):
    """Mirrors the shape SurveyController.GetAll() used to return."""

    id: int
    formId: Optional[str] = None
    pointId: Optional[str] = None
    latitude: float
    longitude: float
    name: Optional[str] = None
    headName: Optional[str] = None
    phone: str
    property: Optional[str] = None
    dataAccess: str
    community: str
    socialStatus: str
    economicStatus: str
    photoUrl: Optional[str] = None
    createdAt: datetime
    userId: int
    username: Optional[str] = None


class NearbySurveyOut(SurveyOut):
    distanceKm: float