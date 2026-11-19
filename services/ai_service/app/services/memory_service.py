import json
from redis.asyncio import Redis
from app.core.config import settings


class MemoryService:
    def __init__(self):
        self.redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)

    async def save_interaction(self, session_id: str, user_text: str, model_text: str):
        """Зберігає запит юзера і відповідь моделі, обрізає історію до 6 останніх реплік."""
        key = f"chat_session:{session_id}"

        user_msg = json.dumps({"role": "user", "parts": [{"text": user_text}]})
        model_msg = json.dumps({"role": "model", "parts": [{"text": model_text}]})

        try:
            await self.redis.rpush(key, user_msg, model_msg)
            await self.redis.ltrim(key, -6, -1)
            await self.redis.expire(key, 1800)
        finally:
            await self.redis.aclose()

    async def get_history(self, session_id: str) -> list[dict]:
        key = f"chat_session:{session_id}"
        try:
            items = await self.redis.lrange(key, 0, -1)
            return [json.loads(item) for item in items]
        finally:
            await self.redis.aclose()