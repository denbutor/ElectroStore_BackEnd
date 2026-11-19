import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api.v1.products import router as products_router
from app.services.event_consumer import start_event_consumer


@asynccontextmanager
async def lifespan(app: FastAPI):
    consumer_task = asyncio.create_task(start_event_consumer())
    yield
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Catalog Service",
    lifespan=lifespan,
    docs_url="/api/v1/catalog/docs",
    openapi_url="/api/v1/catalog/openapi.json",
)

app.include_router(products_router, prefix="/api/v1/products")


@app.get("/health")
async def health_check():
    return {"status": "ok"}