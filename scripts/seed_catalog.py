import asyncio
import io
import json
import os
import re
import uuid
from pathlib import Path

from minio import Minio
from PIL import Image
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DB_USER = os.getenv("POSTGRES_USER", "electro_admin")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "secret_password_123")
DB_HOST = os.getenv("POSTGRES_HOST", "postgres")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
CATALOG_DB = os.getenv("CATALOG_DB_NAME", "catalog_db")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_PUBLIC_URL = os.getenv("MINIO_PUBLIC_URL", "http://localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ROOT_USER", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_ROOT_PASSWORD", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET_NAME", "product-images")

CATALOG_URL = (
    f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{CATALOG_DB}"
)

BASE_DIR = Path(__file__).resolve().parent
SEED_FILE = BASE_DIR / "catalog_seed.json"
IMAGES_DIR = BASE_DIR / "product_images"


def slugify_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower().strip()).strip("-")


def find_image_file(title: str) -> Path | None:
    if not IMAGES_DIR.exists() or not IMAGES_DIR.is_dir():
        return None

    target_key = slugify_key(title)
    allowed_exts = {".webp", ".jpg", ".jpeg", ".png"}

    for file_path in IMAGES_DIR.iterdir():
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in allowed_exts:
            continue
        if slugify_key(file_path.stem) == target_key:
            return file_path
    return None


def upload_photo_to_minio(minio_client: Minio, image_path: Path) -> str:
    if not minio_client.bucket_exists(MINIO_BUCKET):
        minio_client.make_bucket(MINIO_BUCKET)

    with Image.open(image_path) as img:
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
        else:
            img = img.convert("RGB")
        img.thumbnail((800, 800))

        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=80)
        buf.seek(0)
        data_len = buf.getbuffer().nbytes

        object_name = f"{uuid.uuid4().hex}.webp"
        minio_client.put_object(
            MINIO_BUCKET,
            object_name,
            data=buf,
            length=data_len,
            content_type="image/webp",
        )

    base = MINIO_PUBLIC_URL.rstrip("/")
    return f"{base}/{MINIO_BUCKET}/{object_name}"


async def clear_catalog_cache() -> int:
    redis_client = Redis.from_url(REDIS_URL, decode_responses=True)
    deleted = 0
    try:
        for pattern in ("products:*", "categories:*", "product:*"):
            keys = [k async for k in redis_client.scan_iter(match=pattern)]
            if keys:
                deleted += await redis_client.delete(*keys)
    finally:
        await redis_client.aclose()
    return deleted


async def run_seed() -> None:
    if not SEED_FILE.exists():
        raise FileNotFoundError(f"Seed file not found: {SEED_FILE}")

    payload = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    categories: list[dict] = payload.get("categories", [])
    products: list[dict] = payload.get("products", [])

    minio_client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False,
    )

    engine = create_async_engine(CATALOG_URL)
    matched_images = 0

    try:
        async with engine.begin() as conn:
            print("1. Clearing products and categories tables...")
            await conn.execute(
                text("TRUNCATE TABLE products, categories RESTART IDENTITY CASCADE;")
            )

            has_embedding_res = await conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'products' AND column_name = 'embedding';"
                )
            )
            has_embedding = has_embedding_res.scalar() is not None

            print(f"2. Inserting {len(categories)} categories...")
            category_id_by_slug: dict[str, int] = {}
            for cat in categories:
                row = await conn.execute(
                    text(
                        "INSERT INTO categories (name, slug) VALUES (:name, :slug) "
                        "RETURNING id;"
                    ),
                    {"name": cat["name"], "slug": cat["slug"]},
                )
                category_id_by_slug[cat["slug"]] = row.scalar_one()

            print(f"3. Inserting {len(products)} products...")
            for item in products:
                cat_slug = item["category_slug"]
                if cat_slug not in category_id_by_slug:
                    raise ValueError(f"Unknown category_slug '{cat_slug}' for product '{item['title']}'")

                cat_id = category_id_by_slug[cat_slug]
                title = item["title"]
                img_path = find_image_file(title)
                image_url: str | None = None

                if img_path is not None:
                    image_url = upload_photo_to_minio(minio_client, img_path)
                    matched_images += 1
                    print(f"   [IMG] {title} <- {img_path.name}")

                specs_json = json.dumps(item.get("specifications", {}))

                if has_embedding:
                    await conn.execute(
                        text(
                            "INSERT INTO products "
                            "(title, description, price, stock, category_id, specifications, image_url, is_active, embedding) "
                            "VALUES (:title, :description, :price, :stock, :category_id, CAST(:specs AS jsonb), :image_url, TRUE, NULL);"
                        ),
                        {
                            "title": title,
                            "description": item["description"],
                            "price": float(item["price"]),
                            "stock": int(item["stock"]),
                            "category_id": cat_id,
                            "specs": specs_json,
                            "image_url": image_url,
                        },
                    )
                else:
                    await conn.execute(
                        text(
                            "INSERT INTO products "
                            "(title, description, price, stock, category_id, specifications, image_url, is_active) "
                            "VALUES (:title, :description, :price, :stock, :category_id, CAST(:specs AS jsonb), :image_url, TRUE);"
                        ),
                        {
                            "title": title,
                            "description": item["description"],
                            "price": float(item["price"]),
                            "stock": int(item["stock"]),
                            "category_id": cat_id,
                            "specs": specs_json,
                            "image_url": image_url,
                        },
                    )
    finally:
        await engine.dispose()

    print("4. Invalidating catalog cache in Redis...")
    deleted_keys = await clear_catalog_cache()

    print(
        f"Done! Seeded {len(categories)} categories and {len(products)} products "
        f"({matched_images} with photos), cleared {deleted_keys} Redis cache keys."
    )


if __name__ == "__main__":
    asyncio.run(run_seed())