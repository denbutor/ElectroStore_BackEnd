import json
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis
from app.db.models import Product
from app.core.config import settings

class ProductService:
    def __init__(self, db: AsyncSession):
        self.db = db
        # Ініціалізація Redis для публікації подій (Event-Driven)
        self.redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)

    async def _publish_event(self, action: str, product_id: int):
        """Публікує подію в Redis Streams. ШІ-мікросервіс прочитає її і оновить вектори."""
        event_data = {"action": action, "product_id": str(product_id)}
        await self.redis.xadd("product_events", event_data)

    async def get_products(self, category_id: int | None, min_price: float | None, max_price: float | None, skip: int, limit: int):
        query = select(Product).where(Product.is_active == True)
        
        if category_id:
            query = query.where(Product.category_id == category_id)
        if min_price is not None:
            query = query.where(Product.price >= min_price)
        if max_price is not None:
            query = query.where(Product.price <= max_price)
            
        result = await self.db.execute(query.offset(skip).limit(limit))
        return result.scalars().all()

    async def create_product(self, data: dict) -> Product:
        product = Product(**data)
        self.db.add(product)
        await self.db.commit()
        await self.db.refresh(product)
        
        # Сповіщаємо інші сервіси про новий товар
        await self._publish_event("created", product.id)
        return product

    async def soft_delete(self, product_id: int):
        result = await self.db.execute(select(Product).where(Product.id == product_id))
        product = result.scalar_one_or_none()
        
        if not product:
            raise HTTPException(status_code=404, detail="Товар не знайдено")
            
        product.is_active = False # М'яке видалення
        await self.db.commit()
        
        await self._publish_event("deleted", product.id)