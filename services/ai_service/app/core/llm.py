import httpx
from app.core.config import settings

GEMINI_MODEL_TYPES: dict[str, str] = {
    "lite": "gemini-3.5-flash-lite",
    "flash": "gemini-3.8-flash",
    "pro": "gemini-3.1-pro-preview",
}

DEFAULT_MODEL_TYPE = "flash"

GEMINI_CHAT_MODELS: list[str] = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-pro-preview",
]

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSION = 768


def resolve_chat_models(model_type: str | None = None) -> list[str]:
    if not model_type:
        return list(GEMINI_CHAT_MODELS)

    normalized = model_type.strip().lower().removeprefix("models/")
    primary = GEMINI_MODEL_TYPES.get(normalized, normalized)

    ordered = [primary]
    for fallback in GEMINI_CHAT_MODELS:
        if fallback not in ordered:
            ordered.append(fallback)
    return ordered


async def get_embedding(text: str) -> list[float]:
    clean_text = (text or "").strip()
    if not clean_text:
        return [0.0] * EMBEDDING_DIMENSION

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{EMBEDDING_MODEL}:embedContent"
    )
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": settings.GEMINI_API_KEY,
    }
    payload = {
        "model": f"models/{EMBEDDING_MODEL}",
        "content": {
            "parts": [{"text": clean_text}],
        },
        "outputDimensionality": EMBEDDING_DIMENSION,
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    values = data.get("embedding", {}).get("values")
    if not values:
        raise ValueError(f"Порожній embedding у відповіді Gemini API: {data}")

    return values
