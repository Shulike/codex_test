"""
Планировщик задач для микросервиса OpenAI.
Управляет фоновыми задачами, включая очистку неактивных трейдов.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Callable

from storage.thread_manager import ThreadManager

logger = logging.getLogger(__name__)

class Scheduler:
    """Класс для управления фоновыми задачами."""
    def __init__(self, thread_manager: ThreadManager):
        self.thread_manager = thread_manager
        self.tasks = {}
        self.running = False
    async def start(self):
        if self.running:
            return
        self.running = True
        self.tasks["cleanup"] = asyncio.create_task(
            self._periodic_cleanup(hours=5, interval_minutes=10)
        )
        self.tasks["save"] = asyncio.create_task(
            self._periodic_save(interval_minutes=5)
        )
        logger.info("Планировщик задач запущен")
    async def stop(self):
        if not self.running:
            return
        self.running = False
        for name, task in list(self.tasks.items()):
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            del self.tasks[name]
        logger.info("Планировщик задач остановлен")
    async def _periodic_cleanup(self, hours: int = 5, interval_minutes: int = 10):
        try:
            while self.running:
                try:
                    inactive_threads = await self.thread_manager.cleanup_inactive_threads(hours)
                    if inactive_threads:
                        logger.info(f"Очищено {len(inactive_threads)} неактивных трейдов")
                except Exception as e:
                    logger.error(f"Ошибка при очистке неактивных трейдов: {e}")
                await asyncio.sleep(interval_minutes * 60)
        except asyncio.CancelledError:
            logger.info("Задача очистки неактивных трейдов отменена")
            raise
    async def _periodic_save(self, interval_minutes: int = 5):
        try:
            while self.running:
                try:
                    self.thread_manager.storage.periodic_save()
                    logger.info("Данные сохранены")
                except Exception as e:
                    logger.error(f"Ошибка при сохранении данных: {e}")
                await asyncio.sleep(interval_minutes * 60)
        except asyncio.CancelledError:
            logger.info("Задача периодического сохранения данных отменена")
            raise
