"""
Роутер, позволяющий получить имя файла из OpenAI по file_id.
Используется бэкендом Telegram-бота, чтобы декодировать аннотацию
«【...†source】» в строку вида "Источник: <имя_файла>".
"""
from fastapi import APIRouter, HTTPException
from starlette.status import HTTP_404_NOT_FOUND

from services.openai_svc import OpenAIService

router = APIRouter(prefix="/api", tags=["file-metadata"])
openai_service = OpenAIService()

@router.get("/file_metadata/{file_id}")
async def get_file_metadata(file_id: str):
    """
    Пример ответа: {"filename": "my_document.pdf"}.
    Если файл не найден — 404.
    """
    meta = await openai_service.retrieve_file(file_id)
    if not meta:
        raise HTTPException(HTTP_404_NOT_FOUND, detail="File not found in OpenAI")
    return meta

