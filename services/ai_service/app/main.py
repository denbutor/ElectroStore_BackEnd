import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from sqlalchemy import text

from app.api.v1.chat import router as chat_router
from app.db.base import engine
from app.services.event_consumer import consume_product_events


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Очікуємо створення таблиці products сервісом каталогу та додаємо векторну колонку
    for _ in range(15):
        try:
            async with engine.begin() as conn:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                check = await conn.execute(
                    text("SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'products'")
                )
                if check.scalar():
                    await conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS embedding vector(768);"))
                    break
        except Exception:
            pass
        await asyncio.sleep(1)

    # Запуск фонового читача черги Redis Streams
    consumer_task = asyncio.create_task(consume_product_events())

    yield

    # Коректна зупинка фонової задачі та з'єднань з БД
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass

    await engine.dispose()


app = FastAPI(
    title="ElectroStore AI & RAG Service",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

app.include_router(chat_router, prefix="/api/v1")


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "service": "ai_service"}