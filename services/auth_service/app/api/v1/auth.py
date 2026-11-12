from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.base import get_db
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Auth"])

# --- Schemas ---
class RegisterSchema(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None

class LoginSchema(BaseModel):
    email: EmailStr
    password: str

class RefreshSchema(BaseModel):
    refresh_token: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class UserResponse(BaseModel):
    id: int
    email: EmailStr
    full_name: str | None
    role: str
    
    model_config = ConfigDict(from_attributes=True)

# --- Endpoints ---
@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterSchema, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    return await service.register(payload.email, payload.password, payload.full_name)

@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginSchema, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    return await service.login(payload.email, payload.password)

@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshSchema, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    return await service.refresh_tokens(payload.refresh_token)