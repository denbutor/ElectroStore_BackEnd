import google.generativeai as genai
from app.core.config import settings

# Ініціалізація Google GenAI SDK
genai.configure(api_key=settings.GEMINI_API_KEY)

# Використовуємо Flash-модель для генерації тексту (швидка і безкоштовна)
chat_model = genai.GenerativeModel('gemini-1.5-flash')

async def get_embedding(text: str) -> list[float]:
    """Генерує вектор (768 вимірів) для тексту через модель text-embedding-004."""
    result = genai.embed_content(
        model="models/text-embedding-004",
        content=text,
        # task_type="retrieval_document",
        task_type="retrieval_query",
    )
    return result['embedding']