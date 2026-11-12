from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.security import get_current_user_id
from app.services.cart_redis import CartRedisService

router = APIRouter(prefix="/cart", tags=["Cart"])

class CartItemPayload(BaseModel):
    product_id: int
    quantity: int

@router.get("/")
async def view_cart(user_id: int = Depends(get_current_user_id)):
    service = CartRedisService()
    items = await service.get_cart(user_id)
    return {"cart": items}

@router.post("/add")
async def add_to_cart(payload: CartItemPayload, user_id: int = Depends(get_current_user_id)):
    service = CartRedisService()
    await service.add_item(user_id, payload.product_id, payload.quantity)
    return {"status": "ok", "message": "Товар додано до кошика"}

@router.delete("/clear")
async def clear_cart(user_id: int = Depends(get_current_user_id)):
    service = CartRedisService()
    await service.clear_cart(user_id)
    return {"status": "ok", "message": "Кошик очищено"}