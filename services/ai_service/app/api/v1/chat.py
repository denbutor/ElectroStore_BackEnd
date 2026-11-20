import json
import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.llm import GEMINI_CHAT_MODELS
from app.db.base import get_db
from app.services.memory_service import MemoryService
from app.services.rag_service import RAGService

router = APIRouter(prefix="/chat", tags=["AI Chat"])


class ChatPayload(BaseModel):
    session_id: str
    message: str


@router.post("/stream")
async def chat_stream(
    payload: ChatPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    rag_service = RAGService(db)
    memory_service = MemoryService()

    # 1. Шукаємо релевантні товари в БД
    relevant_products = await rag_service.find_relevant_products(payload.message)
    context_str = rag_service.format_context(relevant_products)

    # 2. Відновлюємо історію діалогу з Redis
    history = await memory_service.get_history(payload.session_id)

    # 3. Системна інструкція з контекстом товарів
    system_instruction = (
        # "Ти професійний консультант магазину ElectroStore. "
        # "Твоя задача — допомагати у виборі техніки, перевіряти сумісність комплектуючих "
        # "і пропонувати товари тільки з наведеного контексту. Будь лаконічним.\n"
        # f"{context_str}"
        "You are a professional consultant for the ElectroStore electronics shop. "
        "Your task is to help customers choose hardware, check component compatibility, and answer tech questions. "
        "Prioritize recommending products from the provided store context when available, "
        "but you may also use Google Search to find general technical specs, reviews, or info about external products. "
        "Be concise, always reply in the same language as the user's message, and display all prices in US dollars ($ / USD).\n"
        f"{context_str}"
    )

    

    # system_instruction = (
    #     "You are a professional consultant for the ElectroStore electronics shop. "
    #     "Your task is to help customers choose hardware, check component compatibility, "
    #     "and recommend products only from the provided context. Be concise. "
    #     "Always reply in the same language as the user's message, and display all prices exclusively in US dollars ($ / USD).\n"
    #     f"{context_str}"
    # )

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": settings.GEMINI_API_KEY,
    }
    request_body = {
        "systemInstruction": {
            "parts": [{"text": system_instruction}],
        },
        "contents": [
            *history,
            {"role": "user", "parts": [{"text": payload.message}]},
        ],
        # "tools": [
        #     {"google_search": {}}
        # ],
    }
    
    if settings.ENABLE_GOOGLE_SEARCH:
        request_body["tools"] = [{"google_search": {}}]

    async def event_generator():
        full_response_text = ""
        last_error = ""

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10.0, read=15.0, write=10.0, pool=10.0)
            ) as client:
                for raw_model in GEMINI_CHAT_MODELS:
                    model_name = raw_model.removeprefix("models/")
                    url = (
                        f"https://generativelanguage.googleapis.com/v1beta/models/"
                        f"{model_name}:streamGenerateContent?alt=sse"
                    )

                    try:
                        async with client.stream(
                            "POST", url, headers=headers, json=request_body
                        ) as response:
                            if response.status_code != 200:
                                err_body = await response.aread()
                                last_error = (
                                    f"API {response.status_code} ({model_name}): "
                                    f"{err_body.decode('utf-8', errors='ignore')}"
                                )
                                continue

                            async for line in response.aiter_lines():
                                if await request.is_disconnected():
                                    break
                                if not line.startswith("data: "):
                                    continue

                                raw_data = line[6:].strip()
                                if not raw_data or raw_data == "[DONE]":
                                    continue

                                data = json.loads(raw_data)
                                candidates = data.get("candidates") or []
                                if not candidates:
                                    continue

                                parts = (
                                    candidates[0].get("content", {}).get("parts") or []
                                )
                                for part in parts:
                                    text = part.get("text")
                                    if text:
                                        full_response_text += text
                                        yield f"data: {text}\n\n"

                            break
                    except httpx.TimeoutException as exc:
                        last_error = f"Timeout ({model_name}): {type(exc).__name__}"
                        if not full_response_text:
                            continue
                        raise
                else:
                    yield f"data: [ПОМИЛКА: Усі моделі недоступні. {last_error}]\n\n"

            if full_response_text:
                await memory_service.save_interaction(
                    payload.session_id,
                    payload.message,
                    full_response_text,
                )
        except Exception as exc:
            err_msg = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            yield f"data: [ПОМИЛКА: {err_msg}]\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )