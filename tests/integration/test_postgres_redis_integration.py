from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import text

from tests.integration.conftest import TEST_REDIS_URL
from tests.unit.helpers import add_service_path


@pytest.mark.asyncio
async def test_postgres_connection_and_pgvector_extension(pg_session):
    res = await pg_session.execute(text("SELECT version()"))
    version_str = res.scalar_one()
    assert "PostgreSQL" in version_str

    await pg_session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    ext_res = await pg_session.execute(
        text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
    )
    assert ext_res.scalar_one_or_none() == "vector"


@pytest.mark.asyncio
async def test_redis_cart_and_ttl_integration(redis_client):
    cart_key = "integration:cart:99"
    await redis_client.hincrby(cart_key, "101", 2)
    await redis_client.hincrby(cart_key, "101", 1)
    await redis_client.expire(cart_key, 120)

    data = await redis_client.hgetall(cart_key)
    ttl = await redis_client.ttl(cart_key)

    assert data == {"101": "3"}
    assert 0 < ttl <= 120


@pytest.mark.asyncio
async def test_cart_redis_service_real_redis_roundtrip(redis_client):
    add_service_path("order_service")
    import app.services.cart_redis as cart_mod  # noqa: E402
    from app.services.cart_redis import CartRedisService  # noqa: E402

    orig_from_url = cart_mod.Redis.from_url

    def _test_redis_from_url(url, *args, **kwargs):
        return orig_from_url(TEST_REDIS_URL, *args, **kwargs)

    with patch.object(cart_mod.Redis, "from_url", side_effect=_test_redis_from_url):
        service = CartRedisService()
        await service.add_item(user_id=77, product_id=10, quantity=2)
        await service.add_item(user_id=77, product_id=20, quantity=1)

        cart = await service.get_cart(77)
        assert cart == {10: 2, 20: 1}

        ttl = await redis_client.ttl("cart:77")
        assert ttl > 0

        first_lock = await service.lock_idempotency_key("order-idem-77")
        second_lock = await service.lock_idempotency_key("order-idem-77")
        assert first_lock is True
        assert second_lock is False