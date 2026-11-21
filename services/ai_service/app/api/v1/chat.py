import asyncio
import json
import time
import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.llm import GEMINI_MODEL_TYPES, resolve_chat_models
from app.db.base import get_db
from app.services.memory_service import MemoryService
from app.services.rag_service import RAGService

router = APIRouter(prefix="/chat", tags=["AI Chat"])


class ChatPayload(BaseModel):
    session_id: str
    message: str
    model_type: str | None = "flash"  # "lite" | "flash" | "pro"


def _format_sse_data(text: str) -> str:
    if not text:
        return ""
    lines = text.split("\n")
    return "".join(f"data: {line}\n" for line in lines) + "\n"


@router.get("/models")
async def list_models():
    """Повертає доступні типи AI-моделей для вибору на фронтенді."""
    return {
        "default": "flash",
        "models": [
            {"id": "lite", "name": "Fast (Lite)", "model": GEMINI_MODEL_TYPES["lite"]},
            {"id": "flash", "name": "Balanced (Flash)", "model": GEMINI_MODEL_TYPES["flash"]},
            {"id": "pro", "name": "Expert (Pro)", "model": GEMINI_MODEL_TYPES["pro"]},
        ],
    }


@router.post("/stream")
async def chat_stream(
    payload: ChatPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    rag_service = RAGService(db)
    memory_service = MemoryService()

    # 1. Шукаємо релевантні товари в БД
    t_start = time.perf_counter()
    try:
        relevant_products = await rag_service.find_relevant_products(payload.message)
    except Exception as rag_exc:
        print(f"[AI RAG Warning] {rag_exc}")
        relevant_products = []
    context_str = rag_service.format_context(relevant_products)
    t_rag = time.perf_counter() - t_start

    # 2. Відновлюємо історію діалогу з Redis
    history = await memory_service.get_history(payload.session_id)

    # 3. Системна інструкція з контекстом товарів
    system_instruction = (
        "You are a professional consultant for the ElectroStore electronics shop. "
        "Your task is to help customers choose hardware, check component compatibility, and answer tech questions. "
        "Prioritize recommending products from the provided store context when available, "
        "but you may also use Google Search to find general technical specs, reviews, or info about external products. "
        "Be concise, always reply in the same language as the user's message, and display all prices in US dollars ($ / USD).\n"
        f"{context_str}"
    )

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
    }

    if settings.ENABLE_GOOGLE_SEARCH:
        request_body["tools"] = [{"google_search": {}}]

    candidate_models = resolve_chat_models(payload.model_type)

    async def event_generator():
        full_response_text = ""
        last_error = ""

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10.0, read=75.0, write=15.0, pool=15.0)
            ) as client:
                for idx, raw_model in enumerate(candidate_models):
                    model_name = raw_model.removeprefix("models/")
                    url = (
                        f"https://generativelanguage.googleapis.com/v1beta/models/"
                        f"{model_name}:streamGenerateContent?alt=sse"
                    )

                    max_attempts = 2 if idx == 0 else 1
                    model_succeeded = False
                    first_token_logged = False
                    t_model_start = time.perf_counter()

                    for attempt in range(1, max_attempts + 1):
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
                                    print(f"[AI Chat Warning] {last_error}")
                                    if response.status_code in (429, 503) and attempt < max_attempts:
                                        await asyncio.sleep(0.6)
                                        continue
                                    break

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
                                            if not first_token_logged:
                                                ttfb = time.perf_counter() - t_model_start
                                                print(
                                                    f"[AI Chat Timing] requested={payload.model_type} "
                                                    f"model={model_name} rag={t_rag:.2f}s ttfb={ttfb:.2f}s "
                                                    f"items={len(relevant_products)}"
                                                )
                                                first_token_logged = True
                                            full_response_text += text
                                            sse_chunk = _format_sse_data(text)
                                            if sse_chunk:
                                                yield sse_chunk

                                model_succeeded = True
                                break
                        except httpx.TimeoutException as exc:
                            last_error = f"Timeout ({model_name}): {type(exc).__name__}"
                            print(f"[AI Chat Warning] {last_error}")
                            if not full_response_text:
                                break
                            raise

                    if model_succeeded or full_response_text:
                        break
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
            print(f"[AI Chat Error] {err_msg}")
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
