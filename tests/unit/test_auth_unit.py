from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from jose import jwt

from tests.unit.helpers import add_service_path, make_execute_result

add_service_path("auth_service")

import app.services.auth_service as auth_service_mod  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import (  # noqa: E402
    create_token,
    create_token_pair,
    hash_password,
    verify_password,
)
from app.db.models import User  # noqa: E402
from app.services.auth_service import AuthService  # noqa: E402


def test_password_hash_and_verify():
    raw = "StrongPass123!"
    hashed = hash_password(raw)

    assert hashed != raw
    assert verify_password(raw, hashed) is True
    assert verify_password("WrongPassword", hashed) is False
    assert verify_password(raw, "not-a-valid-bcrypt-hash") is False


def test_create_token_pair_structure_and_claims():
    pair = create_token_pair(user_id=42, role="admin")

    assert pair["token_type"] == "bearer"
    assert "access_token" in pair and "refresh_token" in pair

    access_payload = jwt.decode(
        pair["access_token"], settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
    )
    refresh_payload = jwt.decode(
        pair["refresh_token"], settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
    )

    assert access_payload["sub"] == "42"
    assert access_payload["role"] == "admin"
    assert access_payload["type"] == "access"
    assert refresh_payload["sub"] == "42"
    assert refresh_payload["type"] == "refresh"


@pytest.mark.asyncio
async def test_register_success(mock_db_session):
    mock_db_session.execute.return_value = make_execute_result(scalar_one_or_none=None)

    async def _refresh(obj):
        obj.id = 10

    mock_db_session.refresh.side_effect = _refresh

    service = AuthService(mock_db_session)
    user = await service.register("client@example.com", "Secret123!", "Denys")

    assert user.email == "client@example.com"
    assert user.full_name == "Denys"
    assert user.role == "client"
    assert verify_password("Secret123!", user.hashed_password)
    mock_db_session.add.assert_called_once()
    mock_db_session.commit.assert_awaited_once()
    mock_db_session.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_register_duplicate_email_raises_400(mock_db_session):
    existing_user = User(id=1, email="dup@example.com", hashed_password=hash_password("pw"))
    mock_db_session.execute.return_value = make_execute_result(scalar_one_or_none=existing_user)

    service = AuthService(mock_db_session)
    with pytest.raises(HTTPException) as exc:
        await service.register("dup@example.com", "pw")

    assert exc.value.status_code == 400
    mock_db_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_login_success_and_inactive_user(mock_db_session):
    hashed = hash_password("MyPass123")
    active_user = User(id=7, email="u@test.ua", hashed_password=hashed, role="client", is_active=True)
    mock_db_session.execute.return_value = make_execute_result(scalar_one_or_none=active_user)

    service = AuthService(mock_db_session)
    tokens = await service.login("u@test.ua", "MyPass123")
    assert tokens["token_type"] == "bearer"
    assert tokens["access_token"]

    inactive_user = User(id=7, email="u@test.ua", hashed_password=hashed, role="client", is_active=False)
    mock_db_session.execute.return_value = make_execute_result(scalar_one_or_none=inactive_user)

    with pytest.raises(HTTPException) as exc:
        await service.login("u@test.ua", "MyPass123")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_login_invalid_credentials_raises_401(mock_db_session):
    mock_db_session.execute.return_value = make_execute_result(scalar_one_or_none=None)
    service = AuthService(mock_db_session)

    with pytest.raises(HTTPException) as exc:
        await service.login("missing@test.ua", "bad")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_refresh_tokens_rejects_access_token_and_accepts_refresh_token(mock_db_session):
    service = AuthService(mock_db_session)

    wrong_type_token = create_token({"sub": "5", "type": "access"}, timedelta(minutes=10))
    with pytest.raises(HTTPException) as exc:
        await service.refresh_tokens(wrong_type_token)
    assert exc.value.status_code == 401

    valid_refresh = create_token({"sub": "5", "type": "refresh"}, timedelta(days=1))
    user = User(id=5, email="r@test.ua", hashed_password=hash_password("pw"), role="client", is_active=True)
    mock_db_session.execute.return_value = make_execute_result(scalar_one_or_none=user)

    with patch.object(
        auth_service_mod,
        "create_token_pair",
        return_value={"access_token": "new_a", "refresh_token": "new_r", "token_type": "bearer"},
    ) as mock_pair:
        res = await service.refresh_tokens(valid_refresh)
        assert res["access_token"] == "new_a"
        mock_pair.assert_called_once_with(user_id=5, role="client")