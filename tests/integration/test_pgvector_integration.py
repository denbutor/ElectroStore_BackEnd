from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from tests.unit.helpers import add_service_path


@pytest.mark.asyncio
async def test_pgvector_cosine_distance_query(pg_session):
    await pg_session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    await pg_session.execute(text("DROP TABLE IF EXISTS tmp_vector_items"))
    await pg_session.execute(
        text(
            """
            CREATE TEMP TABLE tmp_vector_items (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                embedding vector(3) NOT NULL
            )
            """
        )
    )
    await pg_session.execute(
        text(
            """
            INSERT INTO tmp_vector_items (title, embedding) VALUES
                ('Exact match', '[1.0, 0.0, 0.0]'),
                ('Orthogonal', '[0.0, 1.0, 0.0]')
            """
        )
    )

    rows = (
        await pg_session.execute(
            text(
                """
                SELECT title, (embedding <=> '[1.0, 0.0, 0.0]'::vector) AS dist
                FROM tmp_vector_items
                ORDER BY dist ASC
                """
            )
        )
    ).all()

    assert len(rows) == 2
    assert rows[0][0] == "Exact match"
    assert float(rows[0][1]) < float(rows[1][1])


@pytest.mark.asyncio
async def test_rag_service_real_postgres_pgvector(pg_session):
    add_service_path("ai_service")
    import app.services.rag_service as rag_mod  # noqa: E402
    from app.core.llm import EMBEDDING_DIMENSION  # noqa: E402
    from app.db.models import Base, ProductVector  # noqa: E402
    from app.services.rag_service import RAGService  # noqa: E402

    await pg_session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    conn = await pg_session.connection()
    await conn.run_sync(Base.metadata.create_all)

    vec_target = [0.0] * EMBEDDING_DIMENSION
    vec_target[0] = 1.0

    vec_other = [0.0] * EMBEDDING_DIMENSION
    vec_other[1] = 1.0

    p1 = ProductVector(
        id=9001,
        title="RTX 4080 Super Gaming",
        price=999.0,
        stock=4,
        specifications={"vram": "16GB GDDR6X"},
        is_active=True,
        embedding=vec_target,
    )
    p2 = ProductVector(
        id=9002,
        title="DDR5 32GB Kit",
        price=129.0,
        stock=15,
        specifications={"capacity": "32GB"},
        is_active=True,
        embedding=vec_other,
    )

    pg_session.add_all([p1, p2])
    await pg_session.flush()

    rag = RAGService(pg_session)
    with patch.object(rag_mod, "get_embedding", new=AsyncMock(return_value=vec_target)):
        items = await rag.find_relevant_products("RTX 4080 Super")

    assert len(items) >= 1
    assert items[0].id == 9001