from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt
from PIL import Image

from tests.unit.helpers import add_service_path, make_execute_result

add_service_path("catalog_service")

import app.services.media as media_mod  # noqa: E402
import app.services.product_service as product_service_mod  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import get_admin_user, get_current_user  # noqa: E402
from app.db.models import Category, Product  # noqa: E402
from app.services.media import process_and_upload_image  # noqa: E402
from app.services.product_service import ProductService, make_slug  # noqa: E402


def test_make_slug_transliteration_and_cleanup():
    assert make_slug("Відеокарти та SSD") == "videokarty-ta-ssd"
    assert make_slug("DDR5 6000MHz") == "ddr5-6000mhz"
    assert make_slug("   ").startswith("cat-")


def test_get_current_user_and_admin_guard():
    token = jwt.encode(
        {"sub": "1", "role": "admin", "type": "access"},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    payload = get_current_user(creds)
    assert payload["role"] == "admin"
    assert get_admin_user(payload)["sub"] == "1"

    client_payload = {"sub": "2", "role": "client", "type": "access"}
    with pytest.raises(HTTPException) as exc:
        get_admin_user(client_payload)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_create_category_deduplicates_and_increments_slug(mock_db_session, mock_redis_client):
    existing = Category(id=3, name="Processors", slug="processors")
    mock_db_session.execute.return_value = make_execute_result(scalar_one_or_none=existing)

    with patch.object(product_service_mod, "Redis") as mock_redis_cls:
        mock_redis_cls.from_url.return_value = mock_redis_client
        service = ProductService(mock_db_session)
        cat = await service.create_category("  processors  ")
        assert cat.id == 3
        mock_db_session.add.assert_not_called()

        mock_db_session.execute.side_effect = [
            make_execute_result(scalar_one_or_none=None),
            make_execute_result(scalar_one_or_none=Category(id=1, name="Other", slug="gpu-coolers")),
            make_execute_result(scalar_one_or_none=None),
        ]
        created = await service.create_category("GPU Coolers")
        assert created.slug == "gpu-coolers-2"
        mock_db_session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_create_product_validation_and_event_publish(mock_db_session, mock_redis_client):
    with patch.object(product_service_mod, "Redis") as mock_redis_cls:
        mock_redis_cls.from_url.return_value = mock_redis_client
        service = ProductService(mock_db_session)

        with pytest.raises(HTTPException) as exc_missing:
            await service.create_product({"title": "GPU", "price": 500.0, "stock": 5})
        assert exc_missing.value.status_code == 400

        mock_db_session.execute.return_value = make_execute_result(scalar_one_or_none=None)
        with pytest.raises(HTTPException) as exc_cat:
            await service.create_product({"title": "GPU", "price": 500.0, "stock": 5, "category_id": 999})
        assert exc_cat.value.status_code == 400

        async def _flush():
            pass

        mock_db_session.flush.side_effect = _flush
        created_prod = Product(
            id=77, title="RTX 4070", price=599.0, stock=10, category_id=2, is_active=True
        )
        mock_db_session.execute.side_effect = [
            make_execute_result(scalar_one_or_none=Category(id=2, name="GPUs", slug="gpus")),
            make_execute_result(scalar_one_or_none=created_prod),
        ]

        def _capture_add(obj):
            if isinstance(obj, Product):
                obj.id = 77

        mock_db_session.add.side_effect = _capture_add

        result = await service.create_product(
            {"title": "RTX 4070", "price": 599.0, "stock": 10, "category_id": 2}
        )
        assert result.id == 77
        mock_redis_client.xadd.assert_awaited_once_with(
            "product_events", {"action": "created", "product_id": "77"}
        )
        mock_redis_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_soft_delete_product(mock_db_session, mock_redis_client):
    prod = Product(id=12, title="Old Card", price=100.0, stock=3, is_active=True)
    mock_db_session.execute.return_value = make_execute_result(scalar_one_or_none=prod)

    with patch.object(product_service_mod, "Redis") as mock_redis_cls:
        mock_redis_cls.from_url.return_value = mock_redis_client
        service = ProductService(mock_db_session)
        await service.soft_delete(12)

        assert prod.is_active is False
        mock_db_session.commit.assert_awaited_once()
        mock_redis_client.xadd.assert_awaited_once_with(
            "product_events", {"action": "deleted", "product_id": "12"}
        )


@pytest.mark.asyncio
async def test_process_and_upload_image_converts_to_webp():
    buf = io.BytesIO()
    Image.new("RGB", (1200, 900), color=(30, 120, 220)).save(buf, format="PNG")
    raw_bytes = buf.getvalue()

    fake_minio = MagicMock()
    fake_minio.bucket_exists.return_value = True

    with patch.object(media_mod, "minio_client", fake_minio):
        url = await process_and_upload_image(raw_bytes) 

    assert url.startswith("http://localhost:9000/product-images/")
    assert url.endswith(".webp")
    fake_minio.put_object.assert_called_once()
    call_kwargs = fake_minio.put_object.call_args.kwargs
    assert call_kwargs["content_type"] == "image/webp"
    assert call_kwargs["length"] > 0