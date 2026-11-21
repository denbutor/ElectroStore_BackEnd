from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import get_embedding
from app.db.models import ProductVector


class RAGService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _build_product_text(product: ProductVector) -> str:
        specs = ", ".join(
            f"{k}: {v}" for k, v in (product.specifications or {}).items()
        )
        desc = getattr(product, "description", "") or ""
        return (
            f"{product.title}. "
            f"{desc}. "
            f"Price: ${product.price}. "
            f"Specifications: {specs}"
        )

    async def reindex_missing_embeddings(self, batch_size: int = 25) -> int:
        """Генерує embedding для активних товарів, де embedding IS NULL."""
        updated = 0
        while True:
            stmt = (
                select(ProductVector)
                .where(
                    ProductVector.is_active == True,
                    ProductVector.embedding == None,
                )
                .order_by(ProductVector.id)
                .limit(batch_size)
            )
            result = await self.db.execute(stmt)
            products = list(result.scalars().all())
            if not products:
                break

            for prod in products:
                emb = await get_embedding(self._build_product_text(prod))
                prod.embedding = emb
                updated += 1

            await self.db.commit()

        return updated

    async def _search_by_keyword(
        self, query: str, limit: int = 3
    ) -> list[ProductVector]:
        clean = query.strip()
        if not clean:
            return []

        tokens = [t for t in clean.split() if len(t) >= 2][:5]
        if not tokens:
            tokens = [clean]

        conditions = []
        params = {}
        for idx, token in enumerate(tokens):
            key = f"pat_{idx}"
            params[key] = f"%{token}%"
            conditions.append(ProductVector.title.ilike(params[key]))
            conditions.append(text(f"CAST(products.specifications AS text) ILIKE :{key}"))

        stmt = (
            select(ProductVector)
            .where(
                ProductVector.is_active == True,
                ProductVector.stock > 0,
                or_(*conditions),
            )
            .order_by(ProductVector.id)
            .limit(limit)
        )
        result = await self.db.execute(stmt, params)
        return list(result.scalars().all())

    async def find_relevant_products(
        self, query: str, limit: int = 3
    ) -> list[ProductVector]:
        """Робить ембеддинг запиту юзера, шукає найближчі товари за косинусною відстанню,
        а при порожньому результаті або збої API підключає текстовий/SQL пошук."""
        products: list[ProductVector] = []
        try:
            query_vector = await get_embedding(query)
            stmt = (
                select(ProductVector)
                .where(
                    ProductVector.is_active == True,
                    ProductVector.stock > 0,
                    ProductVector.embedding != None,
                )
                .order_by(ProductVector.embedding.cosine_distance(query_vector))
                .limit(limit)
            )
            result = await self.db.execute(stmt)
            products = list(result.scalars().all())
        except Exception as exc:
            print(f"[RAG Vector Search Fallback] {exc}")

        if not products:
            products = await self._search_by_keyword(query, limit=limit)

        return products

    def format_context(self, products: list[ProductVector]) -> str:
        """Formats products into a text context for Gemini."""
        if not products:
            return "No relevant in-stock products found for this query."

        context = "Available products in the store:\n"
        for p in products:
            specs = ", ".join(
                f"{k}: {v}" for k, v in (p.specifications or {}).items()
            )
            context += (
                f"- {p.title} | Price: ${p.price} | "
                f"In stock: {p.stock} pcs | Specifications: {specs}\n"
            )
        return context
