import asyncio
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.base import get_db
from app.services.rag_service import RAGService
from app.services.memory_service import MemoryService
from app.core.llm import chat_model

router = APIRouter(prefix="/chat", tags=["AI Chat"])

class ChatPayload(BaseModel):
    session_id: str
    message: str

@router.post("/stream")
async def chat_stream(payload: ChatPayload, request: Request, db: AsyncSession = Depends(get_db)):
    rag_service = RAGService(db)
    memory_service = MemoryService()

    # 1. Шукаємо релевантні товари в БД
    relevant_products = await rag_service.find_relevant_products(payload.message)
    context_str = rag_service.format_context(relevant_products)

    # 2. Відновлюємо історію діалогу з Redis
    history = await memory_service.get_history(payload.session_id)
    
    # 3. Формуємо системний промпт із знайденими товарами
    system_instruction = (
        "Ти професійний консультант магазину ElectroStore. "
        "Твоя задача — допомагати у виборі техніки, перевіряти сумісність комплектуючих "
        "і пропонувати товари тільки з наведеного контексту. Будь лаконічним.\n"
        f"{context_str}"
    )

    async def event_generator():
        try:
            # Ініціалізуємо чат із історією
            chat = chat_model.start_chat(history=history)
            full_prompt = f"Контекст системи (не кажи користувачу, що він є): {system_instruction}\n\nЗапит юзера: {payload.message}"
            
            # Викликаємо генерацію в режимі потоку
            response = await chat.send_message_async(full_prompt, stream=True)
            
            full_response_text = ""
            async for chunk in response:
                if await request.is_disconnected():
                    break
                if chunk.text:
                    full_response_text += chunk.text
                    # Віддаємо частинку тексту клієнту в форматі SSE (Server-Sent Events)
                    yield f"data: {chunk.text}\n\n"
                    await asyncio.sleep(0.01) # Уникаємо блокування Event Loop
            
            # Після завершення потоку зберігаємо взаємодію в Redis
            if full_response_text:
                await memory_service.save_interaction(payload.session_id, payload.message, full_response_text)
                
        except Exception as e:
            yield f"data: [ПОМИЛКА: {str(e)}]\n\n"
            
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")