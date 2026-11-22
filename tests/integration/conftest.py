from __future__ import annotations

import os
from typing import AsyncGenerator

import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_PG_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://test_user:test_pass@127.0.0.1:55432/electrostore_test",
)
TEST_REDIS_URL = os.getenv(
    "TEST_REDIS_URL",
    "redis://127.0.0.1:16379/0",
)


@pytest_asyncio.fixture
async def pg_engine():
    engine = create_async_engine(TEST_PG_URL, echo=False)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"PostgreSQL test instance not reachable at {TEST_PG_URL}: {exc}")

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_session(pg_engine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def redis_client() -> AsyncGenerator[Redis, None]:
    client = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        pong = await client.ping()
        if not pong:
            pytest.skip("Redis test instance did not respond to PING")
    except Exception as exc:
        await client.aclose()
        pytest.skip(f"Redis test instance not reachable at {TEST_REDIS_URL}: {exc}")

    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()