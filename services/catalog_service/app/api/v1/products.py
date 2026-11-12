from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_admin_user
from app.db.base import get_db
from app.db.models import Product
from app.services.media import process_and_upload_image
from app.services.product_service import ProductService

# router = APIRouter(prefix="/products", tags=["Products"])
router = APIRouter(tags=["Products"])


class ProductCreate(BaseModel):
    title: str
    description: str | None = None
    price: float
    stock: int
    category_id: int
    specifications: dict = {}


class ProductResponse(ProductCreate):
    id: int
    image_url: str | None
    is_active: bool
    model_config = ConfigDict(from_attributes=True)


@router.get("/", response_model=list[ProductResponse])
async def get_all_products(
    category_id: int | None = Query(None),
    min_price: float | None = Query(None),
    max_price: float | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
    service = ProductService(db)
    return await service.get_products(category_id, min_price, max_price, skip, limit)


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product_by_id(
    product_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Повертає деталі товару за його ID для order_service та клієнта."""
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.is_active.is_(True))
    )
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Товар з ID {product_id} не знайдено",
        )
    return product


@router.post("/", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_admin_user),
):
    service = ProductService(db)
    return await service.create_product(payload.model_dump())


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_admin_user),
):
    service = ProductService(db)
    await service.soft_delete(product_id)


@router.post("/{product_id}/image", response_model=ProductResponse)
async def upload_image(
    product_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_admin_user),
):
    file_bytes = await file.read()
    image_url = await process_and_upload_image(file_bytes)

    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Товар не знайдено")

    product.image_url = image_url
    await db.commit()
    await db.refresh(product)

    service = ProductService(db)
    await service._publish_event("updated", product.id)

    return product