import argparse
import os
import re
from pathlib import Path
from unicodedata import normalize

import boto3
import psycopg

ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif"}


def normalize_name(value: str) -> str:
    text = normalize("NFKC", value or "").lower()
    text = re.sub(r"[_\-./\\]+", " ", text)
    text = re.sub(r"[^a-zа-яіїєґ0-9\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["MINIO_ENDPOINT"],
        aws_access_key_id=os.environ["MINIO_ACCESS_KEY"],
        aws_secret_access_key=os.environ["MINIO_SECRET_KEY"],
        region_name=os.environ.get("MINIO_REGION", "us-east-1"),
    )


def scan_local_photos(photos_dir: Path) -> dict[str, Path]:
    if not photos_dir.is_dir():
        raise FileNotFoundError(f"Папку не знайдено: {photos_dir}")

    result: dict[str, Path] = {}
    for file_path in sorted(photos_dir.iterdir()):
        if file_path.is_file() and file_path.suffix.lower() in ALLOWED_EXTS:
            key = normalize_name(file_path.stem)
            if key in result:
                print(f"[DUPLICATE FILE] '{key}': {result[key].name} та {file_path.name}")
            else:
                result[key] = file_path
    return result


def build_public_url(bucket: str, object_key: str) -> str:
    public_base = os.environ.get("MINIO_PUBLIC_URL")
    if public_base:
        return f"{public_base.rstrip('/')}/{bucket}/{object_key}"
    endpoint = os.environ["MINIO_ENDPOINT"].rstrip("/")
    return f"{endpoint}/{bucket}/{object_key}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--photos-dir", required=True)
    parser.add_argument("--bucket", default="product-images")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    photos_by_norm = scan_local_photos(Path(args.photos_dir))
    s3 = get_s3_client()

    with psycopg.connect(os.environ["CATALOG_DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, title, image_url FROM products ORDER BY id")
            rows = cur.fetchall()

        matched = []
        unmatched = []

        for prod_id, title, current_url in rows:
            if current_url and not args.overwrite:
                continue

            norm_title = normalize_name(title)
            local_file = photos_by_norm.get(norm_title)
            if not local_file:
                unmatched.append((prod_id, title))
                continue

            object_key = f"products/{prod_id}-{normalize_name(local_file.stem).replace(' ', '-')}{local_file.suffix.lower()}"
            new_url = build_public_url(args.bucket, object_key)
            matched.append((prod_id, title, local_file, object_key, new_url))

        print(f"Збігів знайдено: {len(matched)}")
        for prod_id, title, local_file, object_key, new_url in matched:
            print(f"  [MATCH] #{prod_id} '{title}' <- {local_file.name} -> {new_url}")

        print(f"\nТоварів без фото: {len(unmatched)}")
        for prod_id, title in unmatched:
            print(f"  [NO PHOTO] #{prod_id} '{title}'")

        if not args.apply:
            print("\nРежим DRY-RUN: нічого в MinIO і БД не записано.")
            print("Запусти з прапорцем --apply, щоб завантажити файли й оновити БД.")
            return

        existing_buckets = [b["Name"] for b in s3.list_buckets().get("Buckets", [])]
        if args.bucket not in existing_buckets:
            s3.create_bucket(Bucket=args.bucket)

        with conn.cursor() as cur:
            for prod_id, title, local_file, object_key, new_url in matched:
                s3.upload_file(str(local_file), args.bucket, object_key)
                cur.execute(
                    "UPDATE products SET image_url = %s WHERE id = %s",
                    (new_url, prod_id),
                )
        conn.commit()
        print("\nГотово! Файли завантажені в MinIO, посилання оновлені в БД.")


if __name__ == "__main__":
    main()
