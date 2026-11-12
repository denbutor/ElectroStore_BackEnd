import asyncio
from sqlalchemy import select
from app.db.base import async_session_maker
from app.db.models import ProductVector
from app.core.llm import get_embedding
from app.core.config import settings
from redis.asyncio import Redis

async def generate_vector_for_product(product_id: int):
    """Створює єдиний текстовий опис товару, робить вектор і зберігає в БД."""
    async with async_session_maker() as db:
        result = await db.execute(select(ProductVector).where(ProductVector.id == product_id))
        product = result.scalar_one_or_none()
        
        if not product or not product.is_active:
            return

        # Формуємо текст для векторизації
        specs = " ".join(f"{k} {v}" for k, v in product.specifications.items())
        text_to_embed = f"Товар: {product.title}. Ціна {product.price}. Характеристики: {specs}"
        
        product.embedding = await get_embedding(text_to_embed)
        await db.commit()

async def consume_product_events():
    """Фоновий процес, що читає події з Redis Streams."""
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    last_id = "$" # Починаємо читати тільки нові події

    while True:
        try:
            # Блокуємося на 5 секунд чекаючи нових повідомлень
            events = await redis.xread({"product_events": last_id}, count=10, block=5000)
            for stream, messages in events:
                for msg_id, msg_data in messages:
                    last_id = msg_id
                    action = msg_data.get("action")
                    product_id = int(msg_data.get("product_id", 0))
                    
                    if action in ["created", "updated"] and product_id:
                        await generate_vector_for_product(product_id)
        except Exception as e:
            print(f"Помилка в event_consumer: {e}")
            await asyncio.sleep(5)