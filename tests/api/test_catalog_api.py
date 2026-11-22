from __future__ import annotations

import pytest
from jose import jwt

from tests.api.conftest import load_service_app, make_async_client
from tests.unit.helpers import make_execute_result


def _find_categories_get_path(fastapi_app) -> str:
    for route in getattr(fastapi_app, "routes", []):
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if "categor" in path and "GET" in methods and "{" not in path:
            return path
    return "/api/v1/categories"


def _find_categories_post_path(fastapi_app, fallback: str) -> str:
    for route in getattr(fastapi_app, "routes", []):
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if "categor" in path and "POST" in methods and "{" not in path:
            return path
    return fallback


@pytest.mark.asyncio
async def test_catalog_list_categories_and_admin_guard(api_db_session):
    fastapi_app, _ = load_service_app("catalog_service", api_db_session)

    from app.core.config import settings  # noqa: E402
    from app.db.models import Category  # noqa: E402

    categories_get_path = _find_categories_get_path(fastapi_app)
    categories_post_path = _find_categories_post_path(fastapi_app, categories_get_path)

    api_db_session.execute.return_value = make_execute_result(
        scalars_list=[Category(id=1, name="GPUs", slug="gpus")]
    )

    async with make_async_client(fastapi_app) as client:
        ok_resp = await client.get(categories_get_path)
        assert ok_resp.status_code == 200
        assert ok_resp.json()[0]["slug"] == "gpus"

        # Запит до адмін-роуту зі звичайною роллю `client` має повернути 403
        client_token = jwt.encode(
            {"sub": "10", "role": "client", "type": "access"},
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )
        forbidden_resp = await client.post(
            categories_post_path,
            json={"name": "New Cat"},
            headers={"Authorization": f"Bearer {client_token}"},
        )
        assert forbidden_resp.status_code == 403