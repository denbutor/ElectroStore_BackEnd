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
        self, query: str, limit: int = 6
    ) -> list[ProductVector]:
        clean = query.strip()
        if not clean:
            return []

        tokens = [t for t in clean.split() if len(t) >= 2][:8]
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
        self, query: str, limit: int = 6
    ) -> list[ProductVector]:
        """Робить ембеддинг запиту, шукає найближчі товари за косинусною відстанню,
        а за потреби підключає ключовий/SQL пошук."""
        products: list[ProductVector] = []
        clean_query = (query or "").strip()
        if clean_query:
            try:
                query_vector = await get_embedding(clean_query)
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

        if not products and clean_query:
            products = await self._search_by_keyword(clean_query, limit=limit)

        return products

    async def find_products_for_terms(
        self, terms: list[str], limit_per_term: int = 3, max_total: int = 14
    ) -> list[ProductVector]:
        """Шукає товари у каталозі за списком витягнутих/розпізнаних термінів."""
        collected: dict[int, ProductVector] = {}
        for raw_term in terms[:8]:
            term = (raw_term or "").strip()
            if not term:
                continue
            matches = await self.find_relevant_products(term, limit=limit_per_term)
            for prod in matches:
                if prod.id not in collected:
                    collected[prod.id] = prod
                if len(collected) >= max_total:
                    return list(collected.values())
        return list(collected.values())

    async def get_in_stock_snapshot(self, limit: int = 25) -> list[ProductVector]:
        """Повертає широкий зріз наявних товарів каталогу, щоб модель точно бачила,
        що реально є в магазині (кулери, SSD, БЖ, плати, ноутбуки), а чого немає."""
        stmt = (
            select(ProductVector)
            .where(
                ProductVector.is_active == True,
                ProductVector.stock > 0,
            )
            .order_by(ProductVector.id)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    def format_context(self, products: list[ProductVector]) -> str:
        """Форматує товари каталогу у текстовий контекст для Gemini."""
        if not products:
            return (
                "ElectroStore Catalog Context:\n"
                "Currently NO matching in-stock items were found in the ElectroStore database."
            )

        context = (
            "ElectroStore Catalog Context (ONLY items listed below are currently in stock in our shop; "
            "anything NOT in this list is currently OUT OF STOCK / NOT AVAILABLE in ElectroStore):\n"
        )
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
#         desc = getattr(product, "description", "") or ""
#         return (
#             f"{product.title}. "
#             f"{desc}. "
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
#         self, query: str, limit: int = 4
#     ) -> list[ProductVector]:
#         clean = query.strip()
#         if not clean:
#             return []

#         tokens = [t for t in clean.split() if len(t) >= 2][:6]
#         if not tokens:
#             tokens = [clean]

#         conditions = []
#         params = {}
#         for idx, token in enumerate(tokens):
#             key = f"pat_{idx}"
#             params[key] = f"%{token}%"
#             conditions.append(ProductVector.title.ilike(params[key]))
#             conditions.append(text(f"CAST(products.specifications AS text) ILIKE :{key}"))

#         stmt = (
#             select(ProductVector)
#             .where(
#                 ProductVector.is_active == True,
#                 ProductVector.stock > 0,
#                 or_(*conditions),
#             )
#             .order_by(ProductVector.id)
#             .limit(limit)
#         )
#         result = await self.db.execute(stmt, params)
#         return list(result.scalars().all())

#     async def find_relevant_products(
#         self, query: str, limit: int = 4
#     ) -> list[ProductVector]:
#         """Робить ембеддинг запиту, шукає найближчі товари за косинусною відстанню,
#         а за потреби підключає ключовий/SQL пошук."""
#         products: list[ProductVector] = []
#         clean_query = (query or "").strip()
#         if clean_query:
#             try:
#                 query_vector = await get_embedding(clean_query)
#                 stmt = (
#                     select(ProductVector)
#                     .where(
#                         ProductVector.is_active == True,
#                         ProductVector.stock > 0,
#                         ProductVector.embedding != None,
#                     )
#                     .order_by(ProductVector.embedding.cosine_distance(query_vector))
#                     .limit(limit)
#                 )
#                 result = await self.db.execute(stmt)
#                 products = list(result.scalars().all())
#             except Exception as exc:
#                 print(f"[RAG Vector Search Fallback] {exc}")

#         if not products and clean_query:
#             products = await self._search_by_keyword(clean_query, limit=limit)

#         return products

#     async def find_products_for_terms(
#         self, terms: list[str], limit_per_term: int = 2, max_total: int = 8
#     ) -> list[ProductVector]:
#         """Шукає товари у каталозі за списком витягнутих/розпізнаних термінів (категорії, сокети, DDR, моделі)."""
#         collected: dict[int, ProductVector] = {}
#         for raw_term in terms[:6]:
#             term = (raw_term or "").strip()
#             if not term:
#                 continue
#             matches = await self.find_relevant_products(term, limit=limit_per_term)
#             for prod in matches:
#                 if prod.id not in collected:
#                     collected[prod.id] = prod
#                 if len(collected) >= max_total:
#                     return list(collected.values())
#         return list(collected.values())

#     def format_context(self, products: list[ProductVector]) -> str:
#         """Форматує товари каталогу у текстовий контекст для Gemini."""
#         if not products:
#             return "No relevant in-stock products found in ElectroStore catalog for this query."

#         context = "Available products in ElectroStore catalog:\n"
#         for p in products:
#             specs = ", ".join(
#                 f"{k}: {v}" for k, v in (p.specifications or {}).items()
#             )
#             context += (
#                 f"- {p.title} | Price: ${p.price} | "
#                 f"In stock: {p.stock} pcs | Specifications: {specs}\n"
#             )
#         return context

# # from sqlalchemy import or_, select, text
# # from sqlalchemy.ext.asyncio import AsyncSession

# # from app.core.llm import get_embedding
# # from app.db.models import ProductVector


# # class RAGService:
# #     def __init__(self, db: AsyncSession):
# #         self.db = db

# #     @staticmethod
# #     def _build_product_text(product: ProductVector) -> str:
# #         specs = ", ".join(
# #             f"{k}: {v}" for k, v in (product.specifications or {}).items()
# #         )
# #         desc = getattr(product, "description", "") or ""
# #         return (
# #             f"{product.title}. "
# #             f"{desc}. "
# #             f"Price: ${product.price}. "
# #             f"Specifications: {specs}"
# #         )

# #     async def reindex_missing_embeddings(self, batch_size: int = 25) -> int:
# #         """Генерує embedding для активних товарів, де embedding IS NULL."""
# #         updated = 0
# #         while True:
# #             stmt = (
# #                 select(ProductVector)
# #                 .where(
# #                     ProductVector.is_active == True,
# #                     ProductVector.embedding == None,
# #                 )
# #                 .order_by(ProductVector.id)
# #                 .limit(batch_size)
# #             )
# #             result = await self.db.execute(stmt)
# #             products = list(result.scalars().all())
# #             if not products:
# #                 break

# #             for prod in products:
# #                 emb = await get_embedding(self._build_product_text(prod))
# #                 prod.embedding = emb
# #                 updated += 1

# #             await self.db.commit()

# #         return updated

# #     async def _search_by_keyword(
# #         self, query: str, limit: int = 3
# #     ) -> list[ProductVector]:
# #         clean = query.strip()
# #         if not clean:
# #             return []

# #         tokens = [t for t in clean.split() if len(t) >= 2][:5]
# #         if not tokens:
# #             tokens = [clean]

# #         conditions = []
# #         params = {}
# #         for idx, token in enumerate(tokens):
# #             key = f"pat_{idx}"
# #             params[key] = f"%{token}%"
# #             conditions.append(ProductVector.title.ilike(params[key]))
# #             conditions.append(text(f"CAST(products.specifications AS text) ILIKE :{key}"))

# #         stmt = (
# #             select(ProductVector)
# #             .where(
# #                 ProductVector.is_active == True,
# #                 ProductVector.stock > 0,
# #                 or_(*conditions),
# #             )
# #             .order_by(ProductVector.id)
# #             .limit(limit)
# #         )
# #         result = await self.db.execute(stmt, params)
# #         return list(result.scalars().all())

# #     async def find_relevant_products(
# #         self, query: str, limit: int = 3
# #     ) -> list[ProductVector]:
# #         """Робить ембеддинг запиту юзера, шукає найближчі товари за косинусною відстанню,
# #         а при порожньому результаті або збої API підключає текстовий/SQL пошук."""
# #         products: list[ProductVector] = []
# #         try:
# #             query_vector = await get_embedding(query)
# #             stmt = (
# #                 select(ProductVector)
# #                 .where(
# #                     ProductVector.is_active == True,
# #                     ProductVector.stock > 0,
# #                     ProductVector.embedding != None,
# #                 )
# #                 .order_by(ProductVector.embedding.cosine_distance(query_vector))
# #                 .limit(limit)
# #             )
# #             result = await self.db.execute(stmt)
# #             products = list(result.scalars().all())
# #         except Exception as exc:
# #             print(f"[RAG Vector Search Fallback] {exc}")

# #         if not products:
# #             products = await self._search_by_keyword(query, limit=limit)

# #         return products

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
