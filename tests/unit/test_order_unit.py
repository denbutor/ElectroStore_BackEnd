from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt

from tests.unit.helpers import add_service_path

add_service_path("order_service")

from app.core.config import settings  # noqa: E402
from app.core.httpx_client import fetch_product_price  # noqa: E402
from app.core.security import get_current_user_id  # noqa: E402
from app.services.cart_redis import CartRedisService  # noqa: E402


def test_get_current_user_id_valid_and_invalid():
    valid_token = jwt.encode(
        {"sub": "105", "type": "access"}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=valid_token)
    assert get_current_user_id(creds) == 105

    refresh_token = jwt.encode(
        {"sub": "105", "type": "refresh"}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM
    )
    with pytest.raises(HTTPException) as exc:
        get_current_user_id(HTTPAuthorizationCredentials(scheme="Bearer", credentials=refresh_token))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_cart_redis_service_operations(mock_redis_client):
    with patch("app.services.cart_redis.Redis.from_url", return_value=mock_redis_client):
        service = CartRedisService()
        mock_redis_client.hincrby.return_value = 2
        await service.add_item(user_id=9, product_id=101, quantity=2)
        mock_redis_client.hincrby.assert_awaited_once_with("cart:9", "101", 2)
        mock_redis_client.expire.assert_awaited_once_with("cart:9", 86400 * 7)
        mock_redis_client.aclose.assert_awaited()

    with patch("app.services.cart_redis.Redis.from_url", return_value=mock_redis_client):
        service = CartRedisService()
        mock_redis_client.hincrby.return_value = 0
        await service.add_item(user_id=9, product_id=101, quantity=-2)
        mock_redis_client.hdel.assert_awaited_once_with("cart:9", "101")

    with patch("app.services.cart_redis.Redis.from_url", return_value=mock_redis_client):
        service = CartRedisService()
        mock_redis_client.hgetall.return_value = {"101": "2", "102": "0", "103": "1"}
        cart = await service.get_cart(9)
        assert cart == {101: 2, 103: 1}

    with patch("app.services.cart_redis.Redis.from_url", return_value=mock_redis_client):
        service = CartRedisService()
        assert await service.lock_idempotency_key("idem-abc") is True
        mock_redis_client.set.assert_awaited_once_with("idem:idem-abc", "1", nx=True, ex=3600)


@pytest.mark.asyncio
async def test_fetch_product_price_success_and_404(monkeypatch):
    monkeypatch.setattr(settings, "CATALOG_SERVICE_URL", "http://catalog_service:8000/api/v1")

    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.raise_for_status = MagicMock()
    ok_resp.json.return_value = {"id": 1, "price": 249.5}

    client_mock = AsyncMock()
    client_mock.get = AsyncMock(return_value=ok_resp)
    client_ctx = AsyncMock()
    client_ctx.__aenter__.return_value = client_mock
    client_ctx.__aexit__.return_value = None

    with patch("app.core.httpx_client.httpx.AsyncClient", return_value=client_ctx):
        price = await fetch_product_price(1)
        assert price == 249.5

    not_found_resp = MagicMock()
    not_found_resp.status_code = 404
    req = httpx.Request("GET", "http://catalog_service:8000/api/v1/products/999")
    res_obj = httpx.Response(404, request=req)
    not_found_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404", request=req, response=res_obj
    )

    client_mock.get = AsyncMock(return_value=not_found_resp)
    with patch("app.core.httpx_client.httpx.AsyncClient", return_value=client_ctx):
        with pytest.raises(HTTPException) as exc:
            await fetch_product_price(999)
        assert exc.value.status_code == 400