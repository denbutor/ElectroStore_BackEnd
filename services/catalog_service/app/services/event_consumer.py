import asyncio
import json
import logging
import redis.asyncio as aioredis
from sqlalchemy import update
from app.core.config import settings
# from app.db.base import AsyncSessionLocal
from app.db.models import Product

logger = logging.getLogger("event_consumer")

# async def handle_order_paid(data: dict):
#     """Атомарне списання залишків товарів у базі даних."""
#     items = data.get("items", [])
#     if not items:
#         return

#     async with AsyncSessionLocal() as session:
#         async with session.begin():
#             for item in items:
#                 prod_id = item["product_id"]
#                 qty = item["quantity"]

#                 # Атомарний SQL UPDATE: stock = stock - qty
#                 stmt = (
#                     update(Product)
#                     .where(Product.id == prod_id, Product.stock >= qty)
#                     .values(stock=Product.stock - qty)
#                 )
#                 result = await session.execute(stmt)
#                 if result.rowcount == 0:
#                     logger.warning(f"Недостатньо залишку для товару ID {prod_id} (запитувано: {qty})")
#                 else:
#                     logger.info(f"Списано {qty} шт. товару ID {prod_id}")

from app.db.base import get_db

# async def handle_order_paid(data: dict):
#     items = data.get("items", [])
#     if not items:
#         return

#     async for session in get_db():
#         async with session.begin():
#             for item in items:
#                 prod_id = item["product_id"]
#                 qty = item["quantity"]
#                 stmt = (
#                     update(Product)
#                     .where(Product.id == prod_id, Product.stock >= qty)
#                     .values(stock=Product.stock - qty)
#                 )
#                 result = await session.execute(stmt)
#                 if result.rowcount == 0:
#                     logger.warning(f"Недостатньо залишку для товару ID {prod_id}")
#                 else:
#                     logger.info(f"Списано {qty} шт. товару ID {prod_id}")
#         break

# async def start_event_consumer():
#     """Фоновий слухач черги подій Redis Pub/Sub."""
#     while True:
#         try:
#             r = aioredis.from_url(f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}", decode_responses=True)
#             pubsub = r.pubsub()
#             await pubsub.subscribe("order_events")
#             logger.info("Підключено до каналу order_events")

#             async for message in pubsub.listen():
#                 if message["type"] == "message":
#                     payload = json.loads(message["data"])
#                     if payload.get("event") == "order_paid":
#                         await handle_order_paid(payload)
#         except asyncio.CancelledError:
#             break
#         except Exception as e:
#             logger.error(f"Помилка в event_consumer: {e}. Перепідключення через 5 сек...")
#             await asyncio.sleep(5)

# logger = logging.getLogger("event_consumer")

async def handle_order_paid(data: dict):
    items = data.get("items", [])
    if not items:
        return

    async for session in get_db():
        async with session.begin():
            for item in items:
                prod_id = item["product_id"]
                qty = item["quantity"]
                stmt = (
                    update(Product)
                    .where(Product.id == prod_id, Product.stock >= qty)
                    .values(stock=Product.stock - qty)
                )
                result = await session.execute(stmt)
                if result.rowcount == 0:
                    logger.warning(f"Недостатньо залишку для товару ID {prod_id}")
                else:
                    logger.info(f"Списано {qty} шт. товару ID {prod_id}")
        break

async def start_event_consumer():
    while True:
        try:
            r = aioredis.from_url(
                f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}", 
                decode_responses=True
            )
            pubsub = r.pubsub()
            await pubsub.subscribe("order_events")
            logger.info("Підключено до каналу order_events")

            async for message in pubsub.listen():
                if message["type"] == "message":
                    payload = json.loads(message["data"])
                    if payload.get("event") == "order_paid":
                        await handle_order_paid(payload)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Помилка в event_consumer: {e}. Перепідключення через 5 сек...")
            await asyncio.sleep(5)