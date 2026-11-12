# import httpx
# from fastapi import HTTPException
# from tenacity import retry, stop_after_attempt, wait_exponential
# from app.core.config import settings

# @retry(
#     stop=stop_after_attempt(3), 
#     wait=wait_exponential(multiplier=1, min=2, max=10),
#     reraise=True
# )
# async def fetch_product_price(product_id: int) -> float:
#     """Робить HTTP запит до catalog_service для отримання актуальної ціни."""
#     async with httpx.AsyncClient() as client:
#         try:
#             # Припускаємо, що в каталозі буде створено базовий ендпоінт GET /products/{id}
#             response = await client.get(f"{settings.CATALOG_SERVICE_URL}/products/{product_id}")
#             response.raise_for_status()
#             data = response.json()
#             return float(data["price"])
#         except httpx.HTTPStatusError as e:
#             if e.response.status_code == 404:
#                 raise HTTPException(status_code=400, detail=f"Товар ID {product_id} не знайдено в каталозі")
#             raise e

import httpx
from fastapi import HTTPException
from tenacity import retry, stop_after_attempt, wait_exponential
from app.core.config import settings


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
async def fetch_product_price(product_id: int) -> float:
    """Отримує актуальну ціну товару з catalog_service."""
    # Нормалізуємо базовий URL
    base_url = settings.CATALOG_SERVICE_URL.rstrip("/")
    if not base_url.endswith("/api/v1"):
        base_url = f"{base_url}/api/v1"

    # follow_redirects=True запобігає збоям при невідповідності кінцевого слеша
    async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
        try:
            # Якщо в каталозі шлях без слеша, запит піде на /products/{id}
            url = f"{base_url}/products/{product_id}"
            response = await client.get(url)
            
            # Якщо повернуло 404 або 405, пробуємо зі слешем
            if response.status_code in (404, 405):
                response = await client.get(f"{url}/")

            response.raise_for_status()
            data = response.json()
            return float(data["price"])
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise HTTPException(
                    status_code=400,
                    detail=f"Товар ID {product_id} не знайдено в каталозі",
                )
            raise e