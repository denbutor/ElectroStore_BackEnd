from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from jose import jwt

from tests.api.conftest import load_service_app, make_async_client


def _find_cart_post_path(fastapi_app) -> str:
    for route in getattr(fastapi_app, "routes", []):
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if "cart" in path and "POST" in methods:
            return path
    return "/api/v1/cart/items"


@pytest.mark.asyncio
async def test_cart_requires_auth_and_adds_item_with_token(api_db_session):
    fastapi_app, _ = load_service_app("order_service", api_db_session)

    from app.core.config import settings  # noqa: E402
    import app.api.v1.cart as cart_route_mod  # noqa: E402

    cart_path = _find_cart_post_path(fastapi_app)

    async with make_async_client(fastapi_app) as client:
        unauth_resp = await client.post(cart_path, json={"product_id": 1, "quantity": 1})
        assert unauth_resp.status_code in (401, 403)

        token = jwt.encode(
            {"sub": "25", "role": "client", "type": "access"},
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )
        fake_cart_service = AsyncMock()
        fake_cart_service.add_item = AsyncMock()
        fake_cart_service.get_cart = AsyncMock(return_value={1: 2})

        with patch.object(cart_route_mod, "CartRedisService", return_value=fake_cart_service):
            auth_resp = await client.post(
                cart_path,
                json={"product_id": 1, "quantity": 2},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert auth_resp.status_code == 200
        fake_cart_service.add_item.assert_awaited_once_with(25, 1, 2)