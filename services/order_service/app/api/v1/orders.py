import uuid
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import get_current_user_id
from app.db.base import get_db
from app.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["Orders"])


class CheckoutPayload(BaseModel):
    shipping_address: str


class OrderResponse(BaseModel):
    id: int
    user_id: int
    status: str
    total_amount: float
    shipping_address: str
    model_config = ConfigDict(from_attributes=True)


@router.get("/", response_model=list[OrderResponse])
async def get_my_orders(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    service = OrderService(db)
    return await service.get_user_orders(user_id)


@router.post("/checkout", response_model=OrderResponse)
async def checkout(
    payload: CheckoutPayload,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    x_idempotency_key: str | None = Header(default=None),
):
    idem_key = x_idempotency_key or str(uuid.uuid4())
    service = OrderService(db)
    return await service.checkout(user_id, payload.shipping_address, idem_key)


@router.post("/{order_id}/pay", response_model=OrderResponse)
async def pay_order(
    order_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Імітація успішної оплати замовлення."""
    service = OrderService(db)
    return await service.simulate_payment(order_id, user_id)
