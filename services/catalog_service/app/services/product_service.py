import re
import uuid
from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.models import Category, Product

TRANSLIT_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e",
    "є": "ye", "ж": "zh", "з": "z", "и": "y", "і": "i", "ї": "yi", "й": "y",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "shch", "ь": "", "ю": "yu", "я": "ya", "ы": "y", "э": "e",
    "ё": "yo", "ъ": "",
}


def make_slug(name: str) -> str:
    transliterated = "".join(TRANSLIT_MAP.get(ch, ch) for ch in name.lower().strip())
    slug = re.sub(r"[^a-z0-9]+", "-", transliterated).strip("-")
    return slug or f"cat-{uuid.uuid4().hex[:8]}"


class ProductService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)

    async def _publish_event(self, action: str, product_id: int):
        """Публікує подію в Redis Streams. ШІ-мікросервіс прочитає її і оновить вектори."""
        event_data = {"action": action, "product_id": str(product_id)}
        try:
            await self.redis.xadd("product_events", event_data)
        finally:
            await self.redis.aclose()

    async def get_categories(self) -> list[Category]:
        result = await self.db.execute(select(Category).order_by(Category.id))
        return list(result.scalars().all())

    async def create_category(self, name: str, slug: str | None = None) -> Category:
        clean_name = name.strip()
        if not clean_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Назва категорії не може бути порожньою",
            )

        existing_res = await self.db.execute(
            select(Category).where(func.lower(Category.name) == clean_name.lower())
        )
        existing = existing_res.scalar_one_or_none()
        if existing:
            return existing

        base_slug = make_slug(slug or clean_name)
        candidate_slug = base_slug
        counter = 1
        while True:
            slug_check = await self.db.execute(
                select(Category).where(Category.slug == candidate_slug)
            )
            if not slug_check.scalar_one_or_none():
                break
            counter += 1
            candidate_slug = f"{base_slug}-{counter}"

        category = Category(name=clean_name, slug=candidate_slug)
        self.db.add(category)
        await self.db.commit()
        await self.db.refresh(category)
        return category

    async def get_products(
        self,
        category_id: int | None,
        min_price: float | None,
        max_price: float | None,
        skip: int,
        limit: int,
    ):
        query = (
            select(Product)
            .options(selectinload(Product.category))
            .where(Product.is_active == True)
        )

        if category_id is not None:
            query = query.where(Product.category_id == category_id)
        if min_price is not None:
            query = query.where(Product.price >= min_price)
        if max_price is not None:
            query = query.where(Product.price <= max_price)

        result = await self.db.execute(query.offset(skip).limit(limit))
        return result.scalars().all()

    async def get_product_by_id(self, product_id: int) -> Product | None:
        result = await self.db.execute(
            select(Product)
            .options(selectinload(Product.category))
            .where(Product.id == product_id, Product.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def create_product(self, data: dict) -> Product:
        new_category_name = data.pop("new_category_name", None)
        category_id = data.get("category_id")

        if new_category_name and new_category_name.strip():
            category = await self.create_category(new_category_name)
            data["category_id"] = category.id
        elif category_id is not None:
            cat_res = await self.db.execute(
                select(Category).where(Category.id == category_id)
            )
            if not cat_res.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Категорію з ID {category_id} не знайдено",
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Потрібно обрати існуючу категорію або вказати назву нової",
            )

        product = Product(**data)
        self.db.add(product)
        await self.db.flush()
        new_id = product.id
        await self.db.commit()

        created = await self.get_product_by_id(new_id)
        await self._publish_event("created", new_id)
        return created or product

    async def soft_delete(self, product_id: int):
        result = await self.db.execute(select(Product).where(Product.id == product_id))
        product = result.scalar_one_or_none()

        if not product:
            raise HTTPException(status_code=404, detail="Товар не знайдено")

        product.is_active = False
        await self.db.commit()

        await self._publish_event("deleted", product.id)
