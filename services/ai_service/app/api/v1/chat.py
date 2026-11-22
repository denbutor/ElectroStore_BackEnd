import asyncio
import base64
from datetime import datetime, timezone
import json
import re
import time
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.llm import GEMINI_MODEL_TYPES, resolve_chat_models
from app.db.base import get_db
from app.services.memory_service import MemoryService
from app.services.rag_service import RAGService

router = APIRouter(prefix="/chat", tags=["AI Chat"])

UI_LANG_TAG_RE = re.compile(
    r"^\s*\[\[UI_LANG\s*:\s*([a-zA-Z_-]+)\]\]\s*(?:\r?\n)?", re.IGNORECASE
)
STRIP_EXTRA_SYMBOLS_RE = re.compile(r"[*#~`]+")

MAX_IMAGES_PER_REQUEST = 4
MAX_DECODED_IMAGE_BYTES = 4 * 1024 * 1024  # 4 MB per image after decode
ALLOWED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
DATA_URL_PREFIX_RE = re.compile(r"^data:(image/[a-zA-Z0-9.+-]+);base64,", re.IGNORECASE)

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


class ImageAttachment(BaseModel):
    mime_type: str = Field(..., description="image/jpeg, image/png or image/webp")
    data: str = Field(..., description="Base64 string or data URL")


class ChatPayload(BaseModel):
    session_id: str
    message: str = ""
    images: list[ImageAttachment] = Field(default_factory=list, max_length=MAX_IMAGES_PER_REQUEST)
    model_type: str | None = "flash"  # "lite" | "flash" | "pro"
    preferred_lang: str | None = None
    allow_ui_lang_switch: bool = True


def _normalize_image_attachment(att: ImageAttachment) -> tuple[str, str]:
    """Перевіряє MIME-тип, base64-кодування та розмір декодованого зображення."""
    raw = (att.data or "").strip()
    mime = (att.mime_type or "").strip().lower()

    data_url_match = DATA_URL_PREFIX_RE.match(raw)
    if data_url_match:
        if not mime:
            mime = data_url_match.group(1).lower()
        raw = raw[data_url_match.end():]

    if mime not in ALLOWED_IMAGE_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported image format '{mime}'. Allowed: JPEG, PNG, WEBP.",
        )

    compact_b64 = re.sub(r"\s+", "", raw)
    if not compact_b64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty image payload.",
        )

    try:
        decoded = base64.b64decode(compact_b64, validate=True)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid base64 image data.",
        ) from exc

    if len(decoded) == 0 or len(decoded) > MAX_DECODED_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Each image must not exceed 4 MB after decoding.",
        )

    clean_b64 = base64.b64encode(decoded).decode("ascii")
    return mime, clean_b64


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


def _build_user_parts(prompt_text: str, normalized_images: list[tuple[str, str]]) -> list[dict]:
    parts: list[dict] = []
    if prompt_text:
        parts.append({"text": prompt_text})
    for mime_type, b64_data in normalized_images:
        parts.append(
            {
                "inlineData": {
                    "mimeType": mime_type,
                    "data": b64_data,
                }
            }
        )
    return parts


