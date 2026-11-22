from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.unit.helpers import add_service_path, make_execute_result

add_service_path("ai_service")

import app.core.llm as llm_mod  # noqa: E402
import app.services.memory_service as memory_mod  # noqa: E402
import app.services.rag_service as rag_mod  # noqa: E402

from app.core.llm import EMBEDDING_DIMENSION, get_embedding, resolve_chat_models  # noqa: E402
from app.db.models import ProductVector  # noqa: E402
from app.services.memory_service import MemoryService  # noqa: E402
from app.services.rag_service import RAGService  # noqa: E402


def test_resolve_chat_models_ordering():
    default_chain = resolve_chat_models(None)
    assert default_chain[0] == "gemini-3.8-flash"

    pro_chain = resolve_chat_models("models/pro")
    assert pro_chain[0] == "gemini-3.1-pro-preview"
    assert len(set(pro_chain)) == len(pro_chain)


@pytest.mark.asyncio
async def test_get_embedding_empty_and_mocked_api():
    empty_vec = await get_embedding("   ")
    assert len(empty_vec) == EMBEDDING_DIMENSION
    assert all(v == 0.0 for v in empty_vec)

    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"embedding": {"values": [0.1, 0.2, 0.3]}}

    client_mock = AsyncMock()
    client_mock.post = AsyncMock(return_value=resp)
    client_ctx = AsyncMock()
    client_ctx.__aenter__.return_value = client_mock
    client_ctx.__aexit__.return_value = None

    with patch.object(llm_mod, "httpx") as mock_httpx:
        mock_httpx.AsyncClient.return_value = client_ctx
        vec = await get_embedding("Ryzen 7 9800X3D")
        assert vec == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_memory_service_save_and_get_history(mock_redis_client):
    with patch.object(memory_mod, "Redis") as mock_redis_cls:
        mock_redis_cls.from_url.return_value = mock_redis_client
        mem = MemoryService()
        await mem.save_interaction("sess-1", "Привіт", "Вітаю!")
        mock_redis_client.rpush.assert_awaited_once()
        mock_redis_client.ltrim.assert_awaited_once_with("chat_session:sess-1", -6, -1)
        mock_redis_client.expire.assert_awaited_once_with("chat_session:sess-1", 1800)
        mock_redis_client.aclose.assert_awaited_once()

    with patch.object(memory_mod, "Redis") as mock_redis_cls:
        mock_redis_cls.from_url.return_value = mock_redis_client
        mem = MemoryService()
        mock_redis_client.lrange.return_value = [
            '{"role": "user", "parts": [{"text": "Привіт"}]}',
            '{"role": "model", "parts": [{"text": "Вітаю!"}]}',
        ]
        history = await mem.get_history("sess-1")
        assert len(history) == 2
        assert history[0]["role"] == "user"


@pytest.mark.asyncio
async def test_rag_service_context_and_fallback_search(mock_db_session):
    prod = ProductVector(
        id=1,
        title="MSI MAG B650 Tomahawk WiFi",
        price=209.0,
        stock=17,
        specifications={"socket": "AM5", "chipset": "B650"},
        is_active=True,
        embedding=[0.05] * EMBEDDING_DIMENSION,
    )

    rag = RAGService(mock_db_session)
    empty_ctx = rag.format_context([])
    assert "NO matching in-stock items" in empty_ctx

    ctx = rag.format_context([prod])
    assert "MSI MAG B650 Tomahawk WiFi" in ctx
    assert "$209.0" in ctx
    assert "17 pcs" in ctx

    mock_db_session.execute.side_effect = [
        RuntimeError("pgvector unavailable"),
        make_execute_result(scalars_list=[prod]),
    ]
    with patch.object(
        rag_mod, "get_embedding", new=AsyncMock(return_value=[0.1] * EMBEDDING_DIMENSION)
    ):
        found = await rag.find_relevant_products("B650 AM5")
        assert len(found) == 1
        assert found[0].id == 1