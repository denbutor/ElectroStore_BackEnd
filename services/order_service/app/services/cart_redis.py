from redis.asyncio import Redis
from app.core.config import settings

class CartRedisService:
    def __init__(self):
        self.redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)

    async def add_item(self, user_id: int, product_id: int, quantity: int):
        """Зберігає кошик у структурі Redis Hash (HSET)."""
        key = f"cart:{user_id}"
        # Якщо товар вже є, збільшуємо кількість (HINCRBY)
        await self.redis.hincrby(key, str(product_id), quantity)

    async def get_cart(self, user_id: int) -> dict[int, int]:
        key = f"cart:{user_id}"
        items = await self.redis.hgetall(key)
        return {int(k): int(v) for k, v in items.items()}

    async def clear_cart(self, user_id: int):
        await self.redis.delete(f"cart:{user_id}")

    async def lock_idempotency_key(self, idempotency_key: str) -> bool:
        """Перевіряє ключ. Повертає True, якщо запит унікальний, False - якщо дублікат."""
        key = f"idem:{idempotency_key}"
        # Встановлюємо ключ на 1 годину (3600 сек). nx=True гарантує атомарність перевірки.
        return bool(await self.redis.set(key, "1", nx=True, ex=3600))