"""
Файловое хранилище для микросервиса OpenAI.
Заменяет БД для хранения информации о трейдах.
"""
import json
import os
import time
import threading
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

class FileStorage:
    """Класс для работы с файловым хранилищем."""
    def __init__(self, data_dir: str = "data", filename: str = "threads.json"):
        self.data_dir = data_dir
        self.filename = filename
        self.filepath = os.path.join(data_dir, filename)
        self.lock = threading.RLock()
        self.data = {
            "threads": {},
            "active_runs": {}
        }
        os.makedirs(data_dir, exist_ok=True)
        self._load_data()
    def _load_data(self) -> None:
        try:
            if os.path.exists(self.filepath):
                with open(self.filepath, 'r') as f:
                    self.data = json.load(f)
                logger.info(f"Данные загружены из {self.filepath}")
            else:
                logger.info(f"Файл {self.filepath} не существует, используем пустое хранилище")
        except Exception as e:
            logger.error(f"Ошибка при загрузке данных: {e}")
            self.data = {
                "threads": {},
                "active_runs": {}
            }
    def _save_data(self) -> None:
        try:
            if os.path.exists(self.filepath):
                backup_path = f"{self.filepath}.bak"
                with open(self.filepath, 'r') as src:
                    with open(backup_path, 'w') as dst:
                        dst.write(src.read())
            with open(self.filepath, 'w') as f:
                json.dump(self.data, f, indent=2)
            logger.info(f"Данные сохранены в {self.filepath}")
        except Exception as e:
            logger.error(f"Ошибка при сохранении данных: {e}")
    def add_thread(self, thread_id: str) -> None:
        with self.lock:
            current_time = datetime.now(timezone.utc).isoformat()
            if thread_id not in self.data["threads"]:
                self.data["threads"][thread_id] = {
                    "status": "created",
                    "last_activity": current_time,
                    "assistant_id": None
                }
                self._save_data()
    def set_thread_status(self, thread_id: str, status: str) -> None:
        with self.lock:
            current_time = datetime.now(timezone.utc).isoformat()
            if thread_id in self.data["threads"]:
                self.data["threads"][thread_id]["status"] = status
                self.data["threads"][thread_id]["last_activity"] = current_time
                self._save_data()
            else:
                logger.warning(f"Попытка установить статус для несуществующего треда {thread_id}")
    def get_thread_status(self, thread_id: str) -> Optional[str]:
        with self.lock:
            if thread_id in self.data["threads"]:
                return self.data["threads"][thread_id]["status"]
            return None
    def add_active_run(self, thread_id: str, run_id: str, assistant_id: str) -> None:
        with self.lock:
            current_time = datetime.now(timezone.utc).isoformat()
            if thread_id in self.data["threads"]:
                self.data["threads"][thread_id]["status"] = "in_progress"
                self.data["threads"][thread_id]["last_activity"] = current_time
                self.data["threads"][thread_id]["assistant_id"] = assistant_id
            else:
                self.data["threads"][thread_id] = {
                    "status": "in_progress",
                    "last_activity": current_time,
                    "assistant_id": assistant_id
                }
            self.data["active_runs"][thread_id] = {
                "run_id": run_id,
                "start_time": current_time
            }
            self._save_data()
    def remove_active_run(self, thread_id: str) -> Optional[str]:
        with self.lock:
            if thread_id in self.data["active_runs"]:
                run_id = self.data["active_runs"][thread_id]["run_id"]
                del self.data["active_runs"][thread_id]
                self._save_data()
                return run_id
            return None
    def get_active_run(self, thread_id: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            if thread_id in self.data["active_runs"]:
                return self.data["active_runs"][thread_id]
            return None
    def get_inactive_threads(self, hours: int = 5) -> List[str]:
        with self.lock:
            current_time = datetime.now(timezone.utc)
            inactive_threads = []
            for thread_id, thread_data in self.data["threads"].items():
                if thread_id in self.data["active_runs"]:
                    last_activity = datetime.fromisoformat(thread_data["last_activity"])
                    time_diff = (current_time - last_activity).total_seconds() / 3600
                    if time_diff >= hours:
                        inactive_threads.append(thread_id)
            return inactive_threads
    def cleanup_inactive_threads(self, hours: int = 5) -> List[str]:
        with self.lock:
            inactive_threads = self.get_inactive_threads(hours)
            for thread_id in inactive_threads:
                if thread_id in self.data["active_runs"]:
                    del self.data["active_runs"][thread_id]
                if thread_id in self.data["threads"]:
                    self.data["threads"][thread_id]["status"] = "cancelled_inactive"
            if inactive_threads:
                self._save_data()
            return inactive_threads
    def periodic_save(self) -> None:
        with self.lock:
            self._save_data()
