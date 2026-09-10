from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from ..dependencies import get_db, require_admin, CurrentUser
from ..models import User
from ..schemas import LoginDto, RegisterDto, UserRole
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/Auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/register")
@limiter.limit("5/minute")
def register(
    request: Request,
    dto: RegisterDto,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(require_admin),
):
    if db.query(User).filter(User.username == dto.username).first():
        raise HTTPException(status_code=400, detail="User already exists")

    role_value = dto.role.value if dto.role else UserRole.surveyor.value

    user = User(
        username=dto.username,
        password_hash=hash_password(dto.password),
        role=role_value,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return {"message": "User registered successfully", "role": user.role}


@router.post("/login")
@limiter.limit("5/minute")
def login(request: Request, dto: LoginDto, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == dto.username).first()
    if not user or not verify_password(dto.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(user.id, user.username, user.role)

    return {
        "token": token,
        "userId": user.id,
        "username": user.username,
        "role": user.role,
    }