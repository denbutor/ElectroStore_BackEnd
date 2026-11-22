from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_db_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
def mock_redis_client() -> AsyncMock:
    client = AsyncMock()
    client.xadd = AsyncMock(return_value="1-0")
    client.hincrby = AsyncMock(return_value=1)
    client.hdel = AsyncMock(return_value=1)
    client.expire = AsyncMock(return_value=True)
    client.hgetall = AsyncMock(return_value={})
    client.delete = AsyncMock(return_value=1)
    client.set = AsyncMock(return_value=True)
    client.rpush = AsyncMock(return_value=2)
    client.ltrim = AsyncMock(return_value=True)
    client.lrange = AsyncMock(return_value=[])
    client.aclose = AsyncMock()
    return client