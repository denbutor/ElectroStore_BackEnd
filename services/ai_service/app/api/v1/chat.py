import asyncio
import json
import re
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

UI_LANG_TAG_RE = re.compile(r"^\s*\[\[UI_LANG\s*:\s*([a-zA-Z_-]+)\]\]\s*(?:\r?\n)?", re.IGNORECASE)

SUPPORTED_UI_LANGS = {
    "en": "English",
    "uk": "Ukrainian",
    "pl": "Polish",
    "de": "German",
    "es": "Spanish",
    "fr": "French",
    "it": "Italian",
    "nl": "Dutch",
    "da": "Danish",
    "sv": "Swedish",
    "cs": "Czech",
    "fi": "Finnish",
    "no": "Norwegian",
}


class ChatPayload(BaseModel):
    session_id: str
    message: str
    model_type: str | None = "flash"  # "lite" | "flash" | "pro"
    preferred_lang: str | None = None
    allow_ui_lang_switch: bool = True


def _format_sse_data(text: str) -> str:
    if not text:
        return ""
    lines = text.split("\n")
    return "".join(f"data: {line}\n" for line in lines) + "\n"


def _strip_ui_lang_tag(text: str) -> str:
    """Видаляє службовий маркер [[UI_LANG:...]] з початку тексту перед збереженням у Redis."""
    if not text:
        return ""
    return UI_LANG_TAG_RE.sub("", text, count=1).lstrip("\r\n")


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

    # 3. Системна інструкція з підтримкою 13 локалей UI та вільного спілкування будь-якою мовою
    lang_hint = ""
    if payload.preferred_lang and payload.preferred_lang in SUPPORTED_UI_LANGS:
        lang_name = SUPPORTED_UI_LANGS[payload.preferred_lang]
        lang_hint = (
            f"The user's current UI language is {lang_name} ({payload.preferred_lang}). "
            f"If the user's message is ambiguous or just a product/model name, reply in {lang_name}. "
        )

    supported_codes_str = ", ".join(SUPPORTED_UI_LANGS.keys())

    if payload.allow_ui_lang_switch:
        ui_lang_rule = (
            "UI LANGUAGE ORCHESTRATION RULE (STRICT):\n"
            f"Supported UI language codes are ONLY: [{supported_codes_str}].\n"
            "At the very beginning of your response (before any other text), output a single control tag on the first line:\n"
            "- Output `[[UI_LANG:<code>]]` (using one of the supported codes above) if the user writes a meaningful message (> 3 words) in that language "
            "(even if it contains English hardware/brand names like 'AMD Ryzen 7 9800X3D' or 'RTX 4080'), "
            "OR if the user explicitly asks to switch the site/UI language to one of those supported languages.\n"
            "- Output `[[UI_LANG:none]]` if the message is short (<= 3 words), just a greeting, just a product/component name without a clear language switch request, "
            "OR if the user writes in a language NOT in the supported UI list.\n"
            "Regardless of whether the UI language switches or not, ALWAYS reply in the exact language the user wrote in (any language in the world).\n"
            "Immediately after the closing `]]`, start your normal response.\n"
        )
    else:
        ui_lang_rule = (
            "UI LANGUAGE ORCHESTRATION RULE:\n"
            "Automatic UI language switching is currently LOCKED. Do NOT output any `[[UI_LANG:...]]` tag at all.\n"
            "Always reply in the language of the user's message (any language).\n"
        )

    system_instruction = (
        "You are a professional consultant for the ElectroStore electronics shop. "
        "Your task is to help customers choose hardware, check component compatibility, and answer tech questions. "
        "Prioritize recommending products from the provided store context when available, "
        "but you may also use Google Search to find general technical specs, reviews, or info about external products. "
        f"{lang_hint}"
        "Be concise, always reply in the same language as the user's message (or the requested target language if they asked to switch), "
        "and display all prices in US dollars ($ / USD).\n"
        f"{ui_lang_rule}"
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

            cleaned_response = _strip_ui_lang_tag(full_response_text)
            if cleaned_response:
                await memory_service.save_interaction(
                    payload.session_id,
                    payload.message,
                    cleaned_response,
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