async def _extract_search_terms_from_images(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    model_name: str,
    user_message: str,
    normalized_images: list[tuple[str, str]],
) -> list[str]:
    """Етап 1 дворівневого RAG: швидко розпізнає ключові сутності/категорії/характеристики з фото."""
    if not normalized_images:
        return []

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent"
    )
    probe_prompt = (
        "Identify the hardware components, electronics devices, brands, sockets, "
        "memory types (DDR4/DDR5), wattage, form factors, or categories visible in these images, "
        "plus complementary parts the user may need (e.g., CPU, motherboard, RAM, cooler, SSD, PSU, laptop). "
        f"User note: '{user_message or 'no text'}'. "
        "Return ONLY a JSON array of up to 8 short catalog search terms in English/hardware terms, "
        "e.g. [\"AM5 motherboard\", \"DDR5 RAM\", \"CPU cooler\", \"NVMe SSD\", \"850W PSU\"]."
    )
    body = {
        "contents": [
            {
                "role": "user",
                "parts": _build_user_parts(probe_prompt, normalized_images),
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 160,
        },
    }

    try:
        resp = await client.post(url, headers=headers, json=body, timeout=15.0)
        if resp.status_code != 200:
            return []
        payload = resp.json()
        candidates = payload.get("candidates") or []
        if not candidates:
            return []
        raw_text = "".join(
            p.get("text", "")
            for p in (candidates[0].get("content", {}).get("parts") or [])
        ).strip()
        json_match = re.search(r"\[[\s\S]*?\]", raw_text)
        if not json_match:
            return []
        parsed = json.loads(json_match.group(0))
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()][:8]
    except Exception as exc:
        print(f"[AI Vision Term Extraction Warning] {exc}")
    return []


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
    raw_message = (payload.message or "").strip()
    if len(payload.images) > MAX_IMAGES_PER_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {MAX_IMAGES_PER_REQUEST} images allowed per request.",
        )

    normalized_images = [_normalize_image_attachment(img) for img in payload.images]

    if not raw_message and not normalized_images:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message or at least one image is required.",
        )

    effective_user_prompt = raw_message or (
        "Analyze the attached photo(s) from my gallery, identify what is shown, "
        "check compatibility/suitability, and recommend relevant items from ElectroStore."
    )

    rag_service = RAGService(db)
    memory_service = MemoryService()
    candidate_models = resolve_chat_models(payload.model_type)

    # 1. Дворівневий пошук релевантних товарів у каталозі + зріз наявного складу
    t_start = time.perf_counter()
    relevant_products = []
    try:
        text_products = (
            await rag_service.find_relevant_products(raw_message, limit=6)
            if raw_message
            else []
        )
        vision_products = []
        if normalized_images:
            probe_model = candidate_models[0].removeprefix("models/")
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10.0, read=75.0, write=15.0, pool=15.0)
            ) as probe_client:
                vision_terms = await _extract_search_terms_from_images(
                    probe_client,
                    {
                        "Content-Type": "application/json",
                        "x-goog-api-key": settings.GEMINI_API_KEY,
                    },
                    probe_model,
                    raw_message,
                    normalized_images,
                )
            if vision_terms:
                vision_products = await rag_service.find_products_for_terms(
                    vision_terms, limit_per_term=3, max_total=14
                )

        # Додаємо зріз наявного складу, щоб модель не писала "немає в каталозі" про товари, які є в БД (кулери, SSD тощо)
        catalog_snapshot = await rag_service.get_in_stock_snapshot(limit=24)

        merged_by_id = {}
        for prod in [*text_products, *vision_products, *catalog_snapshot]:
            merged_by_id[prod.id] = prod
            if len(merged_by_id) >= 25:
                break
        relevant_products = list(merged_by_id.values())
    except Exception as rag_exc:
        print(f"[AI RAG Warning] {rag_exc}")
        relevant_products = []

    context_str = rag_service.format_context(relevant_products)
    t_rag = time.perf_counter() - t_start

    # 2. Історія чату в Redis (тільки текст, без зображень)
    history = await memory_service.get_history(payload.session_id)

    # 3. Мовні та сценарні інструкції
    current_date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lang_hint = ""
    if payload.preferred_lang and payload.preferred_lang in SUPPORTED_UI_LANGS:
        lang_name = SUPPORTED_UI_LANGS[payload.preferred_lang]
        lang_hint = (
            f"The user's current UI language is {lang_name} ({payload.preferred_lang}). "
            f"If the user's message is ambiguous, short, or just a photo without text, reply in {lang_name}. "
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
            "- Output `[[UI_LANG:none]]` if the message is short (<= 3 words), just a greeting, just a product/component name, "
            "a photo without text, or in a language NOT in the supported UI list.\n"
            "Regardless of whether the UI language switches or not, ALWAYS reply in the exact language the user wrote in (or preferred UI language if photo-only).\n"
            "Immediately after the closing `]]`, start your normal response.\n"
        )
    else:
        ui_lang_rule = (
            "UI LANGUAGE ORCHESTRATION RULE:\n"
            "Automatic UI language switching is currently LOCKED. Do NOT output any `[[UI_LANG:...]]` tag at all.\n"
            "Always reply in the language of the user's message (or preferred UI language if photo-only).\n"
        )

    honesty_and_accuracy_rule = (
        "HONEST INVENTORY & ENGINEERING PRECISION RULE (CRITICAL — APPLIES TO PC PARTS AND ALL DEVICES):\n"
        "1. **Strict Store Stock Honesty (NO Guessing or Fake Availability):**\n"
        "   - Compare what the user actually needs against the `ElectroStore Catalog Context` provided below.\n"
        "   - **Case A — The exact needed component/device IS in ElectroStore stock:** State directly and clearly that it IS available in ElectroStore, along with its exact price in `$` and stock count.\n"
        "   - **Case B — The ideal component/device is NOT in ElectroStore stock:** State honestly and directly that this item is currently NOT in the ElectroStore catalog/stock, name the single most suitable real-world model/component for the user's task, AND check if ElectroStore has a viable in-stock alternative.\n"
        "   - **Case C — Comparing Ideal Out-of-Stock Item vs. ElectroStore In-Stock Alternative:** Whenever an in-stock alternative exists in ElectroStore, explicitly explain the concrete technical differences between the ideal missing model and the store alternative (e.g., socket/chipset, VRM & cooling capability, RAM capacity/speed, GPU VRAM/connectors, PSU standard ATX 3.0/3.1 & 12V-2x6, screen/battery/portability, or real-world performance impact). If no suitable alternative exists in the store, honestly say so without forcing an incompatible item.\n"
        "2. **Zero Incompatible Combinations (Hard Engineering Check):**\n"
        "   - NEVER put incompatible parts in the same build option (e.g., NEVER pair an AMD AM5 CPU like Ryzen 7 7800X3D/9800X3D with an Intel LGA1851 Z890 motherboard, or an Intel LGA1851 CPU with an AMD X870E/B650 motherboard, or DDR4 RAM with DDR5 boards). If the catalog has no cheaper compatible motherboard for a budget tier, honestly state that no lower-tier compatible board is in stock instead of inserting an incompatible one.\n"
        "   - **Thermal / TDP Check:** Match coolers strictly to real CPU peak power (MTP), not just base TDP. For high-heat CPUs like Intel Core Ultra 9 285K (~250W peak load), do NOT recommend a basic single-tower cooler like ID-Cooling SE-224-XTS as sufficient — state honestly that a 360mm AIO liquid cooler (not in stock if absent) is ideal, and explain the difference compared to the strongest in-stock air cooler (e.g., Thermalright Phantom Spirit 120 SE, which handles gaming/moderate loads well but runs near its thermal limit under sustained all-core rendering).\n"
        "   - **Workload Accuracy for Devices (Laptops, Mini-PCs, Smartphones, Peripherals):** Match specs to actual real-world workflows. For software/backend/Docker/IDE development, prioritize >= 32GB RAM and fast multi-core CPUs/NVMe; if a 16GB laptop (like MacBook Air 16GB) is in stock while a 32GB/64GB model is ideal, explicitly state that 32GB+ is optimal for heavy Docker workloads, note that 32GB MacBooks are not in stock, and explain the practical difference vs. the in-stock 16GB MacBook Air or a 32GB Mini-PC/desktop. Do NOT push heavy gaming laptops with discrete GPUs for pure backend coding unless GPU compute/ML/gaming is requested.\n"
        "   - **Connector & Standard Precision:** Use accurate hardware standards (e.g., RTX 4070 Super uses a 16-pin 12V-2x6 / 12VHPWR connector, compatible with ATX 3.0 / ATX 3.1 PSUs or the included adapter).\n"
    )

    multimodal_scenarios_rule = (
        "MULTIMODAL & HARDWARE CONSULTATION SCENARIOS:\n"
        "1. **PC Build / Upgrade from Photo(s) of Existing Parts:**\n"
        "   - Step A: Identify every part visible in the photo(s) (exact or most likely model, socket, DDR4/DDR5, form factor, power connectors, dimensions) and list strict compatibility constraints.\n"
        "   - Step B: Provide 3 structured, 100%-compatible options:\n"
        "     (1) **Максимум надійності й продуктивності** (Maximum Reliability & Performance)\n"
        "     (2) **Оптимальний баланс** (Optimal Balance)\n"
        "     (3) **Бюджетний варіант** (Budget Option)\n"
        "     For EACH option, clearly separate: (a) Kept parts from the photo, (b) Available in ElectroStore (with `$` price & stock), and (c) Missing parts not in ElectroStore (naming the best model + comparing with any in-stock alternative).\n"
        "2. **Device / Tech Selection for User Tasks (laptops, mini-PCs, phones, monitors, workstations):**\n"
        "   - Analyze the device/workspace in the photo(s) and user's goal, give an honest verdict on fit, present 3 budget/tier options using ElectroStore stock where appropriate, and clearly explain trade-offs vs. ideal out-of-stock models.\n"
        "3. **Uncertain / Blurry / Incomplete Photo Fallback:**\n"
        "   - If the photo is blurry, angled, or hides labels/revisions: name the top likely model(s), state specifically what cannot be verified on the image (e.g., exact chipset revision, socket pinout, wattage sticker), ask 1–2 short confirmation questions, and mark compatibility advice as preliminary until confirmed.\n"
    )

    system_instruction = (
        f"You are a senior hardware engineer and honest consultant for the ElectroStore electronics shop. "
        f"Current date: {current_date_str}. "
        "Your goal is to give accurate, engineering-grade advice on PC components, laptops, smartphones, and electronics. "
        "You may use Google Search to verify technical specifications, release details, and real-world benchmarks, "
        "but NEVER claim an item is in ElectroStore stock unless it is explicitly listed in the `ElectroStore Catalog Context` below. "
        f"{lang_hint}"
        "Do not use '*', '#', '`', or '~' characters in your response; keep normal punctuation such as '.', ',', ';', ':', '-', '–', '—', '!', '?', parentheses, quotes, '/', '%', and '$'. "
        "Be concise, structured, and always display all prices in US dollars ($ / USD).\n"
        f"{ui_lang_rule}\n"
        f"{honesty_and_accuracy_rule}\n"
        f"{multimodal_scenarios_rule}\n"
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
            {
                "role": "user",
                "parts": _build_user_parts(effective_user_prompt, normalized_images),
            },
        ],
    }

    if settings.ENABLE_GOOGLE_SEARCH:
        request_body["tools"] = [{"google_search": {}}]

    # У Redis зберігаємо лише текстовий запис (без base64 зображень)
    redis_user_summary = raw_message
    if normalized_images:
        photo_note = f"[Attached {len(normalized_images)} gallery photo(s)]"
        redis_user_summary = f"{raw_message} {photo_note}".strip() if raw_message else photo_note

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
                                                    f"images={len(normalized_images)} items={len(relevant_products)}"
                                                )
                                                first_token_logged = True
                                            full_response_text += text
                                            clean_text = STRIP_EXTRA_SYMBOLS_RE.sub("", text)
                                            sse_chunk = _format_sse_data(clean_text)
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

            cleaned_response = _strip_ui_lang_tag(
                STRIP_EXTRA_SYMBOLS_RE.sub("", full_response_text)
            )
            if cleaned_response:
                await memory_service.save_interaction(
                    payload.session_id,
                    redis_user_summary,
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

# import asyncio
# import base64
# from datetime import datetime, timezone
# import json
# import re
# import time
# import httpx
# from fastapi import APIRouter, Depends, HTTPException, Request, status
# from fastapi.responses import StreamingResponse
# from pydantic import BaseModel, Field
# from sqlalchemy.ext.asyncio import AsyncSession

# from app.core.config import settings
# from app.core.llm import GEMINI_MODEL_TYPES, resolve_chat_models
# from app.db.base import get_db
# from app.services.memory_service import MemoryService
# from app.services.rag_service import RAGService

# router = APIRouter(prefix="/chat", tags=["AI Chat"])

# UI_LANG_TAG_RE = re.compile(
#     r"^\s*\[\[UI_LANG\s*:\s*([a-zA-Z_-]+)\]\]\s*(?:\r?\n)?", re.IGNORECASE
# )

# MAX_IMAGES_PER_REQUEST = 4
# MAX_DECODED_IMAGE_BYTES = 4 * 1024 * 1024  # 4 MB per image after decode
# ALLOWED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
# DATA_URL_PREFIX_RE = re.compile(r"^data:(image/[a-zA-Z0-9.+-]+);base64,", re.IGNORECASE)

# SUPPORTED_UI_LANGS = {
#     "en": "English",
#     "uk": "Ukrainian",
#     "pl": "Polish",
#     "de": "German",
#     "es": "Spanish",
#     "fr": "French",
#     "it": "Italian",
#     "nl": "Dutch",
#     "da": "Danish",
#     "sv": "Swedish",
#     "cs": "Czech",
#     "fi": "Finnish",
#     "no": "Norwegian",
# }


# class ImageAttachment(BaseModel):
#     mime_type: str = Field(..., description="image/jpeg, image/png or image/webp")
#     data: str = Field(..., description="Base64 string or data URL")


# class ChatPayload(BaseModel):
#     session_id: str
#     message: str = ""
#     images: list[ImageAttachment] = Field(default_factory=list, max_length=MAX_IMAGES_PER_REQUEST)
#     model_type: str | None = "flash"  # "lite" | "flash" | "pro"
#     preferred_lang: str | None = None
#     allow_ui_lang_switch: bool = True


# def _normalize_image_attachment(att: ImageAttachment) -> tuple[str, str]:
#     """Перевіряє MIME-тип, base64-кодування та розмір декодованого зображення."""
#     raw = (att.data or "").strip()
#     mime = (att.mime_type or "").strip().lower()

#     data_url_match = DATA_URL_PREFIX_RE.match(raw)
#     if data_url_match:
#         if not mime:
#             mime = data_url_match.group(1).lower()
#         raw = raw[data_url_match.end():]

#     if mime not in ALLOWED_IMAGE_MIME_TYPES:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail=f"Unsupported image format '{mime}'. Allowed: JPEG, PNG, WEBP.",
#         )

#     compact_b64 = re.sub(r"\s+", "", raw)
#     if not compact_b64:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="Empty image payload.",
#         )

#     try:
#         decoded = base64.b64decode(compact_b64, validate=True)
#     except Exception as exc:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="Invalid base64 image data.",
#         ) from exc

#     if len(decoded) == 0 or len(decoded) > MAX_DECODED_IMAGE_BYTES:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="Each image must not exceed 4 MB after decoding.",
#         )

#     clean_b64 = base64.b64encode(decoded).decode("ascii")
#     return mime, clean_b64


# def _format_sse_data(text: str) -> str:
#     if not text:
#         return ""
#     lines = text.split("\n")
#     return "".join(f"data: {line}\n" for line in lines) + "\n"


# def _strip_ui_lang_tag(text: str) -> str:
#     """Видаляє службовий маркер [[UI_LANG:...]] з початку тексту перед збереженням у Redis."""
#     if not text:
#         return ""
#     return UI_LANG_TAG_RE.sub("", text, count=1).lstrip("\r\n")


# def _build_user_parts(prompt_text: str, normalized_images: list[tuple[str, str]]) -> list[dict]:
#     parts: list[dict] = []
#     if prompt_text:
#         parts.append({"text": prompt_text})
#     for mime_type, b64_data in normalized_images:
#         parts.append(
#             {
#                 "inlineData": {
#                     "mimeType": mime_type,
#                     "data": b64_data,
#                 }
#             }
#         )
#     return parts


# async def _extract_search_terms_from_images(
#     client: httpx.AsyncClient,
#     headers: dict[str, str],
#     model_name: str,
#     user_message: str,
#     normalized_images: list[tuple[str, str]],
# ) -> list[str]:
#     """Етап 1 дворівневого RAG: швидко розпізнає ключові сутності/категорії/характеристики з фото."""
#     if not normalized_images:
#         return []

#     url = (
#         f"https://generativelanguage.googleapis.com/v1beta/models/"
#         f"{model_name}:generateContent"
#     )
#     probe_prompt = (
#         "Identify the hardware components, electronics devices, brands, sockets, "
#         "memory types (DDR4/DDR5), wattage, form factors, or categories visible in these images, "
#         "plus complementary parts the user may need (e.g., CPU, motherboard, RAM, cooler, SSD, PSU, laptop). "
#         f"User note: '{user_message or 'no text'}'. "
#         "Return ONLY a JSON array of up to 8 short catalog search terms in English/hardware terms, "
#         "e.g. [\"AM5 motherboard\", \"DDR5 RAM\", \"CPU cooler\", \"NVMe SSD\", \"850W PSU\"]."
#     )
#     body = {
#         "contents": [
#             {
#                 "role": "user",
#                 "parts": _build_user_parts(probe_prompt, normalized_images),
#             }
#         ],
#         "generationConfig": {
#             "temperature": 0.1,
#             "maxOutputTokens": 160,
#         },
#     }

#     try:
#         resp = await client.post(url, headers=headers, json=body, timeout=15.0)
#         if resp.status_code != 200:
#             return []
#         payload = resp.json()
#         candidates = payload.get("candidates") or []
#         if not candidates:
#             return []
#         raw_text = "".join(
#             p.get("text", "")
#             for p in (candidates[0].get("content", {}).get("parts") or [])
#         ).strip()
#         json_match = re.search(r"\[[\s\S]*?\]", raw_text)
#         if not json_match:
#             return []
#         parsed = json.loads(json_match.group(0))
#         if isinstance(parsed, list):
#             return [str(item).strip() for item in parsed if str(item).strip()][:8]
#     except Exception as exc:
#         print(f"[AI Vision Term Extraction Warning] {exc}")
#     return []


# @router.get("/models")
# async def list_models():
#     """Повертає доступні типи AI-моделей для вибору на фронтенді."""
#     return {
#         "default": "flash",
#         "models": [
#             {"id": "lite", "name": "Fast (Lite)", "model": GEMINI_MODEL_TYPES["lite"]},
#             {"id": "flash", "name": "Balanced (Flash)", "model": GEMINI_MODEL_TYPES["flash"]},
#             {"id": "pro", "name": "Expert (Pro)", "model": GEMINI_MODEL_TYPES["pro"]},
#         ],
#     }


# @router.post("/stream")
# async def chat_stream(
#     payload: ChatPayload,
#     request: Request,
#     db: AsyncSession = Depends(get_db),
# ):
#     raw_message = (payload.message or "").strip()
#     if len(payload.images) > MAX_IMAGES_PER_REQUEST:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail=f"Maximum {MAX_IMAGES_PER_REQUEST} images allowed per request.",
#         )

#     normalized_images = [_normalize_image_attachment(img) for img in payload.images]

#     if not raw_message and not normalized_images:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="Message or at least one image is required.",
#         )

#     effective_user_prompt = raw_message or (
#         "Analyze the attached photo(s) from my gallery, identify what is shown, "
#         "check compatibility/suitability, and recommend relevant items from ElectroStore."
#     )

#     rag_service = RAGService(db)
#     memory_service = MemoryService()
#     candidate_models = resolve_chat_models(payload.model_type)

#     # 1. Дворівневий пошук релевантних товарів у каталозі + зріз наявного складу
#     t_start = time.perf_counter()
#     relevant_products = []
#     try:
#         text_products = (
#             await rag_service.find_relevant_products(raw_message, limit=6)
#             if raw_message
#             else []
#         )
#         vision_products = []
#         if normalized_images:
#             probe_model = candidate_models[0].removeprefix("models/")
#             async with httpx.AsyncClient(
#                 timeout=httpx.Timeout(connect=10.0, read=75.0, write=15.0, pool=15.0)
#             ) as probe_client:
#                 vision_terms = await _extract_search_terms_from_images(
#                     probe_client,
#                     {
#                         "Content-Type": "application/json",
#                         "x-goog-api-key": settings.GEMINI_API_KEY,
#                     },
#                     probe_model,
#                     raw_message,
#                     normalized_images,
#                 )
#             if vision_terms:
#                 vision_products = await rag_service.find_products_for_terms(
#                     vision_terms, limit_per_term=3, max_total=14
#                 )

#         # Додаємо зріз наявного складу, щоб модель не писала "немає в каталозі" про товари, які є в БД (кулери, SSD тощо)
#         catalog_snapshot = await rag_service.get_in_stock_snapshot(limit=24)

#         merged_by_id = {}
#         for prod in [*text_products, *vision_products, *catalog_snapshot]:
#             merged_by_id[prod.id] = prod
#             if len(merged_by_id) >= 25:
#                 break
#         relevant_products = list(merged_by_id.values())
#     except Exception as rag_exc:
#         print(f"[AI RAG Warning] {rag_exc}")
#         relevant_products = []

#     context_str = rag_service.format_context(relevant_products)
#     t_rag = time.perf_counter() - t_start

#     # 2. Історія чату в Redis (тільки текст, без зображень)
#     history = await memory_service.get_history(payload.session_id)

#     # 3. Мовні та сценарні інструкції
#     current_date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

#     lang_hint = ""
#     if payload.preferred_lang and payload.preferred_lang in SUPPORTED_UI_LANGS:
#         lang_name = SUPPORTED_UI_LANGS[payload.preferred_lang]
#         lang_hint = (
#             f"The user's current UI language is {lang_name} ({payload.preferred_lang}). "
#             f"If the user's message is ambiguous, short, or just a photo without text, reply in {lang_name}. "
#         )

#     supported_codes_str = ", ".join(SUPPORTED_UI_LANGS.keys())

#     if payload.allow_ui_lang_switch:
#         ui_lang_rule = (
#             "UI LANGUAGE ORCHESTRATION RULE (STRICT):\n"
#             f"Supported UI language codes are ONLY: [{supported_codes_str}].\n"
#             "At the very beginning of your response (before any other text), output a single control tag on the first line:\n"
#             "- Output `[[UI_LANG:<code>]]` (using one of the supported codes above) if the user writes a meaningful message (> 3 words) in that language "
#             "(even if it contains English hardware/brand names like 'AMD Ryzen 7 9800X3D' or 'RTX 4080'), "
#             "OR if the user explicitly asks to switch the site/UI language to one of those supported languages.\n"
#             "- Output `[[UI_LANG:none]]` if the message is short (<= 3 words), just a greeting, just a product/component name, "
#             "a photo without text, or in a language NOT in the supported UI list.\n"
#             "Regardless of whether the UI language switches or not, ALWAYS reply in the exact language the user wrote in (or preferred UI language if photo-only).\n"
#             "Immediately after the closing `]]`, start your normal response.\n"
#         )
#     else:
#         ui_lang_rule = (
#             "UI LANGUAGE ORCHESTRATION RULE:\n"
#             "Automatic UI language switching is currently LOCKED. Do NOT output any `[[UI_LANG:...]]` tag at all.\n"
#             "Always reply in the language of the user's message (or preferred UI language if photo-only).\n"
#         )

#     honesty_and_accuracy_rule = (
#         "HONEST INVENTORY & ENGINEERING PRECISION RULE (CRITICAL — APPLIES TO PC PARTS AND ALL DEVICES):\n"
#         "1. **Strict Store Stock Honesty (NO Guessing or Fake Availability):**\n"
#         "   - Compare what the user actually needs against the `ElectroStore Catalog Context` provided below.\n"
#         "   - **Case A — The exact needed component/device IS in ElectroStore stock:** State directly and clearly that it IS available in ElectroStore, along with its exact price in `$` and stock count.\n"
#         "   - **Case B — The ideal component/device is NOT in ElectroStore stock:** State honestly and directly that this item is currently NOT in the ElectroStore catalog/stock, name the single most suitable real-world model/component for the user's task, AND check if ElectroStore has a viable in-stock alternative.\n"
#         "   - **Case C — Comparing Ideal Out-of-Stock Item vs. ElectroStore In-Stock Alternative:** Whenever an in-stock alternative exists in ElectroStore, explicitly explain the concrete technical differences between the ideal missing model and the store alternative (e.g., socket/chipset, VRM & cooling capability, RAM capacity/speed, GPU VRAM/connectors, PSU standard ATX 3.0/3.1 & 12V-2x6, screen/battery/portability, or real-world performance impact). If no suitable alternative exists in the store, honestly say so without forcing an incompatible item.\n"
#         "2. **Zero Incompatible Combinations (Hard Engineering Check):**\n"
#         "   - NEVER put incompatible parts in the same build option (e.g., NEVER pair an AMD AM5 CPU like Ryzen 7 7800X3D/9800X3D with an Intel LGA1851 Z890 motherboard, or an Intel LGA1851 CPU with an AMD X870E/B650 motherboard, or DDR4 RAM with DDR5 boards). If the catalog has no cheaper compatible motherboard for a budget tier, honestly state that no lower-tier compatible board is in stock instead of inserting an incompatible one.\n"
#         "   - **Thermal / TDP Check:** Match coolers strictly to real CPU peak power (MTP), not just base TDP. For high-heat CPUs like Intel Core Ultra 9 285K (~250W peak load), do NOT recommend a basic single-tower cooler like ID-Cooling SE-224-XTS as sufficient — state honestly that a 360mm AIO liquid cooler (not in stock if absent) is ideal, and explain the difference compared to the strongest in-stock air cooler (e.g., Thermalright Phantom Spirit 120 SE, which handles gaming/moderate loads well but runs near its thermal limit under sustained all-core rendering).\n"
#         "   - **Workload Accuracy for Devices (Laptops, Mini-PCs, Smartphones, Peripherals):** Match specs to actual real-world workflows. For software/backend/Docker/IDE development, prioritize >= 32GB RAM and fast multi-core CPUs/NVMe; if a 16GB laptop (like MacBook Air 16GB) is in stock while a 32GB/64GB model is ideal, explicitly state that 32GB+ is optimal for heavy Docker workloads, note that 32GB MacBooks are not in stock, and explain the practical difference vs. the in-stock 16GB MacBook Air or a 32GB Mini-PC/desktop. Do NOT push heavy gaming laptops with discrete GPUs for pure backend coding unless GPU compute/ML/gaming is requested.\n"
#         "   - **Connector & Standard Precision:** Use accurate hardware standards (e.g., RTX 4070 Super uses a 16-pin 12V-2x6 / 12VHPWR connector, compatible with ATX 3.0 / ATX 3.1 PSUs or the included adapter).\n"
#     )

#     multimodal_scenarios_rule = (
#         "MULTIMODAL & HARDWARE CONSULTATION SCENARIOS:\n"
#         "1. **PC Build / Upgrade from Photo(s) of Existing Parts:**\n"
#         "   - Step A: Identify every part visible in the photo(s) (exact or most likely model, socket, DDR4/DDR5, form factor, power connectors, dimensions) and list strict compatibility constraints.\n"
#         "   - Step B: Provide 3 structured, 100%-compatible options:\n"
#         "     (1) **Максимум надійності й продуктивності** (Maximum Reliability & Performance)\n"
#         "     (2) **Оптимальний баланс** (Optimal Balance)\n"
#         "     (3) **Бюджетний варіант** (Budget Option)\n"
#         "     For EACH option, clearly separate: (a) Kept parts from the photo, (b) Available in ElectroStore (with `$` price & stock), and (c) Missing parts not in ElectroStore (naming the best model + comparing with any in-stock alternative).\n"
#         "2. **Device / Tech Selection for User Tasks (laptops, mini-PCs, phones, monitors, workstations):**\n"
#         "   - Analyze the device/workspace in the photo(s) and user's goal, give an honest verdict on fit, present 3 budget/tier options using ElectroStore stock where appropriate, and clearly explain trade-offs vs. ideal out-of-stock models.\n"
#         "3. **Uncertain / Blurry / Incomplete Photo Fallback:**\n"
#         "   - If the photo is blurry, angled, or hides labels/revisions: name the top likely model(s), state specifically what cannot be verified on the image (e.g., exact chipset revision, socket pinout, wattage sticker), ask 1–2 short confirmation questions, and mark compatibility advice as preliminary until confirmed.\n"
#     )

#     system_instruction = (
#         f"You are a senior hardware engineer and honest consultant for the ElectroStore electronics shop. "
#         f"Current date: {current_date_str}. "
#         "Your goal is to give accurate, engineering-grade advice on PC components, laptops, smartphones, and electronics. "
#         "You may use Google Search to verify technical specifications, release details, and real-world benchmarks, "
#         "but NEVER claim an item is in ElectroStore stock unless it is explicitly listed in the `ElectroStore Catalog Context` below. "
#         f"{lang_hint}"
#         "Be concise, structured, and always display all prices in US dollars ($ / USD).\n"
#         f"{ui_lang_rule}\n"
#         f"{honesty_and_accuracy_rule}\n"
#         f"{multimodal_scenarios_rule}\n"
#         f"{context_str}"
#     )

#     headers = {
#         "Content-Type": "application/json",
#         "x-goog-api-key": settings.GEMINI_API_KEY,
#     }
#     request_body = {
#         "systemInstruction": {
#             "parts": [{"text": system_instruction}],
#         },
#         "contents": [
#             *history,
#             {
#                 "role": "user",
#                 "parts": _build_user_parts(effective_user_prompt, normalized_images),
#             },
#         ],
#     }

#     if settings.ENABLE_GOOGLE_SEARCH:
#         request_body["tools"] = [{"google_search": {}}]

#     # У Redis зберігаємо лише текстовий запис (без base64 зображень)
#     redis_user_summary = raw_message
#     if normalized_images:
#         photo_note = f"[Attached {len(normalized_images)} gallery photo(s)]"
#         redis_user_summary = f"{raw_message} {photo_note}".strip() if raw_message else photo_note

#     async def event_generator():
#         full_response_text = ""
#         last_error = ""

#         try:
#             async with httpx.AsyncClient(
#                 timeout=httpx.Timeout(connect=10.0, read=75.0, write=15.0, pool=15.0)
#             ) as client:
#                 for idx, raw_model in enumerate(candidate_models):
#                     model_name = raw_model.removeprefix("models/")
#                     url = (
#                         f"https://generativelanguage.googleapis.com/v1beta/models/"
#                         f"{model_name}:streamGenerateContent?alt=sse"
#                     )

#                     max_attempts = 2 if idx == 0 else 1
#                     model_succeeded = False
#                     first_token_logged = False
#                     t_model_start = time.perf_counter()

#                     for attempt in range(1, max_attempts + 1):
#                         try:
#                             async with client.stream(
#                                 "POST", url, headers=headers, json=request_body
#                             ) as response:
#                                 if response.status_code != 200:
#                                     err_body = await response.aread()
#                                     last_error = (
#                                         f"API {response.status_code} ({model_name}): "
#                                         f"{err_body.decode('utf-8', errors='ignore')}"
#                                     )
#                                     print(f"[AI Chat Warning] {last_error}")
#                                     if response.status_code in (429, 503) and attempt < max_attempts:
#                                         await asyncio.sleep(0.6)
#                                         continue
#                                     break

#                                 async for line in response.aiter_lines():
#                                     if await request.is_disconnected():
#                                         break
#                                     if not line.startswith("data: "):
#                                         continue

#                                     raw_data = line[6:].strip()
#                                     if not raw_data or raw_data == "[DONE]":
#                                         continue

#                                     data = json.loads(raw_data)
#                                     candidates = data.get("candidates") or []
#                                     if not candidates:
#                                         continue

#                                     parts = (
#                                         candidates[0].get("content", {}).get("parts") or []
#                                     )
#                                     for part in parts:
#                                         text = part.get("text")
#                                         if text:
#                                             if not first_token_logged:
#                                                 ttfb = time.perf_counter() - t_model_start
#                                                 print(
#                                                     f"[AI Chat Timing] requested={payload.model_type} "
#                                                     f"model={model_name} rag={t_rag:.2f}s ttfb={ttfb:.2f}s "
#                                                     f"images={len(normalized_images)} items={len(relevant_products)}"
#                                                 )
#                                                 first_token_logged = True
#                                             full_response_text += text
#                                             sse_chunk = _format_sse_data(text)
#                                             if sse_chunk:
#                                                 yield sse_chunk

#                                 model_succeeded = True
#                                 break
#                         except httpx.TimeoutException as exc:
#                             last_error = f"Timeout ({model_name}): {type(exc).__name__}"
#                             print(f"[AI Chat Warning] {last_error}")
#                             if not full_response_text:
#                                 break
#                             raise

#                     if model_succeeded or full_response_text:
#                         break
#                 else:
#                     yield f"data: [ПОМИЛКА: Усі моделі недоступні. {last_error}]\n\n"

#             cleaned_response = _strip_ui_lang_tag(full_response_text)
#             if cleaned_response:
#                 await memory_service.save_interaction(
#                     payload.session_id,
#                     redis_user_summary,
#                     cleaned_response,
#                 )
#         except Exception as exc:
#             err_msg = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
#             print(f"[AI Chat Error] {err_msg}")
#             yield f"data: [ПОМИЛКА: {err_msg}]\n\n"

#         yield "data: [DONE]\n\n"

#     return StreamingResponse(
#         event_generator(),
#         media_type="text/event-stream",
#         headers={
#             "Cache-Control": "no-cache",
#             "X-Accel-Buffering": "no",
#         },
#     )