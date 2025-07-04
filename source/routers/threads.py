"""
API роутеры для микросервиса OpenAI.
"""
from fastapi import APIRouter, Depends, HTTPException
import logging
from typing import Dict, Any, Optional, List

from schemas import (
    CreateThreadRequest, CreateThreadResponse,
    AddMessageRequest, RunRequest, RunResponse,
    CancelRunRequest, ThreadStatusResponse, MessageListResponse
)
from storage.thread_manager import ThreadManager
from security import get_api_key

router = APIRouter(prefix="/api", tags=["threads"])
logger = logging.getLogger(__name__)

# Зависимость для получения менеджера трейдов
def get_thread_manager():
    from main import thread_manager
    return thread_manager

@router.post("/create_thread", response_model=CreateThreadResponse)
async def create_thread(
    request: CreateThreadRequest,
    thread_manager: ThreadManager = Depends(get_thread_manager),
    api_key: str = Depends(get_api_key)
):
    """
    Создание нового треда.
    """
    try:
        thread_id = await thread_manager.create_thread(request.initial_message)
        return {"thread_id": thread_id}
    except Exception as e:
        logger.error(f"Ошибка при создании треда: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/add_message")
async def add_message(
    request: AddMessageRequest,
    thread_manager: ThreadManager = Depends(get_thread_manager),
    api_key: str = Depends(get_api_key)
):
    """
    Добавление сообщения в тред.
    """
    try:
        await thread_manager.openai_service.add_message(
            request.thread_id, request.role, request.content
        )
        return {"status": "message_added"}
    except Exception as e:
        logger.error(f"Ошибка при добавлении сообщения: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/run", response_model=ThreadStatusResponse)
async def run_thread(
    request: RunRequest,
    thread_manager: ThreadManager = Depends(get_thread_manager),
    api_key: str = Depends(get_api_key)
):
    """
    Запуск треда.
    """
    try:
        result = await thread_manager.run_thread(request.thread_id, request.assistant_id)
        return {"status": result["status"]}
    except Exception as e:
        logger.error(f"Ошибка при запуске треда: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/cancel_run", response_model=ThreadStatusResponse)
async def cancel_run(
    request: CancelRunRequest,
    thread_manager: ThreadManager = Depends(get_thread_manager),
    api_key: str = Depends(get_api_key)
):
    """
    Отмена выполнения треда.
    """
    try:
        result = await thread_manager.cancel_thread(request.thread_id)
        return {"status": result["status"]}
    except Exception as e:
        logger.error(f"Ошибка при отмене выполнения треда: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/thread_status/{thread_id}", response_model=ThreadStatusResponse)
async def thread_status(
    thread_id: str,
    thread_manager: ThreadManager = Depends(get_thread_manager),
    api_key: str = Depends(get_api_key)
):
    """
    Получение статуса треда.
    """
    try:
        result = await thread_manager.get_thread_status(thread_id)
        return {"status": result["status"]}
    except Exception as e:
        logger.error(f"Ошибка при получении статуса треда: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/latest_message/{thread_id}")
async def latest_message(
    thread_id: str,
    thread_manager: ThreadManager = Depends(get_thread_manager),
    api_key: str = Depends(get_api_key)
):
    """
    Получение последнего сообщения из треда.
    """
    try:
        message = await thread_manager.openai_service.get_latest_message(thread_id)
        return message or {"role": "system", "content": "No messages found"}
    except Exception as e:
        logger.error(f"Ошибка при получении последнего сообщения: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/messages/{thread_id}", response_model=MessageListResponse)
async def get_messages(
    thread_id: str,
    thread_manager: ThreadManager = Depends(get_thread_manager),
    api_key: str = Depends(get_api_key)
):
    """
    Получение сообщений из треда.
    """
    try:
        messages = await thread_manager.openai_service.get_messages(thread_id)
        return {"messages": messages}
    except Exception as e:
        logger.error(f"Ошибка при получении сообщений: {e}")
        raise HTTPException(status_code=500, detail=str(e))

