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

        pattern = f"%{clean}%"
        stmt = (
            select(ProductVector)
            .where(
                ProductVector.is_active == True,
                ProductVector.stock > 0,
                or_(
                    ProductVector.title.ilike(pattern),
                    text("CAST(products.specifications AS text) ILIKE :pat"),
                ),
            )
            .order_by(ProductVector.id)
            .limit(limit)
        )
        result = await self.db.execute(stmt, {"pat": pattern})
        return list(result.scalars().all())

    async def find_relevant_products(
        self, query: str, limit: int = 3
    ) -> list[ProductVector]:
        """Робить ембеддинг запиту юзера, шукає найближчі товари за косинусною відстанню,
        а при порожньому результаті підключає текстовий/SQL пошук."""
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

# from sqlalchemy import or_, select, text
# from sqlalchemy.ext.asyncio import AsyncSession

# from app.core.llm import get_embedding
# from app.db.models import ProductVector


# class RAGService:
#     def __init__(self, db: AsyncSession):
#         self.db = db

#     @staticmethod
#     def _build_product_text(product: ProductVector) -> str:
#         specs = ", ".join(
#             f"{k}: {v}" for k, v in (product.specifications or {}).items()
#         )
#         return (
#             f"{product.title}. "
#             f"{product.description or ''}. "
#             f"Price: ${product.price}. "
#             f"Specifications: {specs}"
#         )

#     async def reindex_missing_embeddings(self, batch_size: int = 25) -> int:
#         """Генерує embedding для активних товарів, де embedding IS NULL."""
#         updated = 0
#         while True:
#             stmt = (
#                 select(ProductVector)
#                 .where(
#                     ProductVector.is_active == True,
#                     ProductVector.embedding == None,
#                 )
#                 .order_by(ProductVector.id)
#                 .limit(batch_size)
#             )
#             result = await self.db.execute(stmt)
#             products = list(result.scalars().all())
#             if not products:
#                 break

#             for prod in products:
#                 emb = await get_embedding(self._build_product_text(prod))
#                 prod.embedding = emb
#                 updated += 1

#             await self.db.commit()

#         return updated

#     async def _search_by_keyword(
#         self, query: str, limit: int = 3
#     ) -> list[ProductVector]:
#         clean = query.strip()
#         if not clean:
#             return []

#         pattern = f"%{clean}%"
#         stmt = (
#             select(ProductVector)
#             .where(
#                 ProductVector.is_active == True,
#                 ProductVector.stock > 0,
#                 or_(
#                     ProductVector.title.ilike(pattern),
#                     ProductVector.description.ilike(pattern),
#                     text("CAST(products.specifications AS text) ILIKE :pat"),
#                 ),
#             )
#             .order_by(ProductVector.id)
#             .limit(limit)
#         )
#         result = await self.db.execute(stmt, {"pat": pattern})
#         return list(result.scalars().all())

#     async def find_relevant_products(
#         self, query: str, limit: int = 3
#     ) -> list[ProductVector]:
#         """Робить ембеддинг запиту юзера, шукає найближчі товари за косинусною відстанню,
#         а при порожньому результаті підключає текстовий/SQL пошук."""
#         query_vector = await get_embedding(query)

#         stmt = (
#             select(ProductVector)
#             .where(
#                 ProductVector.is_active == True,
#                 ProductVector.stock > 0,
#                 ProductVector.embedding != None,
#             )
#             .order_by(ProductVector.embedding.cosine_distance(query_vector))
#             .limit(limit)
#         )
#         result = await self.db.execute(stmt)
#         products = list(result.scalars().all())

#         if not products:
#             products = await self._search_by_keyword(query, limit=limit)

#         return products

#     def format_context(self, products: list[ProductVector]) -> str:
#         """Formats products into a text context for Gemini."""
#         if not products:
#             return "No relevant in-stock products found for this query."

#         context = "Available products in the store:\n"
#         for p in products:
#             specs = ", ".join(
#                 f"{k}: {v}" for k, v in (p.specifications or {}).items()
#             )
#             context += (
#                 f"- {p.title} | Price: ${p.price} | "
#                 f"In stock: {p.stock} pcs | Specifications: {specs}\n"
#             )
#         return context

# # from sqlalchemy import select
# # from sqlalchemy.ext.asyncio import AsyncSession

# # from app.core.llm import get_embedding
# # from app.db.models import ProductVector


# # class RAGService:
# #     def __init__(self, db: AsyncSession):
# #         self.db = db

# #     async def find_relevant_products(
# #         self, query: str, limit: int = 3
# #     ) -> list[ProductVector]:
# #         """Робить ембеддинг запиту юзера та шукає найближчі товари косинусною відстанню."""
# #         query_vector = await get_embedding(query)

# #         stmt = (
# #             select(ProductVector)
# #             .where(
# #                 ProductVector.is_active == True,
# #                 ProductVector.stock > 0,
# #                 ProductVector.embedding != None,
# #             )
# #             .order_by(ProductVector.embedding.cosine_distance(query_vector))
# #             .limit(limit)
# #         )
# #         result = await self.db.execute(stmt)
# #         return list(result.scalars().all())

# #     def format_context(self, products: list[ProductVector]) -> str:
# #         """Formats products into a text context for Gemini."""
# #         if not products:
# #             return "No relevant in-stock products found for this query."

# #         context = "Available products in the store:\n"
# #         for p in products:
# #             specs = ", ".join(
# #                 f"{k}: {v}" for k, v in (p.specifications or {}).items()
# #             )
# #             context += (
# #                 f"- {p.title} | Price: ${p.price} | "
# #                 f"In stock: {p.stock} pcs | Specifications: {specs}\n"
# #             )
# #         return context

# #     # def format_context(self, products: list[ProductVector]) -> str:
# #     #     """Форматує товари у текстовий контекст для Gemini."""
# #     #     if not products:
# #     #         return "Актуальних товарів на складі за цим запитом не знайдено."

# #     #     context = "Знайдені товари в магазині:\n"
# #     #     for p in products:
# #     #         specs = ", ".join(
# #     #             f"{k}: {v}" for k, v in (p.specifications or {}).items()
# #     #         )
# #     #         context += (
# #     #             f"- {p.title} | Ціна: {p.price} грн | "
# #     #             f"В наявності: {p.stock} шт. | Характеристики: {specs}\n"
# #     #         )
# #     #     return context