import asyncio
import google.generativeai as genai
from app.core.config import settings

genai.configure(api_key=settings.GEMINI_API_KEY)

GEMINI_CHAT_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.8-flash",
    "gemini-flash-latest",
]


async def get_embedding(text: str) -> list[float]:
    """Генерує вектор розмірності 768 через актуальну модель gemini-embedding-001."""
    result = await asyncio.to_thread(
        genai.embed_content,
        model="models/gemini-embedding-001",
        content=text,
        output_dimensionality=768,
    )
    return result["embedding"]