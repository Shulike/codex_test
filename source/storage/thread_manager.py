"""
Менеджер трейдов для микросервиса OpenAI.
Управляет трейдами и их жизненным циклом.
"""
import asyncio
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from storage.file_storage import FileStorage
from services.openai_svc import OpenAIService

logger = logging.getLogger(__name__)

class ThreadManager:
    """Класс для управления трейдами."""
    def __init__(self, storage: FileStorage, openai_service: OpenAIService):
        self.storage = storage
        self.openai_service = openai_service
        self.background_tasks = {}
    async def create_thread(self, initial_message: str) -> str:
        thread = await self.openai_service.create_thread(initial_message)
        thread_id = thread.id
        self.storage.add_thread(thread_id)
        return thread_id
    async def run_thread(self, thread_id: str, assistant_id: str) -> Dict[str, Any]:
        status = self.storage.get_thread_status(thread_id)
        if status is None:
            self.storage.add_thread(thread_id)
        await self.cancel_thread(thread_id)
        run = await self.openai_service.create_run(thread_id, assistant_id)
        run_id = run.id
        self.storage.add_active_run(thread_id, run_id, assistant_id)
        self.storage.set_thread_status(thread_id, "in_progress")
        task = asyncio.create_task(
            self._poll_run_status(thread_id, run_id)
        )
        self.background_tasks[thread_id] = task
        return {"thread_id": thread_id, "status": "in_progress"}
    async def cancel_thread(self, thread_id: str) -> Dict[str, Any]:
        if thread_id in self.background_tasks and not self.background_tasks[thread_id].done():
            self.background_tasks[thread_id].cancel()
            try:
                await self.background_tasks[thread_id]
            except asyncio.CancelledError:
                pass
            del self.background_tasks[thread_id]
        run_id = self.storage.get_active_run(thread_id)
        if run_id:
            run_id = run_id["run_id"]
            try:
                await self.openai_service.cancel_run(thread_id, run_id)
            except Exception as e:
                logger.error(f"Ошибка при отмене запуска {run_id} для треда {thread_id}: {e}")
        self.storage.remove_active_run(thread_id)
        self.storage.set_thread_status(thread_id, "cancelled")
        return {"thread_id": thread_id, "status": "cancelled"}
    async def get_thread_status(self, thread_id: str) -> Dict[str, Any]:
        status = self.storage.get_thread_status(thread_id)
        if status is None:
            return {"thread_id": thread_id, "status": "not_found"}
        return {"thread_id": thread_id, "status": status}
    async def _poll_run_status(self, thread_id: str, run_id: str, backoff: int = 1, max_backoff: int = 10):
        try:
            while True:
                run = await self.openai_service.get_run(thread_id, run_id)
                if run.status == 'completed':
                    self.storage.set_thread_status(thread_id, 'completed')
                    self.storage.remove_active_run(thread_id)
                    return
                elif run.status == 'failed':
                    self.storage.set_thread_status(thread_id, 'failed')
                    self.storage.remove_active_run(thread_id)
                    return
                elif run.status == 'cancelled':
                    self.storage.set_thread_status(thread_id, 'cancelled')
                    self.storage.remove_active_run(thread_id)
                    return
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
        except asyncio.CancelledError:
            self.storage.set_thread_status(thread_id, 'cancelled')
            self.storage.remove_active_run(thread_id)
            raise
        except Exception as e:
            logger.error(f"Ошибка при отслеживании статуса запуска {run_id} для треда {thread_id}: {e}")
            self.storage.set_thread_status(thread_id, 'error')
            self.storage.remove_active_run(thread_id)
    async def cleanup_inactive_threads(self, hours: int = 5) -> List[str]:
        inactive_threads = self.storage.get_inactive_threads(hours)
        for thread_id in inactive_threads:
            await self.cancel_thread(thread_id)
        return inactive_threads
