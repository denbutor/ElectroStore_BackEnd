# from __future__ import annotations

import importlib
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from tests.unit.helpers import ROOT_DIR, add_service_path, make_execute_result  # noqa: F401


def _collect_db_dependencies(fastapi_app) -> list:
    found = []
    seen = set()

    def _walk_dependant(dependant):
        call = dependant.call
        if call is not None and callable(call):
            name = getattr(call, "__name__", "").lower()
            if ("db" in name or "session" in name) and call not in seen:
                seen.add(call)
                found.append(call)
        for sub in dependant.dependencies:
            _walk_dependant(sub)

    for route in getattr(fastapi_app, "routes", []):
        dependant = getattr(route, "dependant", None)
        if dependant is not None:
            _walk_dependant(dependant)
    return found


def load_service_app(service_name: str, db_override_session: AsyncMock):
    """Завантажує FastAPI `app` конкретного мікросервісу та підміняє залежність БД."""
    add_service_path(service_name)

    for mod_name in [
        m
        for m in sys.modules
        if m == "app.main" or m.startswith("app.api") or m.startswith("app.db")
    ]:
        del sys.modules[mod_name]

    main_mod = importlib.import_module("app.main")
    fastapi_app = main_mod.app

    async def _override_get_db():
        yield db_override_session

    for dep in _collect_db_dependencies(fastapi_app):
        fastapi_app.dependency_overrides[dep] = _override_get_db

    return fastapi_app, main_mod


@pytest.fixture
def api_db_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock(return_value=make_execute_result())
    return session


def make_async_client(fastapi_app) -> AsyncClient:
    transport = ASGITransport(app=fastapi_app)
    return AsyncClient(transport=transport, base_url="http://testserver")