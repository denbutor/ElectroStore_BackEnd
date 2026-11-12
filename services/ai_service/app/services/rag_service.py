from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import ProductVector
from app.core.llm import get_embedding

class RAGService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def find_relevant_products(self, query: str, limit: int = 3) -> list[ProductVector]:
        """Робить ембеддинг запиту юзера та шукає найближчі товари косинусною відстанню."""
        query_vector = await get_embedding(query)
        
        stmt = (
            select(ProductVector)
            .where(ProductVector.is_active == True, ProductVector.stock > 0, ProductVector.embedding != None)
            .order_by(ProductVector.embedding.cosine_distance(query_vector))
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    def format_context(self, products: list[ProductVector]) -> str:
        """Форматує товари у текстовий контекст для Gemini."""
        if not products:
            return "Актуальних товарів на складі за цим запитом не знайдено."
        
        context = "Знайдені товари в магазині:\n"
        for p in products:
            specs = ", ".join(f"{k}: {v}" for k, v in p.specifications.items())
            context += f"- {p.title} | Ціна: {p.price} грн | В наявності: {p.stock} шт. | Характеристики: {specs}\n"
        return context