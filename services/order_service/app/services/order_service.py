# from fastapi import HTTPException, status
# from sqlalchemy import select
# from sqlalchemy.ext.asyncio import AsyncSession
# from app.db.models import Order, OrderItem
# from app.services.cart_redis import CartRedisService
# from app.core.httpx_client import fetch_product_price

# class OrderService:
#     def __init__(self, db: AsyncSession):
#         self.db = db
#         self.cart_service = CartRedisService()

#     async def checkout(self, user_id: int, shipping_address: str, idempotency_key: str) -> Order:
#         # 1. Захист від подвійних кліків "Оплатити"
#         if not await self.cart_service.lock_idempotency_key(idempotency_key):
#             raise HTTPException(status_code=400, detail="Замовлення вже обробляється або створено")

#         # 2. Отримання кошика з Redis
#         cart = await self.cart_service.get_cart(user_id)
#         if not cart:
#             raise HTTPException(status_code=400, detail="Кошик порожній")

#         total_amount = 0.0
#         order_items = []

#         # 3. Динамічна валідація цін через HTTP запит до catalog_service
#         for product_id, quantity in cart.items():
#             if quantity <= 0:
#                 continue
#             actual_price = await fetch_product_price(product_id)
#             total_amount += actual_price * quantity
#             order_items.append(
#                 OrderItem(product_id=product_id, quantity=quantity, unit_price=actual_price)
#             )

#         # 4. Атомарна транзакція БД
#         async with self.db.begin():
#             new_order = Order(
#                 user_id=user_id,
#                 total_amount=total_amount,
#                 shipping_address=shipping_address,
#                 status="pending_payment"
#             )
#             self.db.add(new_order)
#             await self.db.flush() # Отримуємо ID замовлення до коміту

#             for item in order_items:
#                 item.order_id = new_order.id
#                 self.db.add(item)
                
#         # 5. Очищення кошика після успішної транзакції
#         await self.cart_service.clear_cart(user_id)
        
#         return new_order

#     async def simulate_payment(self, order_id: int, user_id: int) -> Order:
#         """Метод для імітації оплати (наприклад, через Stripe Test Mode)."""
#         result = await self.db.execute(select(Order).where(Order.id == order_id, Order.user_id == user_id))
#         order = result.scalar_one_or_none()
        
#         if not order:
#             raise HTTPException(status_code=404, detail="Замовлення не знайдено")
#         if order.status != "pending_payment":
#             raise HTTPException(status_code=400, detail="Замовлення вже оплачено або скасовано")
            
#         order.status = "paid"
#         await self.db.commit()
#         await self.db.refresh(order)
#         return order

import json
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Order, OrderItem
from app.services.cart_redis import CartRedisService
from app.core.httpx_client import fetch_product_price

class OrderService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.cart_service = CartRedisService()

    async def checkout(self, user_id: int, shipping_address: str, idempotency_key: str) -> Order:
        if not await self.cart_service.lock_idempotency_key(idempotency_key):
            raise HTTPException(status_code=400, detail="Замовлення вже обробляється або створено")

        cart = await self.cart_service.get_cart(user_id)
        if not cart:
            raise HTTPException(status_code=400, detail="Кошик порожній")

        total_amount = 0.0
        order_items = []

        for product_id, quantity in cart.items():
            if quantity <= 0:
                continue
            actual_price = await fetch_product_price(product_id)
            total_amount += actual_price * quantity
            order_items.append(
                OrderItem(product_id=product_id, quantity=quantity, unit_price=actual_price)
            )

        async with self.db.begin():
            new_order = Order(
                user_id=user_id,
                total_amount=total_amount,
                shipping_address=shipping_address,
                status="pending_payment"
            )
            self.db.add(new_order)
            await self.db.flush()

            for item in order_items:
                item.order_id = new_order.id
                self.db.add(item)

        await self.cart_service.clear_cart(user_id)
        return new_order

    async def simulate_payment(self, order_id: int, user_id: int) -> Order:
        """Імітація успішної оплати та відправка події на списання залишків."""
        result = await self.db.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.id == order_id, Order.user_id == user_id)
        )
        order = result.scalar_one_or_none()

        if not order:
            raise HTTPException(status_code=404, detail="Замовлення не знайдено")
        if order.status != "pending_payment":
            raise HTTPException(status_code=400, detail="Замовлення вже оплачено або скасовано")

        order.status = "paid"
        await self.db.commit()
        await self.db.refresh(order)

        # Публікація події в Redis для catalog_service
        event_payload = {
            "event": "order_paid",
            "order_id": order.id,
            "items": [
                {"product_id": item.product_id, "quantity": item.quantity}
                for item in order.items
            ]
        }
        await self.cart_service.redis.publish("order_events", json.dumps(event_payload))

        return order