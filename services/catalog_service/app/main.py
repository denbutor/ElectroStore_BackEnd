import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import text
from app.api.v1.products import router as products_router
from app.db.base import Base, engine
from app.services.event_consumer import start_event_consumer


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                "ALTER TABLE products "
                "ADD COLUMN IF NOT EXISTS image_url VARCHAR(512), "
                "ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE, "
                "ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;"
            )
        )

    consumer_task = asyncio.create_task(start_event_consumer())
    yield
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    await engine.dispose()


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
