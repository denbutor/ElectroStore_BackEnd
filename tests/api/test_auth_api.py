from __future__ import annotations

import pytest

from tests.api.conftest import load_service_app, make_async_client
from tests.unit.helpers import make_execute_result


@pytest.mark.asyncio
async def test_auth_register_and_login_flow(api_db_session):
    fastapi_app, _ = load_service_app("auth_service", api_db_session)

    from app.core.security import hash_password  # noqa: E402
    from app.db.models import User  # noqa: E402

    # 1. Реєстрація нового користувача
    api_db_session.execute.return_value = make_execute_result(scalar_one_or_none=None)

    async def _refresh(obj):
        obj.id = 15

    api_db_session.refresh.side_effect = _refresh

    async with make_async_client(fastapi_app) as client:
        resp = await client.post(
            "/api/v1/auth/register",
            json={"email": "new@electrostore.ua", "password": "Password123!", "full_name": "Test User"},
        )

    assert resp.status_code in (200, 201)
    body = resp.json()
    assert body["email"] == "new@electrostore.ua"
    assert body["role"] == "client"

    # 2. Логін з коректним паролем
    stored_hash = hash_password("Password123!")
    api_db_session.execute.return_value = make_execute_result(
        scalar_one_or_none=User(
            id=15, email="new@electrostore.ua", hashed_password=stored_hash, role="client", is_active=True
        )
    )

    async with make_async_client(fastapi_app) as client:
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "new@electrostore.ua", "password": "Password123!"},
        )

    assert login_resp.status_code == 200
    tokens = login_resp.json()
    assert "access_token" in tokens
    assert "refresh_token" in tokens
    assert tokens["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_auth_login_invalid_password_returns_401(api_db_session):
    fastapi_app, _ = load_service_app("auth_service", api_db_session)

    from app.core.security import hash_password  # noqa: E402
    from app.db.models import User  # noqa: E402

    api_db_session.execute.return_value = make_execute_result(
        scalar_one_or_none=User(
            id=1, email="u@electrostore.ua", hashed_password=hash_password("RightPass123"), role="client", is_active=True
        )
    )

    async with make_async_client(fastapi_app) as client:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "u@electrostore.ua", "password": "WrongPass123"},
        )

    assert resp.status_code == 401