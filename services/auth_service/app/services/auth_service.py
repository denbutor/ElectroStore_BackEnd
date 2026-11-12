from fastapi import HTTPException, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.security import create_token_pair, hash_password, verify_password
from app.db.models import User

class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def register(self, email: str, password: str, full_name: str | None = None) -> User:
        result = await self.db.execute(select(User).where(User.email == email))
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Користувач із такою електронною поштою вже існує"
            )

        new_user = User(
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
            role="client",
        )
        self.db.add(new_user)
        
        # Обробляємо транзакцію прямо в сервісі
        await self.db.commit()
        await self.db.refresh(new_user)
        return new_user

    async def login(self, email: str, password: str) -> dict[str, str]:
        result = await self.db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user or not verify_password(password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Невірний email або пароль"
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Обліковий запис деактивовано"
            )

        return create_token_pair(user_id=user.id, role=user.role)

    async def refresh_tokens(self, refresh_token: str) -> dict[str, str]:
        try:
            payload = jwt.decode(
                refresh_token,
                settings.JWT_SECRET,
                algorithms=[settings.JWT_ALGORITHM],
            )
            if payload.get("type") != "refresh":
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Недійсний тип токена")
            user_id = int(payload.get("sub"))
        except (JWTError, TypeError, ValueError):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Невалідний refresh-токен")

        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Користувача не знайдено або заблоковано")

        return create_token_pair(user_id=user.id, role=user.role)