import io
import uuid
from minio import Minio
from PIL import Image
from app.core.config import settings

minio_client = Minio(
    settings.MINIO_ENDPOINT,
    access_key=settings.MINIO_ROOT_USER,
    secret_key=settings.MINIO_ROOT_PASSWORD,
    secure=False,
)


def ensure_bucket_exists():
    if not minio_client.bucket_exists(settings.MINIO_BUCKET_NAME):
        minio_client.make_bucket(settings.MINIO_BUCKET_NAME)


async def process_and_upload_image(file_bytes: bytes) -> str:
    """Стискає зображення, конвертує у WebP та завантажує в MinIO."""
    ensure_bucket_exists()

    image = Image.open(io.BytesIO(file_bytes))
    image.thumbnail((800, 800))

    output = io.BytesIO()
    image.save(output, format="WEBP", quality=80)
    output.seek(0)

    filename = f"{uuid.uuid4().hex}.webp"
    minio_client.put_object(
        settings.MINIO_BUCKET_NAME,
        filename,
        data=output,
        length=output.getbuffer().nbytes,
        content_type="image/webp",
    )

    public_base = settings.MINIO_PUBLIC_URL.rstrip("/")
    return f"{public_base}/{settings.MINIO_BUCKET_NAME}/{filename}"
