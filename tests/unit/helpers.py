from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT_DIR = Path(__file__).resolve().parents[2]

# Безпечні змінні оточення для юніт-тестів (щоб Settings не вимагав реального .env)
os.environ.setdefault("POSTGRES_USER", "test_user")
os.environ.setdefault("POSTGRES_PASSWORD", "test_pass")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CATALOG_DB_NAME", "test_catalog_db")
os.environ.setdefault("AUTH_DB_NAME", "test_auth_db")
os.environ.setdefault("ORDER_DB_NAME", "test_order_db")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("MINIO_ROOT_USER", "minioadmin")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "minioadmin")
os.environ.setdefault("MINIO_BUCKET_NAME", "product-images")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_PUBLIC_URL", "http://localhost:9000")
os.environ.setdefault("JWT_SECRET", "unit-test-secret-key-at-least-32-chars")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")


# def add_service_path(service_name: str) -> None:
#     service_dir = str(ROOT_DIR / "services" / service_name)
#     if service_dir not in sys.path:
#         sys.path.insert(0, service_dir)


def add_service_path(service_name: str) -> None:
    service_dir = str(ROOT_DIR / "services" / service_name)

    # Прибираємо шляхи інших сервісів, щоб уникнути конфлікту пакета `app`
    services_root = str(ROOT_DIR / "services")
    sys.path[:] = [
        p for p in sys.path
        if not p.startswith(services_root) or p == service_dir
    ]
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)

    # Очищаємо закешований пакет `app` та його підмодулі
    for mod_name in list(sys.modules):
        if mod_name == "app" or mod_name.startswith("app."):
            del sys.modules[mod_name]

def make_execute_result(
    *,
    scalar_one_or_none=None,
    scalar=None,
    scalars_list: list | None = None,
    rowcount: int = 1,
) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_one_or_none
    result.scalar.return_value = scalar
    result.rowcount = rowcount

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = scalars_list if scalars_list is not None else []
    result.scalars.return_value = scalars_mock
    return result