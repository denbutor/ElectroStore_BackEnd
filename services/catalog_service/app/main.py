# from contextlib import asynccontextmanager
# from fastapi import FastAPI
# from fastapi.responses import ORJSONResponse
# from app.api.v1.products import router as products_router
# from app.db.base import Base, engine

# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     # Автоматичне створення таблиць (категорії та товари)
#     async with engine.begin() as conn:
#         await conn.run_sync(Base.metadata.create_all)
#     yield
#     await engine.dispose()

# app = FastAPI(
#     title="ElectroStore Catalog Service",
#     default_response_class=ORJSONResponse,
#     lifespan=lifespan,
# )

# # app.include_router(products_router, prefix="/products", tags=["Products"])
# app.include_router(products_router, prefix="/api/v1/products")

# @app.get("/health", tags=["System"])
# async def health_check():
#     return {"status": "ok", "service": "catalog_service"}

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api.v1.products import router as products_router
from app.services.event_consumer import start_event_consumer

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Старт слухача в фоні
    consumer_task = asyncio.create_task(start_event_consumer())
    yield
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="Catalog Service", lifespan=lifespan)

app.include_router(products_router, prefix="/api/v1/products")

@app.get("/health")
async def health_check():
    return {"status": "ok"}