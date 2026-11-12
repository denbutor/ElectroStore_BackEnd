from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from app.api.v1.cart import router as cart_router
from app.api.v1.orders import router as orders_router
from app.db.base import Base, engine

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Автоматичне створення таблиць замовлень
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()

app = FastAPI(
    title="ElectroStore Order & Cart Service",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

app.include_router(cart_router, prefix="/api/v1")
app.include_router(orders_router, prefix="/api/v1")

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "service": "order_service"}