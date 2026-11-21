import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.v1.chat import router as chat_router
from app.db.base import engine
from app.services.event_consumer import consume_product_events
from app.services.rag_service import RAGService

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ready = False
    last_err: Exception | None = None

    for _ in range(15):
        try:
            async with engine.begin() as conn:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                check = await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_schema = 'public' AND table_name = 'products'"
                    )
                )
                if check.scalar():
                    await conn.execute(
                        text(
                            "ALTER TABLE products "
                            "ADD COLUMN IF NOT EXISTS embedding vector(768);"
                        )
                    )
                    ready = True
                    break
        except Exception as exc:
            last_err = exc
        await asyncio.sleep(1)

    if not ready and last_err is not None:
        print(f"Попередження при ініціалізації pgvector/products: {last_err}")

    reindex_task: asyncio.Task | None = None
    if ready:
        async def _background_reindex() -> None:
            try:
                async with AsyncSessionLocal() as session:
                    rag = RAGService(session)
                    count = await rag.reindex_missing_embeddings()
                    if count:
                        print(f"Проіндексовано товарів без embedding: {count}")
            except Exception as exc:
                print(f"Попередження при доіндексації embedding: {exc}")

        reindex_task = asyncio.create_task(_background_reindex())

    consumer_task = asyncio.create_task(consume_product_events())

    yield

    for task in (reindex_task, consumer_task):
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    await engine.dispose()


app = FastAPI(
    title="ElectroStore AI & RAG Service",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
    root_path="/api/v1/ai",
)

app.include_router(chat_router, prefix="/api/v1")


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "service": "ai_service"}
