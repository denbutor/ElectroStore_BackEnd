from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from app.api.v1.auth import router as auth_router
from app.db.base import Base, engine

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Автоматичне створення таблиць при старті (відмова від Alembic для спрощення диплому)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Коректне закриття з'єднань при вимкненні сервісу
    await engine.dispose()

app = FastAPI(
    title="ElectroStore Auth Service",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

# Підключення роутера
app.include_router(auth_router, prefix="/api/v1")

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "service": "auth_service"}